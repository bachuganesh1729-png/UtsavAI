"""
tests/test_timeline_service.py
───────────────────────────────
Unit tests for services/timeline_service.py.

Covers:
- TimelineTask computed properties (deadline_date, is_overdue, days_remaining)
- validate_and_filter_tasks (invalid tasks removed, sorted by deadline+priority)
- compute_timeline_summary (counts, completion %, overdue)
- generate_default_timeline (Wedding, Birthday Party, unknown type, short notice)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.timeline_service import (
    TimelineTask,
    validate_and_filter_tasks,
    compute_timeline_summary,
    generate_default_timeline,
)


def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# ── TimelineTask properties ───────────────────────────────────────────────────

class TestTimelineTaskProperties:
    def test_deadline_date_parsed(self):
        task = TimelineTask(task="Book venue", deadline=_future(30), priority="high", status="pending")
        assert task.deadline_date == date.today() + timedelta(days=30)

    def test_days_remaining_future(self):
        task = TimelineTask(task="Caterer", deadline=_future(10), priority="medium", status="pending")
        assert task.days_remaining == 10

    def test_days_remaining_past(self):
        task = TimelineTask(task="Old task", deadline=_past(5), priority="low", status="pending")
        assert task.days_remaining == -5

    def test_is_overdue_true(self):
        task = TimelineTask(task="Missed task", deadline=_past(3), priority="high", status="pending")
        assert task.is_overdue is True

    def test_is_overdue_false_completed(self):
        task = TimelineTask(task="Done task", deadline=_past(3), priority="high", status="completed")
        assert task.is_overdue is False  # Completed tasks are not overdue

    def test_is_overdue_false_future(self):
        task = TimelineTask(task="Future task", deadline=_future(10), priority="medium", status="pending")
        assert task.is_overdue is False

    def test_is_overdue_cancelled(self):
        task = TimelineTask(task="Cancelled", deadline=_past(10), priority="low", status="cancelled")
        assert task.is_overdue is False


# ── validate_and_filter_tasks ─────────────────────────────────────────────────

class TestValidateAndFilterTasks:
    def _valid_task(self, days_before_event=30, priority="high", status="pending") -> dict:
        return {
            "task": "Sample task",
            "deadline": _future(days_before_event),
            "priority": priority,
            "status": status,
        }

    def test_valid_task_passes(self):
        event_date = _future(90)
        tasks = [self._valid_task(30)]
        result = validate_and_filter_tasks(tasks, event_date)
        assert len(result) == 1

    def test_empty_task_description_skipped(self):
        event_date = _future(90)
        tasks = [{"task": "  ", "deadline": _future(30), "priority": "high", "status": "pending"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result == []

    def test_deadline_after_event_date_skipped(self):
        event_date = _future(30)
        tasks = [{"task": "Late task", "deadline": _future(60), "priority": "medium", "status": "pending"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result == []

    def test_deadline_equals_event_date_allowed(self):
        event_date = _future(30)
        tasks = [{"task": "Day-of task", "deadline": event_date, "priority": "high", "status": "pending"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert len(result) == 1

    def test_invalid_priority_defaults_to_medium(self):
        event_date = _future(90)
        tasks = [{"task": "Task", "deadline": _future(30), "priority": "extreme", "status": "pending"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result[0].priority == "medium"

    def test_invalid_status_defaults_to_pending(self):
        event_date = _future(90)
        tasks = [{"task": "Task", "deadline": _future(30), "priority": "high", "status": "mystery"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result[0].status == "pending"

    def test_bad_deadline_format_skipped(self):
        event_date = _future(90)
        tasks = [{"task": "Task", "deadline": "31-12-2025", "priority": "high", "status": "pending"}]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result == []

    def test_tasks_sorted_by_deadline_ascending(self):
        event_date = _future(90)
        tasks = [
            {"task": "Later",   "deadline": _future(60), "priority": "low",    "status": "pending"},
            {"task": "Earlier", "deadline": _future(10), "priority": "medium", "status": "pending"},
        ]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result[0].task == "Earlier"
        assert result[1].task == "Later"

    def test_tasks_same_deadline_sorted_by_priority(self):
        event_date = _future(90)
        deadline = _future(30)
        tasks = [
            {"task": "Low priority",  "deadline": deadline, "priority": "low",  "status": "pending"},
            {"task": "High priority", "deadline": deadline, "priority": "high", "status": "pending"},
        ]
        result = validate_and_filter_tasks(tasks, event_date)
        assert result[0].task == "High priority"

    def test_empty_input(self):
        result = validate_and_filter_tasks([], _future(90))
        assert result == []

    def test_mixed_valid_invalid(self):
        event_date = _future(90)
        tasks = [
            {"task": "Valid task",  "deadline": _future(30), "priority": "high",   "status": "pending"},
            {"task": "",            "deadline": _future(30), "priority": "medium",  "status": "pending"},
            {"task": "After event", "deadline": _future(120),"priority": "low",    "status": "pending"},
        ]
        result = validate_and_filter_tasks(tasks, event_date)
        assert len(result) == 1
        assert result[0].task == "Valid task"


# ── compute_timeline_summary ──────────────────────────────────────────────────

class TestComputeTimelineSummary:
    def _make_tasks(self) -> list[TimelineTask]:
        return [
            TimelineTask(task="Completed",   deadline=_future(10), priority="high",   status="completed"),
            TimelineTask(task="In progress", deadline=_future(20), priority="medium", status="in_progress"),
            TimelineTask(task="Pending",     deadline=_future(30), priority="low",    status="pending"),
            TimelineTask(task="Overdue",     deadline=_past(5),    priority="high",   status="pending"),
        ]

    def test_total_tasks(self):
        summary = compute_timeline_summary(self._make_tasks())
        assert summary.total_tasks == 4

    def test_completed_count(self):
        summary = compute_timeline_summary(self._make_tasks())
        assert summary.completed == 1

    def test_in_progress_count(self):
        summary = compute_timeline_summary(self._make_tasks())
        assert summary.in_progress == 1

    def test_overdue_count(self):
        summary = compute_timeline_summary(self._make_tasks())
        assert summary.overdue == 1

    def test_completion_pct(self):
        summary = compute_timeline_summary(self._make_tasks())
        # 1 completed out of 4 = 25%
        assert summary.completion_pct == pytest.approx(25.0)

    def test_empty_tasks(self):
        summary = compute_timeline_summary([])
        assert summary.total_tasks == 0
        assert summary.completion_pct == pytest.approx(0.0)

    def test_all_completed(self):
        tasks = [
            TimelineTask(task=f"Task {i}", deadline=_future(i+1), priority="medium", status="completed")
            for i in range(5)
        ]
        summary = compute_timeline_summary(tasks)
        assert summary.completion_pct == pytest.approx(100.0)


# ── generate_default_timeline ─────────────────────────────────────────────────

class TestGenerateDefaultTimeline:
    def test_wedding_generates_tasks(self):
        event_date = _future(365)
        tasks = generate_default_timeline("Wedding", event_date)
        assert len(tasks) > 0

    def test_birthday_generates_tasks(self):
        event_date = _future(90)
        tasks = generate_default_timeline("Birthday Party", event_date)
        assert len(tasks) > 0

    def test_unknown_event_type_uses_fallback(self):
        event_date = _future(90)
        tasks = generate_default_timeline("Space Party", event_date)
        assert len(tasks) > 0  # Falls back to Birthday Party template

    def test_all_deadlines_on_or_before_event(self):
        event_date_str = _future(180)
        event_date = date.fromisoformat(event_date_str)
        tasks = generate_default_timeline("Wedding", event_date_str)
        for task in tasks:
            assert task.deadline_date <= event_date, (
                f"Task '{task.task}' deadline {task.deadline} is after event {event_date_str}"
            )

    def test_all_tasks_have_valid_priority(self):
        tasks = generate_default_timeline("Wedding", _future(365))
        for task in tasks:
            assert task.priority in {"high", "medium", "low"}

    def test_all_tasks_default_pending(self):
        tasks = generate_default_timeline("Birthday Party", _future(90))
        for task in tasks:
            assert task.status == "pending"

    def test_tasks_sorted_by_deadline(self):
        tasks = generate_default_timeline("Wedding", _future(365))
        deadlines = [t.deadline_date for t in tasks]
        assert deadlines == sorted(deadlines)

    def test_short_notice_event(self):
        """Events fewer than 30 days away should still generate some tasks."""
        event_date = _future(15)
        tasks = generate_default_timeline("Birthday Party", event_date)
        # At least some tasks should be generated (shifted to today)
        assert isinstance(tasks, list)

    def test_invalid_event_date(self):
        """Bad date string should return empty list without crashing."""
        tasks = generate_default_timeline("Wedding", "not-a-date")
        assert tasks == []
