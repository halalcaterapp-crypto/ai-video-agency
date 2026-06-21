"""
video_gen.py — Generate video clips using the Higgsfield Python SDK.

SDK docs: https://github.com/higgsfield-ai/higgsfield-client
Auth: HF_KEY="api_key:api_secret" env var (set from HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET)
"""

import logging
import os
import time
import requests
from pathlib import Path

# ── Bridge Railway env vars → Higgsfield SDK env vars ─────────────────────────
# The SDK reads HF_KEY or HF_API_KEY + HF_API_SECRET from environment.
# We store them as HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET in Railway.
_key    = os.getenv("HIGGSFIELD_API_KEY", "")
_secret = os.getenv("HIGGSFIELD_API_SECRET", "")
if _key and _secret:
    os.environ["HF_KEY"] = f"{_key}:{_secret}"
elif _key:
    os.environ["HF_API_KEY"] = _key

import higgsfield_client  # noqa: E402 — must come after env setup
import config

logger = logging.getLogger(__name__)

# ── Model IDs ─────────────────────────────────────────────────────────────────
T2I_MODEL = "bytedance/seedream/v4/text-to-image"
I2V_MODEL = "higgsfield-ai/dop/standard"


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _extract_image_url(result: dict) -> str:
    """Pull image URL from SDK result."""
    logger.debug("T2I result: %s", result)
    if "images" in result:
        imgs = result["images"]
        if isinstance(imgs, list) and imgs:
            img = imgs[0]
            return img["url"] if isinstance(img, dict) else img
    if "url" in result:
        return result["url"]
    if "output" in result:
        out = result["output"]
        if isinstance(out, list) and out:
            return out[0].get("url") or out[0]
        if isinstance(out, dict):
            return out.get("url", "")
    raise ValueError(f"Cannot find image URL in T2I result: {result}")


def _extract_video_url(result: dict) -> str:
    """Pull video URL from SDK result."""
    logger.debug("I2V result: %s", result)
    for key in ("video", "videos", "url", "output"):
        if key in result:
            val = result[key]
            if isinstance(val, dict):
                return val.get("url", "")
            if isinstance(val, list) and val:
                item = val[0]
                return item.get("url") if isinstance(item, dict) else item
            if isinstance(val, str) and val.startswith("http"):
                return val
    raise ValueError(f"Cannot find video URL in I2V result: {result}")


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
    t2i_result = higgsfield_client.subscribe(
        T2I_MODEL,
        arguments={
            "prompt":       prompt,
            "resolution":   "2K",
            "aspect_ratio": "16:9",
            "camera_fixed": False,
        }
    )
    image_url = _extract_image_url(t2i_result)
    logger.info("Shot %02d: Image ready → %s", scene_number, image_url)

    ext = image_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
    _download(image_url, os.path.join(shot_dir, f"keyframe.{ext}"))

    # ── Step 2: Image → Video ─────────────────────────────────────────────────
    logger.info("Shot %02d: Animating to video (target %ds)...", scene_number, duration_seconds)
    i2v_result = higgsfield_client.subscribe(
        I2V_MODEL,
        arguments={
            "image_url": image_url,
            "prompt":    prompt,
            "duration":  duration_seconds,
        }
    )
    video_url = _extract_video_url(i2v_result)
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
