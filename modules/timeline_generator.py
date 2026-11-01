"""
modules/timeline_generator.py
──────────────────────────────
Timeline Generator UI module for UtsavAI.

Responsibilities:
- Display preparation tasks for the active event, sorted by deadline.
- Show progress metrics (completion %, overdue count, etc.).
- Allow users to update task status via dropdown.
- Allow manual task addition and task regeneration from defaults.

Layer contract: modules/ may import from services/, utils/, and streamlit.
               modules/ must NOT be imported by services/ or utils/.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from services.database_service import (
    get_timeline_tasks,
    update_task_status,
    create_timeline_tasks,
    get_event,
)
from services.timeline_service import (
    validate_and_filter_tasks,
    compute_timeline_summary,
    generate_default_timeline,
    TimelineTask,
)
from utils.config import TASK_STATUSES, TASK_PRIORITIES
from utils.formatters import format_date, format_date_relative, format_status_badge
from utils.styles import render_metric_card, render_section_header
from utils.validators import validate_task_deadline, validate_free_text


# ── Status display order ──────────────────────────────────────────────────────

_STATUS_LABELS = {
    "pending": "⏳ Pending",
    "in_progress": "🔄 In Progress",
    "completed": "✅ Completed",
    "cancelled": "❌ Cancelled",
}

_PRIORITY_COLOURS = {
    "high": "#542C46",
    "medium": "#C49A55",
    "low": "#718B72",
}


# ── Public entry point ────────────────────────────────────────────────────────

def render_timeline_generator(config) -> None:
    """Main entry point called by app.py."""
    st.markdown(
        render_section_header(
            "📅 Timeline & Task Manager",
            "Track your preparation schedule and stay on top of every deadline",
        ),
        unsafe_allow_html=True,
    )

    event_id = st.session_state.get("active_event_id")
    if not event_id:
        st.info(
            "💡 **No active event selected.** "
            "Go to **AI Event Planner** to create an event first."
        )
        return

    event = get_event(event_id)
    if not event:
        st.error(f"Event #{event_id} not found.")
        st.session_state["active_event_id"] = None
        return

    _render_timeline_body(event)


# ── Main body ─────────────────────────────────────────────────────────────────

def _render_timeline_body(event: dict) -> None:
    event_id = event["id"]
    event_date_str = event.get("event_date", "")
    event_type = event.get("event_type", "")

    # Load raw tasks, then validate/sort via service
    raw_tasks = get_timeline_tasks(event_id)
    tasks = validate_and_filter_tasks(raw_tasks, event_date_str)
    summary = compute_timeline_summary(tasks)

    # Progress bar + metrics
    _render_progress_section(summary, event_date_str)

    st.markdown("---")

    tab_tasks, tab_add, tab_regenerate = st.tabs([
        "📋 All Tasks",
        "➕ Add Task",
        "🔄 Regenerate",
    ])

    with tab_tasks:
        _render_tasks_tab(tasks, event_date_str)

    with tab_add:
        _render_add_task_tab(event_id, event_date_str)

    with tab_regenerate:
        _render_regenerate_tab(event_id, event_type, event_date_str)


# ── Progress section ──────────────────────────────────────────────────────────

def _render_progress_section(summary, event_date_str: str) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.markdown(
            render_metric_card("Total Tasks", str(summary.total_tasks), "In plan", "#C49A55"),
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            render_metric_card("Completed", str(summary.completed), "Done", "#718B72"),
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            render_metric_card("In Progress", str(summary.in_progress), "Ongoing", "#C49A55"),
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            render_metric_card("Pending", str(summary.pending), "Not started", "#542C46"),
            unsafe_allow_html=True,
        )
    with col5:
        overdue_colour = "#542C46" if summary.overdue > 0 else "#718B72"
        st.markdown(
            render_metric_card("Overdue", str(summary.overdue), "Past deadline", overdue_colour),
            unsafe_allow_html=True,
        )

    # Completion progress bar
    st.markdown(f"**Overall Completion: {summary.completion_pct:.1f}%**")
    st.progress(summary.completion_pct / 100.0)

    # Days to event
    if event_date_str:
        days_label = format_date_relative(event_date_str)
        event_label = format_date(event_date_str)
        colour = "#542C46" if "ago" in days_label else "#718B72"
        st.markdown(
            f'<div class="banner banner-info">📅 Event date: <strong>{event_label}</strong> '
            f'— <strong style="color:{colour}">{days_label}</strong></div>',
            unsafe_allow_html=True,
        )

    # Overdue warning
    if summary.overdue > 0:
        st.markdown(
            f'<div class="banner banner-error">⚠️ <strong>{summary.overdue} task(s) are overdue!</strong> '
            "Update their status or reschedule.</div>",
            unsafe_allow_html=True,
        )


# ── Tasks tab ─────────────────────────────────────────────────────────────────

def _render_tasks_tab(tasks: list[TimelineTask], event_date_str: str) -> None:
    if not tasks:
        st.info(
            "No tasks found. Generate a timeline in the **Regenerate** tab "
            "or add tasks manually in **Add Task**."
        )
        return

    # Filter controls
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        status_filter = st.multiselect(
            "Filter by status",
            options=TASK_STATUSES,
            default=[],
            format_func=lambda s: _STATUS_LABELS.get(s, s),
            key="tl_status_filter",
        )
    with col_f2:
        priority_filter = st.multiselect(
            "Filter by priority",
            options=TASK_PRIORITIES,
            default=[],
            key="tl_priority_filter",
        )

    filtered = tasks
    if status_filter:
        filtered = [t for t in filtered if t.status in status_filter]
    if priority_filter:
        filtered = [t for t in filtered if t.priority in priority_filter]

    if not filtered:
        st.info("No tasks match the selected filters.")
        return

    st.markdown(f"Showing **{len(filtered)}** task(s):")

    for task in filtered:
        _render_task_row(task)


def _render_task_row(task: TimelineTask) -> None:
    """Render a single task row with status update control."""
    overdue_style = "background:#fff1f2; border-left:4px solid #542C46;" if task.is_overdue else ""
    completed_style = "opacity:0.6;" if task.status == "completed" else ""
    priority_colour = _PRIORITY_COLOURS.get(task.priority, "#C9A84C")

    with st.expander(
        f"{format_status_badge(task.status)}  |  "
        f"**{task.task}**  ·  {format_date(task.deadline)}  ·  "
        f"{format_date_relative(task.deadline)}",
        expanded=task.is_overdue,
    ):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**Priority:** {format_status_badge(task.priority)}")
            st.markdown(f"**Deadline:** {format_date(task.deadline)}")
            if task.notes:
                st.markdown(f"**Notes:** {task.notes}")
            if task.is_overdue:
                st.markdown(
                    '<span style="color:#542C46; font-weight:600;">⚠️ This task is overdue!</span>',
                    unsafe_allow_html=True,
                )

        with col2:
            current_index = TASK_STATUSES.index(task.status) if task.status in TASK_STATUSES else 0
            new_status = st.selectbox(
                "Update Status",
                options=TASK_STATUSES,
                index=current_index,
                format_func=lambda s: _STATUS_LABELS.get(s, s),
                key=f"status_sel_{task.id}",
            )
            if new_status != task.status:
                if st.button("💾 Update", key=f"update_status_{task.id}"):
                    if update_task_status(task.id, new_status):
                        st.success(f"✅ Status updated to '{new_status}'.")
                        st.rerun()
                    else:
                        st.error("Failed to update status.")


# ── Add task tab ──────────────────────────────────────────────────────────────

def _render_add_task_tab(event_id: int, event_date_str: str) -> None:
    st.markdown("Add a single preparation task to your timeline.")

    try:
        max_date = date.fromisoformat(event_date_str)
    except (ValueError, TypeError):
        max_date = date.today() + timedelta(days=365)

    with st.form("add_task_form"):
        task_text = st.text_input(
            "Task Description *",
            max_chars=200,
            placeholder="e.g. Book florist for wedding stage",
        )
        col1, col2 = st.columns(2)
        with col1:
            deadline = st.date_input(
                "Deadline *",
                value=min(date.today() + timedelta(days=30), max_date),
                min_value=date.today(),
                max_value=max_date,
            )
        with col2:
            priority = st.selectbox(
                "Priority",
                options=TASK_PRIORITIES,
                index=1,  # Default medium
                format_func=lambda p: format_status_badge(p),
            )
        task_notes = st.text_input("Notes (optional)", max_chars=200)
        add_submitted = st.form_submit_button("➕ Add Task", use_container_width=True)

    if add_submitted:
        errors = []
        if not task_text.strip():
            errors.append("Task description cannot be empty.")

        deadline_str = deadline.isoformat()
        ok, msg = validate_task_deadline(deadline_str, event_date_str)
        if not ok:
            errors.append(f"Deadline: {msg}")

        ok, msg = validate_free_text(task_notes, "Notes")
        if not ok:
            errors.append(f"Notes: {msg}")

        if errors:
            for e in errors:
                st.error(f"❌ {e}")
        else:
            # Fetch existing tasks, append new one, and re-save with create_timeline_tasks
            existing_raw = get_timeline_tasks(event_id)
            new_task = {
                "task": task_text.strip(),
                "deadline": deadline_str,
                "priority": priority,
                "status": "pending",
                "notes": task_notes.strip(),
            }
            all_tasks = [
                {
                    "task": t["task"],
                    "deadline": t["deadline"],
                    "priority": t.get("priority", "medium"),
                    "status": t.get("status", "pending"),
                    "notes": t.get("notes", ""),
                }
                for t in existing_raw
            ] + [new_task]
            if create_timeline_tasks(event_id, all_tasks):
                st.success(f"✅ Task '{task_text.strip()}' added.")
                st.rerun()
            else:
                st.error("Failed to add task. Please try again.")


# ── Regenerate tab ────────────────────────────────────────────────────────────

def _render_regenerate_tab(event_id: int, event_type: str, event_date_str: str) -> None:
    st.markdown(
        "Regenerate the timeline using **rule-based defaults** for your event type. "
        "⚠️ This will replace all existing tasks (including status updates)."
    )

    st.markdown(f"**Event type:** {event_type}  |  **Event date:** {format_date(event_date_str)}")

    confirm = st.checkbox(
        "I understand this will replace all current tasks.",
        key="regen_confirm",
    )

    if st.button(
        "🔄 Regenerate Timeline",
        disabled=not confirm,
        type="primary",
        key="regen_btn",
    ):
        with st.spinner("Generating timeline…"):
            tasks = generate_default_timeline(event_type, event_date_str)

        if not tasks:
            st.error("Could not generate tasks. Check that the event date is valid.")
            return

        task_dicts = [
            {
                "task": t.task,
                "deadline": t.deadline,
                "priority": t.priority,
                "status": "pending",
                "notes": t.notes,
            }
            for t in tasks
        ]
        if create_timeline_tasks(event_id, task_dicts):
            st.success(f"✅ Timeline regenerated with {len(tasks)} tasks.")
            st.rerun()
        else:
            st.error("Failed to regenerate timeline. Please try again.")
