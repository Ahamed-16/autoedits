"""Configuration. Secrets come from .env, everything else from config.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml") as fh:
    CFG = yaml.safe_load(fh)

WORK = ROOT / CFG.get("work_dir", "work")
WORK.mkdir(exist_ok=True)
DB_PATH = ROOT / CFG.get("db_path", "data/autoedits.db")

# --- secrets -----------------------------------------------------------------
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
YT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# --- knobs -------------------------------------------------------------------
REGION = CFG["channel"]["region"]              # "AE"
DRAFTS_PER_NIGHT = CFG["pipeline"]["drafts_per_night"]

# Who writes the scripts: "groq" (free tier, strict schema) or "ollama"
# (local, free, slow). Both enforce the schema at the decoder, not in a prompt.
WRITER = CFG["models"]["writer"]
GROQ_MODEL = CFG["models"].get("groq_model", "openai/gpt-oss-120b")
# gpt-oss spends completion budget on reasoning before the JSON begins, so
# this ceiling covers thinking AND output. "" leaves reasoning_effort unset.
GROQ_MAX_TOKENS = int(CFG["models"].get("groq_max_tokens", 2000))
GROQ_EFFORT = str(CFG["models"].get("groq_reasoning_effort", "") or "")
# Groq counts prompt + max_completion_tokens against tokens-per-minute, so
# the reservation is spent whether or not the model uses it. Free tier: 8000.
GROQ_TPM = int(CFG["models"].get("groq_tpm", 8000))
OLLAMA_HOST = CFG["models"]["ollama_host"]
OLLAMA_MODEL = CFG["models"]["ollama_model"]
# CPU-only boxes need a long leash: ~1500 tokens of JSON at 3-6 tok/s.
OLLAMA_TIMEOUT = CFG["models"].get("ollama_timeout", 900)

# chatterbox (your voice, ships) | kokoro (preset voice, for timing checks)
VOICE_ENGINE = CFG["voice"]["engine"]


def require(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to {ROOT / '.env'} "
            f"(copy .env.example to .env first)."
        )
    return value
