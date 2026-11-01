"""
tests/test_validators_extended.py
───────────────────────────────────
Extended unit tests for utils/validators.py hardening.

Covers:
- Boolean rejection for validate_guest_count, validate_budget, validate_amount, validate_event_date, validate_task_deadline
- NaN and infinity rejection for numeric validators
- Fractional guest count rejection (e.g. 3.7, 10.5, but accepting 10.0 or 100)
- Negative value rejection
- validate_ai_event_plan with total_budget tolerance check (>5% over budget)
- validate_ai_event_plan with valid and invalid milestone dates, task texts, categories
- validate_ai_budget_suggestions with empty string summary, >20 optimizations, invalid fields
"""

from __future__ import annotations

import math
from datetime import date, timedelta
import pytest

from utils.validators import (
    validate_guest_count,
    validate_budget,
    validate_amount,
    validate_event_date,
    validate_task_deadline,
    validate_ai_event_plan,
    validate_ai_budget_suggestions,
)


def _ok(result: tuple[bool, str]) -> None:
    assert result[0] is True, f"Expected OK but got error: {result[1]}"


def _err(result: tuple[bool, str], fragment: str = "") -> None:
    assert result[0] is False, "Expected error but got OK"
    if fragment:
        assert fragment.lower() in result[1].lower(), (
            f"Expected '{fragment}' in error message but got: {result[1]}"
        )


# ── Boolean & Type Rejections ─────────────────────────────────────────────────

class TestBooleanAndTypeRejection:
    def test_guest_count_rejects_bool_true(self):
        _err(validate_guest_count(True), "whole number")

    def test_guest_count_rejects_bool_false(self):
        _err(validate_guest_count(False), "whole number")

    def test_budget_rejects_bool_true(self):
        _err(validate_budget(True), "numeric")

    def test_budget_rejects_bool_false(self):
        _err(validate_budget(False), "numeric")

    def test_amount_rejects_bool_true(self):
        _err(validate_amount(True), "numeric")

    def test_amount_rejects_bool_false(self):
        _err(validate_amount(False), "numeric")

    def test_event_date_rejects_bool(self):
        _err(validate_event_date(True), "date")
        _err(validate_event_date(False), "date")

    def test_task_deadline_rejects_bool(self):
        _err(validate_task_deadline(True), "date")
        _err(validate_task_deadline(False), "date")


# ── NaN and Infinity Rejection ────────────────────────────────────────────────

class TestNaNAndInfinityRejection:
    def test_guest_count_nan(self):
        _err(validate_guest_count(math.nan), "finite")

    def test_guest_count_pos_inf(self):
        _err(validate_guest_count(math.inf), "finite")

    def test_guest_count_neg_inf(self):
        _err(validate_guest_count(-math.inf), "finite")

    def test_budget_nan(self):
        _err(validate_budget(math.nan), "finite")

    def test_budget_inf(self):
        _err(validate_budget(math.inf), "finite")

    def test_budget_neg_inf(self):
        _err(validate_budget(-math.inf), "finite")

    def test_amount_nan(self):
        _err(validate_amount(math.nan), "finite")

    def test_amount_inf(self):
        _err(validate_amount(math.inf), "finite")

    def test_amount_neg_inf(self):
        _err(validate_amount(-math.inf), "finite")


# ── Fractional Guest Count Rejection ──────────────────────────────────────────

class TestFractionalGuestCount:
    def test_rejects_float_with_fraction(self):
        _err(validate_guest_count(3.7), "whole number")
        _err(validate_guest_count(10.25), "whole number")
        _err(validate_guest_count(0.5), "whole number")

    def test_accepts_integer_valued_float(self):
        _ok(validate_guest_count(100.0))
        _ok(validate_guest_count(50.0))

    def test_rejects_string_float_fraction(self):
        _err(validate_guest_count("3.7"), "whole number")
        _err(validate_guest_count("150.9"), "whole number")

    def test_accepts_string_float_integer_value(self):
        _ok(validate_guest_count("100.0"))

    def test_rejects_negative_guest_count(self):
        _err(validate_guest_count(-10), "negative")


# ── Deadline Cross-Validation Edge Cases ──────────────────────────────────────

class TestTaskDeadlineEdgeCases:
    def test_invalid_event_date_does_not_block_valid_deadline(self):
        deadline = (date.today() + timedelta(days=30)).isoformat()
        _ok(validate_task_deadline(deadline, "not-a-real-date"))
        _ok(validate_task_deadline(deadline, None))
        _ok(validate_task_deadline(deadline, 12345))

    def test_deadline_after_valid_event_date_fails(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        deadline = (date.today() + timedelta(days=61)).isoformat()
        _err(validate_task_deadline(deadline, event_date), "after the event")


# ── Extended AI Event Plan Validation ─────────────────────────────────────────

class TestExtendedAiEventPlanValidation:
    def _base_plan(self) -> dict:
        future = (date.today() + timedelta(days=60)).isoformat()
        return {
            "event_summary": "Intimate wedding in Bangalore.",
            "key_highlights": ["Mandap ritual", "Carnatic concert"],
            "budget_breakdown": {
                "Venue": 100_000.0,
                "Catering": 150_000.0,
            },
            "timeline_milestones": [
                {"task": "Book venue", "deadline": future, "priority": "high"}
            ],
            "vendor_checklist": [
                {"category": "Catering", "name_suggestion": "Annapurna Caterers"}
            ],
        }

    def test_valid_plan_with_budget_within_tolerance(self):
        plan = self._base_plan()
        # Sum is 250,000. Total budget = 240,000. 240,000 * 1.05 = 252,000 (within 5% tolerance)
        _ok(validate_ai_event_plan(plan, total_budget=240_000.0))

    def test_invalid_plan_budget_exceeds_tolerance(self):
        plan = self._base_plan()
        # Sum is 250,000. Total budget = 200,000. 200,000 * 1.05 = 210,000 (exceeds tolerance)
        _err(validate_ai_event_plan(plan, total_budget=200_000.0), "exceeds total budget")

    def test_budget_breakdown_rejects_bool(self):
        plan = self._base_plan()
        plan["budget_breakdown"]["Venue"] = True
        _err(validate_ai_event_plan(plan), "numeric")

    def test_budget_breakdown_rejects_nan(self):
        plan = self._base_plan()
        plan["budget_breakdown"]["Venue"] = math.nan
        _err(validate_ai_event_plan(plan), "finite")

    def test_budget_breakdown_rejects_negative(self):
        plan = self._base_plan()
        plan["budget_breakdown"]["Venue"] = -5000.0
        _err(validate_ai_event_plan(plan), "negative")

    def test_timeline_milestones_rejects_malformed_deadline(self):
        plan = self._base_plan()
        plan["timeline_milestones"][0]["deadline"] = "2025/12/31"
        _err(validate_ai_event_plan(plan), "ISO date")

    def test_timeline_milestones_rejects_invalid_priority(self):
        plan = self._base_plan()
        plan["timeline_milestones"][0]["priority"] = "urgent"
        _err(validate_ai_event_plan(plan), "priority")

    def test_timeline_milestones_rejects_empty_task(self):
        plan = self._base_plan()
        plan["timeline_milestones"][0]["task"] = "   "
        _err(validate_ai_event_plan(plan), "task")

    def test_vendor_checklist_rejects_empty_category(self):
        plan = self._base_plan()
        plan["vendor_checklist"][0]["category"] = ""
        _err(validate_ai_event_plan(plan), "category")


# ── Extended AI Budget Suggestions Validation ─────────────────────────────────

class TestExtendedAiBudgetSuggestionsValidation:
    def test_valid_empty_optimizations(self):
        data = {
            "summary": "Everything looks balanced.",
            "optimizations": [],
        }
        _ok(validate_ai_budget_suggestions(data))

    def test_valid_empty_summary(self):
        data = {
            "summary": "",
            "optimizations": [
                {"category": "Venue", "suggestion": "Negotiate package", "potential_saving": "5%"}
            ],
        }
        _ok(validate_ai_budget_suggestions(data))

    def test_rejects_more_than_20_optimizations(self):
        data = {
            "summary": "Too many suggestions.",
            "optimizations": [
                {"category": f"Cat {i}", "suggestion": f"Sugg {i}", "potential_saving": "5%"}
                for i in range(21)
            ],
        }
        _err(validate_ai_budget_suggestions(data), "cannot contain more than 20")

    def test_rejects_missing_potential_saving(self):
        data = {
            "summary": "Advice.",
            "optimizations": [
                {"category": "Decor", "suggestion": "Use local flowers"}
            ],
        }
        _err(validate_ai_budget_suggestions(data), "potential_saving")

    def test_rejects_empty_category_in_optimization(self):
        data = {
            "summary": "Advice.",
            "optimizations": [
                {"category": "  ", "suggestion": "Save money", "potential_saving": "10%"}
            ],
        }
        _err(validate_ai_budget_suggestions(data), "category")
