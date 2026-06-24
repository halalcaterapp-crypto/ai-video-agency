"""
logo_gen.py - Generate an icon+text business logo using OpenAI image generation.

Tries gpt-image-1 (newest, supports transparency) first, falls back to dall-e-2.
Returns a local PNG file path ready for ffmpeg overlay.
"""

import base64
import logging
import os
import requests
import openai
import config

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = (
    "Professional business logo for the brand '{name}'. "
    "Design: a simple icon symbol on the left and the brand name as clean text on the right. "
    "Style: minimalist, modern, vector-like. "
    "Colors: white icon and white text on a solid black background (#000000). "
    "No gradients, no drop shadows, no decorative borders. "
    "Suitable for use as a small video watermark in the corner of a commercial."
)

# Models to try in order, with their extra kwargs
_MODELS = [
    ("gpt-image-1", {"quality": "medium"}),
    ("dall-e-2",    {}),
]


def generate_logo(product_name: str, job_dir: str) -> str:
    """
    Generate a professional icon+text logo for `product_name`.

    Args:
        product_name: The brand/product name to include in the logo text.
        job_dir:      Directory where the PNG will be saved.

    Returns:
        Absolute path to the saved logo PNG.

    Raises:
        RuntimeError: If all image generation models fail.
    """
    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    prompt = PROMPT_TEMPLATE.format(name=product_name)
    logo_path = os.path.join(job_dir, "generated_logo.png")

    last_err = None
    for model, extra_kwargs in _MODELS:
        try:
            logger.info("Generating logo with model '%s' for '%s' ...", model, product_name)
            response = client.images.generate(
                model=model,
                prompt=prompt,
                size="1024x1024",
                n=1,
                **extra_kwargs,
            )
            item = response.data[0]

            # gpt-image-1 returns b64_json; dall-e-2/3 return a URL
            if getattr(item, "b64_json", None):
                img_bytes = base64.b64decode(item.b64_json)
            else:
                img_bytes = requests.get(item.url, timeout=30).content

            with open(logo_path, "wb") as f:
                f.write(img_bytes)

            logger.info("Logo saved via %s -> %s (%d bytes)", model, logo_path, len(img_bytes))
            return logo_path

        except Exception as exc:
            logger.warning("Model '%s' failed: %s — trying next ...", model, exc)
            last_err = exc

    raise RuntimeError(f"All logo generation models failed. Last error: {last_err}")
