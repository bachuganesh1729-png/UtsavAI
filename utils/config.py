"""
utils/config.py
───────────────
Central configuration for UtsavAI.

Responsibilities:
- Load Gemini API key and model name from Streamlit secrets or environment variables.
- Expose typed application constants.
- Configure the root logger (never logging secrets).
- Provide a structured AppConfig dataclass consumed by services.

Layer contract: utils/ may only import from the Python standard library.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

# ── Logging setup ─────────────────────────────────────────────────────────────
# Called once at import time. Subsequent imports reuse the same handler.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Gemini model fallback ─────────────────────────────────────────────────────
# This constant is the ONLY place a model name appears as a literal.
# It is used only when neither secrets.toml nor the environment provides one.
_DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash-preview-05-20"

# ── Supported event types ─────────────────────────────────────────────────────
EVENT_TYPES: list[str] = [
    "Wedding",
    "Birthday Party",
    "College Event",
    "Community Celebration",
    "Baby Shower",
    "Engagement Ceremony",
    "Anniversary",
    "Corporate Event",
    "Other",
]

# ── Budget categories ─────────────────────────────────────────────────────────
BUDGET_CATEGORIES: list[str] = [
    "Venue",
    "Catering",
    "Decoration",
    "Photography & Videography",
    "Music & Entertainment",
    "Attire & Grooming",
    "Invitations & Stationery",
    "Transportation",
    "Accommodation",
    "Gifts & Favours",
    "Mehendi & Makeup",
    "Flowers & Garlands",
    "Pandit / Officiant",
    "Miscellaneous",
]

# ── Vendor status options ─────────────────────────────────────────────────────
VENDOR_STATUSES: list[str] = ["pending", "contacted", "booked", "confirmed", "cancelled"]

# ── Task priority options ─────────────────────────────────────────────────────
TASK_PRIORITIES: list[str] = ["high", "medium", "low"]

# ── Task status options ───────────────────────────────────────────────────────
TASK_STATUSES: list[str] = ["pending", "in_progress", "completed", "cancelled"]

# ── DB path ───────────────────────────────────────────────────────────────────
DB_PATH: str = "utsavai.db"

# ── App metadata ──────────────────────────────────────────────────────────────
APP_NAME: str = "UtsavAI"
APP_TAGLINE: str = "Your Celebration. Your Budget. Your Perfect Plan."
APP_VERSION: str = "1.0.0"


@dataclass(frozen=True)
class AppConfig:
    """
    Immutable configuration resolved once at startup.

    Attributes:
        gemini_api_key: The Gemini API key, or None if not configured.
        gemini_model:   The Gemini model identifier to use.
        ai_available:   True when a non-empty API key is present.
    """

    gemini_api_key: Optional[str]
    gemini_model: str
    ai_available: bool = field(init=False)

    def __post_init__(self) -> None:
        # frozen=True prevents direct attribute assignment; use object.__setattr__
        object.__setattr__(
            self,
            "ai_available",
            bool(self.gemini_api_key and self.gemini_api_key.strip()),
        )


def _safe_get_secret(key: str) -> Optional[str]:
    """
    Attempt to read a value from Streamlit secrets without crashing if the
    secrets file is absent, the key is missing, or Streamlit is not running.

    Returns None instead of raising any exception.
    """
    try:
        import streamlit as st  # local import — avoids circular dependency at module level

        value = st.secrets.get(key)
        return str(value).strip() if value else None
    except Exception:
        # Streamlit not running (e.g. during pytest) or secrets file absent.
        return None


def load_config() -> AppConfig:
    """
    Resolve configuration using the priority chain:
        1. Streamlit secrets  (st.secrets)
        2. Environment variable
        3. Hardcoded default (model only — no default for API key)

    The API key is NEVER logged. Only its presence/absence is logged.

    Returns:
        AppConfig: Fully resolved, immutable configuration object.
    """
    # ── API key resolution ────────────────────────────────────────────────────
    api_key: Optional[str] = (
        _safe_get_secret("GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or None
    )

    # ── Model name resolution ─────────────────────────────────────────────────
    model: str = (
        _safe_get_secret("GEMINI_MODEL")
        or os.environ.get("GEMINI_MODEL", "").strip()
        or _DEFAULT_GEMINI_MODEL
    )

    config = AppConfig(gemini_api_key=api_key, gemini_model=model)

    # Log config state — never log the key value itself
    if config.ai_available:
        logger.info("AppConfig loaded. AI available. Model: %s", config.gemini_model)
    else:
        logger.warning(
            "AppConfig loaded. GEMINI_API_KEY not found in secrets or environment. "
            "AI features will be disabled. Non-AI features remain fully functional."
        )

    return config
