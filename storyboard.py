"""
storyboard.py - Call Claude to generate a fully structured shot-list JSON
from a client brief (product name, target audience, tone).
"""

import json
import logging
import re
import anthropic
import config

logger = logging.getLogger(__name__)

DIRECTOR_SYSTEM_PROMPT = """You are a world-class Commercial Director and AI Prompt Engineer with credits on \
Super Bowl spots and luxury brand campaigns. You specialize in Higgsfield AI video generation and know \
exactly how to craft prompts that produce stunning, cinematic, award-winning visuals.

Your job: take a client brief and produce a 5-shot commercial that looks like it cost $500,000 to make.

═══════════════════════════════════════════════
SHOT STRUCTURE — follow this exactly for all 5 shots
═══════════════════════════════════════════════
Shot 1 — WORLD ESTABLISH: A wide or aerial shot that creates the world and mood. Product may be distant or implied.
Shot 2 — PRODUCT HERO: The product is the undeniable star. Beauty shot. Make it gorgeous and desirable.
Shot 3 — LIFESTYLE / EMOTION: A person experiencing or benefiting from the product. Human connection. Feeling.
Shot 4 — PRODUCT FEATURE DETAIL: Extreme close-up on a specific feature, texture, or unique quality of the product.
Shot 5 — BRAND CLOSE: Cinematic closing shot. Product prominent. Aspirational. Leaves the viewer wanting it.

═══════════════════════════════════════════════
HIGGSFIELD PROMPT FORMULA — every prompt must use ALL of these elements
═══════════════════════════════════════════════
[PRODUCT FOCUS] + [ENVIRONMENT & SET DESIGN] + [LIGHTING SETUP] + [CAMERA MOVEMENT] + [ATMOSPHERIC DETAILS] + [FILM QUALITY MARKERS]

CAMERA MOVEMENTS — pick one dynamic movement per shot, never use a static camera:
• "slow cinematic push-in towards [subject]"
• "low-angle ground-level tracking shot following [subject]"
• "dramatic drone pull-back revealing [scene]"
• "smooth orbital rotation around [product]"
• "handheld intimate follow shot of [person]"
• "rack focus from foreground blur to sharp [product]"
• "crane shot rising above [subject]"
• "extreme slow-motion close-up with subtle micro camera drift"

LIGHTING — be specific, not generic. Choose one style per shot:
• Golden hour: "warm golden hour backlight, long soft shadows, lens flare kissing the edge of frame"
• Studio product: "three-point product lighting, large soft box key light, hairline rim light separating product from dark background"
• Moody: "single practical light source, deep shadows, volumetric light rays cutting through darkness"
• Luxury: "cool blue ambient fill contrasted with warm tungsten practicals, sharp specular highlights on surfaces"
• Natural: "overcast diffused daylight, soft even illumination, true-to-life color rendering"

ATMOSPHERIC DETAILS — always include at least one per shot:
steam rising, condensation droplets on glass, floating dust particles in light beams, \
slow-motion liquid splash, silk fabric billowing, wisps of smoke, bokeh light orbs, \
morning mist, crushed ice glistening, wet surface reflections, breath vapor in cold air, \
slow swirling foam, golden pollen floating

FILM QUALITY MARKERS — end every single prompt with these exact words:
"shot on ARRI Alexa Mini LF, anamorphic 2.39:1 widescreen, extremely shallow depth of field, \
photorealistic 8K, luxury commercial grade, safe for all audiences, \
no nudity, no violence, no text, no watermarks"

═══════════════════════════════════════════════
EXAMPLE of an excellent Higgsfield prompt (study this structure)
═══════════════════════════════════════════════
"A sleek obsidian glass bottle of premium cold brew coffee sits on a wet black granite countertop, \
surrounded by scattered whole roasted coffee beans, inside a dark moody upscale kitchen set. \
Three-point product lighting: large soft box key light from camera left, cool blue rim light \
separating the bottle from the black background, warm amber fill catching the condensation droplets \
glistening on the glass surface. Smooth orbital rotation around the bottle starting from a low \
15-degree hero angle. Wisps of cold vapor drift from the bottle cap, bokeh circles from distant \
kitchen pendant lights float in the background. \
Shot on ARRI Alexa Mini LF, anamorphic 2.39:1 widescreen, extremely shallow depth of field, \
photorealistic 8K, luxury commercial grade, safe for all audiences, no nudity, no violence, no text, no watermarks."

═══════════════════════════════════════════════
VOICEOVER RULES
═══════════════════════════════════════════════
• Write like a top-tier copywriter — punchy, benefit-driven, emotionally resonant
• Total script: 15–20 seconds when read aloud at a measured pace (3–4 sentences)
• Opening line must hook immediately — no "Introducing..." or "Meet..." openers
• Every sentence should paint a picture or create a feeling
• Closing line must be a strong call to action or powerful emotional payoff

═══════════════════════════════════════════════
STRICT OUTPUT RULES
═══════════════════════════════════════════════
1. Output ONLY valid raw JSON — NO markdown fences, NO commentary, NO extra text.
2. Follow this exact schema:
{
  "project_title": "Catchy, evocative title",
  "full_voiceover": "The complete 15-20 second spoken script.",
  "total_estimated_duration": 20,
  "shots": [
    {
      "scene_number": 1,
      "voiceover_segment": "The specific line spoken during this shot.",
      "duration_seconds": 4,
      "higgsfield_prompt": "Your full cinematic prompt following all rules above."
    }
  ]
}
3. Exactly 5 shots. Duration per shot: 3–5 seconds each.
4. Every higgsfield_prompt MUST end with the film quality markers.
5. The product must be visually present and prominent in shots 2, 4, and 5.
6. Output ONLY the JSON. Nothing else."""


def generate_storyboard(product_name, target_audience, tone, key_benefits=""):
    """
    Call Claude with the director system prompt and client brief.
    Returns the parsed shot-list dict.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    benefits_line = (
        f"Key Benefits / What Makes It Unique: {key_benefits}\n"
        if key_benefits else ""
    )

    user_message = (
        f"Product: {product_name}\n"
        f"Target Audience: {target_audience}\n"
        f"Tone / Style: {tone}\n"
        f"{benefits_line}"
        "\nIMPORTANT: Every shot and every voiceover line must directly connect to this specific "
        "product and its benefits. Do NOT use generic commercial visuals — make it unmistakably "
        "about THIS product. The viewer should know exactly what the product is and why they need "
        "it within the first 5 seconds.\n\n"
        "Generate a complete video shot list for this product. Output ONLY the raw JSON object."
    )

    logger.info("Calling Claude to generate storyboard for '%s'...", product_name)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=DIRECTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    logger.debug("Raw storyboard response (first 200 chars):\n%s", raw[:200])

    # Strip any accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    # Extract just the JSON object if there is surrounding text
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        raw = json_match.group(0)

    # Try standard parse first, then fall back to relaxed parse
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Remove trailing commas before } or ] which Claude sometimes adds
        raw_fixed = re.sub(r',\s*([}\]])', r'\1', raw)
        try:
            result = json.loads(raw_fixed)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse storyboard JSON. Raw response:\n%s", raw)
            raise ValueError(f"Claude returned invalid JSON: {e}") from e

    if not isinstance(result, dict):
        raise ValueError(f"Storyboard must be a JSON object, got: {type(result).__name__}")

    if "full_voiceover" not in result or "shots" not in result:
        raise ValueError(f"Storyboard missing required keys. Got keys: {list(result.keys())}")

    logger.info(
        "Storyboard generated: '%s' - %d shots, ~%s seconds",
        result.get("project_title", "Untitled"),
        len(result.get("shots", [])),
        result.get("total_estimated_duration", "?"),
    )
    return result
