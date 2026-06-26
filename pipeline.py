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


def _make_job_dir(product_name: str) -> str:
    """Create and return a unique working directory for this pipeline run."""
    slug = "".join(c if c.isalnum() else "_" for c in product_name)[:30]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    job_id = f"{slug}_{timestamp}_{uuid.uuid4().hex[:6]}"
    job_dir = os.path.join(config.BASE_OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    logger.info("Job directory: %s", job_dir)
    return job_dir


def run(
    product_name: str,
    target_audience: str,
    tone: str,
    client_email: str,
    key_benefits: str = "",
    logo_path: str = None,
    generate_logo: bool = False,
) -> dict:
    """Execute the complete pipeline for one client submission."""
    job_dir = _make_job_dir(product_name)
    result = {
        "success": False,
        "video_path": None,
        "storyboard": None,
        "error": None,
    }

    try:
        # -- 1. Storyboarding
        logger.info("=== STEP 1: Storyboarding ===")
        sb = storyboard.generate_storyboard(product_name, target_audience, tone, key_benefits)
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
        enriched_shots = video_gen.generate_all_clips(sb["shots"], job_dir)
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

        # -- 5. Email Delivery
        logger.info("=== STEP 5: Sending to %s ===", client_email)
        sent = email_sender.send_video_to_client(
            to_email=client_email,
            product_name=product_name,
            project_title=sb["project_title"],
            video_path=final_path,
        )
        if not sent:
            logger.error("Email delivery failed -- video is still at %s", final_path)
        else:
            logger.info("Pipeline complete! Video delivered to %s", client_email)

        result["success"] = True

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)
        result["error"] = str(exc)

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
