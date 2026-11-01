"""
app.py
───────
UtsavAI — Streamlit application entry point.

Responsibilities:
- Bootstrap session state and database.
- Inject global CSS.
- Render the navigation sidebar.
- Dispatch to the appropriate page module.
- Display the AI-unavailable warning when no API key is configured.
- Display the SQLite persistence note prominently (not via filesystem detection).

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

# ── Page config (must be the first Streamlit call) ────────────────────────────
st.set_page_config(
    page_title="UtsavAI — Celebration Planner",
    page_icon="🎊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/your-repo/UtsavAI",
        "Report a bug": "https://github.com/your-repo/UtsavAI/issues",
        "About": "UtsavAI — Your Celebration. Your Budget. Your Perfect Plan.",
    },
)

# ── Internal imports (after set_page_config) ──────────────────────────────────
from utils.config import load_config, APP_NAME, APP_TAGLINE
from utils.styles import inject_css
from services.database_service import initialize_database

# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _bootstrap() -> None:
    """
    Run once-per-session initialisation:
    - Load AppConfig into session state.
    - Initialise the SQLite database.
    - Inject global CSS.

    Uses st.session_state to avoid re-running on every Streamlit rerun.
    """
    if "app_config" not in st.session_state:
        config = load_config()
        st.session_state["app_config"] = config
        st.session_state["db_initialised"] = initialize_database()

    if "active_event_id" not in st.session_state:
        st.session_state["active_event_id"] = None

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []


# ── Navigation ────────────────────────────────────────────────────────────────

_PAGES = {
    "🏠  Dashboard":             "dashboard",
    "🎉  AI Event Planner":      "event_planner",
    "💰  Budget Manager":        "budget_manager",
    "📅  Timeline":              "timeline_generator",
    "🤝  Vendor Manager":        "vendor_manager",
    "💬  AI Assistant":          "ai_assistant",
}


def _render_sidebar(config) -> str:
    """Render the navigation sidebar and return the selected page key."""
    with st.sidebar:
        # ── Brand header ──────────────────────────────────────────────────────
        st.markdown(
            """
            <div style="text-align:center; padding: 1rem 0 0.5rem;">
                <div style="font-size:2.4rem; margin-bottom:0.2rem;">🎊</div>
                <h2 style="
                    font-family: 'Cormorant Garamond', Georgia, serif;
                    color: #FAF7F0;
                    font-size: 1.7rem;
                    font-weight: 700;
                    margin: 0;
                    letter-spacing: -0.01em;
                ">UtsavAI</h2>
                <p style="
                    color: rgba(255,255,255,0.65);
                    font-size: 0.72rem;
                    margin: 0.2rem 0 0;
                    letter-spacing: 0.05em;
                ">Your Celebration Planner</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<hr style='border-color: rgba(201,168,76,0.4); margin: 0.8rem 0;'>", unsafe_allow_html=True)

        # ── AI status indicator ───────────────────────────────────────────────
        if config.ai_available:
            st.markdown(
                "<div style='text-align:center; color: #86EFAC; font-size:0.8rem; margin-bottom:0.5rem;'>"
                "✅ AI Connected</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center; color: #FCD34D; font-size:0.8rem; margin-bottom:0.5rem;'>"
                "⚠️ AI Offline</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<hr style='border-color: rgba(201,168,76,0.3); margin: 0.5rem 0 0.8rem;'>", unsafe_allow_html=True)

        # ── Navigation ────────────────────────────────────────────────────────
        selected_label = st.radio(
            label="Navigation",
            options=list(_PAGES.keys()),
            label_visibility="collapsed",
        )

        st.markdown("<hr style='border-color: rgba(201,168,76,0.3); margin: 0.8rem 0;'>", unsafe_allow_html=True)

        # ── Active event indicator ────────────────────────────────────────────
        active_id = st.session_state.get("active_event_id")
        if active_id:
            st.markdown(
                f"<div style='color:rgba(255,255,255,0.7); font-size:0.78rem; text-align:center;'>"
                f"📋 Active event: <strong style='color:#FAF7F0;'>#{active_id}</strong></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='color:rgba(255,255,255,0.55); font-size:0.78rem; text-align:center;'>"
                "No active event selected</div>",
                unsafe_allow_html=True,
            )

        # ── Model info (dev reference) ────────────────────────────────────────
        if config.ai_available:
            st.markdown(
                f"<div style='color:rgba(255,255,255,0.35); font-size:0.68rem; text-align:center; margin-top:1rem;'>"
                f"Model: {config.gemini_model}</div>",
                unsafe_allow_html=True,
            )

    return _PAGES[selected_label]


# ── AI unavailable banner ─────────────────────────────────────────────────────

def _render_ai_warning(model_available: bool) -> None:
    """
    Show a clear, styled warning when the Gemini API key is not configured.
    Never crashes — just informs the user and lets them continue.
    """
    if model_available:
        return
    st.markdown(
        """
        <div class="ai-unavailable-banner">
            <h4>⚠️ AI Features Not Configured</h4>
            <p>
                Gemini API key not found. AI-powered features (Event Planner, AI Assistant,
                Budget Suggestions) are <strong>disabled</strong>, but all other tools work fully.<br><br>
                To enable AI: copy <code>.streamlit/secrets.toml.example</code> to
                <code>.streamlit/secrets.toml</code> and add your
                <a href="https://aistudio.google.com/app/apikey" target="_blank">Gemini API key</a>.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── SQLite persistence note ───────────────────────────────────────────────────

def _render_persistence_note() -> None:
    """
    Always display the SQLite persistence limitation note.

    This is NOT detected via filesystem checks — it is always shown
    because Streamlit Community Cloud does not guarantee persistence
    and users must be aware of this regardless of platform.
    """
    st.info(
        "🗄️  **Data Persistence Note:** UtsavAI uses a local SQLite database. "
        "On **Streamlit Community Cloud**, data is stored in an ephemeral filesystem "
        "and **will be lost when the app restarts or redeploys**. "
        "For local use, data persists normally between sessions.",
        icon=None,
    )


# ── Hero header ───────────────────────────────────────────────────────────────

def _render_hero() -> None:
    """Render the top hero section for the dashboard."""
    st.markdown(
        f"""
        <div class="utsav-hero">
            <h1>🎊 {APP_NAME}</h1>
            <p class="tagline">{APP_TAGLINE}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Dashboard page ────────────────────────────────────────────────────────────

def _render_dashboard(config) -> None:
    """Render the main dashboard / landing page."""
    _render_hero()
    _render_ai_warning(config.ai_available)
    _render_persistence_note()

    st.markdown("---")
    st.markdown("### Welcome to UtsavAI")
    st.markdown(
        "Use the **navigation panel** on the left to get started. Here is what each module does:"
    )

    features = [
        ("🎉", "AI Event Planner",  "Generate a personalised event plan with budget breakdown, timeline and vendor checklist — powered by Gemini AI."),
        ("💰", "Budget Manager",    "Allocate your budget across categories, track actual spending and identify overruns with interactive charts."),
        ("📅", "Timeline",          "View and manage your preparation schedule. Track task completion and stay on top of deadlines."),
        ("🤝", "Vendor Manager",    "Add, edit and track vendors. Know who is booked, who is pending and who needs follow-up."),
        ("💬", "AI Assistant",      "Ask questions about your event. Get suggestions on budget, arrangements and cultural traditions."),
    ]

    cols = st.columns(3)
    for idx, (icon, title, desc) in enumerate(features):
        with cols[idx % 3]:
            st.markdown(
                f"""
                <div class="metric-card" style="border-top: 4px solid {'#6B2D3E' if idx % 2 == 0 else '#C9A84C'}; min-height: 160px;">
                    <p style="font-size:2rem; margin:0 0 0.4rem;">{icon}</p>
                    <p style="font-weight:600; color:#2C1810; font-size:0.95rem; margin:0 0 0.4rem;">{title}</p>
                    <p style="font-size:0.83rem; color:#8A6A5A; margin:0; line-height:1.5;">{desc}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if (idx + 1) % 3 == 0 and idx < len(features) - 1:
            cols = st.columns(3)

    st.markdown(
        """
        <div class="gold-divider"></div>
        <div class="cloud-persistence-note">
            📖 <strong>Getting started:</strong> Navigate to <em>AI Event Planner</em> to create your first event,
            or go to <em>Budget Manager</em> to start planning manually without an AI key.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Placeholder module stubs ──────────────────────────────────────────────────
# Phase 1 stubs — replaced by full module implementations in Phase 2.

def _render_stub(title: str, icon: str, description: str, config) -> None:
    """Render a placeholder page for modules not yet implemented in Phase 1."""
    _render_ai_warning(config.ai_available)
    st.markdown(f"## {icon} {title}")
    st.info(
        f"**{title}** will be fully implemented in Phase 2. "
        f"The foundation services and database layer are ready. — {description}"
    )


# ── Main entrypoint ───────────────────────────────────────────────────────────

def main() -> None:
    """Main application entry point."""
    _bootstrap()
    inject_css()

    config = st.session_state["app_config"]
    page = _render_sidebar(config)

    if page == "dashboard":
        _render_dashboard(config)
    elif page == "event_planner":
        try:
            from modules.event_planner import render_event_planner
            render_event_planner(config)
        except ImportError:
            _render_stub("AI Event Planner", "🎉", "Generate personalised event plans.", config)
    elif page == "budget_manager":
        try:
            from modules.budget_manager import render_budget_manager
            render_budget_manager(config)
        except ImportError:
            _render_stub("Budget Manager", "💰", "Manage your event budget.", config)
    elif page == "timeline_generator":
        try:
            from modules.timeline_generator import render_timeline_generator
            render_timeline_generator(config)
        except ImportError:
            _render_stub("Timeline Generator", "📅", "Manage preparation tasks.", config)
    elif page == "vendor_manager":
        try:
            from modules.vendor_manager import render_vendor_manager
            render_vendor_manager(config)
        except ImportError:
            _render_stub("Vendor Manager", "🤝", "Track your vendors.", config)
    elif page == "ai_assistant":
        try:
            from modules.ai_assistant import render_ai_assistant
            render_ai_assistant(config)
        except ImportError:
            _render_stub("AI Assistant", "💬", "Conversational planning help.", config)
    else:
        st.error("Page not found. Please select a page from the navigation panel.")


if __name__ == "__main__":
    main()
