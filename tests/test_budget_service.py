"""
tests/test_budget_service.py
─────────────────────────────
Unit tests for services/budget_service.py.

Covers:
- BudgetItem computed properties (variance, utilisation, over-budget flag)
- compute_budget_summary (totals, unallocated, overrun detection)
- Edge cases (zero budget, empty items, all over/under)
- distribute_ai_budget (scale-down, negative amounts, non-numeric, unknown categories)
- calculate_per_guest_cost (zero guests, normal)
- suggest_default_allocation (known/unknown event types, flat distribution)
- build_chart_data (parallel lists)
- Floating-point precision
"""

from __future__ import annotations

import pytest

from services.budget_service import (
    BudgetItem,
    BudgetSummary,
    compute_budget_summary,
    distribute_ai_budget,
    calculate_per_guest_cost,
    suggest_default_allocation,
    build_chart_data,
)


# ── BudgetItem properties ─────────────────────────────────────────────────────

class TestBudgetItem:
    def test_variance_under_budget(self):
        item = BudgetItem(category="Venue", allocated_amount=50_000, actual_amount=40_000)
        assert item.variance == pytest.approx(10_000)

    def test_variance_over_budget(self):
        item = BudgetItem(category="Catering", allocated_amount=30_000, actual_amount=35_000)
        assert item.variance == pytest.approx(-5_000)

    def test_variance_exact(self):
        item = BudgetItem(category="Decor", allocated_amount=10_000, actual_amount=10_000)
        assert item.variance == pytest.approx(0.0)

    def test_is_over_budget_false(self):
        item = BudgetItem(category="Venue", allocated_amount=50_000, actual_amount=40_000)
        assert item.is_over_budget is False

    def test_is_over_budget_true(self):
        item = BudgetItem(category="Catering", allocated_amount=30_000, actual_amount=35_000)
        assert item.is_over_budget is True

    def test_is_over_budget_equal(self):
        item = BudgetItem(category="Music", allocated_amount=10_000, actual_amount=10_000)
        assert item.is_over_budget is False

    def test_utilisation_pct_normal(self):
        item = BudgetItem(category="Venue", allocated_amount=50_000, actual_amount=25_000)
        assert item.utilisation_pct == pytest.approx(50.0)

    def test_utilisation_pct_zero_allocation(self):
        item = BudgetItem(category="Venue", allocated_amount=0, actual_amount=5_000)
        assert item.utilisation_pct == pytest.approx(0.0)

    def test_utilisation_pct_capped_at_999(self):
        item = BudgetItem(category="Venue", allocated_amount=1, actual_amount=100_000)
        assert item.utilisation_pct == pytest.approx(999.9)


# ── compute_budget_summary ────────────────────────────────────────────────────

class TestComputeBudgetSummary:
    def _items(self):
        return [
            {"category": "Venue",    "allocated_amount": 50_000, "actual_amount": 45_000},
            {"category": "Catering", "allocated_amount": 80_000, "actual_amount": 90_000},
            {"category": "Decor",    "allocated_amount": 30_000, "actual_amount": 25_000},
        ]

    def test_total_allocated(self):
        summary = compute_budget_summary(200_000, self._items())
        assert summary.total_allocated == pytest.approx(160_000)

    def test_total_actual(self):
        summary = compute_budget_summary(200_000, self._items())
        assert summary.total_actual == pytest.approx(160_000)

    def test_unallocated(self):
        summary = compute_budget_summary(200_000, self._items())
        assert summary.unallocated == pytest.approx(40_000)

    def test_overrun_categories(self):
        summary = compute_budget_summary(200_000, self._items())
        assert "Catering" in summary.overrun_categories
        assert "Venue" not in summary.overrun_categories

    def test_overrun_amount(self):
        summary = compute_budget_summary(200_000, self._items())
        assert summary.overrun_amount == pytest.approx(10_000)

    def test_is_not_over_budget(self):
        summary = compute_budget_summary(200_000, self._items())
        # total_actual = 160_000, total_budget = 200_000
        assert summary.is_over_budget is False

    def test_is_over_budget(self):
        summary = compute_budget_summary(150_000, self._items())
        # total_actual = 160_000 > 150_000
        assert summary.is_over_budget is True

    def test_empty_items(self):
        summary = compute_budget_summary(100_000, [])
        assert summary.total_allocated == 0.0
        assert summary.total_actual == 0.0
        assert summary.unallocated == 100_000
        assert summary.overrun_categories == []

    def test_zero_budget(self):
        summary = compute_budget_summary(0, [])
        assert summary.allocation_pct == pytest.approx(0.0)
        assert summary.utilisation_pct == pytest.approx(0.0)

    def test_invalid_item_skipped(self):
        items = [
            {"category": "Venue", "allocated_amount": "bad", "actual_amount": 0},
            {"category": "Catering", "allocated_amount": 50_000, "actual_amount": 40_000},
        ]
        summary = compute_budget_summary(100_000, items)
        # "bad" amount item should be skipped; only Catering counted
        assert len(summary.items) == 1
        assert summary.items[0].category == "Catering"

    def test_completion_pct(self):
        summary = compute_budget_summary(200_000, self._items())
        assert 0 <= summary.utilisation_pct <= 100

    def test_floating_point_precision(self):
        items = [
            {"category": "A", "allocated_amount": 1_000.10, "actual_amount": 333.33},
            {"category": "B", "allocated_amount": 2_000.20, "actual_amount": 666.67},
        ]
        summary = compute_budget_summary(5_000, items)
        # Python arithmetic should avoid compounding float errors
        assert summary.total_allocated == pytest.approx(3_000.30, rel=1e-4)


# ── distribute_ai_budget ──────────────────────────────────────────────────────

class TestDistributeAiBudget:
    def test_amounts_scaled_when_exceeding_budget(self):
        ai_breakdown = {"Venue": 100_000, "Catering": 150_000}  # sum = 250_000
        budget = 200_000
        items = distribute_ai_budget(ai_breakdown, budget, ["Venue", "Catering"])
        total = sum(i.allocated_amount for i in items)
        assert total == pytest.approx(budget, rel=1e-4)

    def test_amounts_unchanged_when_under_budget(self):
        ai_breakdown = {"Venue": 50_000, "Catering": 80_000}  # sum = 130_000
        budget = 200_000
        items = distribute_ai_budget(ai_breakdown, budget, ["Venue", "Catering"])
        total = sum(i.allocated_amount for i in items)
        assert total == pytest.approx(130_000, rel=1e-4)

    def test_negative_amount_zeroed(self):
        ai_breakdown = {"Venue": -5_000, "Catering": 50_000}
        items = distribute_ai_budget(ai_breakdown, 100_000, ["Venue", "Catering"])
        venue_item = next(i for i in items if i.category == "Venue")
        assert venue_item.allocated_amount == pytest.approx(0.0)

    def test_non_numeric_amount_skipped(self):
        ai_breakdown = {"Venue": "fifty thousand", "Catering": 50_000}
        items = distribute_ai_budget(ai_breakdown, 100_000, ["Venue", "Catering"])
        categories = [i.category for i in items]
        assert "Venue" not in categories
        assert "Catering" in categories

    def test_empty_breakdown(self):
        items = distribute_ai_budget({}, 100_000, ["Venue", "Catering"])
        assert items == []

    def test_zero_total_no_scaling(self):
        ai_breakdown = {"Venue": 0, "Catering": 0}
        items = distribute_ai_budget(ai_breakdown, 100_000, ["Venue", "Catering"])
        # All zeros, total is 0 — no scaling applied
        assert all(i.allocated_amount == 0.0 for i in items)


# ── calculate_per_guest_cost ──────────────────────────────────────────────────

class TestCalculatePerGuestCost:
    def test_normal(self):
        result = calculate_per_guest_cost(500_000, 100)
        assert result == pytest.approx(5_000.0)

    def test_zero_guests(self):
        result = calculate_per_guest_cost(500_000, 0)
        assert result == pytest.approx(0.0)

    def test_negative_guests(self):
        result = calculate_per_guest_cost(500_000, -1)
        assert result == pytest.approx(0.0)

    def test_single_guest(self):
        result = calculate_per_guest_cost(100_000, 1)
        assert result == pytest.approx(100_000.0)


# ── suggest_default_allocation ────────────────────────────────────────────────

class TestSuggestDefaultAllocation:
    def test_wedding_total_equals_budget(self):
        from utils.config import BUDGET_CATEGORIES
        items = suggest_default_allocation(500_000, "Wedding", BUDGET_CATEGORIES)
        total = sum(i.allocated_amount for i in items)
        assert total == pytest.approx(500_000, rel=1e-3)

    def test_birthday_total_equals_budget(self):
        cats = ["Venue", "Catering", "Decoration", "Music & Entertainment"]
        items = suggest_default_allocation(100_000, "Birthday Party", cats)
        total = sum(i.allocated_amount for i in items)
        assert total == pytest.approx(100_000, rel=1e-3)

    def test_unknown_event_type_flat_distribution(self):
        cats = ["A", "B", "C", "D"]
        items = suggest_default_allocation(40_000, "Space Party", cats)
        # Flat distribution: 10_000 each
        for item in items:
            assert item.allocated_amount == pytest.approx(10_000, rel=1e-3)

    def test_empty_categories(self):
        items = suggest_default_allocation(100_000, "Wedding", [])
        assert items == []

    def test_all_amounts_non_negative(self):
        from utils.config import BUDGET_CATEGORIES
        items = suggest_default_allocation(100, "Wedding", BUDGET_CATEGORIES)
        for item in items:
            assert item.allocated_amount >= 0


# ── build_chart_data ──────────────────────────────────────────────────────────

class TestBuildChartData:
    def test_returns_three_parallel_lists(self):
        summary = compute_budget_summary(
            100_000,
            [
                {"category": "Venue",    "allocated_amount": 40_000, "actual_amount": 35_000},
                {"category": "Catering", "allocated_amount": 60_000, "actual_amount": 65_000},
            ],
        )
        cats, alloc, actual = build_chart_data(summary)
        assert len(cats) == len(alloc) == len(actual) == 2
        assert "Venue" in cats
        assert "Catering" in cats

    def test_empty_summary(self):
        summary = compute_budget_summary(100_000, [])
        cats, alloc, actual = build_chart_data(summary)
        assert cats == []
        assert alloc == []
        assert actual == []
