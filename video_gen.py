"""
video_gen.py — Generate one video clip per shot via Higgsfield's Cloud API.

New API (api.higgsfield.ai/v1/generations):
  1. POST /v1/generations  { task, model, prompt, ... }  → { id, status }
  2. GET  /v1/generations/{id}                           → { id, status, output }

Auth: Authorization: Bearer {HIGGSFIELD_API_KEY}
"""

import logging
import os
import time
import requests
from pathlib import Path
import config

logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": config.HIGGSFIELD_AUTH,
    "Content-Type":  "application/json",
    "Accept":        "application/json",
})

SUBMIT_URL = f"{config.HIGGSFIELD_BASE_URL}/v1/generations"


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _submit(payload: dict) -> str:
    """POST a generation request and return the generation id."""
    logger.debug("Submitting to %s: %s", SUBMIT_URL, payload)
    resp = SESSION.post(SUBMIT_URL, json=payload, timeout=30)
    if not resp.ok:
        logger.error("Higgsfield submit error %d: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    gen_id = data.get("id") or data.get("request_id")
    logger.debug("Submitted → id=%s", gen_id)
    return gen_id


def _poll(gen_id: str) -> dict:
    """Poll until the job completes. Returns the full response dict."""
    status_url = f"{config.HIGGSFIELD_BASE_URL}/v1/generations/{gen_id}"
    for attempt in range(1, config.MAX_POLL_ATTEMPTS + 1):
        time.sleep(config.POLL_INTERVAL_SECONDS)
        try:
            resp = SESSION.get(status_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Poll %d/%d — network error (%s), retrying...",
                           attempt, config.MAX_POLL_ATTEMPTS, e)
            continue

        status = data.get("status", "unknown")
        logger.debug("Poll %d/%d → %s", attempt, config.MAX_POLL_ATTEMPTS, status)

        if status in ("completed", "succeeded", "success"):
            return data
        if status in ("failed", "error", "nsfw", "cancelled"):
            logger.error("Higgsfield job %s failed. Full response: %s", gen_id, data)
            raise RuntimeError(
                f"Higgsfield job {gen_id} ended with status '{status}'"
            )
        # queued | processing | in_progress → keep waiting

    raise TimeoutError(
        f"Higgsfield job {gen_id} did not complete within "
        f"{config.MAX_POLL_ATTEMPTS * config.POLL_INTERVAL_SECONDS}s"
    )


def _extract_image_url(data: dict) -> str:
    """Pull the image URL out of a completed generation response."""
    # Try common response shapes
    output = data.get("output") or data
    if isinstance(output, list):
        output = output[0]
    for key in ("url", "image_url", "image", "result"):
        if key in output:
            val = output[key]
            if isinstance(val, list):
                return val[0].get("url") or val[0]
            return val
    # Fallback: scan all values for a URL string
    for v in output.values():
        if isinstance(v, str) and v.startswith("http"):
            return v
    raise ValueError(f"Cannot find image URL in response: {data}")


def _extract_video_url(data: dict) -> str:
    """Pull the video URL out of a completed generation response."""
    output = data.get("output") or data
    if isinstance(output, list):
        output = output[0]
    for key in ("url", "video_url", "video", "result", "mp4_url"):
        if key in output:
            val = output[key]
            if isinstance(val, dict):
                return val.get("url", "")
            if isinstance(val, list):
                return val[0].get("url") or val[0]
            return val
    for v in output.values():
        if isinstance(v, str) and v.startswith("http"):
            return v
    raise ValueError(f"Cannot find video URL in response: {data}")


def _download(url: str, dest_path: str) -> str:
    """Download a file from url to dest_path. Returns dest_path."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_kb = os.path.getsize(dest_path) / 1024
    logger.debug("Downloaded %.1f KB → %s", size_kb, dest_path)
    return dest_path


# ── Per-shot generation ───────────────────────────────────────────────────────

def generate_shot_clip(
    scene_number: int,
    prompt: str,
    duration_seconds: int,
    job_dir: str,
) -> str:
    """
    Full two-step pipeline for a single shot.
    Returns the local path to the final .mp4 clip.
    """
    shot_dir = os.path.join(job_dir, f"shot_{scene_number:02d}")
    os.makedirs(shot_dir, exist_ok=True)

    # ── Step 1: Text → Image ─────────────────────────────────────────────────
    logger.info("Shot %02d: Generating keyframe image...", scene_number)
    t2i_id = _submit({
        "task":    "text-to-image",
        "model":   config.HIGGSFIELD_T2I_MODEL,
        "prompt":  prompt,
        "width":   1280,
        "height":  720,
    })
    t2i_result = _poll(t2i_id)
    image_cdn_url = _extract_image_url(t2i_result)
    logger.info("Shot %02d: Image ready.", scene_number)

    ext = image_cdn_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
    _download(image_cdn_url, os.path.join(shot_dir, f"keyframe.{ext}"))

    # ── Step 2: Image → Video ─────────────────────────────────────────────────
    logger.info("Shot %02d: Animating to video (target %ds)...", scene_number, duration_seconds)
    i2v_id = _submit({
        "task":        "image-to-video",
        "model":       config.HIGGSFIELD_I2V_MODEL,
        "prompt":      prompt,
        "input_image": image_cdn_url,
        "duration":    duration_seconds,
    })
    i2v_result = _poll(i2v_id)
    video_cdn_url = _extract_video_url(i2v_result)
    logger.info("Shot %02d: Video ready.", scene_number)

    clip_path = os.path.join(shot_dir, "clip.mp4")
    _download(video_cdn_url, clip_path)
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
