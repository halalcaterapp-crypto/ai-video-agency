"""
video_gen.py - Generate video clips using Higgsfield REST API for both T2I and I2V.

Step 1: Higgsfield Soul Standard -> keyframe image from text
Step 2: Higgsfield DoP Standard -> animated video from image

Auth: HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET env vars (Railway Variables)
Polling: uses status_url from response, falls back to /requests/{id}/status
"""

import logging
import os
import time
import requests
from pathlib import Path

import config

logger = logging.getLogger(__name__)

HF_BASE = "https://platform.higgsfield.ai"
POLL_INTERVAL = 8
MAX_POLLS = 150


def _hf_headers():
    key    = config.HIGGSFIELD_API_KEY
    secret = config.HIGGSFIELD_API_SECRET
    if not key:
        raise ValueError("HIGGSFIELD_API_KEY not set")
    auth = f"Key {key}:{secret}" if secret else f"Key {key}"
    return {
        "Authorization": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _download(url, dest_path):
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=180, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.debug("Downloaded %.1f KB -> %s", os.path.getsize(dest_path) / 1024, dest_path)
    return dest_path


def _extract_url(data):
    """Extract any result URL from a Higgsfield response dict."""
    for key in ("url", "image_url", "video_url", "imageUrl", "videoUrl"):
        if key in data and isinstance(data[key], str) and data[key].startswith("http"):
            return data[key]
    for key in ("video", "image", "images", "videos", "output", "result", "data"):
        val = data.get(key)
        if isinstance(val, list) and val:
            item = val[0]
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, dict):
                u = item.get("url") or item.get("image_url") or item.get("video_url", "")
                if u:
                    return u
        if isinstance(val, dict):
            u = val.get("url") or val.get("image_url") or val.get("video_url", "")
            if u:
                return u
        if isinstance(val, str) and val.startswith("http"):
            return val
    return ""


def _hf_submit_and_poll(endpoint, payload):
    """Submit a job to Higgsfield and poll until complete. Returns final response dict."""
    submit_url = f"{HF_BASE}/{endpoint}"
    headers = _hf_headers()

    logger.info("Submitting to Higgsfield: %s", submit_url)
    resp = requests.post(submit_url, json=payload, headers=headers, timeout=60)
    logger.info("Higgsfield response %d: %s", resp.status_code, resp.text[:400])
    resp.raise_for_status()
    data = resp.json()

    # Check if result is already available in submit response
    if _extract_url(data):
        return data

    # Get request_id and status_url from response
    request_id = (
        data.get("request_id") or data.get("id") or
        data.get("requestId") or (data.get("data") or {}).get("id")
    )
    if not request_id:
        raise ValueError(f"No request_id in response: {data}")

    # Use status_url from response if available, otherwise construct it
    # Correct Higgsfield format: /requests/{id}/status  (plural, with /status)
    status_url = (
        data.get("status_url") or
        data.get("statusUrl") or
        f"{HF_BASE}/requests/{request_id}/status"
    )

    logger.info("Job submitted, request_id=%s — polling %s", request_id, status_url)

    for attempt in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        sr = requests.get(status_url, headers=headers, timeout=30)
        sr.raise_for_status()
        sdata = sr.json()
        status = (sdata.get("status") or sdata.get("state") or "").lower()
        logger.info("Poll %d — status=%s", attempt + 1, status)

        if status in ("completed", "succeeded", "done", "success"):
            return sdata
        if status in ("failed", "error", "cancelled", "nsfw"):
            raise RuntimeError(f"Higgsfield job failed: {sdata}")

    raise TimeoutError(f"Higgsfield job timed out after {MAX_POLLS * POLL_INTERVAL}s")


def generate_shot_clip(scene_number, prompt, duration_seconds, job_dir):
    shot_dir = os.path.join(job_dir, f"shot_{scene_number:02d}")
    os.makedirs(shot_dir, exist_ok=True)

    # Step 1: Text -> Image (Higgsfield Soul Standard)
    logger.info("Shot %02d: Generating keyframe via Higgsfield Soul Standard...", scene_number)
    t2i_data = _hf_submit_and_poll(
        "higgsfield-ai/soul/standard",
        {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "720p"},
    )
    image_url = _extract_url(t2i_data)
    if not image_url:
        raise ValueError(f"No image URL in T2I response: {t2i_data}")
    logger.info("Shot %02d: Image ready -> %s", scene_number, image_url)
    _download(image_url, os.path.join(shot_dir, "keyframe.jpg"))

    # Step 2: Image -> Video (Higgsfield DoP Standard)
    logger.info("Shot %02d: Animating to video (%ds)...", scene_number, duration_seconds)
    i2v_data = _hf_submit_and_poll(
        "higgsfield-ai/dop/standard",
        {"image_url": image_url, "prompt": prompt, "duration": min(duration_seconds, 5)},
    )
    video_url = _extract_url(i2v_data)
    if not video_url:
        raise ValueError(f"No video URL in I2V response: {i2v_data}")
    logger.info("Shot %02d: Video ready -> %s", scene_number, video_url)

    clip_path = os.path.join(shot_dir, "clip.mp4")
    _download(video_url, clip_path)
    logger.info("Shot %02d: Clip saved -> %s", scene_number, clip_path)
    return clip_path


def generate_all_clips(shots, job_dir):
    enriched = []
    for i, shot in enumerate(shots, start=1):
        logger.info("Generating clip %d/%d (scene %d)...", i, len(shots), shot["scene_number"])
        clip_path = generate_shot_clip(
            scene_number=shot["scene_number"],
            prompt=shot["higgsfield_prompt"],
            duration_seconds=shot["duration_seconds"],
            job_dir=job_dir,
        )
        enriched.append({**shot, "clip_path": clip_path})
    logger.info("All %d clips generated.", len(shots))
  