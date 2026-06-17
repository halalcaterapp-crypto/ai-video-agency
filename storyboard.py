"""
storyboard.py — Call Claude to generate a fully structured shot-list JSON
from a client brief (product name, target audience, tone).
"""

import json
import logging
import anthropic
import config

logger = logging.getLogger(__name__)

DIRECTOR_SYSTEM_PROMPT = """You are an expert Commercial Video Director and AI Prompt Engineer
specializing in Higgsfield AI video generation. Your job is to take a raw client brief and convert
it into a fully structured video production shot list.

You must design a sequence of short video clips (2 to 5 seconds each) that visually match a
compelling voiceover.

HIGGSFIELD PROMPTING RULES:
To get the best results from Higgsfield, your visual prompts must follow this exact formula:
[Subject & Action] + [Environment/Setting] + [Lighting] + [Camera Angle & Movement] + [Overall Vibe/Format]

Example of a good Higgsfield prompt:
"A sleek black sports car driving on a rain-slicked neon cyberpunk city street, volumetric lighting
reflecting off puddles, low angle tracking shot following the car, cinematic 8k resolution, photorealistic."

STRICT OUTPUT RULES:
1. You must output ONLY valid, raw JSON — no markdown fences, no commentary.
2. The JSON must strictly follow this schema:
{
  "project_title": "A catchy title for the video",
  "full_voiceover": "The complete spoken script for the video.",
  "total_estimated_duration": "Total seconds as a number string, e.g. 30",
  "shots": [
    {
      "scene_number": 1,
      "voiceover_segment": "The specific sentence spoken during this shot",
      "duration_seconds": 4,
      "higgsfield_prompt": "Your highly detailed visual prompt following the formula above."
    }
  ]
}
3. Produce between 6 and 10 shots. Keep the total voiceover under 60 seconds.
4. Every higgsfield_prompt must be photorealistic, cinematic, and detailed."""


def generate_storyboard(product_name: str, target_audience: str, tone: str) -> dict:
    """
    Call Claude with the director system prompt and client brief.
    Returns the parsed shot-list dict.

    Args:
        product_name:     e.g. "ProSleep Pillow"
        target_audience:  e.g. "busy professionals aged 30-45 who struggle with sleep"
        tone:             e.g. "calm, premium, aspirational"

    Returns:
        dict matching the schema above
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    user_message = (
        f"Product: {product_name}\n"
        f"Target Audience: {target_audience}\n"
        f"Tone / Style: {tone}\n\n"
        "Generate a complete video shot list for this product. Output ONLY the raw JSON — no other text."
    )

    logger.info("Calling Claude to generate storyboard for '%s'...", product_name)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=DIRECTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    storyboard = json.loads(raw)
    logger.info(
        "Storyboard generated: '%s' — %d shots, ~%s seconds",
        storyboard.get("project_title"),
        len(storyboard.get("shots", [])),
        storyboard.get("total_estimated_duration"),
    )
    return storyboard
