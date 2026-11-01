"""
modules/event_planner.py
─────────────────────────
AI Event Planner UI module for UtsavAI.

Responsibilities:
- Render a multi-step event creation form.
- Validate all inputs using utils.validators before any DB or AI call.
- Call gemini_service.generate_event_plan() to produce a personalised plan.
- Persist the event, budget items, timeline tasks, and vendors via DB service.
- Set st.session_state["active_event_id"] on successful creation.
- Display the generated plan in a clear, tabbed layout.
- Gracefully degrade when AI is unavailable (rule-based fallback via services).

Layer contract: modules/ may import from services/, utils/, and streamlit.
               modules/ must NOT be imported by services/ or utils/.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from services.database_service import (
    create_event,
    get_event,
    list_events,
    upsert_budget_items,
    create_timeline_tasks,
    create_vendor,
    delete_event,
)
from services.gemini_service import generate_event_plan
from services.budget_service import distribute_ai_budget, suggest_default_allocation
from services.timeline_service import (
    validate_and_filter_tasks,
    generate_default_timeline,
)
from services.vendor_service import parse_ai_vendor_checklist, get_default_vendors
from utils.config import EVENT_TYPES, BUDGET_CATEGORIES
from utils.validators import (
    validate_event_name,
    validate_location,
    validate_guest_count,
    validate_budget,
    validate_event_date,
    validate_free_text,
    validate_ai_event_plan,
)
from utils.formatters import (
    format_currency,
    format_currency_compact,
    format_date,
    format_status_badge,
)
from utils.styles import render_metric_card, render_section_header


# ── Constants ─────────────────────────────────────────────────────────────────

_MIN_DATE = date.today()
_DEFAULT_FUTURE_DAYS = 90  # Default event date offset in the date picker


# ── Public entry point ────────────────────────────────────────────────────────

def render_event_planner(config) -> None:
    """Main entry point called by app.py."""
    st.markdown(
        render_section_header(
            "🎉 AI Event Planner",
            "Create a personalised event plan powered by Gemini AI",
        ),
        unsafe_allow_html=True,
    )

    # Top-level tabs: create new vs view existing
    tab_create, tab_existing = st.tabs(["✨ Create New Event", "📋 My Events"])

    with tab_create:
        _render_create_tab(config)

    with tab_existing:
        _render_existing_events_tab(config)


# ── Create-event tab ──────────────────────────────────────────────────────────

def _render_create_tab(config) -> None:
    """Render the new-event creation form and handle submission."""

    if not config.ai_available:
        st.markdown(
            """
            <div class="banner banner-warning">
            ⚠️ <strong>AI Offline:</strong> Gemini API key not configured.
            A rule-based event plan will be generated using default templates.
            You can still create and manage your event fully.
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("### Event Details")

    with st.form("event_planner_form", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            event_name = st.text_input(
                "Event Name *",
                placeholder="e.g. Priya & Rahul's Wedding",
                max_chars=120,
                help="Give your event a memorable name (max 120 characters).",
            )
            event_type = st.selectbox(
                "Event Type *",
                options=EVENT_TYPES,
                help="Select the type of celebration.",
            )
            location = st.text_input(
                "Location *",
                placeholder="e.g. Hyderabad, Telangana",
                help="City or region where the event will be held.",
            )

        with col2:
            event_date = st.date_input(
                "Event Date *",
                value=_MIN_DATE + timedelta(days=_DEFAULT_FUTURE_DAYS),
                min_value=_MIN_DATE,
                help="When is the event? Must be today or in the future.",
            )
            guest_count = st.number_input(
                "Expected Guest Count *",
                min_value=1,
                max_value=100_000,
                value=100,
                step=10,
                help="Approximate number of guests attending.",
            )
            total_budget = st.number_input(
                "Total Budget (₹) *",
                min_value=100.0,
                max_value=1_000_000_000.0,
                value=500_000.0,
                step=5_000.0,
                format="%.0f",
                help="Total budget in Indian Rupees.",
            )

        preferences = st.text_area(
            "Preferences & Special Requests",
            placeholder=(
                "e.g. Vegetarian catering only, outdoor venue preferred, "
                "traditional Telugu ceremony with modern reception..."
            ),
            max_chars=500,
            height=100,
            help="Any preferences, themes, dietary requirements, or cultural notes.",
        )

        submitted = st.form_submit_button(
            "✨ Generate Event Plan",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        _handle_form_submission(
            config=config,
            event_name=event_name,
            event_type=event_type,
            location=location,
            event_date=event_date,
            guest_count=int(guest_count),
            total_budget=float(total_budget),
            preferences=preferences,
        )

    # Show previously generated plan from this session (if any)
    if "last_generated_plan" in st.session_state:
        _render_plan(st.session_state["last_generated_plan"])


def _handle_form_submission(
    config,
    event_name: str,
    event_type: str,
    location: str,
    event_date,
    guest_count: int,
    total_budget: float,
    preferences: str,
) -> None:
    """Validate inputs, generate plan, persist to DB, and update session state."""

    # ── Input validation ───────────────────────────────────────────────────────
    errors: list[str] = []

    ok, msg = validate_event_name(event_name)
    if not ok:
        errors.append(f"Event Name: {msg}")

    ok, msg = validate_location(location)
    if not ok:
        errors.append(f"Location: {msg}")

    ok, msg = validate_guest_count(guest_count)
    if not ok:
        errors.append(f"Guest Count: {msg}")

    ok, msg = validate_budget(total_budget)
    if not ok:
        errors.append(f"Budget: {msg}")

    event_date_str = event_date.isoformat() if hasattr(event_date, "isoformat") else str(event_date)
    ok, msg = validate_event_date(event_date_str)
    if not ok:
        errors.append(f"Event Date: {msg}")

    ok, msg = validate_free_text(preferences, "Preferences")
    if not ok:
        errors.append(f"Preferences: {msg}")

    if errors:
        for err in errors:
            st.error(f"❌ {err}")
        return

    # ── Generate plan (AI or fallback) ─────────────────────────────────────────
    with st.spinner("✨ Generating your personalised event plan…"):
        plan_data = _generate_plan(
            config=config,
            event_name=event_name,
            event_type=event_type,
            location=location,
            event_date_str=event_date_str,
            guest_count=guest_count,
            total_budget=total_budget,
            preferences=preferences,
        )

    if plan_data is None:
        return  # Error already shown inside _generate_plan

    # ── Persist to DB ──────────────────────────────────────────────────────────
    with st.spinner("💾 Saving event to database…"):
        event_id = _persist_event(
            event_name=event_name,
            event_type=event_type,
            location=location,
            event_date_str=event_date_str,
            guest_count=guest_count,
            total_budget=total_budget,
            preferences=preferences,
            plan_data=plan_data,
        )

    if event_id is None:
        st.error("❌ Failed to save event to database. Please try again.")
        return

    # ── Update session state ───────────────────────────────────────────────────
    st.session_state["active_event_id"] = event_id
    st.session_state["last_generated_plan"] = {
        "event_id": event_id,
        "event_name": event_name,
        "event_type": event_type,
        "location": location,
        "event_date": event_date_str,
        "guest_count": guest_count,
        "total_budget": total_budget,
        "plan": plan_data,
    }

    st.success(
        f"🎉 Event **{event_name}** created successfully! "
        f"Event ID #{event_id} is now active. "
        "Navigate to Budget Manager, Timeline, or Vendor Manager to continue planning."
    )


def _generate_plan(
    config,
    event_name: str,
    event_type: str,
    location: str,
    event_date_str: str,
    guest_count: int,
    total_budget: float,
    preferences: str,
) -> dict | None:
    """
    Generate an event plan. Uses Gemini AI when available, falls back to
    rule-based defaults from the service layer otherwise.
    Returns the plan dict or None on error.
    """
    if config.ai_available:
        result = generate_event_plan(
            config=config,
            event_name=event_name,
            event_type=event_type,
            location=location,
            event_date=event_date_str,
            guest_count=guest_count,
            total_budget=total_budget,
            preferences=preferences,
        )
        if result.success:
            val_ok, val_err = validate_ai_event_plan(result.data, total_budget)
            if val_ok:
                return result.data
            st.warning(
                f"⚠️ AI plan response failed validation: {val_err}. "
                "A rule-based plan has been generated instead."
            )
        else:
            # AI failed — show warning and fall through to default
            st.warning(
                f"⚠️ AI plan generation failed: {result.error.message} "
                "A rule-based plan has been generated instead."
            )

    # Rule-based fallback
    return _build_fallback_plan(
        event_name=event_name,
        event_type=event_type,
        event_date_str=event_date_str,
        total_budget=total_budget,
    )


def _build_fallback_plan(
    event_name: str,
    event_type: str,
    event_date_str: str,
    total_budget: float,
) -> dict:
    """Build a minimal plan dict using rule-based service defaults."""
    # Budget
    budget_items = suggest_default_allocation(total_budget, event_type, BUDGET_CATEGORIES)
    budget_breakdown = {item.category: item.allocated_amount for item in budget_items}

    # Timeline
    tasks = generate_default_timeline(event_type, event_date_str)
    milestones = [
        {"task": t.task, "deadline": t.deadline, "priority": t.priority}
        for t in tasks
    ]

    # Vendors
    vendors = get_default_vendors(event_type)

    return {
        "event_summary": (
            f"A {event_type.lower()} event — {event_name}. "
            "This plan was generated using rule-based defaults because AI was not available. "
            "Use the Budget Manager and Timeline modules to customise it."
        ),
        "key_highlights": [
            f"Event type: {event_type}",
            f"Budget: {format_currency(total_budget)}",
            "Default budget allocation applied",
            "Preparation timeline generated",
            "Vendor checklist ready",
        ],
        "budget_breakdown": budget_breakdown,
        "timeline_milestones": milestones,
        "vendor_checklist": [
            {
                "category": v["category"],
                "name_suggestion": v["name"],
                "notes": v["notes"],
            }
            for v in vendors
        ],
        "cultural_notes": "",
    }


def _persist_event(
    event_name: str,
    event_type: str,
    location: str,
    event_date_str: str,
    guest_count: int,
    total_budget: float,
    preferences: str,
    plan_data: dict,
) -> int | None:
    """Create the event record and all child records. Returns event_id or None."""

    # Create event record
    event_id = create_event(
        name=event_name,
        event_type=event_type,
        event_date=event_date_str,
        guest_count=guest_count,
        total_budget=total_budget,
        location=location,
        preferences=preferences,
    )
    if event_id is None:
        return None

    # Budget items — convert AI breakdown via distribute_ai_budget
    ai_breakdown = plan_data.get("budget_breakdown", {})
    if ai_breakdown:
        budget_items = distribute_ai_budget(ai_breakdown, total_budget, BUDGET_CATEGORIES)
    else:
        budget_items = suggest_default_allocation(total_budget, event_type, BUDGET_CATEGORIES)

    budget_dicts = [
        {
            "category": item.category,
            "allocated_amount": item.allocated_amount,
            "actual_amount": 0.0,
            "notes": "",
        }
        for item in budget_items
    ]
    upsert_budget_items(event_id, budget_dicts)

    # Timeline tasks
    raw_milestones = plan_data.get("timeline_milestones", [])
    valid_tasks = validate_and_filter_tasks(raw_milestones, event_date_str)
    if valid_tasks:
        task_dicts = [
            {
                "task": t.task,
                "deadline": t.deadline,
                "priority": t.priority,
                "status": "pending",
                "notes": t.notes,
            }
            for t in valid_tasks
        ]
        create_timeline_tasks(event_id, task_dicts)

    # Vendors
    ai_vendor_list = plan_data.get("vendor_checklist", [])
    parsed_vendors = parse_ai_vendor_checklist(ai_vendor_list)
    if not parsed_vendors:
        parsed_vendors = get_default_vendors(event_type)
    for vendor in parsed_vendors:
        create_vendor(
            event_id=event_id,
            category=vendor.get("category", "Other"),
            name=vendor.get("name", "TBD"),
            contact="",
            status="pending",
            notes=vendor.get("notes", ""),
        )

    return event_id


# ── Plan display ──────────────────────────────────────────────────────────────

def _render_plan(plan_ctx: dict) -> None:
    """Render the generated event plan in a structured, readable layout."""
    plan = plan_ctx.get("plan", {})
    event_name = plan_ctx.get("event_name", "Your Event")
    event_id = plan_ctx.get("event_id")
    total_budget = plan_ctx.get("total_budget", 0)

    st.markdown("---")
    st.markdown(
        render_section_header(
            f"📋 Generated Plan: {event_name}",
            f"Event #{event_id} · Active event set",
        ),
        unsafe_allow_html=True,
    )

    # Summary
    summary = plan.get("event_summary", "")
    if summary:
        st.info(f"📝 {summary}")

    # Cultural notes
    cultural_notes = plan.get("cultural_notes", "")
    if cultural_notes and cultural_notes.strip():
        st.markdown(
            f'<div class="banner banner-info">🏮 <strong>Cultural Notes:</strong> {cultural_notes}</div>',
            unsafe_allow_html=True,
        )

    # Plan tabs
    p_tab1, p_tab2, p_tab3, p_tab4 = st.tabs([
        "✨ Highlights",
        "💰 Budget Breakdown",
        "📅 Timeline",
        "🤝 Vendors",
    ])

    with p_tab1:
        highlights = plan.get("key_highlights", [])
        if highlights:
            for hl in highlights:
                st.markdown(f"- {hl}")
        else:
            st.info("No highlights available.")

    with p_tab2:
        breakdown = plan.get("budget_breakdown", {})
        if breakdown:
            col1, col2 = st.columns(2)
            items = list(breakdown.items())
            mid = len(items) // 2 + len(items) % 2
            with col1:
                for cat, amt in items[:mid]:
                    pct = (amt / total_budget * 100) if total_budget > 0 else 0
                    st.markdown(f"**{cat}** — {format_currency(float(amt))} ({pct:.1f}%)")
            with col2:
                for cat, amt in items[mid:]:
                    pct = (amt / total_budget * 100) if total_budget > 0 else 0
                    st.markdown(f"**{cat}** — {format_currency(float(amt))} ({pct:.1f}%)")
        else:
            st.info("No budget breakdown available.")

    with p_tab3:
        milestones = plan.get("timeline_milestones", [])
        if milestones:
            for milestone in milestones:
                priority = milestone.get("priority", "medium")
                badge = format_status_badge(priority)
                st.markdown(
                    f"- **{milestone.get('task', '')}** — "
                    f"`{milestone.get('deadline', '')}` {badge}"
                )
        else:
            st.info("No timeline milestones available.")

    with p_tab4:
        vendor_list = plan.get("vendor_checklist", [])
        if vendor_list:
            for v in vendor_list:
                cat = v.get("category", "Other")
                name = v.get("name_suggestion", "TBD")
                notes = v.get("notes", "")
                with st.expander(f"📌 {cat} — {name}"):
                    if notes:
                        st.markdown(f"*{notes}*")
                    else:
                        st.markdown("*No additional notes.*")
        else:
            st.info("No vendor checklist available.")

    st.markdown(
        '<div class="banner banner-success">✅ Your event has been saved. '
        "Navigate to Budget Manager, Timeline, or Vendor Manager to continue planning.</div>",
        unsafe_allow_html=True,
    )


# ── Existing events tab ───────────────────────────────────────────────────────

def _render_existing_events_tab(config) -> None:
    """List all saved events and allow the user to switch active event or delete."""
    events = list_events()

    if not events:
        st.info(
            "No events created yet. Go to **Create New Event** to get started!"
        )
        return

    st.markdown(f"**{len(events)} event(s) found.** Click an event to set it as active.")

    active_id = st.session_state.get("active_event_id")

    for evt in events:
        eid = evt["id"]
        is_active = eid == active_id
        border_colour = "#542C46" if is_active else "#E0D5C5"
        active_badge = " 🟢 **Active**" if is_active else ""

        with st.expander(
            f"{'★ ' if is_active else ''}#{eid} — {evt['name']} ({evt['event_type']}) · {format_date(evt['event_date'])}",
            expanded=is_active,
        ):
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.markdown(f"**Location:** {evt.get('location', '—')}")
                st.markdown(f"**Guests:** {evt.get('guest_count', '—'):,}")
                st.markdown(f"**Budget:** {format_currency_compact(float(evt.get('total_budget', 0)))}")
                prefs = evt.get("preferences", "")
                if prefs:
                    st.markdown(f"**Preferences:** {prefs[:100]}{'…' if len(prefs) > 100 else ''}")
            with col2:
                if not is_active:
                    if st.button(f"Set Active", key=f"activate_{eid}"):
                        st.session_state["active_event_id"] = eid
                        # Clear last plan display to avoid showing stale plan
                        st.session_state.pop("last_generated_plan", None)
                        st.rerun()
                else:
                    st.markdown("*Currently active*")
            with col3:
                if st.button(f"🗑️ Delete", key=f"delete_{eid}", type="secondary"):
                    st.session_state[f"confirm_delete_{eid}"] = True

            # Deletion confirmation
            if st.session_state.get(f"confirm_delete_{eid}"):
                st.warning(
                    f"⚠️ Delete **{evt['name']}** and ALL its budget, timeline, and vendor data? "
                    "This cannot be undone."
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Yes, delete", key=f"confirm_yes_{eid}", type="primary"):
                        if delete_event(eid):
                            if st.session_state.get("active_event_id") == eid:
                                st.session_state["active_event_id"] = None
                                st.session_state.pop("last_generated_plan", None)
                            st.session_state.pop(f"confirm_delete_{eid}", None)
                            st.success(f"Event #{eid} deleted.")
                            st.rerun()
                        else:
                            st.error("Failed to delete event.")
                with c2:
                    if st.button("Cancel", key=f"confirm_no_{eid}"):
                        st.session_state.pop(f"confirm_delete_{eid}", None)
                        st.rerun()
