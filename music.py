"""
music.py - Background music selection and download for video commercials.

Uses royalty-free tracks from Pixabay (CC0 license — free for all commercial use).
Falls back to ffmpeg-generated ambient sound if all downloads fail.
Music is cached in /tmp so it survives the session but re-downloads after restarts.
"""

import logging
import os
import re
import subprocess
import requests
import imageio_ffmpeg

logger = logging.getLogger(__name__)

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_CACHE_DIR = "/tmp/swiftai_music"

# Royalty-free CC0 tracks from Pixabay — grouped by mood
# Multiple fallback URLs per mood in case one goes down
_TONE_TRACKS = {
    "calm": [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
        "https://cdn.pixabay.com/download/audio/2021/04/07/audio_c8d98f9e33.mp3",
    ],
    "energetic": [
        "https://cdn.pixabay.com/download/audio/2022/10/25/audio_946f99aa0c.mp3",
        "https://cdn.pixabay.com/download/audio/2022/08/25/audio_09e2ed3822.mp3",
    ],
    "warm": [
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb749d65c.mp3",
        "https://cdn.pixabay.com/download/audio/2021/11/13/audio_cb4f97dd53.mp3",
    ],
    "luxurious": [
        "https://cdn.pixabay.com/download/audio/2022/10/12/audio_2c897e58db.mp3",
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
    ],
    "informative": [
        "https://cdn.pixabay.com/download/audio/2022/03/10/audio_1a609e7a52.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb749d65c.mp3",
    ],
    "playful": [
        "https://cdn.pixabay.com/download/audio/2022/10/25/audio_946f99aa0c.mp3",
        "https://cdn.pixabay.com/download/audio/2021/08/09/audio_dc39bde808.mp3",
    ],
}

_DEFAULT_TRACKS = _TONE_TRACKS["calm"]


def _tone_key(tone: str) -> str:
    t = tone.lower()
    for key in _TONE_TRACKS:
        if key in t:
            return key
    return "calm"


def _generate_ambient_fallback(output_path: str, duration: int = 40) -> str:
    """
    Generate a simple ambient background using layered sine waves + reverb.
    Used only if all Pixabay downloads fail.
    """
    # A-minor chord (A2, E3, A3, C4, E4) layered softly
    expr = (
        "0.07*sin(110*2*PI*t)+"
        "0.05*sin(165*2*PI*t)+"
        "0.05*sin(220*2*PI*t)+"
        "0.04*sin(262*2*PI*t)+"
        "0.03*sin(330*2*PI*t)"
    )
    cmd = [
        _FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc={expr}:c=stereo:s=44100:d={duration}",
        "-af", "aecho=0.8:0.9:1000|1800:0.3|0.25,lowpass=f=600,volume=0.4",
        "-c:a", "libmp3lame", "-q:a", "5",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True)
    logger.info("Ambient fallback generated -> %s", output_path)
    return output_path


def get_background_music(tone: str = "") -> str | None:
    """
    Return a path to a background music MP3 matching the given tone.
    Downloads on first use, caches for the session. Returns None on total failure.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = _tone_key(tone)
    cache_path = os.path.join(_CACHE_DIR, f"{key}.mp3")

    # Use cached version if valid
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 20_000:
        logger.info("Using cached background music: %s (%s)", cache_path, key)
        return cache_path

    # Try downloading each URL
    urls = _TONE_TRACKS.get(key, _DEFAULT_TRACKS)
    for url in urls:
        try:
            logger.info("Downloading background music [%s]: %s ...", key, url[:70])
            resp = requests.get(
                url, timeout=25, stream=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SwiftAI/1.0)"},
            )
            resp.raise_for_status()
            with open(cache_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            size = os.path.getsize(cache_path)
            if size > 20_000:
                logger.info("Background music ready -> %s (%.1f KB)", cache_path, size / 1024)
                return cache_path
            logger.warning("Downloaded file too small (%d bytes), trying next URL", size)
        except Exception as exc:
            logger.warning("Music download failed (%s): %s", url[:50], exc)

    # All downloads failed — generate ambient fallback so pipeline doesn't lose music
    logger.warning("All music downloads failed — using ambient fallback")
    try:
        return _generate_ambient_fallback(cache_path)
    except Exception as exc:
        logger.error("Ambient fallback generation also failed: %s", exc)
        return None
