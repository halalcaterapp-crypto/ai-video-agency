"""
video_gen.py — Generate one video clip per shot via Higgsfield's REST API.

Two-step process per shot:
  1. Text → Image  (higgsfield-ai/soul/standard)
  2. Image → Video (higgsfield-ai/dop/standard)

Uses polling with configurable interval / max attempts.
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


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _submit(model_id: str, payload: dict) -> str:
    """POST to Higgsfield and return the request_id."""
    url = f"{config.HIGGSFIELD_BASE_URL}/{model_id}"
    resp = SESSION.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    request_id = data["request_id"]
    logger.debug("Submitted to %s → request_id=%s", model_id, request_id)
    return request_id


def _poll(request_id: str) -> dict:
    """
    Poll the status endpoint until the job completes (or fails).
    Automatically retries on transient network errors.
    Returns the completed response dict.
    """
    status_url = f"{config.HIGGSFIELD_BASE_URL}/requests/{request_id}/status"
    for attempt in range(1, config.MAX_POLL_ATTEMPTS + 1):
        time.sleep(config.POLL_INTERVAL_SECONDS)
        try:
            resp = SESSION.get(status_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Poll %d/%d — network error (%s), retrying...", attempt, config.MAX_POLL_ATTEMPTS, e)
            continue

        status = data.get("status", "unknown")
        logger.debug("Poll %d/%d → %s", attempt, config.MAX_POLL_ATTEMPTS, status)

        if status == "completed":
            return data
        if status in ("failed", "nsfw"):
            raise RuntimeError(
                f"Higgsfield job {request_id} ended with status '{status}'"
            )
        # queued | in_progress → keep waiting

    raise TimeoutError(
        f"Higgsfield job {request_id} did not complete within "
        f"{config.MAX_POLL_ATTEMPTS * config.POLL_INTERVAL_SECONDS}s"
    )


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

def generate_image_for_shot(prompt: str, shot_dir: str) -> str:
    """
    Step 1: Text → Image.
    Returns the local path to the downloaded PNG/JPG.
    """
    logger.info("  [T2I] Submitting image generation...")
    request_id = _submit(
        config.HIGGSFIELD_T2I_MODEL,
        {
            "prompt":       prompt,
            "aspect_ratio": "16:9",
            "resolution":   "720p",
        },
    )
    result = _poll(request_id)
    image_url = result["images"][0]["url"]
    logger.info("  [T2I] Image ready: %s", image_url)

    ext = image_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
    image_path = os.path.join(shot_dir, f"frame.{ext}")
    return _download(image_url, image_path)


def generate_video_for_shot(
    image_path: str, prompt: str, duration_seconds: int, shot_dir: str
) -> str:
    """
    Step 2: Image → Video.
    The local image_path is not directly uploadable; we need a public URL.
    We re-use the Higgsfield CDN URL obtained in step 1 instead of re-uploading.

    NOTE: pass `image_url` (the CDN string) instead of the local path when
          calling this from pipeline.py — see generate_shot_clip() below.
    """
    raise NotImplementedError("Call generate_shot_clip() directly.")


def generate_shot_clip(
    scene_number: int,
    prompt: str,
    duration_seconds: int,
    job_dir: str,
) -> str:
    """
    Full two-step pipeline for a single shot.
    Returns the local path to the final .mp4 clip.

    Args:
        scene_number:     1-based index (used for file naming)
        prompt:           The Higgsfield visual prompt for this shot
        duration_seconds: Target clip length (2-5 s)
        job_dir:          Directory dedicated to this pipeline run
    """
    shot_dir = os.path.join(job_dir, f"shot_{scene_number:02d}")
    os.makedirs(shot_dir, exist_ok=True)

    # ── Step 1: Text → Image ─────────────────────────────────────────────────
    logger.info("Shot %02d: Generating keyframe image...", scene_number)
    t2i_request_id = _submit(
        config.HIGGSFIELD_T2I_MODEL,
        {
            "prompt":       prompt,
            "aspect_ratio": "16:9",
            "resolution":   "720p",
        },
    )
    t2i_result = _poll(t2i_request_id)
    image_cdn_url = t2i_result["images"][0]["url"]
    logger.info("Shot %02d: Image ready.", scene_number)

    # Also save a local copy for reference
    ext = image_cdn_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
    _download(image_cdn_url, os.path.join(shot_dir, f"keyframe.{ext}"))

    # ── Step 2: Image → Video ─────────────────────────────────────────────────
    logger.info("Shot %02d: Animating to video (target %ds)...", scene_number, duration_seconds)
    i2v_request_id = _submit(
        config.HIGGSFIELD_I2V_MODEL,
        {
            "image_url": image_cdn_url,
            "prompt":    prompt,
            "duration":  duration_seconds,
        },
    )
    i2v_result = _poll(i2v_request_id)
    video_cdn_url = i2v_result["video"]["url"]
    logger.info("Shot %02d: Video ready.", scene_number)

    clip_path = os.path.join(shot_dir, "clip.mp4")
    _download(video_cdn_url, clip_path)
    logger.info("Shot %02d: Clip saved → %s", scene_number, clip_path)
    return clip_path


# ── Batch generation ──────────────────────────────────────────────────────────

def generate_all_clips(shots: list[dict], job_dir: str) -> list[dict]:
    """
    Iterate through the shot list and generate a clip for each.

    Args:
        shots:   List of shot dicts from the storyboard JSON.
        job_dir: Root directory for this job's working files.

    Returns:
        The same list with an added 'clip_path' key per shot.
    """
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
