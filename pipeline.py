"""
pipeline.py -- Master orchestrator.

Runs the full automated workflow:
  1. Claude -> storyboard JSON
  2. OpenAI TTS -> voiceover MP3
  3. Higgsfield (T2I + I2V) -> per-shot MP4 clips
  4. MoviePy -> assembled final MP4
  5. SendGrid -> email to client

Designed to be called from a background thread in app.py so the Flask
response can return immediately.
"""

import json
import logging
import os
import traceback
import uuid
from datetime import datetime
import config
import storyboard
import tts
import video_gen
import assembler
import email_sender
import logo_gen
import music

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def _make_job_dir(product_name: str):
    """Create a unique working directory for this run. Returns (job_id, job_dir).

    The job id is also the download-link slug, so the random part is 16 hex
    characters rather than 6 - a link nobody should be able to guess.
    """
    slug = "".join(c if c.isalnum() else "_" for c in product_name)[:30]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    job_id = f"{slug}_{timestamp}_{uuid.uuid4().hex[:16]}"
    job_dir = os.path.join(config.BASE_OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    logger.info("Job directory: %s", job_dir)
    return job_id, job_dir


def run(
    product_name: str,
    target_audience: str,
    tone: str,
    client_email: str,
    key_benefits: str = "",
    logo_path: str = None,
    generate_logo: bool = False,
    business_type: str = "product",
    business_address: str = "",
    business_phone: str = "",
    business_website: str = "",
    cultural_preference: str = "standard",
) -> dict:
    """Execute the complete pipeline for one client submission."""
    job_id, job_dir = _make_job_dir(product_name)
    result = {
        "success": False,
        "video_path": None,
        "download_url": None,
        "storyboard": None,
        "error": None,
    }

    try:
        # -- 1. Storyboarding
        logger.info("=== STEP 1: Storyboarding ===")
        sb = storyboard.generate_storyboard(
            product_name, target_audience, tone, key_benefits, business_type,
            business_address=business_address,
            business_phone=business_phone,
            business_website=business_website,
            cultural_preference=cultural_preference,
        )
        result["storyboard"] = sb

        sb_path = os.path.join(job_dir, "storyboard.json")
        with open(sb_path, "w") as f:
            json.dump(sb, f, indent=2)
        logger.info("Storyboard saved -> %s", sb_path)

        # -- 2. TTS Voiceover
        logger.info("=== STEP 2: TTS Voiceover ===")
        voiceover_path = os.path.join(job_dir, "voiceover.mp3")
        tts.generate_voiceover(sb["full_voiceover"], voiceover_path)

        # -- 3. Higgsfield Clip Generation
        logger.info("=== STEP 3: Generating %d video clips ===", len(sb["shots"]))
        enriched_shots = video_gen.generate_all_clips(
            sb["shots"], job_dir, cultural_preference=cultural_preference
        )
        logger.info("generate_all_clips returned %s with %s items",
                    type(enriched_shots).__name__,
                    len(enriched_shots) if enriched_shots is not None else "None")
        if not enriched_shots:
            raise RuntimeError(f"generate_all_clips returned empty/None: {enriched_shots!r}")

        # -- 3.5. Background music
        logger.info("=== STEP 3.5a: Fetching background music ===")
        music_path = music.get_background_music(tone)

        # -- 3.5b. Logo (optional)
        if generate_logo and not logo_path:
            logger.info("=== STEP 3.5: Generating logo with DALL-E ===")
            try:
                logo_path = logo_gen.generate_logo(product_name, job_dir)
            except Exception as logo_err:
                logger.warning("Logo generation failed (skipping): %s", logo_err)
                logo_path = None

        # -- 4. Video Assembly
        logger.info("=== STEP 4: Assembling final video ===")
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "" for c in sb["project_title"]
        ).strip().replace(" ", "_")[:50]
        final_path = os.path.join(job_dir, f"{safe_title}_final.mp4")

        assembler.assemble_video(
            enriched_shots, voiceover_path, final_path,
            logo_path=logo_path, music_path=music_path,
        )
        result["video_path"] = final_path

        # -- 5. Email Delivery (a download link, not a 10 MB attachment)
        download_url = f"{config.PUBLIC_BASE_URL}/download/{job_id}"
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        result["download_url"] = download_url

        logger.info("=== STEP 5: Sending to %s ===", client_email)
        logger.info("Download link: %s (%.1f MB)", download_url, size_mb)
        sent = email_sender.send_video_to_client(
            to_email=client_email,
            product_name=product_name,
            project_title=sb["project_title"],
            video_path=final_path,
            download_url=download_url,
            size_mb=size_mb,
        )
        if not sent:
            # The file is on the volume and the link works regardless, so this
            # is recoverable now - hand the client the URL below by hand.
            logger.error(
                "Email delivery failed -- video is still downloadable at %s",
                download_url,
            )
        else:
            logger.info("Pipeline complete! Link delivered to %s", client_email)

        result["success"] = True

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)
        result["error"] = str(exc)
        # Notify the client so they're not left waiting forever
        try:
            email_sender.send_failure_notice(client_email, product_name)
        except Exception as mail_err:
            logger.error("Could not send failure notice: %s", mail_err)

    return result


if __name__ == "__main__":
    import sys
    product = input("Product name: ").strip() or "ProSleep Pillow"
    audience = input("Target audience: ").strip() or "busy professionals aged 30-45"
    style = input("Tone/style: ").strip() or "calm, premium, aspirational"
    email_addr = input("Delivery email: ").strip() or "test@example.com"
    out = run(product, audience, style, email_addr)
    print("Success:", out["success"])
    print("Video:", out["video_path"])
    if out["error"]:
        print("Error:", out["error"])
    sys.exit(0 if out["success"] else 1)
