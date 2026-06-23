"""
assembler.py - Stitch Higgsfield clips + TTS audio into the final MP4.
Uses ffmpeg subprocess instead of MoviePy to avoid OOM on Railway's 512MB limit.
ffmpeg streams each clip without loading everything into RAM at once.
"""

import logging
import os
import subprocess
from pathlib import Path
import imageio_ffmpeg

logger = logging.getLogger(__name__)

TARGET_WIDTH  = 1280
TARGET_HEIGHT = 720
TARGET_FPS    = 24

# Use bundled ffmpeg binary from imageio-ffmpeg (no system install needed)
_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
logger.info("Using ffmpeg: %s", _FFMPEG_EXE)


def _ffmpeg(args, desc="ffmpeg"):
    cmd = [_FFMPEG_EXE, "-y"] + args
    logger.info("ffmpeg [%s]: %s", desc, " ".join(cmd[-6:]))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg stderr:\n%s", result.stderr[-1500:])
        raise RuntimeError(f"ffmpeg failed ({desc}): {result.stderr[-400:]}")
    return result


def assemble_video(enriched_shots, voiceover_path, output_path):
    """
    Combine all clips + audio into the final MP4 using ffmpeg subprocess.

    Args:
        enriched_shots: Shot dicts with 'clip_path', 'duration_seconds', 'scene_number'.
        voiceover_path: Path to the TTS MP3 file.
        output_path:    Where to write the final MP4.

    Returns:
        output_path on success.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    job_dir = str(Path(output_path).parent)

    # Step 1: Normalize each clip to target resolution/fps, trim to duration
    normalized = []
    for shot in enriched_shots:
        clip_path  = shot["clip_path"]
        target_dur = min(float(shot.get("duration_seconds", 3)), 5.0)
        scene_num  = shot["scene_number"]
        out = os.path.join(job_dir, f"norm_{scene_num:02d}.mp4")

        logger.info("Normalizing shot %02d (%.1fs) ...", scene_num, target_dur)
        _ffmpeg([
            "-i", clip_path,
            "-vf", (
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={TARGET_FPS}"
            ),
            "-t", str(target_dur),
            "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            out,
        ], f"normalize shot {scene_num}")
        normalized.append(out)
        logger.info("Shot %02d normalized -> %s", scene_num, out)

    # Step 2: Write concat list
    concat_txt = os.path.join(job_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in normalized:
            # Use basename only — ffmpeg resolves paths relative to concat.txt's directory
            f.write(f"file '{os.path.basename(p)}'\n")

    # Step 3: Concatenate clips
    concat_mp4 = os.path.join(job_dir, "concat_video.mp4")
    logger.info("Concatenating %d clips ...", len(normalized))
    _ffmpeg([
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c", "copy",
        concat_mp4,
    ], "concat")
    logger.info("Clips concatenated -> %s", concat_mp4)

    # Step 4: Mix voiceover audio
    logger.info("Mixing voiceover from '%s' ...", voiceover_path)
    _ffmpeg([
        "-i", concat_mp4,
        "-i", voiceover_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ], "audio mix")
    logger.info("Assembly complete: %s", output_path)

    # Cleanup temp files
    for p in normalized + [concat_txt, concat_mp4]:
        try:
            os.remove(p)
        except Exception:
            pass

    return output_path
