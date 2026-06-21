"""
video_gen.py — Generate video clips using DALL-E 3 (T2I) + Higgsfield REST API (I2V).

Step 1: DALL-E 3 via OpenAI → keyframe image (downloaded locally)
Step 2: Higgsfield DoP Standard REST API → animated video clip

Auth: HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET env vars (Railway Variables)
API:  POST https://platform.higgsfield.ai/higgsfield-ai/dop/standard
      Authorization: Key {key}:{secret}
"""

import logging
import os
import time
import requests
from pathlib import Path
from openai import OpenAI

import config

logger = logging.getLogger(__name__)

# ── Higgsfield REST API ───────────────────────────────────────────────────────
HF_BASE      = "https://platform.higgsfield.ai"
HF_I2V_PATH  = "/higgsfield-ai/dop/standard"
HF_STATUS_PATH = "/request/{request_id}"

POLL_INTERVAL = 8    # seconds between status checks
MAX_POLLS     = 150  # bail after ~20 min


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hf_auth_header() -> str:
    key    = config.HIGGSFIELD_API_KEY
    secret = config.HIGGSFIELD_API_SECRET
    if key and secret:
        return f"Key {key}:{secret}"
    if key:
        return f"Key {key}"
    raise ValueError("HIGGSFIELD_API_KEY not set")


def _download(url: str, dest_path: str) -> str:
    """Download a file from url to dest_path. Returns dest_path."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=180, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_kb = os.path.getsize(dest_path) / 1024
    logger.debug("Downloaded %.1f KB → %s", size_kb, dest_path)
    return dest_path


def _generate_image_dalle3(prompt: str) -> str:
    """Generate a keyframe image with DALL-E 3. Returns the image URL."""
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt[:4000],
        size="1792x1024",   # 16:9 landscape
        quality="standard",
        n=1,
    )
    url = response.data[0].url
    logger.debug("DALL-E 3 image URL: %s", url)
    return url


def _higgsfield_i2v(image_url: str, prompt: str, duration: int) -> str:
    """
    Submit an image-to-video job to Higgsfield DoP Standard REST API.
    Polls until complete. Returns the video URL.
    """
    headers = {
        "Authorization": _hf_auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "image_url": image_url,
        "prompt":    prompt,
        "duration":  min(duration, 5),   # DoP Standard max is 5s
    }

    # ── Submit ────────────────────────────────────────────────────────────────
    url = f"{HF_BASE}{HF_I2V_PATH}"
    logger.info("Submitting I2V to Higgsfield: %s", url)
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    logger.info("Higgsfield submit response %d: %s", resp.status_code, resp.text[:500])
    resp.raise_for_status()

    data = resp.json()
    request_id = data.get("id") or data.get("request_id") or data.get("requestId")
    if not request_id:
        # Some endpoints return the result immediately
        video_url = _extract_video_url_from_response(data)
        if video_url:
            return video_url
        raise ValueError(f"No request_id in Higgsfield response: {data}")

    logger.info("Higgsfield job submitted, request_id=%s", request_id)

    # ── Poll ──────────────────────────────────────────────────────────────────
    status_url = f"{HF_BASE}/request/{request_id}"
    for attempt in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        sr = requests.get(status_url, headers=headers, timeout=30)
        sr.raise_for_status()
        sdata = sr.json()
        status = (sdata.get("status") or "").lower()
        logger.info("Poll %d/%d — status=%s", attempt + 1, MAX_POLLS, status)

        if status in ("completed", "succeeded", "done", "success"):
            video_url = _extract_video_url_from_response(sdata)
            if video_url:
                return video_url
            raise ValueError(f"Job completed but no video URL found: {sdata}")
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Higgsfield job failed: {sdata}")

    raise TimeoutError(f"Higgsfield job timed out after {MAX_POLLS * POLL_INTERVAL}s")


def _extract_video_url_from_response(data: dict) -> str:
    """Extract video URL from various Higgsfield response shapes."""
    # Common patterns
    for key in ("video_url", "videoUrl", "url", "output_url"):
        if key in data and isinstance(data[key], str):
            return data[key]
    # Nested output
    for key in ("output", "result", "data"):
        if key in data:
            val = data[key]
            if isinstance(val, str) and val.startswith("http"):
                return val
            if isinstance(val, dict):
                for k in ("url", "video_url", "videoUrl"):
                    if k in val:
                        return val[k]
            if isinstance(val, list) and val:
                item = val[0]
                if isinstance(item, str):
                    return item
                if isinstance(item, dict):
                    return item.get("url", "")
    # Videos key
    if "videos" in data:
        vids = data["videos"]
        if isinstance(vids, list) and vids:
            v = vids[0]
            return v.get("url", "") if isinstance(v, dict) else v
    return ""


# ── Per-shot generation ───────────────────────────────────────────────────────

def generate_shot_clip(
    scene_number: int,
    prompt: str,
    duration_seconds: int,
    job_dir: str,
) -> str:
    """
    Full pipeline for a single shot.
    Returns the local path to the final .mp4 clip.
    """
    shot_dir = os.path.join(job_dir, f"shot_{scene_number:02d}")
    os.makedirs(shot_dir, exist_ok=True)

    # ── Step 1: Text → Image (DALL-E 3) ─────────────────────────────────────
    logger.info("Shot %02d: Generating keyframe via DALL-E 3...", scene_number)
    dalle_url = _generate_image_dalle3(prompt)

    # Download locally so we have a copy (DALL-E URLs expire in ~1 hour)
    keyframe_path = os.path.join(shot_dir, "keyframe.jpg")
    _download(dalle_url, keyframe_path)
    logger.info("Shot %02d: Keyframe saved → %s", scene_number, keyframe_path)

    # ── Step 2: Image → Video (Higgsfield DoP Standard) ──────────────────────
    logger.info("Shot %02d: Animating keyframe (target %ds)...", scene_number, duration_seconds)
    # Use the temporary DALL-E URL directly — Higgsfield fetches it during generation
    # (the URL is valid long enough since we submit immediately after download)
    video_url = _higgsfield_i2v(dalle_url, prompt, duration_seconds)
    logger.info("Shot %02d: Video ready → %s", scene_number, video_url)

    clip_path = os.path.join(shot_dir, "clip.mp4")
    _download(video_url, clip_path)
    logger.info("Shot %02d: Clip saved → %s", scene_number, clip_path)
    return clip_path


# ── Batch generation ──────────────────────────────────────────────────────────

def generate_all_clips(shots: list[dict], job_dir: str) -> list[dict]:
    """Iterate through shots and generate a clip for each."""
    enriched = []
    total = len(shots)
    for i, shot in enumerate(shots, start=1):
        logger.info("▶ Generating clip %d/%d (scene %d)...", i, total, shot["scene_number"])
        clip_path = generate_shot_clip(
            scene_number=shot["scene_number"],
            prompt=shot["higgsfield_prompt"],
            duration_seconds=shot["duration_seconds"],
            job_dir=job_dir,
        )
        enriched.append({**shot, "clip_path": clip_path})

    logger.info("All %d clips generated.", total)
    return enriched
