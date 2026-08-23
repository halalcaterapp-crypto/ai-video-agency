"""
video_gen.py - Generate video clips using Higgsfield REST API for both T2I and I2V.

Step 1: Higgsfield Soul Standard -> keyframe image from text
Step 2: Higgsfield DoP Standard -> animated video from image

Auth: HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET env vars (Railway Variables)
Polling: uses status_url from response, falls back to /requests/{id}/status
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

HF_BASE = "https://platform.higgsfield.ai"
POLL_INTERVAL = 8
MAX_POLLS = 300        # 40 minutes per job (Higgsfield queue can be slow)
MAX_SHOT_RETRIES = 2   # retry timed-out shots before failing the pipeline
MAX_POLL_ERRORS = 5    # consecutive status-endpoint failures before giving up
SUBMIT_ATTEMPTS = 4    # retries on transient network / 5xx / 429 errors at submit

# Shots are independent Higgsfield jobs, and DoP takes ~6 minutes to render a
# 5s clip no matter what else is running. Generating them one after another
# made STEP 3 cost 7x longer than it needed to (~45 min instead of ~7). Run
# them concurrently instead. Lower this if Higgsfield starts returning 429s.
MAX_PARALLEL_SHOTS = int(os.getenv("HF_MAX_PARALLEL_SHOTS", "7"))

# Clip length requested from Higgsfield I2V.
# Storyboards ask for 5-6s per shot (7-8s for the CTA), so a hard 3s cap here
# starved the timeline: 7 shots x 3s = 21s of footage under a ~38s voiceover,
# and the assembler papered over the gap with a long frozen last frame.
# We now request the storyboard length and step down only if the API refuses.
DURATION_LADDER = [
    int(x) for x in os.getenv("HF_DURATION_LADDER", "5,4,3").split(",") if x.strip()
]
MAX_CLIP_SECONDS = DURATION_LADDER[0]

# Set once the API has accepted a length, so later shots skip rejected values.
# Written from worker threads, so guard it with a lock.
_accepted_duration = None
_duration_lock = threading.Lock()

# Suffix appended to prompts on NSFW retry — strips risky language, asserts safety
_NSFW_SAFE_SUFFIX = (
    ", clean professional commercial, fully clothed people only, "
    "safe for all audiences, family-friendly advertising, "
    "no nudity, no suggestive content, no violence, no text, no watermarks, "
    "photorealistic 8K, luxury commercial grade"
)

# The safe-prompt retry truncates to the first 150 characters, which would drop
# any wardrobe constraint the storyboard placed later in the prompt. When the
# client selected a cultural mode we re-assert it explicitly on the retry.
# "standard" (the form default) adds nothing — an ordinary order is unaffected.
_CULTURAL_SAFE_SUFFIX = {
    "islamic": (
        ", all women wearing hijab and loose full-coverage modest clothing, "
        "men in conservative full-length clothing, no bare skin beyond face and hands, "
        "no alcohol, no pork, no physical contact between men and women"
    ),
    "family": (
        ", modest everyday clothing, wholesome family-friendly scene, "
        "no alcohol, no tobacco, no suggestive posing"
    ),
    "professional": (
        ", formal business attire, clean corporate setting, "
        "restrained professional mood, no alcohol, no nightlife"
    ),
}
_CULTURAL_SAFE_SUFFIX["modest"] = _CULTURAL_SAFE_SUFFIX["islamic"]


def _make_safe_prompt(prompt: str, cultural_preference: str = "standard") -> str:
    """Truncate prompt and append explicit safety markers for NSFW retry."""
    # Keep first 150 chars (core subject/scene), drop any trailing partial word
    short = prompt[:150].rsplit(" ", 1)[0]
    cultural = _CULTURAL_SAFE_SUFFIX.get((cultural_preference or "").lower().strip(), "")
    return short + _NSFW_SAFE_SUFFIX + cultural


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


def _post_with_retry(url, payload, headers, attempts=SUBMIT_ATTEMPTS):
    """POST a job, retrying transient network / 5xx failures with a short backoff.

    4xx responses are not retried -- bad request, auth and quota errors do not
    fix themselves. An NSFW rejection is re-raised as RuntimeError so the
    existing safe-prompt retry in _submit_t2i still catches it.
    """
    last_err = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            logger.info("Higgsfield response %d: %s", resp.status_code, resp.text[:400])
            if 400 <= resp.status_code < 500:
                if "nsfw" in resp.text.lower():
                    raise RuntimeError(f"Higgsfield job failed (nsfw): {resp.text[:300]}")
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # 429 is expected once shots run concurrently -- back off, don't fail.
            if status == 429:
                last_err = exc
                if i < attempts:
                    wait = 15 * i
                    logger.warning(
                        "Higgsfield rate-limited us (attempt %d/%d) -- waiting %ds. "
                        "Lower HF_MAX_PARALLEL_SHOTS if this repeats.",
                        i, attempts, wait,
                    )
                    time.sleep(wait)
                continue
            if status is not None and 400 <= status < 500:
                raise
            last_err = exc
            if i < attempts:
                wait = 5 * i
                logger.warning(
                    "Submit failed (attempt %d/%d): %s -- retrying in %ds",
                    i, attempts, exc, wait,
                )
                time.sleep(wait)
    raise last_err


def _hf_submit_and_poll(endpoint, payload):
    """Submit a job to Higgsfield and poll until complete. Returns final response dict."""
    submit_url = f"{HF_BASE}/{endpoint}"
    headers = _hf_headers()

    logger.info("Submitting to Higgsfield: %s", submit_url)
    data = _post_with_retry(submit_url, payload, headers)

    if _extract_url(data):
        return data

    request_id = (
        data.get("request_id") or data.get("id") or
        data.get("requestId") or (data.get("data") or {}).get("id")
    )
    if not request_id:
        raise ValueError(f"No request_id in response: {data}")

    status_url = (
        data.get("status_url") or
        data.get("statusUrl") or
        f"{HF_BASE}/requests/{request_id}/status"
    )

    logger.info("Job submitted, request_id=%s -- polling %s", request_id, status_url)

    consecutive_poll_errors = 0
    for attempt in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        try:
            sr = requests.get(status_url, headers=headers, timeout=30)
            sr.raise_for_status()
            sdata = sr.json()
        except (requests.RequestException, ValueError) as poll_err:
            # A single 502 from the status endpoint used to kill the whole job.
            consecutive_poll_errors += 1
            logger.warning(
                "Poll %d failed (%d/%d consecutive): %s",
                attempt + 1, consecutive_poll_errors, MAX_POLL_ERRORS, poll_err,
            )
            if consecutive_poll_errors >= MAX_POLL_ERRORS:
                raise RuntimeError(
                    f"Higgsfield status endpoint unreachable after "
                    f"{MAX_POLL_ERRORS} consecutive failures: {poll_err}"
                )
            continue
        consecutive_poll_errors = 0
        status = (sdata.get("status") or sdata.get("state") or "").lower()
        logger.info("Poll %d -- status=%s", attempt + 1, status)

        if status in ("completed", "succeeded", "done", "success"):
            return sdata
        if status in ("failed", "error", "cancelled", "nsfw"):
            raise RuntimeError(f"Higgsfield job failed: {sdata}")

    raise TimeoutError(f"Higgsfield job timed out after {MAX_POLLS * POLL_INTERVAL}s")


def _submit_t2i(prompt, scene_number, cultural_preference="standard"):
    """Submit T2I job; retry with a safe prompt if Higgsfield returns NSFW."""
    payload = {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "720p"}
    try:
        return _hf_submit_and_poll("higgsfield-ai/soul/standard", payload)
    except RuntimeError as exc:
        if "nsfw" in str(exc).lower():
            safe_prompt = _make_safe_prompt(prompt, cultural_preference)
            logger.warning(
                "Shot %02d NSFW flagged — retrying with safe prompt "
                "(len=%d, cultural=%s)...",
                scene_number, len(safe_prompt), cultural_preference,
            )
            return _hf_submit_and_poll(
                "higgsfield-ai/soul/standard",
                {"prompt": safe_prompt, "aspect_ratio": "16:9", "resolution": "720p"},
            )
        raise


def _clip_duration_for(duration_seconds):
    """Clip length to request, honouring any ceiling the API has already enforced."""
    ceiling = _accepted_duration or MAX_CLIP_SECONDS
    try:
        wanted = int(round(float(duration_seconds)))
    except (TypeError, ValueError):
        wanted = ceiling
    return max(1, min(wanted, ceiling))


def _submit_i2v(image_url, prompt, requested_duration):
    """Submit the I2V job, stepping down the ladder if the API rejects the length."""
    global _accepted_duration

    candidates = [requested_duration] + [
        d for d in DURATION_LADDER if d < requested_duration
    ]
    last_err = None
    for duration in candidates:
        try:
            data = _hf_submit_and_poll(
                "higgsfield-ai/dop/standard",
                {"image_url": image_url, "prompt": prompt, "duration": duration},
            )
            with _duration_lock:
                if _accepted_duration != duration:
                    logger.info(
                        "Higgsfield accepted duration=%ss -- using that for the rest of this run.",
                        duration,
                    )
                    _accepted_duration = duration
            return data
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
            body = (resp.text if resp is not None else "")[:300]
            if status == 400 and "duration" in body.lower():
                logger.warning(
                    "Higgsfield rejected duration=%ss (%s) -- stepping down.", duration, body
                )
                last_err = exc
                continue
            raise
    raise last_err or RuntimeError("No acceptable clip duration for Higgsfield I2V")


def _generate_shot_clip_once(scene_number, prompt, duration_seconds, job_dir,
                             cultural_preference="standard"):
    """Single attempt to generate one shot clip (T2I → I2V)."""
    shot_dir = os.path.join(job_dir, f"shot_{scene_number:02d}")
    os.makedirs(shot_dir, exist_ok=True)

    logger.info("Shot %02d: Generating keyframe via Higgsfield Soul Standard...", scene_number)
    t2i_data = _submit_t2i(prompt, scene_number, cultural_preference)
    image_url = _extract_url(t2i_data)
    if not image_url:
        raise ValueError(f"No image URL in T2I response: {t2i_data}")
    logger.info("Shot %02d: Image ready -> %s", scene_number, image_url)
    _download(image_url, os.path.join(shot_dir, "keyframe.jpg"))

    requested = _clip_duration_for(duration_seconds)
    logger.info(
        "Shot %02d: Animating to video (storyboard %ss -> requesting %ss)...",
        scene_number, duration_seconds, requested,
    )
    i2v_data = _submit_i2v(image_url, prompt, requested)
    video_url = _extract_url(i2v_data)
    if not video_url:
        raise ValueError(f"No video URL in I2V response: {i2v_data}")
    logger.info("Shot %02d: Video ready -> %s", scene_number, video_url)

    clip_path = os.path.join(shot_dir, "clip.mp4")
    _download(video_url, clip_path)
    logger.info("Shot %02d: Clip saved -> %s", scene_number, clip_path)
    return clip_path


def generate_shot_clip(scene_number, prompt, duration_seconds, job_dir,
                       cultural_preference="standard"):
    """Generate one shot clip with automatic retry on Higgsfield timeout."""
    last_err = None
    for attempt in range(1, MAX_SHOT_RETRIES + 1):
        try:
            return _generate_shot_clip_once(
                scene_number, prompt, duration_seconds, job_dir, cultural_preference
            )
        except TimeoutError as exc:
            last_err = exc
            if attempt < MAX_SHOT_RETRIES:
                logger.warning(
                    "Shot %02d timed out (attempt %d/%d) — waiting 60s then retrying...",
                    scene_number, attempt, MAX_SHOT_RETRIES,
                )
                time.sleep(60)
            else:
                logger.error("Shot %02d failed after %d attempts.", scene_number, MAX_SHOT_RETRIES)
    raise last_err


def generate_all_clips(shots, job_dir, cultural_preference="standard"):
    """Generate every shot clip, running the shots concurrently.

    Each shot is an independent pair of Higgsfield jobs (keyframe, then
    animation), and DoP spends ~6 minutes on a 5s clip regardless of what else
    is in flight. Running them sequentially therefore cost roughly
    len(shots) x 6 minutes; running them together costs about as long as the
    slowest single shot. Results are returned in storyboard order regardless
    of the order they finish in.
    """
    total = len(shots)
    workers = max(1, min(MAX_PARALLEL_SHOTS, total))
    logger.info(
        "Generating %d clips, up to %d at a time (~the cost of one shot, not %d)...",
        total, workers, total,
    )

    results = [None] * total
    errors = []

    def _one(shot):
        return {
            **shot,
            "clip_path": generate_shot_clip(
                scene_number=shot["scene_number"],
                prompt=shot["higgsfield_prompt"],
                duration_seconds=shot["duration_seconds"],
                job_dir=job_dir,
                cultural_preference=cultural_preference,
            ),
        }

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shot") as pool:
        futures = {pool.submit(_one, shot): i for i, shot in enumerate(shots)}
        completed = 0
        for fut in as_completed(futures):
            i = futures[fut]
            scene = shots[i]["scene_number"]
            try:
                results[i] = fut.result()
                completed += 1
                logger.info("Progress: %d/%d clips complete (shot %02d done).",
                            completed, total, scene)
            except Exception as exc:
                errors.append((scene, exc))
                logger.error("Shot %02d failed: %s", scene, exc)

    if errors:
        detail = "; ".join(f"shot {n}: {e}" for n, e in sorted(errors))
        raise RuntimeError(f"{len(errors)} of {total} shots failed -- {detail}")

    logger.info("All %d clips generated successfully.", total)
    return results
