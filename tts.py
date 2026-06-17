"""
tts.py — Convert voiceover text to speech using OpenAI TTS and save as MP3.
"""

import logging
import os
from pathlib import Path
from openai import OpenAI
import config

logger = logging.getLogger(__name__)


def generate_voiceover(text: str, output_path: str) -> str:
    """
    Generate a spoken MP3 from the full voiceover script.

    Args:
        text:        The complete voiceover text.
        output_path: Where to save the MP3 (e.g. "outputs/job_abc/voiceover.mp3").

    Returns:
        The path to the saved MP3.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    logger.info("Generating TTS voiceover (%d chars)...", len(text))

    response = client.audio.speech.create(
        model=config.TTS_MODEL,
        voice=config.TTS_VOICE,
        input=text,
        response_format="mp3",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    response.stream_to_file(output_path)

    size_kb = os.path.getsize(output_path) / 1024
    logger.info("Voiceover saved to '%s' (%.1f KB)", output_path, size_kb)
    return output_path
