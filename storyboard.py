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
Shot 1 — CLINIC ESTABLISH: Pristine, modern medical office exterior or welcoming reception — clean, bright, professional. No people. Architecture and space only.
Shot 2 — PRIMARY SERVICE VISUAL: The hero visual for the clinic's main service. If hypertension/BP management: a sleek blood pressure monitor with crisp digital readout. If diabetes: a modern glucometer with test strips and lancet device arranged beautifully. If cardiology: a glowing EKG waveform or stethoscope on a clean surface. If dental: polished dental instruments laid out precisely. Match the visual to what the key benefits describe — medical equipment only, no people.
Shot 3 — DIAGNOSTIC PRECISION: Close-up of specialized medical equipment in detail — gloved hands operating a device, a diagnostic screen showing clean data, a precisely arranged set of medical tools. Clinical lighting, hyper-detailed, no faces.
Shot 4 — HEALTH OUTCOME VISUAL: A symbolic representation of the health result — a heart rate monitor showing healthy rhythm, a glucometer reading a perfect number, a blood pressure cuff showing normal readings, supplement bottles or prescription packaging in clean arrangement. Abstract and aspirational.
Shot 5 — BRAND CLOSE: A pristine medical office exam room — padded exam table with fresh white paper roll, a wall-mounted otoscope and blood pressure cuff in their holders, a clean counter with neatly arranged medical supplies, soft clinical lighting. No people. The room should look like a private practice exam room, NOT a hospital ward or ER. Intimate, professional, trustworthy.""",
        "voiceover": "Empathetic and authoritative. Open with the patient's health concern. Establish the clinic's expertise and specific services. Name the conditions managed (BP, diabetes, cholesterol, etc.). Close with confidence and a clear CTA — call today, book your appointment.",
        "prominence": "Medical equipment and the clinic environment are the visual heroes throughout. No full human figures — at most gloved hands operating equipment. Every shot must feel clinical, precise, and trustworthy.",
    },

    "spa": {
        "label": "Beauty & Spa",
        "subject": "Spa / Salon Service",
        "shots": """\
Shot 1 — SANCTUARY REVEAL: Luxurious spa or salon interior — soft lighting, pristine treatment table, candles, fresh flowers, calming atmosphere. No people.
Shot 2 — HERO PRODUCT / TOOL: The signature service product or tool as the visual star — a serum bottle with golden liquid dripping from the dropper, a jade roller on marble, hot stone arrangement, professional hair tools gleaming under studio light. Close and beautiful.
Shot 3 — SENSORY DETAIL: Extreme close-up of a treatment material — thick cream swirling, essential oil drops hitting water in slow motion, steam rising from a warm towel, brush strokes of a face mask, bubbles in a foot bath. No faces.
Shot 4 — RESULTS VISUAL: A close-up of radiant, glowing skin texture, smooth hair reflecting light, perfectly manicured nails, or a serene before-and-after skin close-up. The result, not the process.
Shot 5 — BRAND CLOSE: The full spa environment in its most beautiful state — products beautifully arranged, candles glowing, clean surfaces, an invitation to escape. Aspirational and peaceful.""",
        "voiceover": "Indulgent, sensory, aspirational. Paint a picture of escape and transformation. Speak to the stress they carry and the peace they'll find. Close with an inviting, gentle CTA.",
        "prominence": "Products, tools, and results are the visual heroes throughout. No full human figures — at most gloved hands applying a treatment. Environment must feel luxurious and immaculate in every shot.",
    },

    "home_services": {
        "label": "Home Services",
        "subject": "Service / Company",
        "shots": """\
Shot 1 — THE PROBLEM VISUAL: A close-up of the issue itself — a dripping pipe joint with water beads, a sparking electrical panel with loose wires, a cracked HVAC unit, a broken roof tile in the rain. No people. The problem is the story.
Shot 2 — HERO TOOLS: The signature tools of the trade arranged or in action — a gleaming pipe wrench gripping copper pipe, a voltage tester lighting up on a breaker panel, HVAC gauges connected to a unit, roofing nail gun on fresh shingles. Professional grade, cinematic lighting.
Shot 3 — CRAFTSMANSHIP IN ACTION: Gloved or bare hands only — no faces — working with precision. Soldering a clean copper joint, wiring a panel with neat bundled cables, tightening a fitting, sealing a roof seam with perfect technique.
Shot 4 — THE FINISHED RESULT: The completed work in perfect condition — a gleaming new pipe connection with no drips, a clean organized electrical panel with labeled breakers, a brand new HVAC unit humming outside, a pristine roof line. Workmanship as the hero.
Shot 5 — BRAND / TRUCK CLOSE: The company's service truck parked cleanly, logo visible, tools organized in the truck bed — or a wide shot of the repaired home exterior looking perfect. Reliability and professionalism through equipment and results, not people.""",
        "voiceover": "Reliable, direct, trustworthy. Open with the stress of the problem. Establish speed, expertise, and reliability. Name the specific service. Close with a bold guarantee or fast-response CTA.",
        "prominence": "Tools, equipment, and finished work are the undisputed visual heroes. No faces — only hands when needed for context. Every shot must communicate expert craftsmanship through the quality of the work shown.",
    },

    "restaurant": {
        "label": "Restaurant & Food",
        "subject": "Restaurant / Food Business",
        "shots": """\
Shot 1 — AMBIANCE ESTABLISH: The restaurant at its most beautiful — warm lighting, perfect table settings, candles, flowers, the space empty and inviting at golden hour. Architecture and atmosphere only.
Shot 2 — SIGNATURE DISH HERO: The most stunning dish plated to perfection, center frame, steam rising. This is the undeniable star. No people — just the food in all its glory.
Shot 3 — KITCHEN IN ACTION: The cooking process as cinematic art — flames leaping in a pan, sauce being ladle-poured over a dish, fresh herbs being chopped, pasta being tossed, bread coming out of a brick oven. Hands and food only, no faces.
Shot 4 — SENSORY CLOSE-UP: Extreme close-up — a fork cutting into a perfectly seared steak revealing the pink center, sauce drizzled in slow motion, cheese pull, steam rising from a bowl, garnish being placed with tweezers. Pure food porn.
Shot 5 — FINAL PRESENTATION: The hero dish or a spread of signature items in perfect restaurant lighting — a wide beauty shot that makes the viewer immediately want to order.""",
        "voiceover": "Sensory and inviting. Make the viewer taste it through words. Speak to flavors, freshness, and the craft. Close with a warm invitation to come in or order now.",
        "prominence": "Food is the absolute hero in every shot. Restaurant environment supports the food. Hands are acceptable in cooking shots but no faces — let the food do all the talking.",
    },

    "fitness": {
        "label": "Fitness & Wellness",
        "subject": "Gym / Studio / Service",
        "shots": """\
Shot 1 — FACILITY REVEAL: The gym or studio at its most powerful — rows of gleaming equipment, turf stretching into the background, weights racked perfectly, morning light streaming through tall windows. Empty and cinematic.
Shot 2 — EQUIPMENT HERO: The signature equipment of the facility as the visual star — a barbell loaded with weight plates catching the light, a cable machine with perfect chrome details, a rowing machine in motion, a boxing bag hanging in dramatic light.
Shot 3 — TRAINING IN ACTION: Close and dynamic — hands gripping a barbell chalk-covered, feet hitting a treadmill belt in slow motion, a jump rope blurring at speed, weights being racked with authority. Hands and body parts only — no faces needed.
Shot 4 — PRECISION DETAIL: Extreme close-up — a heart rate monitor reading peak performance, sweat beads on skin in slow motion, grip chalk cloud in dramatic light, a fitness tracker showing results, resistance bands under tension.
Shot 5 — FACILITY POWER SHOT: Wide-angle cinematic shot of the full facility — all equipment visible, perfect lighting, the promise of transformation conveyed through the space itself. Aspirational and motivating.""",
        "voiceover": "Motivational and high-energy. Challenge the viewer. Speak to who they want to become. Use short, punchy sentences. Name the equipment and programs available. End with a powerful CTA.",
        "prominence": "Equipment, tools, and the facility are the visual heroes. Body parts in action (hands, feet, arms) are acceptable close-ups. Full-face shots of people should be avoided — let the equipment and environment tell the story.",
    },

    "real_estate": {
        "label": "Real Estate",
        "subject": "Property / Agency",
        "shots": """\
Shot 1 — EXTERIOR REVEAL: Stunning property exterior — drone pull-back or wide shot at golden hour, perfect landscaping, architectural beauty. No people. The home is the star.
Shot 2 — INTERIOR HERO: The most impressive interior space — open-plan living room, gourmet kitchen, or master suite — beautifully staged, perfectly lit, empty and aspirational.
Shot 3 — ARCHITECTURAL DETAIL: Premium finishes in close-up — marble countertop surface, custom cabinetry hardware, a fireplace with dancing flames, floor-to-ceiling windows with a view, hardwood floors gleaming.
Shot 4 — LIFESTYLE ENVIRONMENT: A beautifully set dining table, a coffee mug on a balcony railing with a city view behind it, a perfectly made bed in soft morning light — the suggestion of the life, not people living it.
Shot 5 — DREAM CLOSE: Sunset or golden-hour wide shot of the full property exterior — the home glowing warmly from within, landscaping lit, the promise of this life made visual.""",
        "voiceover": "Aspirational and evocative. Don't sell square footage — sell the life. Speak to what it feels like to live there. Close with urgency — limited homes, call today.",
        "prominence": "The property architecture, interior design, and premium finishes are the heroes in every shot. No people — suggest lifestyle through environment, objects, and atmosphere alone.",
    },

    "professional": {
        "label": "Professional Services",
        "subject": "Firm / Practice",
        "shots": """\
Shot 1 — AUTHORITY ESTABLISH: A polished, modern professional office — clean desk, city view through floor-to-ceiling windows, neatly organized files, premium furniture. No people. The environment communicates success.
Shot 2 — EXPERTISE VISUAL: The tools and artifacts of professional excellence — a legal book open to a relevant page, a financial chart on a large monitor showing growth, a contract with a pen ready to sign, a laptop showing clean professional work. Close and credible.
Shot 3 — PRECISION AT WORK: Hands only — writing notes with a quality pen, typing on a keyboard with purpose, placing a document on a desk, highlighting key text in a brief. Professional detail without faces.
Shot 4 — RESULTS ON SCREEN: A monitor or document showing positive outcomes — an upward trending graph, a winning legal brief header, a financial report showing gains, a clean project timeline. Abstract proof of expertise.
Shot 5 — BRAND CLOSE: The full office environment in perfect order — wide shot of the workspace, city skyline visible, everything in its place. The visual promise of competence, trust, and results.""",
        "voiceover": "Authoritative and reassuring. Open with the problem your clients face. Establish expertise and track record. Close with confidence and a clear next step — free consultation, call today.",
        "prominence": "Office environment, professional tools, and result visuals are the heroes. No faces — only hands for document/keyboard shots. Every frame must communicate trustworthiness through order and precision.",
    },

    "automotive": {
        "label": "Automotive",
        "subject": "Dealership / Auto Service",
        "shots": """\
Shot 1 — VEHICLE REVEAL: A stunning hero car shot — low angle, dramatic lighting, showroom or open road. The vehicle is everything. No people.
Shot 2 — ENGINEERING DETAIL: Close-up of the vehicle's most impressive features — the engine bay gleaming, a tire gripping pavement in slow motion, a door handle in chrome detail, headlights activating in low light.
Shot 3 — INTERIOR HERO: The cabin as a luxury environment — stitched leather seats, a backlit dashboard, steering wheel controls, a digital display showing navigation. Aspirational and tactile.
Shot 4 — SERVICE / TOOLS: For repair shops — professional mechanic tools arranged on a clean surface, a torque wrench on a wheel bolt, a lift raising a vehicle, oil draining in perfect amber slow motion. For dealerships — the showroom floor with vehicles in perfect alignment.
Shot 5 — THE RESULT: A gleaming, perfectly detailed vehicle in dramatic light — washed, polished, showroom-ready. The vehicle as art.""",
        "voiceover": "Bold and confident. Speak to performance, trust, and value. For dealerships: sell the experience. For service: sell reliability and expertise. Strong, direct CTA.",
        "prominence": "The vehicle is the absolute star in every shot. No people — tools and vehicle details only. Every frame should make the viewer want to own or service their vehicle here.",
    },

    "education": {
        "label": "Education & Coaching",
        "subject": "School / Program / Coach",
        "shots": """\
Shot 1 — LEARNING ENVIRONMENT: An inspiring classroom, training studio, or online workspace — bright, organized, motivating. Clean desks, books, whiteboards with content, screens showing course material. No people.
Shot 2 — CURRICULUM / TOOLS HERO: The learning materials as the visual star — a textbook open to compelling content, a laptop showing a course interface, flashcards spread on a desk, certificates or diplomas on a wall, specialized equipment for the skill being taught.
Shot 3 — SKILL IN ACTION: Hands only — writing notes with focus, typing code on a keyboard, sketching a design, solving a problem on paper, using specialized tools relevant to what's being taught. No faces.
Shot 4 — RESULTS EVIDENCE: Tangible proof of outcomes — a diploma or certificate in frame, a before/after of a student's work, a screen showing a completed project, a grade or score result, a portfolio piece. What success looks like.
Shot 5 — BRAND / FACILITY CLOSE: The full learning environment at its best — wide shot of the classroom or studio perfectly set up, equipment ready, materials organized. The promise of transformation through preparation.""",
        "voiceover": "Inspiring and empowering. Open with the limitation the student faces. Show the transformation. Name the specific skills or certifications gained. Close with a motivating invitation to begin.",
        "prominence": "Learning materials, tools, and result evidence are the visual heroes. No faces — hands on tools or keyboards are acceptable. The environment must look organized, credible, and inspiring.",
    },

    "retail": {
        "label": "Retail Store",
        "subject": "Store / Brand",
        "shots": """\
Shot 1 — STORE REVEAL: Inviting storefront or beautifully merchandised interior — warm lighting, products perfectly displayed, visual richness. No people.
Shot 2 — HERO PRODUCT SHOWCASE: The best-selling or most signature item as a beauty shot — perfectly lit, styled, irresistible. Product photography quality in motion.
Shot 3 — PRODUCT DETAIL: Close-up of the product's quality — texture of fabric, grain of wood, shine of metal, color of packaging, the tactile details that justify the purchase. No faces needed.
Shot 4 — COLLECTION / DISPLAY: A wider shot of products beautifully arranged — shelves styled to perfection, a display table with coordinated items, the full range shown together. The abundance and curation of the store.
Shot 5 — BRAND CLOSE: The storefront exterior or a signature display at its most beautiful — an invitation to visit. Clean, inviting, and memorable.""",
        "voiceover": "Warm and inviting with excitement. Speak to quality, uniqueness, and the joy of finding exactly what they were looking for. Close with an invitation to visit or shop online.",
        "prominence": "Products are the heroes in every single shot. No people — let the products speak entirely for themselves. Every frame should make the viewer want to own what they're seeing.",
    },

    "general": {
        "label": "General Business",
        "subject": "Business / Brand",
        "shots": """\
Shot 1 — BRAND WORLD ESTABLISH: Wide, atmospheric shot that immediately conveys the essence and world of this business — the space, the environment, the tools. No people needed.
Shot 2 — CORE SERVICE / PRODUCT HERO: The most important thing this business does or provides — shown as a beautiful, compelling close-up of the work, product, or service in its best form.
Shot 3 — CRAFT / TOOLS IN ACTION: The instruments and tools of this business — close-up of hands at work, equipment operating, materials being transformed. The skill made visible without showing faces.
Shot 4 — QUALITY DETAIL: An extreme close-up that proves the standard — craftsmanship, precision, or the unique differentiator that sets this business apart from competitors.
Shot 5 — BRAND CLOSE: A confident, aspirational wide shot of the full business environment — everything in order, everything at its best. The visual promise of what working with this business delivers.""",
        "voiceover": "Clear, confident, and emotionally resonant. Open with the problem or desire. Show the solution. Name what makes this business different. Close with a compelling reason to act now.",
        "prominence": "The work, products, tools, and environment are the heroes. Hands in action are acceptable. No faces — let the quality of the work and space communicate everything the viewer needs to know.",
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
photorealistic 8K, luxury commercial grade, safe for all audiences, no nudity, no violence, no text, no watermarks, no readable text on products, no brand labels on packaging, no writing on bottles or containers."

═══════════════════════════════════════════════
STRICT OUTPUT RULES
═══════════════════════════════════════════════
1. Output ONLY valid raw JSON — NO markdown fences, NO commentary, NO extra text.
2. Follow this exact schema:
{
  "project_title": "Catchy, evocative title",
  "full_voiceover": "The complete 30-38 second spoken script.",
  "total_estimated_duration": 38,
  "shots": [
    {
      "scene_number": 1,
      "voiceover_segment": "The specific line spoken during this shot.",
      "duration_seconds": 5,
      "higgsfield_prompt": "Your full cinematic prompt following all rules above."
    }
  ]
}
3. Exactly 7 shots. Duration per shot: 5–6 seconds each. Shot 7 must be 7–8 seconds (CTA needs time). Total must reach 35–42 seconds.
   Shots 1–5 follow the business type structure above.
   Shot 6 — REINFORCEMENT: A second hero visual that deepens the brand story — a different angle on the main service, product, or environment.
   Shot 7 — CALL TO ACTION CLOSE: A final aspirational wide or beauty shot. The voiceover_segment for Shot 7 MUST include the full CTA — business name, address (if provided), phone number (if provided), and website (if provided) — spoken completely with no rush.
4. Every higgsfield_prompt MUST end with the film quality markers.
5. Output ONLY the JSON. Nothing else."""


def _build_prompt(business_type: str) -> str:
    """Build the complete director system prompt for the given business type."""
    bt = BUSINESS_TYPES.get(business_type) or BUSINESS_TYPES["general"]

    return f"""You are a world-class Commercial Director and AI Prompt Engineer with credits on \
Super Bowl spots, luxury brand campaigns, and award-winning service business commercials. \
You specialize in Higgsfield AI video generation and know exactly how to craft prompts \
that produce stunning, cinematic, award-winning visuals for ANY type of business.

Your job: take this client brief and produce a 7-shot, 30-35 second commercial that looks like it cost $500,000 to make.

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
    business_address: str = "",
    business_phone: str = "",
    business_website: str = "",
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
    address_line = f"Business Address: {business_address}\n" if business_address else ""
    phone_line   = f"Phone Number: {business_phone}\n"       if business_phone   else ""
    website_line = f"Website: {business_website}\n"          if business_website else ""

    contact_block = ""
    if address_line or phone_line or website_line:
        contact_block = (
            "\nCONTACT DETAILS — weave these naturally into the CTA voiceover of Shot 7:\n"
            + address_line + phone_line + website_line
        )

    user_message = (
        f"{subject_label} Name: {product_name}\n"
        f"Target Audience: {target_audience}\n"
        f"Tone / Style: {tone}\n"
        f"{benefits_line}"
        f"{contact_block}"
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
