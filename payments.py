"""
payments.py - Confirm with Stripe that a payment actually happened.

The /paid route used to trust its own URL: anyone who typed it got a free
video. A URL is not a receipt. This module takes the Checkout Session id that
Stripe appends to the success redirect and asks Stripe directly whether that
session was paid, and for how much - which is also how the tier is decided.

Fails closed. If the key is missing, the id is malformed, or Stripe says
anything other than "paid", nobody gets through.
"""

import logging
import re

import stripe

import config

logger = logging.getLogger(__name__)

# Stripe Checkout Session ids look like cs_test_... / cs_live_...
_SESSION_ID_RE = re.compile(r"^cs_[A-Za-z0-9_]{8,255}$")


class PaymentError(Exception):
    """Raised when a session cannot be confirmed as paid."""


def looks_like_session_id(session_id: str) -> bool:
    return bool(session_id and _SESSION_ID_RE.match(session_id))


def verify_session(session_id: str) -> dict:
    """
    Confirm a Checkout Session was paid. Returns a dict on success:
        {session_id, amount_total, currency, email}
    Raises PaymentError otherwise.
    """
    if not config.STRIPE_SECRET_KEY:
        logger.error(
            "STRIPE_SECRET_KEY is not set -- cannot verify payments. "
            "Add it in Railway > Variables."
        )
        raise PaymentError("Payment verification is not configured yet.")

    if not looks_like_session_id(session_id):
        logger.warning("Rejected malformed session id: %r", (session_id or "")[:40])
        raise PaymentError("That checkout link doesn't look valid.")

    stripe.api_key = config.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:
        logger.warning("Stripe could not retrieve session %s: %s", session_id[:20], exc)
        raise PaymentError("We couldn't confirm that payment with Stripe.")

    status = getattr(session, "payment_status", None)
    if status != "paid":
        logger.warning("Session %s is not paid (status=%s)", session_id[:20], status)
        raise PaymentError("That payment hasn't completed.")

    details = getattr(session, "customer_details", None) or {}
    email = (details.get("email") if isinstance(details, dict)
             else getattr(details, "email", None)) or ""

    info = {
        "session_id": session_id,
        "amount_total": getattr(session, "amount_total", 0) or 0,
        "currency": getattr(session, "currency", "usd"),
        "email": email,
    }
    logger.info(
        "Verified Stripe payment: %s, %s %s",
        session_id[:20], info["amount_total"], info["currency"],
    )
    return info
