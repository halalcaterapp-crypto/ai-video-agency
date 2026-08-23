"""
config.py - Load all environment variables and shared constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

# Email delivery.
# SendGrid discontinued its free plan in July 2025 and started rejecting
# free-tier keys with 401 Unauthorized, which silently broke every delivery.
# Resend replaces it: free tier covers 3,000 emails/month.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# Higgsfield - support both naming conventions
HIGGSFIELD_API_KEY    = os.getenv("HIGGSFIELD_API_KEY") or os.getenv("HF_API_KEY", "")
HIGGSFIELD_API_SECRET = os.getenv("HIGGSFIELD_API_SECRET") or os.getenv("HF_API_SECRET", "")

# Email / Branding
FROM_EMAIL = os.getenv("FROM_EMAIL", "studio@swiftaivideos.com")
FROM_NAME  = os.getenv("FROM_NAME",  "SwiftAI Videos")

# Public base URL used to build download links in delivery emails.
# Railway injects RAILWAY_PUBLIC_DOMAIN automatically; PUBLIC_BASE_URL wins if set.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL", "").strip()
    or (f"https://{_railway_domain}" if _railway_domain else "https://swiftaivideos.com")
).rstrip("/")

# Claude
CLAUDE_MODEL = "claude-opus-4-8"

# OpenAI TTS
TTS_MODEL = "tts-1"
TTS_VOICE = "alloy"

# Output directory.
# Railway's container filesystem is ephemeral - a restart wipes it, and a
# finished video that failed to deliver is gone for good. Point OUTPUT_DIR at
# a mounted Railway volume so completed jobs survive restarts and stay
# downloadable.
BASE_OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs").rstrip("/") or "outputs"
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
