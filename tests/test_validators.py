"""
tests/test_validators.py
─────────────────────────
Unit tests for utils/validators.py.

Covers:
- Event name validation (empty, too long, no letters, Unicode)
- Location validation
- Guest count (boundaries, non-numeric, zero)
- Budget (negative, zero, NaN, infinity, boundaries)
- Event date (past, today, future, bad format)
- Task deadline (relative to event date, bad format)
- AI event plan schema validation (missing fields, wrong types, numeric amounts)
- AI budget suggestion schema validation
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from utils.validators import (
    validate_event_name,
    validate_location,
    validate_free_text,
    validate_guest_count,
    validate_budget,
    validate_amount,
    validate_event_date,
    validate_task_deadline,
    validate_event_type,
    validate_vendor_status,
    validate_priority,
    validate_ai_event_plan,
    validate_ai_budget_suggestions,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(result: tuple[bool, str]) -> None:
    """Assert validation passed."""
    assert result[0] is True, f"Expected OK but got error: {result[1]}"


def err(result: tuple[bool, str], fragment: str = "") -> None:
    """Assert validation failed, optionally checking the error message."""
    assert result[0] is False, "Expected error but got OK"
    if fragment:
        assert fragment.lower() in result[1].lower(), (
            f"Expected '{fragment}' in error message but got: {result[1]}"
        )


# ── Event name ────────────────────────────────────────────────────────────────

class TestValidateEventName:
    def test_valid_name(self):
        ok(validate_event_name("Priya's Wedding"))

    def test_valid_unicode_name(self):
        ok(validate_event_name("రాహుల్ పెళ్ళి"))   # Telugu

    def test_valid_mixed(self):
        ok(validate_event_name("Ramesh 50th Birthday 2025"))

    def test_empty_string(self):
        err(validate_event_name(""), "empty")

    def test_whitespace_only(self):
        err(validate_event_name("   "), "empty")

    def test_too_long(self):
        err(validate_event_name("A" * 121), "120")

    def test_exactly_max_length(self):
        ok(validate_event_name("A" * 120))

    def test_digits_only(self):
        err(validate_event_name("12345"), "letter")

    def test_special_chars_only(self):
        err(validate_event_name("!!! ###"), "letter")

    def test_not_a_string(self):
        err(validate_event_name(42), "string")

    def test_none_input(self):
        err(validate_event_name(None), "string")


# ── Guest count ───────────────────────────────────────────────────────────────

class TestValidateGuestCount:
    def test_valid_count(self):
        ok(validate_guest_count(100))

    def test_minimum(self):
        ok(validate_guest_count(1))

    def test_maximum(self):
        ok(validate_guest_count(100_000))

    def test_zero(self):
        err(validate_guest_count(0), "at least 1")

    def test_negative(self):
        err(validate_guest_count(-5))

    def test_exceeds_maximum(self):
        err(validate_guest_count(100_001))

    def test_float_string(self):
        err(validate_guest_count("10.5"))

    def test_none(self):
        err(validate_guest_count(None))

    def test_string_integer(self):
        ok(validate_guest_count("500"))   # "500" should be coercible


# ── Budget ────────────────────────────────────────────────────────────────────

class TestValidateBudget:
    def test_valid_budget(self):
        ok(validate_budget(500_000))

    def test_minimum(self):
        ok(validate_budget(100.0))

    def test_below_minimum(self):
        err(validate_budget(50.0))

    def test_zero(self):
        err(validate_budget(0))

    def test_negative(self):
        err(validate_budget(-1000))

    def test_maximum(self):
        ok(validate_budget(1_000_000_000.0))

    def test_above_maximum(self):
        err(validate_budget(1_000_000_001.0))

    def test_nan(self):
        err(validate_budget(math.nan), "finite")

    def test_infinity(self):
        err(validate_budget(math.inf), "finite")

    def test_negative_infinity(self):
        err(validate_budget(-math.inf), "finite")

    def test_string_number(self):
        ok(validate_budget("250000"))

    def test_non_numeric(self):
        err(validate_budget("lakhs"))


# ── Amount ────────────────────────────────────────────────────────────────────

class TestValidateAmount:
    def test_zero_is_valid(self):
        ok(validate_amount(0.0))

    def test_positive(self):
        ok(validate_amount(5000.0))

    def test_negative(self):
        err(validate_amount(-1.0), "negative")

    def test_nan(self):
        err(validate_amount(math.nan), "finite")


# ── Event date ────────────────────────────────────────────────────────────────

class TestValidateEventDate:
    def test_future_date(self):
        future = (date.today() + timedelta(days=60)).isoformat()
        ok(validate_event_date(future))

    def test_today(self):
        ok(validate_event_date(date.today().isoformat()))

    def test_past_date(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        err(validate_event_date(past), "past")

    def test_date_object(self):
        ok(validate_event_date(date.today() + timedelta(days=30)))

    def test_invalid_format(self):
        err(validate_event_date("31-12-2025"), "YYYY-MM-DD")

    def test_non_string(self):
        err(validate_event_date(20251231))

    def test_none(self):
        err(validate_event_date(None))


# ── Task deadline ─────────────────────────────────────────────────────────────

class TestValidateTaskDeadline:
    def setup_method(self):
        self.event_date = (date.today() + timedelta(days=90)).isoformat()

    def test_valid_deadline_before_event(self):
        deadline = (date.today() + timedelta(days=30)).isoformat()
        ok(validate_task_deadline(deadline, self.event_date))

    def test_deadline_equals_event_date(self):
        ok(validate_task_deadline(self.event_date, self.event_date))

    def test_deadline_after_event_date(self):
        after = (date.today() + timedelta(days=100)).isoformat()
        err(validate_task_deadline(after, self.event_date), "after the event")

    def test_no_event_date_provided(self):
        """Without event_date cross-validation, any valid date should pass."""
        future = (date.today() + timedelta(days=200)).isoformat()
        ok(validate_task_deadline(future))

    def test_invalid_format(self):
        err(validate_task_deadline("15/01/2025"), "YYYY-MM-DD")


# ── Enum validators ───────────────────────────────────────────────────────────

class TestEnumValidators:
    def test_valid_event_type(self):
        ok(validate_event_type("Wedding", ["Wedding", "Birthday Party"]))

    def test_invalid_event_type(self):
        err(validate_event_type("Disco", ["Wedding", "Birthday Party"]))

    def test_valid_vendor_status(self):
        ok(validate_vendor_status("booked", ["pending", "booked", "confirmed"]))

    def test_invalid_vendor_status(self):
        err(validate_vendor_status("unknown", ["pending", "booked"]))

    def test_valid_priority(self):
        ok(validate_priority("high", ["high", "medium", "low"]))

    def test_invalid_priority(self):
        err(validate_priority("extreme", ["high", "medium", "low"]))


# ── AI event plan schema ──────────────────────────────────────────────────────

class TestValidateAiEventPlan:
    def _valid_plan(self) -> dict:
        future = (date.today() + timedelta(days=90)).isoformat()
        return {
            "event_summary": "A beautiful wedding celebration.",
            "key_highlights": ["Outdoor ceremony", "Live music"],
            "budget_breakdown": {"Venue": 50000, "Catering": 80000},
            "timeline_milestones": [
                {"task": "Book venue", "deadline": future, "priority": "high"}
            ],
            "vendor_checklist": [
                {"category": "Photography", "name_suggestion": "Local photographer", "notes": "Review portfolio"}
            ],
        }

    def test_valid_plan(self):
        ok(validate_ai_event_plan(self._valid_plan()))

    def test_not_a_dict(self):
        err(validate_ai_event_plan(["list"]), "object")

    def test_missing_event_summary(self):
        plan = self._valid_plan()
        del plan["event_summary"]
        err(validate_ai_event_plan(plan), "missing")

    def test_missing_budget_breakdown(self):
        plan = self._valid_plan()
        del plan["budget_breakdown"]
        err(validate_ai_event_plan(plan), "missing")

    def test_empty_event_summary(self):
        plan = self._valid_plan()
        plan["event_summary"] = "  "
        err(validate_ai_event_plan(plan), "non-empty")

    def test_budget_breakdown_not_dict(self):
        plan = self._valid_plan()
        plan["budget_breakdown"] = [1000, 2000]
        err(validate_ai_event_plan(plan), "object")

    def test_non_numeric_budget_amount(self):
        plan = self._valid_plan()
        plan["budget_breakdown"]["Venue"] = "fifty thousand"
        err(validate_ai_event_plan(plan), "numeric")

    def test_timeline_not_a_list(self):
        plan = self._valid_plan()
        plan["timeline_milestones"] = {"task": "Book venue"}
        err(validate_ai_event_plan(plan), "list")

    def test_milestone_missing_task(self):
        plan = self._valid_plan()
        plan["timeline_milestones"] = [{"deadline": "2025-01-01", "priority": "high"}]
        err(validate_ai_event_plan(plan), "task")

    def test_vendor_checklist_missing_category(self):
        plan = self._valid_plan()
        plan["vendor_checklist"] = [{"name_suggestion": "Photographer"}]
        err(validate_ai_event_plan(plan), "category")

    def test_key_highlights_not_a_list(self):
        plan = self._valid_plan()
        plan["key_highlights"] = "Just one highlight"
        err(validate_ai_event_plan(plan), "list")


# ── AI budget suggestions schema ──────────────────────────────────────────────

class TestValidateAiBudgetSuggestions:
    def _valid_suggestions(self) -> dict:
        return {
            "optimizations": [
                {"category": "Catering", "suggestion": "Use buffet instead of plated service.", "potential_saving": "10-15%"}
            ],
            "summary": "Focus on catering and decoration to reduce costs.",
        }

    def test_valid_suggestions(self):
        ok(validate_ai_budget_suggestions(self._valid_suggestions()))

    def test_missing_optimizations(self):
        data = {"summary": "Good plan."}
        err(validate_ai_budget_suggestions(data), "missing")

    def test_missing_summary(self):
        data = {"optimizations": []}
        err(validate_ai_budget_suggestions(data), "missing")

    def test_optimizations_not_list(self):
        data = {"optimizations": "reduce catering", "summary": "Good."}
        err(validate_ai_budget_suggestions(data), "list")

    def test_optimization_missing_category(self):
        data = {
            "optimizations": [{"suggestion": "Cut flowers budget."}],
            "summary": "Good.",
        }
        err(validate_ai_budget_suggestions(data), "category")

    def test_not_a_dict(self):
        err(validate_ai_budget_suggestions("just text"), "object")
