"""
storyboard.py - Call Claude to generate a fully structured shot-list JSON.

Supports 12 business types, each with a custom shot structure and voiceover style
so the commercial feels tailor-made for that category.
"""

import json
import logging
import re
import anthropic
import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS TYPE DEFINITIONS
# Each entry has:
#   label       - display name
#   subject     - what to call "the thing" in the user message
#   shots       - 5-shot structure description for Claude
#   voiceover   - copywriting style guidance
#   prominence  - which shots must prominently feature the key subject
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_TYPES = {

    "product": {
        "label": "Physical Product",
        "subject": "Product",
        "shots": """\
Shot 1 — WORLD ESTABLISH: Wide or aerial shot creating the world and mood. Product may be distant or implied.
Shot 2 — PRODUCT HERO: The product is the undeniable star. Cinematic beauty shot. Make it gorgeous and desirable.
Shot 3 — LIFESTYLE / EMOTION: A person experiencing or benefiting from the product. Human connection and feeling.
Shot 4 — FEATURE DETAIL: Extreme close-up on a specific feature, texture, or unique quality of the product.
Shot 5 — BRAND CLOSE: Aspirational closing shot. Product prominent. Leaves the viewer wanting it immediately.""",
        "voiceover": "Benefit-driven, punchy. Lead with the transformation the product creates. Highlight what makes it unique. Close with a strong CTA that creates urgency.",
        "prominence": "The product must be visually prominent and recognizable in shots 2, 4, and 5.",
    },

    "medical": {
        "label": "Health & Medical",
        "subject": "Practice / Service",
        "shots": """\
Shot 1 — WELCOMING SPACE: Clean, modern, calming medical/clinic environment. Warm lighting, professional but approachable.
Shot 2 — EXPERT IN ACTION: Doctor, dentist, or specialist performing their work — confident, skilled, caring expression.
Shot 3 — PATIENT EXPERIENCE: Patient looking visibly comfortable, relieved, or mid-positive-experience. Human and emotional.
Shot 4 — PRECISION DETAIL: Close-up of professional hands, specialized equipment, or a treatment being carefully delivered.
Shot 5 — POSITIVE OUTCOME: Patient leaving with a smile, a healed result shown, or a trust-building moment with staff.""",
        "voiceover": "Empathetic and authoritative. Open with the patient's pain point or fear. Show expertise and care. Close with relief, confidence, and a clear CTA (call today, book online).",
        "prominence": "The medical professional must appear confident and caring in shots 2 and 5. The clinic environment must feel clean and modern throughout.",
    },

    "spa": {
        "label": "Beauty & Spa",
        "subject": "Spa / Salon Service",
        "shots": """\
Shot 1 — SANCTUARY REVEAL: Luxurious, serene spa or salon interior. Soft lighting, clean lines, instantly relaxing atmosphere.
Shot 2 — SERVICE IN PROGRESS: Skilled professional performing a treatment — massage, facial, styling — with relaxed, glowing client.
Shot 3 — SENSORY DETAIL: Extreme close-up of a product or tool being used — serum dripping, steam rising, brush stroking.
Shot 4 — TRANSFORMATION MOMENT: Client's glowing skin, perfect hair, or expression of pure bliss and relaxation.
Shot 5 — BRAND CLOSE: Serene closing — candles, flowers, the space in perfect light — or radiant client with quiet confidence.""",
        "voiceover": "Indulgent, sensory, aspirational. Paint a picture of escape and transformation. Speak to the stress they carry and the peace they'll find. Close with an inviting, gentle CTA.",
        "prominence": "The service and its results must be visible in shots 2, 3, and 4. The environment must feel luxurious and immaculate throughout.",
    },

    "home_services": {
        "label": "Home Services",
        "subject": "Service / Company",
        "shots": """\
Shot 1 — THE PROBLEM: A realistic home scene hinting at the issue — a leaking pipe, dark circuit panel, broken HVAC — subtle stress in the environment.
Shot 2 — PROFESSIONAL ARRIVAL: Uniformed technician walking confidently toward the camera or door, branded truck visible behind them.
Shot 3 — EXPERT AT WORK: Close and dynamic — professional hands working with precision, tools in use, focused and competent.
Shot 4 — THE FIX COMPLETE: The repaired/installed result in perfect condition — clean, finished, professional-grade workmanship detail.
Shot 5 — HOMEOWNER RELIEF: Happy homeowner in their now-resolved space — bright, warm, problem gone. Handshake or thumbs-up moment.""",
        "voiceover": "Reliable, direct, trustworthy. Open with the stress of the problem. Establish speed, expertise, and reliability. Close with a bold guarantee or fast-response CTA.",
        "prominence": "The uniformed professional must appear competent and clean in shots 2, 3, and 5. The resolution and craftsmanship must be clear in shot 4.",
    },

    "restaurant": {
        "label": "Restaurant & Food",
        "subject": "Restaurant / Food Business",
        "shots": """\
Shot 1 — AMBIANCE ESTABLISH: The restaurant's atmosphere — warm lighting, beautiful table settings, the energy of the space at golden hour.
Shot 2 — SIGNATURE DISH HERO: The most stunning dish on the menu, plated to perfection. This is the star. Make it mouthwatering.
Shot 3 — KITCHEN IN ACTION: Chefs at work — flames, precision plating, fresh ingredients being prepared with passion and skill.
Shot 4 — SENSORY DETAIL: Extreme close-up — steam rising from a dish, sauce being poured, a perfect cross-section, glistening textures.
Shot 5 — GUEST EXPERIENCE: Happy diners sharing a meal, laughing, savoring — or a final beauty shot of the dish being served tableside.""",
        "voiceover": "Sensory and inviting. Make the viewer taste it through words. Speak to the experience, not just the food. Close with a warm invitation to come in or order now.",
        "prominence": "The food must be the visual hero in shots 2 and 4. The restaurant atmosphere must feel warm and inviting throughout.",
    },

    "fitness": {
        "label": "Fitness & Wellness",
        "subject": "Gym / Studio / Service",
        "shots": """\
Shot 1 — ENERGY ESTABLISH: The gym, studio, or outdoor training environment — powerful, dynamic, motivating atmosphere.
Shot 2 — PEAK PERFORMANCE: A person training at full intensity — perfect form, visible effort, powerful and inspiring.
Shot 3 — COACH / INSTRUCTOR: Expert trainer in action — motivating a client, correcting form, leading with energy and expertise.
Shot 4 — DETERMINATION DETAIL: Extreme close-up — gripping weights, sweat on skin, focused eyes, muscles engaged — raw and real.
Shot 5 — ACHIEVEMENT MOMENT: Person completing a set, crossing a finish line, or standing triumphant — transformed, empowered, energized.""",
        "voiceover": "Motivational and high-energy. Challenge the viewer. Speak to who they want to become. Use short, punchy sentences that hit like reps. End with a powerful call to action.",
        "prominence": "Human performance and transformation must drive shots 2, 4, and 5. The facility must look professional and high-energy throughout.",
    },

    "real_estate": {
        "label": "Real Estate",
        "subject": "Property / Agency",
        "shots": """\
Shot 1 — EXTERIOR REVEAL: Stunning property exterior — drone pull-back or wide shot at golden hour, showcasing curb appeal.
Shot 2 — INTERIOR HERO: The most impressive interior space — living room, kitchen, or master suite — beautifully lit and styled.
Shot 3 — LIFESTYLE MOMENT: A person or family naturally enjoying the space — morning coffee, kids playing, dinner — emotional connection.
Shot 4 — ARCHITECTURAL DETAIL: Premium finishes in close-up — marble countertops, custom cabinetry, a fireplace, panoramic windows.
Shot 5 — DREAM CLOSE: Sunset or golden-hour shot of the exterior, or an aspirational lifestyle moment that says "this is the life you deserve.""",
        "voiceover": "Aspirational and evocative. Don't sell square footage — sell the life. Speak to what it feels like to live there. Close with urgency (limited homes, call today).",
        "prominence": "The property must be visually stunning and prominently featured in shots 1, 2, and 4. Lifestyle emotion must drive shots 3 and 5.",
    },

    "professional": {
        "label": "Professional Services",
        "subject": "Firm / Practice",
        "shots": """\
Shot 1 — AUTHORITY ESTABLISH: A polished professional office or workspace — confident, organized, successful. Instills immediate trust.
Shot 2 — EXPERT CONSULTATION: Professional in engaged conversation with a client — listening, advising, solution-focused body language.
Shot 3 — THE COMPLEXITY RESOLVED: A visual metaphor of order from chaos — organized documents, a decisive handshake, a clear strategy on screen.
Shot 4 — PRECISION DETAIL: Close-up of professional at work — writing, analyzing data, signing a document — focused and capable.
Shot 5 — CLIENT SUCCESS MOMENT: Client leaving with confidence and relief, a handshake closing a deal, or a celebration of a successful outcome.""",
        "voiceover": "Authoritative and reassuring. Open with the problem your clients face. Establish your expertise and track record. Close with confidence and a clear next step.",
        "prominence": "The professional must project confidence and expertise in shots 2, 4, and 5. The office environment must feel polished and successful throughout.",
    },

    "automotive": {
        "label": "Automotive",
        "subject": "Dealership / Auto Service",
        "shots": """\
Shot 1 — VEHICLE REVEAL: A stunning hero car shot — low angle, dramatic lighting, showroom or open road. Power and beauty.
Shot 2 — EXPERT SERVICE: Technician working on a vehicle with precision, or salesperson walking a customer through a car with genuine enthusiasm.
Shot 3 — INTERIOR / DETAIL HERO: The cabin, dashboard, or a specific premium feature — leather, technology, engineering craft up close.
Shot 4 — THE RESULT: A gleaming, finished vehicle — washed, detailed, showroom-ready — parked in perfect light.
Shot 5 — CUSTOMER DRIVE-AWAY: Happy customer behind the wheel pulling out, or receiving keys — pride, satisfaction, and freedom.""",
        "voiceover": "Bold and confident. Speak to performance, trust, and value. For dealerships: speak to the experience. For service shops: speak to reliability and expertise. Strong CTA.",
        "prominence": "The vehicle must be the visual star in shots 1, 4, and 5. Human expertise and customer satisfaction must drive shots 2 and 5.",
    },

    "education": {
        "label": "Education & Coaching",
        "subject": "School / Program / Coach",
        "shots": """\
Shot 1 — LEARNING ENVIRONMENT: An inspiring classroom, training space, or online studio setup — bright, organized, motivating.
Shot 2 — TEACHING MOMENT: Instructor teaching with passion and clarity — engaged with students, animated, clearly an expert.
Shot 3 — STUDENT BREAKTHROUGH: A student's face showing genuine understanding or excitement — the "aha moment" — authentic and powerful.
Shot 4 — SKILL IN ACTION: Close-up of a student applying what they've learned — hands on keyboard, practicing, creating, building.
Shot 5 — ACHIEVEMENT / TRANSFORMATION: Student or graduate looking confident and empowered — the before/after transformation completed.""",
        "voiceover": "Inspiring and empowering. Open with the limitation or frustration the student faces. Show the transformation your program delivers. Close with a motivating invitation to begin.",
        "prominence": "The instructor must project expertise and passion in shot 2. Student transformation must be visible and emotional in shots 3 and 5.",
    },

    "retail": {
        "label": "Retail Store",
        "subject": "Store / Brand",
        "shots": """\
Shot 1 — STORE REVEAL: Inviting storefront or beautifully merchandised interior — warm, welcoming, visually rich.
Shot 2 — PRODUCT SHOWCASE: Hero shot of signature or best-selling items — beautifully displayed, styled, irresistible.
Shot 3 — DISCOVERY MOMENT: A customer's eyes lighting up while discovering something — authentic, joyful, the thrill of finding it.
Shot 4 — CRAFTSMANSHIP DETAIL: Close-up of product quality — texture, stitching, material, finish — the details that justify the choice.
Shot 5 — HAPPY CUSTOMER: Satisfied shopper leaving with their purchase, or a warm moment at checkout — the joy of the find.""",
        "voiceover": "Warm and inviting with a hint of excitement. Speak to discovery, quality, and the joy of finding exactly what you were looking for. Close with an invitation to visit or shop.",
        "prominence": "Products must be visually prominent and beautiful in shots 2 and 4. The store atmosphere must feel inviting throughout.",
    },

    "general": {
        "label": "General Business",
        "subject": "Business / Brand",
        "shots": """\
Shot 1 — BRAND WORLD ESTABLISH: Wide, atmospheric shot that immediately conveys the essence and world of this business.
Shot 2 — THE CORE OFFER: The most important thing this business does or provides — shown clearly, beautifully, and compellingly.
Shot 3 — HUMAN CONNECTION: A real person (customer or team member) experiencing genuine benefit or joy from this business.
Shot 4 — QUALITY DETAIL: Close-up that proves the standard — craftsmanship, care, precision, or the unique differentiator.
Shot 5 — BRAND CLOSE: A confident, aspirational closing shot that leaves the viewer knowing exactly what this business stands for.""",
        "voiceover": "Clear, confident, and emotionally resonant. Open with the problem or desire. Show the solution this business provides. Close with a compelling reason to act now.",
        "prominence": "The business's core offer must be visually clear in shots 2 and 4. Human emotion and connection must drive shots 3 and 5.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STATIC CINEMATOGRAPHY RULES (shared across all business types)
# ─────────────────────────────────────────────────────────────────────────────
_CINEMATOGRAPHY_RULES = """\
═══════════════════════════════════════════════
HIGGSFIELD PROMPT FORMULA — use ALL elements in every prompt
═══════════════════════════════════════════════
[MAIN SUBJECT & ACTION] + [ENVIRONMENT & SET DESIGN] + [LIGHTING SETUP] + [CAMERA MOVEMENT] + [ATMOSPHERIC DETAILS] + [FILM QUALITY MARKERS]

CAMERA MOVEMENTS — one per shot, never static:
• "slow cinematic push-in towards [subject]"
• "low-angle ground-level tracking shot following [subject]"
• "dramatic drone pull-back revealing [scene]"
• "smooth orbital rotation around [subject]"
• "handheld intimate follow shot of [person]"
• "rack focus from foreground blur to sharp [subject]"
• "crane shot rising above [subject]"
• "extreme slow-motion close-up with subtle micro camera drift"
• "dolly zoom pulling focus from background to [subject]"

LIGHTING — be specific per shot:
• Golden hour: "warm golden hour backlight, long soft shadows, lens flare kissing the edge of frame"
• Studio: "three-point lighting, large soft box key light, hairline rim light separating subject from dark background"
• Moody: "single practical light source, deep shadows, volumetric light rays cutting through darkness"
• Luxury: "cool blue ambient fill contrasted with warm tungsten practicals, sharp specular highlights"
• Natural: "overcast diffused daylight, soft even illumination, true-to-life color rendering"
• Clinical: "bright, even, shadowless white light, clean and hygienic, professional medical lighting"

ATMOSPHERIC DETAILS — always include at least one per shot:
steam rising, condensation droplets on glass, floating dust particles in light beams,
slow-motion liquid splash, fabric billowing softly, wisps of smoke or vapor, bokeh light orbs,
morning mist, surfaces glistening, warm breath vapor, swirling foam or liquid, golden particles floating,
fresh steam from hot coffee, sunlight through blinds casting stripe shadows, slow-motion water droplets

FILM QUALITY MARKERS — end every single prompt with these exact words:
"shot on ARRI Alexa Mini LF, anamorphic 2.39:1 widescreen, extremely shallow depth of field, \
photorealistic 8K, luxury commercial grade, safe for all audiences, no nudity, no violence, no text, no watermarks"

═══════════════════════════════════════════════
EXAMPLE of an excellent Higgsfield prompt (study this)
═══════════════════════════════════════════════
"A sleek obsidian glass bottle of premium cold brew coffee sits on a wet black granite countertop, \
surrounded by scattered whole roasted coffee beans, inside a dark moody upscale kitchen set. \
Three-point product lighting: large soft box key light from camera left, cool blue rim light \
separating the bottle from the black background, warm amber fill catching condensation droplets \
glistening on the glass surface. Smooth orbital rotation around the bottle from a low 15-degree hero angle. \
Wisps of cold vapor drift from the bottle cap, bokeh circles from kitchen pendant lights float in background. \
Shot on ARRI Alexa Mini LF, anamorphic 2.39:1 widescreen, extremely shallow depth of field, \
photorealistic 8K, luxury commercial grade, safe for all audiences, no nudity, no violence, no text, no watermarks."

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
5. Output ONLY the JSON. Nothing else."""


def _build_prompt(business_type: str) -> str:
    """Build the complete director system prompt for the given business type."""
    bt = BUSINESS_TYPES.get(business_type) or BUSINESS_TYPES["general"]

    return f"""You are a world-class Commercial Director and AI Prompt Engineer with credits on \
Super Bowl spots, luxury brand campaigns, and award-winning service business commercials. \
You specialize in Higgsfield AI video generation and know exactly how to craft prompts \
that produce stunning, cinematic, award-winning visuals for ANY type of business.

Your job: take this client brief and produce a 5-shot commercial that looks like it cost $500,000 to make.

═══════════════════════════════════════════════
BUSINESS CATEGORY: {bt['label'].upper()}
SHOT STRUCTURE — follow this exactly:
═══════════════════════════════════════════════
{bt['shots']}

VISUAL PROMINENCE RULE: {bt['prominence']}

VOICEOVER STYLE FOR THIS CATEGORY:
{bt['voiceover']}

{_CINEMATOGRAPHY_RULES}"""


def generate_storyboard(
    product_name: str,
    target_audience: str,
    tone: str,
    key_benefits: str = "",
    business_type: str = "product",
) -> dict:
    """
    Call Claude with the director system prompt and client brief.
    Returns the parsed shot-list dict.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    bt = BUSINESS_TYPES.get(business_type) or BUSINESS_TYPES["general"]
    subject_label = bt["subject"]

    benefits_line = (
        f"Key Benefits / What Makes It Unique: {key_benefits}\n"
        if key_benefits else ""
    )

    user_message = (
        f"{subject_label} Name: {product_name}\n"
        f"Target Audience: {target_audience}\n"
        f"Tone / Style: {tone}\n"
        f"{benefits_line}"
        f"\nIMPORTANT: Every shot and every voiceover line must directly and unmistakably "
        f"represent THIS specific {subject_label.lower()} — '{product_name}'. "
        "Do NOT use generic visuals. The viewer must know exactly what this business is "
        "and why they should choose it within the first 5 seconds.\n\n"
        "Generate a complete video shot list. Output ONLY the raw JSON object."
    )

    system_prompt = _build_prompt(business_type)
    logger.info(
        "Generating storyboard for '%s' [type=%s]...", product_name, business_type
    )

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    logger.debug("Raw storyboard (first 200 chars):\n%s", raw[:200])

    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    # Extract JSON object if surrounded by text
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        raw = json_match.group(0)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raw_fixed = re.sub(r',\s*([}\]])', r'\1', raw)
        try:
            result = json.loads(raw_fixed)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse storyboard JSON:\n%s", raw)
            raise ValueError(f"Claude returned invalid JSON: {e}") from e

    if not isinstance(result, dict):
        raise ValueError(f"Storyboard must be a JSON object, got: {type(result).__name__}")
    if "full_voiceover" not in result or "shots" not in result:
        raise ValueError(f"Storyboard missing required keys. Got: {list(result.keys())}")

    logger.info(
        "Storyboard generated: '%s' — %d shots, ~%s seconds",
        result.get("project_title", "Untitled"),
        len(result.get("shots", [])),
        result.get("total_estimated_duration", "?"),
    )
    return result
