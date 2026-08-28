"""
moderation.py - Screen a customer brief before anything is spent on it.

Runs before the token is consumed and before a single Higgsfield credit is
used, so a refusal costs the customer nothing and they can correct a false
positive and resubmit with the same purchase.

Two layers:

  1. A keyword pass. Instant, free, and catches the unambiguous cases. This
     is the floor: it still works if the Anthropic API is unreachable.

  2. A Claude classifier. Catches everything the keyword list would miss -
     euphemism, paraphrase, and briefs that only read wrong as a whole.

Two different reasons to refuse, deliberately kept apart in the categories
below, because they warrant different wording to the customer:

  * Content nobody should be generating - sexual material, violence, hate,
    illegal goods, fraud, impersonation.
  * Businesses that are lawful but that Stripe does not allow this account to
    serve - cannabis, vape, firearms, gambling, payday lending, adult
    services. Taking these orders risks the payment account both businesses
    depend on.
"""

import json
import logging
import re

import config

logger = logging.getLogger(__name__)

# ── Categories ────────────────────────────────────────────────────────────────
# Prohibited outright.
HARM_CATEGORIES = {
    "csam":            "sexual content involving minors",
    "sexual":          "sexual or adult content",
    "violence":        "violence, weapons used against people, or terrorism",
    "hate":            "hateful or discriminatory content",
    "illegal_drugs":   "illegal drugs",
    "fraud":           "fraud, scams, or counterfeit goods",
    "impersonation":   "impersonating a real person, brand, or institution",
    "malware":         "hacking, malware, or account-cracking services",
}

# Lawful, but not permitted on this payment account.
RESTRICTED_CATEGORIES = {
    "adult_services":  "adult entertainment or companionship services",
    "cannabis":        "cannabis, CBD, or related products",
    "vape_tobacco":    "vaping, e-cigarettes, or tobacco",
    "firearms":        "firearms, ammunition, or weapons",
    "gambling":        "gambling, betting, or casino services",
    "lending":         "payday lending, debt relief, or credit repair",
    "crypto_schemes":  "cryptocurrency schemes or get-rich-quick offers",
}

ALL_CATEGORIES = {**HARM_CATEGORIES, **RESTRICTED_CATEGORIES}

# ── Layer 1: keyword floor ────────────────────────────────────────────────────
# Deliberately specific. A word like "shot" is film vocabulary; "gun" appears in
# "gun for hire". These patterns aim to be unambiguous rather than exhaustive -
# layer 2 is what catches the rest.
_PATTERNS = [
    ("csam", r"\b(child|children|minor|minors|underage|teen|teens|preteen|loli|shota)\s*(porn\w*|sex\w*|nude\w*|naked|erotic\w*)"),
    ("csam", r"\bcp\b.{0,12}\b(porn\w*|content)\b"),

    ("sexual", r"\b(porn|porno|pornograph\w*|xxx|hardcore|softcore)\b"),
    ("sexual", r"\b(nude|nudes|nudity|naked|topless|nsfw)\b"),
    ("sexual", r"\b(erotic|erotica|fetish\w*|bdsm|orgy|orgies|hentai)\b"),
    ("sexual", r"\b(onlyfans|fansly|chaturbate|cam\s?girls?|cam\s?boys?|webcam\s?models?)\b"),
    ("sexual", r"\bsex\s?(shops?|toys?|work|workers?|tapes?|cams?)\b"),
    ("sexual", r"\badult\s?(films?|movies?|videos?|entertainment|content|site|website)\b"),

    ("adult_services", r"\b(escorts?|escort\s?services?|brothels?|prostitut\w*)\b"),
    ("adult_services", r"\b(strip\s?clubs?|strippers?|gentlemen'?s\s?clubs?)\b"),
    ("adult_services", r"\b(massage\s?parlou?rs?|happy\s?ending|sugar\s?(dadd(y|ies)|bab(y|ies)))\b"),

    ("violence", r"\b(terroris\w*|jihadis\w*|bomb\s?making|how\s+to\s+kill)\b"),
    ("violence", r"\b(behead\w*|torture|massacres?|genocide)\b"),
    ("violence", r"\b(hit\s?m(a|e)n|assassination\s?services?)\b"),

    ("hate", r"\b(white\s?(power|supremac\w*)|neo\s?nazis?|ethnic\s?cleansing)\b"),
    ("hate", r"\b(kill|exterminate|deport)\s+all\s+\w+"),

    ("illegal_drugs", r"\b(cocaine|heroin|meth|methamphetamine|fentanyl|mdma|ecstasy|lsd|ketamine)\b"),
    ("illegal_drugs", r"\b(drug\s?dealers?|buy\s?drugs|dark\s?web\s?markets?)\b"),

    ("fraud", r"\b(counterfeit\w*|knock\s?offs?)\b"),
    ("fraud", r"\breplica\s?(watch(es)?|bags?|designer|handbags?)\b"),
    ("fraud", r"\bfake\s?(ids?|passports?|diplomas?|degrees?|reviews?|testimonials?)\b"),
    ("fraud", r"\b(money\s?laundering|ponzi|pyramid\s?schemes?)\b"),
    ("fraud", r"\b(essay\s?mills?|write\s?my\s?(essay|thesis))\b"),

    ("malware", r"\b(malware|ransomware|keyloggers?|ddos\s?services?|botnets?|spyware)\b"),
    ("malware", r"\b(hack(ing)?\s?(services?|tools?)|crack\s?accounts?|spy\s?on\s?(your\s?)?(partner|spouse|wife|husband))\b"),

    ("cannabis", r"\b(cannabis|marijuana|dispensar(y|ies)|thc|cbd)\b"),
    ("cannabis", r"\b(weed\s?(shops?|stores?)|smoke\s?shops?|head\s?shops?|bongs?|dab\s?rigs?)\b"),

    ("vape_tobacco", r"\b(vape|vapes|vaping|vape\s?shops?|e-?cig\w*|e-?liquids?|juul|hookahs?|shisha)\b"),
    ("vape_tobacco", r"\b(nicotine\s?pouch\w*|cigarettes?|cigar\s?(shops?|lounges?)|tobacco\s?(shops?|stores?))\b"),

    ("firearms", r"\b(firearms?|handguns?|rifles?|shotguns?|ammunition|ammo)\b"),
    ("firearms", r"\b(gun\s?(shops?|stores?|ranges?|dealers?)|silencers?|suppressors?|ghost\s?guns?)\b"),

    ("gambling", r"\b(casinos?|betting|sportsbooks?|bookmakers?|poker\s?rooms?|slot\s?machines?)\b"),
    ("gambling", r"\b(online\s?gambl\w*|lottery\s?(schemes?|systems?)|roulette)\b"),

    ("lending", r"\b(payday\s?loans?|debt\s?(relief|settlement|consolidation)|credit\s?repair)\b"),
    ("lending", r"\b(bail\s?bonds?|loan\s?sharks?)\b"),

    ("crypto_schemes", r"\b(get\s?rich\s?quick|guaranteed\s?returns?|double\s?your\s?money)\b"),
    ("crypto_schemes", r"\b(crypto\s?(signals?|pumps?)|pump\s?and\s?dump|forex\s?signals?|hyip)\b"),
]


_COMPILED = [(cat, re.compile(rx, re.I)) for cat, rx in _PATTERNS]


class Verdict:
    """The outcome of screening one brief."""

    def __init__(self, allowed, category=None, reason="", layer=""):
        self.allowed = allowed
        self.category = category
        self.reason = reason
        self.layer = layer          # "keyword", "classifier", "clean", "error"

    @property
    def is_restricted(self):
        """True when the refusal is about the payment account, not the content."""
        return self.category in RESTRICTED_CATEGORIES

    def customer_message(self):
        """Headline and detail to show the customer. Plain, not preachy."""
        if self.allowed:
            return ("", "")
        what = ALL_CATEGORIES.get(self.category, "content we can't produce")
        if self.is_restricted:
            return (
                "We can't make a video for this business.",
                f"Our payment provider doesn't permit us to serve businesses in "
                f"this category ({what}). Your purchase has NOT been used — reply "
                f"to your Stripe receipt and we'll refund you in full.",
            )
        return (
            "We can't make this video.",
            f"This brief describes {what}, which falls outside what we produce. "
            f"Your purchase has NOT been used, so if you think this was a mistake "
            f"you can edit the brief and submit again, or reply to your Stripe "
            f"receipt for a refund.",
        )

    def __repr__(self):
        return f"<Verdict allowed={self.allowed} category={self.category} layer={self.layer}>"


def _keyword_scan(text: str):
    """Return (category, matched_text) for the first hard hit, or (None, None)."""
    for category, rx in _COMPILED:
        m = rx.search(text)
        if m:
            return category, m.group(0)
    return None, None


_CLASSIFIER_SYSTEM = """You screen briefs submitted to an AI video generation service that makes short promotional and creative videos for small businesses, students and hobbyists.

Decide whether a brief should be produced. Block it if it describes any of:

PROHIBITED CONTENT
- csam: anything sexual involving minors
- sexual: sexual or adult content, nudity, pornography, suggestive material
- violence: violence against people, weapons used on people, terrorism, gore
- hate: content demeaning or targeting people by race, religion, ethnicity, gender, sexuality or disability
- illegal_drugs: illegal drugs or drug paraphernalia
- fraud: scams, counterfeit goods, fake documents, fake reviews, academic cheating services
- impersonation: posing as a real named person, brand or government body
- malware: hacking services, malware, spyware, account cracking

RESTRICTED BUSINESSES (lawful, but our payment provider forbids them)
- adult_services: escort, strip club, adult entertainment, companionship services
- cannabis: cannabis, marijuana, CBD, smoke or head shops
- vape_tobacco: vaping, e-cigarettes, hookah, tobacco
- firearms: firearms, ammunition, weapons dealers, gun ranges
- gambling: casinos, betting, sportsbooks, lotteries
- lending: payday loans, debt relief, credit repair, bail bonds
- crypto_schemes: get-rich-quick offers, guaranteed returns, crypto signal groups

Otherwise allow it. Be practical, not squeamish:
- A restaurant serving alcohol, a pharmacy, a medical clinic, a security company, a butcher, a costume shop, a martial arts gym, a Halloween attraction, a toy gun in a kids' story, a historical documentary about war — all ALLOWED.
- Fiction and fairy tales involving mild peril, monsters or conflict are ALLOWED. This service makes children's stories and school projects.
- Only block when the brief's actual subject falls in a listed category, not when a word merely appears.

Reply with JSON only:
{"decision": "allow"} or {"decision": "block", "category": "<category key>", "reason": "<one short sentence>"}"""


def _classify(brief: str) -> Verdict:
    """Ask Claude. Raises on API trouble so the caller can fall back."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=200,
        system=_CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": f"<brief>\n{brief}\n</brief>"}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    data = json.loads(m.group(0) if m else raw)

    if str(data.get("decision", "")).lower() == "block":
        category = data.get("category") or "sexual"
        if category not in ALL_CATEGORIES:
            category = "sexual"
        return Verdict(False, category, data.get("reason", "")[:200], "classifier")
    return Verdict(True, layer="classifier")


def screen_brief(product_name="", target_audience="", key_benefits="",
                 business_type="", tone="", **_ignored) -> Verdict:
    """
    Screen everything the customer typed. Call before consuming their token.

    Never raises: a screening failure must not take the site down. If the
    classifier is unreachable the keyword floor still applies and the order is
    allowed through with a warning logged, on the reasoning that Higgsfield's
    own NSFW filter is a second line of defence and an Anthropic outage should
    not stop every legitimate sale.
    """
    brief = "\n".join(str(x) for x in
                      (product_name, target_audience, key_benefits, business_type, tone) if x)

    if not brief.strip():
        return Verdict(True, layer="clean")

    category, hit = _keyword_scan(brief)
    if category:
        logger.warning(
            "BLOCKED by keyword: category=%s matched=%r product=%r",
            category, hit, product_name[:60],
        )
        return Verdict(False, category, f"matched {hit!r}", "keyword")

    try:
        verdict = _classify(brief)
    except Exception as exc:
        logger.error(
            "Moderation classifier unavailable (%s) -- keyword screen passed, allowing. "
            "product=%r", exc, product_name[:60],
        )
        return Verdict(True, layer="error")

    if not verdict.allowed:
        logger.warning(
            "BLOCKED by classifier: category=%s reason=%r product=%r",
            verdict.category, verdict.reason, product_name[:60],
        )
    return verdict
