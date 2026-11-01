"""
utils/styles.py
────────────────
CSS injection helpers for UtsavAI.

Provides a single inject_css() function that reads assets/styles.css and
injects it into the Streamlit page. Also provides small helper functions for
rendering styled HTML components safely.

Colour palette (v2 — Deep Plum / Champagne Gold):
  Primary (plum):    #542C46
  Accent (gold):     #C49A55
  Rose accent:       #C98289
  Sage green:        #718B72
  Ivory bg:          #FAF7F2

Layer contract: utils/ may only import from the Python standard library.
The streamlit import is localised to functions that require it.
"""

from __future__ import annotations

from pathlib import Path


# Path to the global stylesheet, relative to the project root
_CSS_PATH = Path(__file__).parent.parent / "assets" / "styles.css"

# ── Palette constants (used by modules for inline Plotly colours etc.) ─────────
COLOUR_PLUM      = "#542C46"
COLOUR_PLUM_MID  = "#6B3A5A"
COLOUR_GOLD      = "#C49A55"
COLOUR_GOLD_DARK = "#A07D38"
COLOUR_ROSE      = "#C98289"
COLOUR_SAGE      = "#718B72"
COLOUR_IVORY     = "#FAF7F2"
COLOUR_TEXT      = "#292524"
COLOUR_BORDER    = "#E8DDE4"

# Plotly chart palette — ordered for category series
CHART_COLOURS = [
    "#542C46",  # plum
    "#C49A55",  # gold
    "#C98289",  # rose
    "#718B72",  # sage
    "#8A5070",  # plum-light
    "#A07D38",  # gold-dark
    "#9C8A93",  # text-light
    "#3A5C3B",  # sage-dark
    "#6B3A5A",  # plum-mid
    "#F0E0C0",  # gold-light
    "#F5E4E5",  # rose-light
    "#E2EDE2",  # sage-light
    "#4A1E38",  # plum-deep
    "#D4AF6A",  # gold-bright
]


def inject_css() -> None:
    """
    Read assets/styles.css and inject it into the current Streamlit page.

    Safe to call multiple times — Streamlit deduplicates identical injections.
    If the CSS file is missing, logs a warning and skips injection.
    """
    import streamlit as st
    import logging

    logger = logging.getLogger(__name__)

    if not _CSS_PATH.exists():
        logger.warning("CSS file not found at %s. Skipping style injection.", _CSS_PATH)
        return

    try:
        css_content = _CSS_PATH.read_text(encoding="utf-8")
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
    except OSError as exc:
        logger.warning("Could not read CSS file: %s", exc)


def render_metric_card(
    title: str,
    value: str,
    subtitle: str = "",
    colour: str = COLOUR_PLUM,
) -> str:
    """
    Return an HTML string for a styled metric card with a coloured top border.

    Args:
        title:    Card heading text (displayed in small caps).
        value:    Primary displayed value (large Playfair Display).
        subtitle: Optional secondary line in muted text.
        colour:   Accent colour for the top border. Defaults to deep plum.

    Returns:
        HTML string — safe to pass to st.markdown(..., unsafe_allow_html=True).
    """
    subtitle_html = f'<p class="metric-subtitle">{subtitle}</p>' if subtitle else ""
    return (
        f'<div class="metric-card" style="border-top: 3px solid {colour};">'
        f'  <p class="metric-title">{title}</p>'
        f'  <p class="metric-value">{value}</p>'
        f"  {subtitle_html}"
        f"</div>"
    )


def render_status_pill(status: str) -> str:
    """
    Return an HTML span styled as a status pill.

    The CSS class is derived from the status string (lowercased, underscores → hyphens).
    """
    css_class = f"status-pill status-{status.lower().replace(' ', '-').replace('_', '-')}"
    label = status.replace("_", " ").title()
    return f'<span class="{css_class}">{label}</span>'


def render_section_header(title: str, subtitle: str = "") -> str:
    """Return HTML for a gold-accented section header with optional subtitle."""
    subtitle_html = f'<p class="section-subtitle">{subtitle}</p>' if subtitle else ""
    return (
        f'<div class="section-header">'
        f'  <h2 class="section-title">{title}</h2>'
        f"  {subtitle_html}"
        f"</div>"
    )


def render_info_banner(message: str, banner_type: str = "info") -> str:
    """
    Return HTML for a styled information banner.

    Args:
        message:     Banner text (may contain safe HTML).
        banner_type: One of "info", "warning", "success", "error".
    """
    icons = {"info": "ℹ️", "warning": "⚠️", "success": "✅", "error": "❌"}
    icon = icons.get(banner_type, "ℹ️")
    return (
        f'<div class="banner banner-{banner_type}">'
        f"  {icon} {message}"
        f"</div>"
    )


def render_feature_card(
    icon: str,
    title: str,
    description: str,
    accent_class: str = "card-plum-top",
) -> str:
    """
    Return HTML for a dashboard feature card.

    Args:
        icon:         Emoji icon string.
        title:        Card title text.
        description:  Short description text.
        accent_class: CSS class for the coloured top border.
                      One of: card-plum-top, card-gold-top, card-rose-top, card-sage-top.
    """
    return (
        f'<div class="feature-card {accent_class}">'
        f'  <span class="icon">{icon}</span>'
        f'  <p class="feature-title">{title}</p>'
        f'  <p class="feature-desc">{description}</p>'
        f"</div>"
    )
