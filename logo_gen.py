"""
logo_gen.py - Generate an icon+text business logo using DALL-E 3.

Returns a local PNG file path ready for ffmpeg overlay.
"""

import logging
import os
import requests
import openai
import config

logger = logging.getLogger(__name__)


def generate_logo(product_name: str, job_dir: str) -> str:
    """
    Generate a professional icon+text logo for `product_name` using DALL-E 3.

    Args:
        product_name: The brand/product name to include in the logo text.
        job_dir:      Directory where the PNG will be saved.

    Returns:
        Absolute path to the saved logo PNG.
    """
    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    prompt = (
        f"Professional business logo for the brand '{product_name}'. "
        "Design: a simple icon symbol on the left and the brand name as clean text on the right. "
        "Style: minimalist, modern, vector-like. "
        "Colors: white icon and white text on a solid black background (#000000). "
        "No gradients, no drop shadows, no decorative borders. "
        "Suitable for use as a small video watermark in the corner of a commercial."
    )

    logger.info("Generating logo with DALL-E 3 for '%s' ...", product_name)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    logger.info("DALL-E logo URL received, downloading ...")

    img_bytes = requests.get(image_url, timeout=30).content
    logo_path = os.path.join(job_dir, "generated_logo.png")
    with open(logo_path, "wb") as f:
        f.write(img_bytes)

    logger.info("Logo saved -> %s (%d bytes)", logo_path, len(img_bytes))
    return logo_path
