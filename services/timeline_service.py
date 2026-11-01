"""
services/timeline_service.py
─────────────────────────────
Timeline generation and management for UtsavAI.

Responsibilities:
- Generate preparation schedules from AI data or rule-based defaults.
- Validate task deadlines relative to event date.
- Sort and group tasks by deadline and priority.
- Provide progress metrics.

Layer contract: services/ may import from utils/ and the standard library.
                services/ must NOT import from modules/ or streamlit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from utils.validators import validate_task_deadline

logger = logging.getLogger(__name__)


# ── Domain types ──────────────────────────────────────────────────────────────

@dataclass
class TimelineTask:
    """A single preparation task."""
    task:     str
    deadline: str     # ISO date string YYYY-MM-DD
    priority: str     # high | medium | low
    status:   str     # pending | in_progress | completed | cancelled
    notes:    str = ""
    id:       int = 0  # DB row ID (0 = not yet persisted)

    @property
    def deadline_date(self) -> date:
        try:
            return date.fromisoformat(self.deadline)
        except ValueError:
            return date.today()

    @property
    def is_overdue(self) -> bool:
        return self.status not in ("completed", "cancelled") and self.deadline_date < date.today()

    @property
    def days_remaining(self) -> int:
        return (self.deadline_date - date.today()).days


@dataclass
class TimelineSummary:
    """Aggregated timeline metrics."""
    total_tasks:     int
    completed:       int
    in_progress:     int
    pending:         int
    overdue:         int
    completion_pct:  float
    tasks:           list[TimelineTask]


# ── Validation ────────────────────────────────────────────────────────────────

def validate_and_filter_tasks(
    raw_tasks: list[dict[str, Any]],
    event_date: str,
) -> list[TimelineTask]:
    """
    Validate a list of raw task dicts (e.g. from AI or DB) and return
    a list of TimelineTask objects with invalid entries filtered out.

    Validation rules:
    - Task description must be a non-empty string.
    - Deadline must be a valid ISO date on or before event_date.
    - Overdue deadlines are preserved (never silently moved to today).
    - Only truly unparseable date strings (malformed ISO) are filtered out.
    - Priority must be one of: high, medium, low.

    Args:
        raw_tasks:  List of dicts with task, deadline, priority, status, notes.
        event_date: Event date string (YYYY-MM-DD) used for deadline validation.

    Returns:
        List of valid TimelineTask objects, sorted by deadline ascending.
    """
    valid_tasks: list[TimelineTask] = []
    valid_priorities = {"high", "medium", "low"}
    valid_statuses   = {"pending", "in_progress", "completed", "cancelled"}

    for i, raw in enumerate(raw_tasks):
        task_text = str(raw.get("task", "")).strip()

        raw_dl = raw.get("deadline", "")
        if isinstance(raw_dl, (date, datetime)):
            deadline = raw_dl.isoformat()[:10]
        else:
            deadline = str(raw_dl).strip()

        priority = str(raw.get("priority", "medium")).strip().lower()
        status   = str(raw.get("status", "pending")).strip().lower()
        notes    = str(raw.get("notes", ""))

        if not task_text:
            logger.warning("Task[%d] skipped: empty task description.", i)
            continue

        ok, err = validate_task_deadline(deadline, event_date)
        if not ok:
            logger.warning("Task[%d] '%s' skipped: %s", i, task_text, err)
            continue

        if priority not in valid_priorities:
            logger.warning("Task[%d] '%s' has invalid priority '%s'; defaulting to 'medium'.", i, task_text, priority)
            priority = "medium"

        if status not in valid_statuses:
            status = "pending"

        valid_tasks.append(
            TimelineTask(
                task=task_text,
                deadline=deadline,
                priority=priority,
                status=status,
                notes=notes,
                id=int(raw.get("id", 0)),
            )
        )

    # Sort by deadline ascending, then by priority weight
    priority_weight = {"high": 0, "medium": 1, "low": 2}
    valid_tasks.sort(
        key=lambda t: (t.deadline_date, priority_weight.get(t.priority, 1))
    )

    return valid_tasks


# ── Summary ───────────────────────────────────────────────────────────────────

def compute_timeline_summary(tasks: list[TimelineTask]) -> TimelineSummary:
    """
    Compute aggregated metrics from a list of TimelineTask objects.
    completion_pct counts 'completed' tasks only.
    """
    total     = len(tasks)
    completed = sum(1 for t in tasks if t.status == "completed")
    in_prog   = sum(1 for t in tasks if t.status == "in_progress")
    pending   = sum(1 for t in tasks if t.status == "pending")
    overdue   = sum(1 for t in tasks if t.is_overdue)
    pct       = round((completed / total * 100), 1) if total > 0 else 0.0

    return TimelineSummary(
        total_tasks=total,
        completed=completed,
        in_progress=in_prog,
        pending=pending,
        overdue=overdue,
        completion_pct=pct,
        tasks=tasks,
    )


# ── Default timeline generation (no AI required) ───────────────────────────────

def generate_default_timeline(
    event_type: str,
    event_date_str: str,
) -> list[TimelineTask]:
    """
    Generate a rule-based preparation timeline when AI is unavailable.

    Task deadlines are computed relative to event_date.
    Overdue tasks preserve their original deadline (never shifted to today).
    Does NOT crash if event_date is in the past.

    Args:
        event_type:     Type of celebration (e.g., "Wedding").
        event_date_str: ISO date string (YYYY-MM-DD).

    Returns:
        Sorted list of TimelineTask objects (all deadlines <= event_date).
    """
    try:
        event_date = date.fromisoformat(event_date_str.strip())
    except (ValueError, AttributeError):
        logger.error("Invalid event_date_str: %s", event_date_str)
        return []

    # Template: (days_before_event, task, priority)
    _TEMPLATES: dict[str, list[tuple[int, str, str]]] = {
        "Wedding": [
            (365, "Set overall wedding budget and guest list", "high"),
            (300, "Book wedding venue", "high"),
            (270, "Book caterer and finalise menu options", "high"),
            (240, "Book photographer and videographer", "high"),
            (210, "Book mehendi artist and makeup artist", "medium"),
            (180, "Send save-the-date invitations", "medium"),
            (150, "Book pandit / officiant and confirm rituals", "medium"),
            (120, "Finalise bridal and groom attire", "medium"),
            (90,  "Send formal wedding invitations", "high"),
            (60,  "Confirm all vendor bookings", "high"),
            (45,  "Arrange accommodation for outstation guests", "medium"),
            (30,  "Finalise decoration themes and flowers", "medium"),
            (21,  "Confirm final guest count with caterer", "high"),
            (14,  "Prepare welcome kits / gifts for guests", "low"),
            (7,   "Final venue walkthrough with all vendors", "high"),
            (3,   "Rehearsal dinner / pre-wedding gathering", "medium"),
            (1,   "Final payment settlements with vendors", "high"),
        ],
        "Birthday Party": [
            (60, "Decide party theme and guest list", "high"),
            (45, "Book venue or arrange home setup", "high"),
            (30, "Send invitations", "medium"),
            (21, "Book caterer or order cake / food", "high"),
            (14, "Arrange decorations and party supplies", "medium"),
            (7,  "Confirm RSVPs and finalise guest count", "medium"),
            (3,  "Prepare party favours and activities", "low"),
            (1,  "Set up venue and confirm all arrangements", "high"),
        ],
    }

    templates = _TEMPLATES.get(event_type, _TEMPLATES.get("Birthday Party", []))
    tasks: list[TimelineTask] = []

    for days_before, task_text, priority in templates:
        deadline = event_date - timedelta(days=days_before)
        if deadline > event_date:
            continue  # Skip tasks that fall after the event

        tasks.append(
            TimelineTask(
                task=task_text,
                deadline=deadline.isoformat(),
                priority=priority,
                status="pending",
            )
        )

    # Sort by deadline ascending
    tasks.sort(key=lambda t: t.deadline_date)
    logger.info(
        "Generated %d default timeline tasks for event type '%s' on %s.",
        len(tasks), event_type, event_date_str,
    )
    return tasks
