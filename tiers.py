"""
tiers.py - Pricing tiers.

Two prices, one pipeline:
  business ($39.99)  a real business advertising itself. Unlocks every category.
  personal ($14.99)  fun, creative, school and college videos. Creative types only.

Both tiers cost the same to produce (~65 Higgsfield credits), so the personal
tier is deliberately thin-margin - it exists to reach students and hobbyists,
not to carry the business.

The tier is never taken from a query parameter. It is derived from the amount
Stripe says was actually paid, so it cannot be forged by editing a URL.
"""

PERSONAL = "personal"
BUSINESS = "business"

# Categories a personal purchase may use. Everything else is business-only.
PERSONAL_TYPES = {"fantasy", "space", "nature", "kids", "cinematic", "school"}

PERSONAL_PRICE_CENTS = 1499
BUSINESS_PRICE_CENTS = 3999

# Anything at or above this counts as a business purchase. Sits between the two
# prices so a promo or price tweak on either side doesn't silently reclassify.
BUSINESS_THRESHOLD_CENTS = 2500

PRICES = {PERSONAL: PERSONAL_PRICE_CENTS, BUSINESS: BUSINESS_PRICE_CENTS}
LABELS = {PERSONAL: "Personal & Creative", BUSINESS: "Business Commercial"}


def tier_for_amount(amount_cents) -> str:
    """Which tier did this payment buy? Derived from Stripe's amount_total."""
    try:
        return BUSINESS if int(amount_cents) >= BUSINESS_THRESHOLD_CENTS else PERSONAL
    except (TypeError, ValueError):
        return PERSONAL          # fail closed: the cheaper, more limited tier


def allows(tier: str, business_type: str) -> bool:
    """May this tier order this category?"""
    if tier == BUSINESS:
        return True
    return business_type in PERSONAL_TYPES


def price_display(tier: str) -> str:
    return "$%.2f" % (PRICES.get(tier, PERSONAL_PRICE_CENTS) / 100.0)


def label(tier: str) -> str:
    return LABELS.get(tier, LABELS[PERSONAL])


def default_type(tier: str) -> str:
    """Which card is pre-selected on the form."""
    return "product" if tier == BUSINESS else "cinematic"
