"""
config.py — Load all environment variables and shared constants.
Copy .env.example to .env and fill in your keys before running.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
HIGGSFIELD_API_KEY  = os.getenv("HIGGSFIELD_API_KEY", "")
HIGGSFIELD_API_SECRET = os.getenv("HIGGSFIELD_API_SECRET", "")
SENDGRID_API_KEY    = os.getenv("SENDGRID_API_KEY", "")

# ── Email / Branding ─────────────────────────────────────────────────────────
FROM_EMAIL = os.getenv("FROM_EMAIL", "studio@youragency.com")
FROM_NAME  = os.getenv("FROM_NAME",  "AI Video Studio")

# ── Higgsfield ───────────────────────────────────────────────────────────────
HIGGSFIELD_BASE_URL = "https://platform.higgsfield.ai"
HIGGSFIELD_AUTH     = f"Key {HIGGSFIELD_API_KEY}:{HIGGSFIELD_API_SECRET}"

# Text-to-image model (generates the first frame for each shot)
HIGGSFIELD_T2I_MODEL = "higgsfield-ai/soul/standard"
# Image-to-video model (animates the generated frame)
HIGGSFIELD_I2V_MODEL = "higgsfield-ai/dop/standard"

# Polling
POLL_INTERVAL_SECONDS = 6     # how often to check generation status
MAX_POLL_ATTEMPTS     = 200   # bail out after ~20 min per clip

# ── Claude ───────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-opus-4-8"

# ── OpenAI TTS ───────────────────────────────────────────────────────────────
TTS_MODEL = "tts-1"
TTS_VOICE = "alloy"          # alloy | echo | fable | onyx | nova | shimmer

# ── Output directories ───────────────────────────────────────────────────────
BASE_OUTPUT_DIR = "outputs"
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
