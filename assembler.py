"""
assembler.py — Stitch Higgsfield clips + TTS audio + caption overlays into
the final MP4 using MoviePy.

Dependencies: moviepy==1.0.3, ImageMagick (for TextClip rendering).
Install ImageMagick and ensure the `magick` / `convert` binary is on PATH,
then set IMAGEMAGICK_BINARY in your .env if it differs from the default.
"""

# Patch for Pillow 10+ compatibility — moviepy 1.0.3 uses Image.ANTIALIAS
# which was removed in Pillow 10.0.0. This must run before moviepy is imported.
from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import logging
import os
import textwrap
from pathlib import Path
import config

logger = logging.getLogger(__name__)

# Optional: override the ImageMagick binary path via env
_MAGICK_BINARY = os.getenv("IMAGEMAGICK_BINARY", "")

# Lazy import so the rest of the app works even if moviepy is missing
def _import_moviepy():
    try:
        from moviepy.editor import (
            VideoFileClip,
            AudioFileClip,
            TextClip,
            CompositeVideoClip,
            concatenate_videoclips,
        )
        if _MAGICK_BINARY:
            from moviepy.config import change_settings
            change_settings({"IMAGEMAGICK_BINARY": _MAGICK_BINARY})
        return VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
    except ImportError as e:
        raise ImportError(
            "MoviePy is not installed. Run: pip install moviepy==1.0.3"
        ) from e


# ── Constants ─────────────────────────────────────────────────────────────────
TARGET_WIDTH  = 1920
TARGET_HEIGHT = 1080
TARGET_FPS    = 24
CAPTION_FONT  = "Arial-Bold"
CAPTION_SIZE  = 48
CAPTION_COLOR = "white"
CAPTION_STROKE_COLOR = "black"
CAPTION_STROKE_WIDTH = 2
CAPTION_MARGIN_BOTTOM = 90   # pixels from bottom edge
MAX_CAPTION_CHARS = 60       # wrap long segments


def _make_caption_clip(text: str, duration: float, video_w: int, video_h: int):
    """
    Build a semi-transparent captioned TextClip for one shot.
    Returns a positioned TextClip or None if TextClip creation fails.
    """
    (
        VideoFileClip, AudioFileClip, TextClip,
        CompositeVideoClip, concatenate_videoclips
    ) = _import_moviepy()

    # Wrap long text
    wrapped = "\n".join(textwrap.wrap(text, width=MAX_CAPTION_CHARS))

    try:
        txt = TextClip(
            wrapped,
            fontsize=CAPTION_SIZE,
            font=CAPTION_FONT,
            color=CAPTION_COLOR,
            stroke_color=CAPTION_STROKE_COLOR,
            stroke_width=CAPTION_STROKE_WIDTH,
            method="caption",
            size=(video_w - 160, None),   # constrain width, auto height
            align="center",
        )
        txt = txt.set_duration(duration)
        txt = txt.set_position(("center", video_h - txt.h - CAPTION_MARGIN_BOTTOM))
        return txt
    except Exception as exc:
        logger.warning("Caption creation failed (%s) — skipping captions for this clip.", exc)
        return None


def assemble_video(
    enriched_shots: list[dict],
    voiceover_path: str,
    output_path: str,
) -> str:
    """
    Combine all clips + audio + captions into the final deliverable MP4.

    Args:
        enriched_shots: Shot dicts, each with 'clip_path', 'voiceover_segment',
                        and 'duration_seconds'.
        voiceover_path: Path to the TTS MP3 file.
        output_path:    Where to write the final MP4.

    Returns:
        output_path on success.
    """
    (
        VideoFileClip, AudioFileClip, TextClip,
        CompositeVideoClip, concatenate_videoclips
    ) = _import_moviepy()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Load and normalise each clip ─────────────────────────────────────────
    processed_clips = []
    for shot in enriched_shots:
        clip_path = shot["clip_path"]
        target_dur = float(shot["duration_seconds"])
        caption_text = shot.get("voiceover_segment", "")

        logger.info("Processing clip: %s", clip_path)
        clip = VideoFileClip(clip_path)

        # Trim or extend (freeze-frame) to target duration
        actual_dur = clip.duration
        if actual_dur > target_dur:
            clip = clip.subclip(0, target_dur)
        elif actual_dur < target_dur:
            # Freeze the last frame to pad
            from moviepy.video.fx.freeze import freeze
            clip = freeze(clip, t=actual_dur - 0.05, total_duration=target_dur)

        # Resize to 1920×1080
        clip = clip.resize((TARGET_WIDTH, TARGET_HEIGHT))
        clip = clip.set_fps(TARGET_FPS)

        # Mute the original audio — we'll replace with TTS
        clip = clip.without_audio()

        # Caption overlay
        caption = _make_caption_clip(caption_text, clip.duration, TARGET_WIDTH, TARGET_HEIGHT)
        if caption is not None:
            clip = CompositeVideoClip([clip, caption])

        processed_clips.append(clip)

    # ── Concatenate ───────────────────────────────────────────────────────────
    logger.info("Concatenating %d clips...", len(processed_clips))
    final_video = concatenate_videoclips(processed_clips, method="compose")

    # ── Add TTS audio ─────────────────────────────────────────────────────────
    logger.info("Attaching voiceover audio from '%s'...", voiceover_path)
    tts_audio = AudioFileClip(voiceover_path)

    # Trim audio if it's longer than the video; otherwise let video run silent at end
    if tts_audio.duration > final_video.duration:
        tts_audio = tts_audio.subclip(0, final_video.duration)

    final_video = final_video.set_audio(tts_audio)

    # ── Export ────────────────────────────────────────────────────────────────
    logger.info("Exporting final video to '%s'...", output_path)
    final_video.write_videofile(
        output_path,
        fps=TARGET_FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=output_path.replace(".mp4", "_tmp_audio.m4a"),
        remove_temp=True,
        logger=None,  # suppress moviepy's own progress bar in logs
    )

    # Cleanup
    final_video.close()
    tts_audio.close()
    for c in processed_clips:
        try:
            c.close()
        except Exception:
            pass

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info("Final video saved: %s (%.1f MB)", output_path, size_mb)
    return output_path
