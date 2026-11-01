"""
modules/ai_assistant.py
────────────────────────
Conversational AI Assistant UI module for UtsavAI.

Responsibilities:
- Render a chat interface using st.chat_message.
- Send user messages to gemini_service.answer_event_question().
- Maintain conversation history in st.session_state["chat_history"].
- Inject the active event as context for every AI call.
- Handle missing API key and all AI error types gracefully.
- Provide quick-start suggestion prompts.

Layer contract: modules/ may import from services/, utils/, and streamlit.
               modules/ must NOT be imported by services/ or utils/.
"""

from __future__ import annotations

import streamlit as st

from services.database_service import get_event
from services.gemini_service import answer_event_question
from utils.styles import render_section_header


# ── Quick-start prompts ───────────────────────────────────────────────────────

_QUICK_PROMPTS: list[str] = [
    "What are the most important things to book first for my event?",
    "How can I reduce my catering costs without compromising quality?",
    "What cultural traditions should I consider for my wedding?",
    "How many days before the event should I confirm all vendors?",
    "Give me a checklist for the week before the event.",
    "What questions should I ask a wedding photographer?",
]

_MAX_HISTORY_TURNS = 20  # Limit stored turns to avoid unbounded growth


# ── Public entry point ────────────────────────────────────────────────────────

def render_ai_assistant(config) -> None:
    """Main entry point called by app.py."""
    st.markdown(
        render_section_header(
            "💬 AI Assistant",
            "Ask anything about your event — get personalised planning advice",
        ),
        unsafe_allow_html=True,
    )

    # AI availability check
    if not config.ai_available:
        _render_ai_unavailable()
        return

    event_context = _get_event_context()
    _render_chat_interface(config, event_context)


# ── AI unavailable ────────────────────────────────────────────────────────────

def _render_ai_unavailable() -> None:
    st.markdown(
        """
        <div class="ai-unavailable-banner">
            <h4>⚠️ AI Assistant Not Available</h4>
            <p>
                The AI Assistant requires a Gemini API key. To enable it:<br><br>
                1. Copy <code>.streamlit/secrets.toml.example</code> →
                   <code>.streamlit/secrets.toml</code><br>
                2. Add your <a href="https://aistudio.google.com/app/apikey"
                   target="_blank">Gemini API key</a> to the file.<br>
                3. Restart the app.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### 💡 Planning Tips (No AI Required)")
    tips = [
        "📅 **Book your venue first** — popular venues fill up 6-12 months in advance.",
        "💰 **Allocate ~30% to catering** — it is typically the largest cost for Indian events.",
        "📸 **Shortlist photographers early** — good wedding photographers book out fast.",
        "📨 **Send invitations at least 4 weeks early** — 6 weeks for destination weddings.",
        "✅ **Confirm all vendors 1 week before** — reconfirm final guest count with caterer 3 days before.",
        "🎭 **Build in a 10% contingency** — unexpected costs always arise.",
    ]
    for tip in tips:
        st.markdown(f"- {tip}")


# ── Event context ─────────────────────────────────────────────────────────────

def _get_event_context() -> dict:
    """Return the active event as a context dict for the AI prompt."""
    event_id = st.session_state.get("active_event_id")
    if event_id:
        event = get_event(event_id)
        if event:
            return dict(event)
    return {}


# ── Chat interface ────────────────────────────────────────────────────────────

def _render_chat_interface(config, event_context: dict) -> None:
    # Event context banner
    if event_context:
        name = event_context.get("name", "Unknown")
        etype = event_context.get("event_type", "")
        edate = event_context.get("event_date", "TBD")
        budget = float(event_context.get("total_budget", 0))
        st.markdown(
            f'<div class="banner banner-info">📋 <strong>Active event context:</strong> '
            f'{name} ({etype}) · {edate} · ₹{budget:,.0f}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="banner banner-warning">⚠️ No active event selected. '
            "The AI will answer general planning questions. "
            "Create an event in <strong>AI Event Planner</strong> for personalised advice.</div>",
            unsafe_allow_html=True,
        )

    # ── Quick prompts ──────────────────────────────────────────────────────────
    with st.expander("💡 Quick Prompts — click to ask", expanded=False):
        cols = st.columns(2)
        for i, prompt in enumerate(_QUICK_PROMPTS):
            with cols[i % 2]:
                if st.button(prompt, key=f"qp_{i}", use_container_width=True):
                    _send_message(config, prompt, event_context)

    # ── Chat history ───────────────────────────────────────────────────────────
    history: list[dict] = st.session_state.get("chat_history", [])

    if not history:
        with st.chat_message("assistant", avatar="🎊"):
            st.markdown(
                "Namaste! 🙏 I'm your UtsavAI planning assistant. "
                "I'm here to help you plan the perfect celebration — "
                "ask me about budgets, vendors, timelines, traditions, or anything else "
                "about your event!"
            )

    # Render history
    for turn in history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        avatar = "🎊" if role == "assistant" else None
        with st.chat_message(role, avatar=avatar):
            st.markdown(content)

    # ── Chat input ─────────────────────────────────────────────────────────────
    user_input = st.chat_input(
        "Ask anything about your event…",
        key="ai_chat_input",
    )

    if user_input and user_input.strip():
        _send_message(config, user_input.strip(), event_context)

    # ── Clear history ──────────────────────────────────────────────────────────
    if history:
        if st.button("🗑️ Clear conversation", key="clear_chat", type="secondary"):
            st.session_state["chat_history"] = []
            st.rerun()


# ── Message handling ──────────────────────────────────────────────────────────

def _send_message(config, question: str, event_context: dict) -> None:
    """
    Append the user question to history, call the AI, append the AI reply,
    and rerun to refresh the chat display.
    """
    history: list[dict] = st.session_state.setdefault("chat_history", [])

    # Append user turn
    history.append({"role": "user", "content": question})

    # Show user message immediately (optimistic render before spinner)
    with st.chat_message("user"):
        st.markdown(question)

    # Call the AI
    with st.chat_message("assistant", avatar="🎊"):
        with st.spinner("Thinking…"):
            result = answer_event_question(
                config=config,
                question=question,
                event_context=event_context,
                conversation_history=history[:-1],  # Exclude the just-added user turn
            )

        if result.success:
            answer = result.data.get("answer", "I'm sorry, I couldn't generate a response.")
            st.markdown(answer)
            history.append({"role": "assistant", "content": answer})
        else:
            error_msg = result.error.message
            # Map specific error kinds to friendly messages
            friendly = _friendly_error(result.error)
            st.markdown(
                f'<div class="banner banner-error">❌ {friendly}</div>',
                unsafe_allow_html=True,
            )
            # Still append an error placeholder to history so context is clear
            history.append({
                "role": "assistant",
                "content": f"*(Error: {error_msg})*",
            })

    # Trim history to avoid unbounded growth
    if len(history) > _MAX_HISTORY_TURNS * 2:
        st.session_state["chat_history"] = history[-(  _MAX_HISTORY_TURNS * 2):]

    st.rerun()


def _friendly_error(error) -> str:
    """Return a user-friendly string for a given AIError."""
    from services.gemini_service import AIErrorKind
    kind_map = {
        AIErrorKind.MISSING_CREDENTIALS: (
            "The Gemini API key is not configured or is invalid. "
            "Please check your <code>secrets.toml</code>."
        ),
        AIErrorKind.RATE_LIMIT: (
            "Gemini API rate limit reached. Please wait a moment and try again."
        ),
        AIErrorKind.TIMEOUT: (
            "The request timed out. Please check your connection and try again."
        ),
        AIErrorKind.INVALID_RESPONSE: (
            "Gemini returned an unexpected response. Please try rephrasing your question."
        ),
        AIErrorKind.API_ERROR: (
            "Gemini API returned an error. Please try again."
        ),
        AIErrorKind.UNEXPECTED: (
            "An unexpected error occurred. Please try again."
        ),
    }
    return kind_map.get(error.kind, error.message)
