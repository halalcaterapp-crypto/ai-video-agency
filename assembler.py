"""
assembler.py - Stitch Higgsfield clips + TTS audio + caption overlays into
the final MP4 using MoviePy.
"""

# Patch for Pillow 10+ compatibility - moviepy 1.0.3 uses Image.ANTIALIAS
# which was removed in Pillow 10.0.0. Must run before moviepy is imported.
from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import logging
import os
import textwrap
from pathlib import Path
import config

logger = logging.getLogger(__name__)

_MAGICK_BINARY = os.getenv("IMAGEMAGICK_BINARY", "")

TARGET_WIDTH  = 1280
TARGET_HEIGHT = 720
TARGET_FPS    = 24
CAPTION_FONT  = "Arial-Bold"
CAPTION_SIZE  = 40
CAPTION_COLOR = "white"
CAPTION_STROKE_COLOR = "black"
CAPTION_STROKE_WIDTH = 2
CAPTION_MARGIN_BOTTOM = 60
MAX_CAPTION_CHARS = 60


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
        raise ImportError("MoviePy is not installed. Run: pip install moviepy==1.0.3") from e


def _make_caption_clip(text, duration, video_w, video_h):
    """Build a captioned TextClip for one shot. Returns None on failure."""
    (VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips) = _import_moviepy()
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
            size=(video_w - 160, None),
            align="center",
        )
        txt = txt.set_duration(duration)
        txt = txt.set_position(("center", video_h - txt.h - CAPTION_MARGIN_BOTTOM))
        return txt
    except Exception as exc:
        logger.warning("Caption creation failed (%s) - skipping captions.", exc)
        return None


def assemble_video(enriched_shots, voiceover_path, output_path):
    """
    Combine all clips + audio + captions into the final MP4.

    Args:
        enriched_shots: Shot dicts with 'clip_path', 'voiceover_segment', 'duration_seconds'.
        voiceover_path: Path to the TTS MP3 file.
        output_path:    Where to write the final MP4.

    Returns:
        output_path on success.
    """
    (VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips) = _import_moviepy()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    processed_clips = []
    for shot in enriched_shots:
        clip_path    = shot["clip_path"]
        target_dur   = float(shot["duration_seconds"])
        caption_text = shot.get("voiceover_segment", "")

        logger.info("Processing clip: %s", clip_path)
        clip = VideoFileClip(clip_path)

        # Trim or pad to target duration
        if clip.duration > target_dur:
            clip = clip.subclip(0, target_dur)
        elif clip.duration < target_dur:
            try:
                from moviepy.video.fx.freeze import freeze
                clip = freeze(clip, t=clip.duration - 0.05, total_duration=target_dur)
            except Exception:
                pass  # keep clip at its natural duration if freeze fails

        clip = clip.resize((TARGET_WIDTH, TARGET_HEIGHT))
        clip = clip.set_fps(TARGET_FPS)
        clip = clip.without_audio()

        caption = _make_caption_clip(caption_text, clip.duration, TARGET_WIDTH, TARGET_HEIGHT)
        if caption is not None:
            clip = CompositeVideoClip([clip, caption])

        processed_clips.append(clip)

    logger.info("Concatenating %d clips...", len(processed_clips))
    final_video = concatenate_videoclips(processed_clips, method="compose")

    logger.info("Attaching voiceover from '%s'...", voiceover_path)
    tts_audio = AudioFileClip(voiceover_path)
    if tts_audio.duration > final_video.duration:
        tts_audio = tts_audio.subclip(0, final_video.duration)
    final_video = final_video.set_audio(tts_audio)

    logger.info("Exporting final video to '%s'...", output_path)
    final_video.write_videofile(
        output_path,
        fps=TARGET_FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=output_path.replace(".mp4", "_tmp_audio.m4a"),
        remove_temp=True,
        logger=None,
    )

    final_video.close()
    tts_audio.close()
    for c in processed_clips:
        try:
            c.close()
        except Exception:
            pass

    logger.info("Assembly complete: %s", output_path)
    return output_path
