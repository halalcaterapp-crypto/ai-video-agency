"""
config.py - Load all environment variables and shared constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
SENDGRID_API_KEY  = os.getenv("SENDGRID_API_KEY", "")

# Higgsfield - support both naming conventions
HIGGSFIELD_API_KEY    = os.getenv("HIGGSFIELD_API_KEY") or os.getenv("HF_API_KEY", "")
HIGGSFIELD_API_SECRET = os.getenv("HIGGSFIELD_API_SECRET") or os.getenv("HF_API_SECRET", "")

# Email / Branding
FROM_EMAIL = os.getenv("FROM_EMAIL", "studio@swiftaivideos.com")
FROM_NAME  = os.getenv("FROM_NAME",  "SwiftAI Videos")

# Claude
CLAUDE_MODEL = "claude-opus-4-8"

# OpenAI TTS
TTS_MODEL = "tts-1"
TTS_VOICE = "alloy"

# Output directories
BASE_OUTPUT_DIR = "outputs"
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
