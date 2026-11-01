"""
services/budget_service.py
───────────────────────────
Budget calculation and management for UtsavAI.

ALL financial arithmetic is performed here in Python.
AI-generated budget figures from gemini_service are treated as
SUGGESTIONS only and are re-verified/re-totalled by this module
before persistence or display.

Layer contract: services/ may import from utils/ and the standard library.
                services/ must NOT import from modules/ or streamlit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Domain types ──────────────────────────────────────────────────────────────


@dataclass
class BudgetItem:
    """A single budget line item."""
    category:         str
    allocated_amount: float
    actual_amount:    float = 0.0
    notes:            str   = ""

    @property
    def variance(self) -> float:
        """Positive = under budget. Negative = over budget."""
        return round(self.allocated_amount - self.actual_amount, 2)

    @property
    def is_over_budget(self) -> bool:
        return self.actual_amount > self.allocated_amount

    @property
    def utilisation_pct(self) -> float:
        """Percentage of allocation spent. Returns 0.0 if allocation is zero."""
        if self.allocated_amount == 0:
            return 0.0
        return min((self.actual_amount / self.allocated_amount) * 100, 999.9)


@dataclass
class BudgetSummary:
    """Aggregated budget metrics for an event."""
    total_budget:      float
    total_allocated:   float
    total_actual:      float
    unallocated:       float
    total_variance:    float
    overrun_amount:    float
    overrun_categories: list[str]
    items:             list[BudgetItem]

    @property
    def is_over_budget(self) -> bool:
        return self.total_actual > self.total_budget

    @property
    def utilisation_pct(self) -> float:
        if self.total_budget == 0:
            return 0.0
        return min((self.total_actual / self.total_budget) * 100, 999.9)

    @property
    def allocation_pct(self) -> float:
        """Percentage of total budget that has been allocated across categories."""
        if self.total_budget == 0:
            return 0.0
        return min((self.total_allocated / self.total_budget) * 100, 100.0)


# ── Core calculations ─────────────────────────────────────────────────────────


def compute_budget_summary(
    total_budget: float, items: list[dict[str, Any]]
) -> BudgetSummary:
    """
    Compute the full budget summary from raw DB rows or dicts.

    Args:
        total_budget: Total event budget in INR.
        items:        List of dicts with keys: category, allocated_amount,
                      actual_amount, notes (optional).

    Returns:
        BudgetSummary with all computed metrics.

    All arithmetic uses Python float operations. Figures are never taken
    directly from AI responses without re-computation here.
    """
    budget_items: list[BudgetItem] = []
    for item in items:
        try:
            budget_items.append(
                BudgetItem(
                    category=str(item.get("category", "Unknown")),
                    allocated_amount=round(float(item.get("allocated_amount", 0.0)), 2),
                    actual_amount=round(float(item.get("actual_amount", 0.0)), 2),
                    notes=str(item.get("notes", "")),
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping invalid budget item: %s | Error: %s", item, exc)

    total_allocated = round(sum(i.allocated_amount for i in budget_items), 2)
    total_actual = round(sum(i.actual_amount for i in budget_items), 2)
    unallocated = round(max(0.0, float(total_budget) - total_allocated), 2)
    total_variance = round(total_allocated - total_actual, 2)
    overrun_categories = [i.category for i in budget_items if i.is_over_budget]
    overrun_amount = round(sum(
        abs(i.variance) for i in budget_items if i.is_over_budget
    ), 2)

    return BudgetSummary(
        total_budget=round(float(total_budget), 2),
        total_allocated=total_allocated,
        total_actual=total_actual,
        unallocated=unallocated,
        total_variance=total_variance,
        overrun_amount=overrun_amount,
        overrun_categories=overrun_categories,
        items=budget_items,
    )


def distribute_ai_budget(
    ai_breakdown: dict[str, Any],
    total_budget: float,
    allowed_categories: list[str],
) -> list[BudgetItem]:
    """
    Convert an AI-generated budget breakdown into validated BudgetItems.

    Ensures:
    - Only allowed categories are included (if non-empty).
    - All amounts are non-negative floats.
    - The total across all items does not exceed total_budget.
      If the AI total exceeds the budget, all amounts are scaled down
      proportionally so the sum equals total_budget.
    - Amounts are re-computed in Python; AI totals are not trusted.

    Args:
        ai_breakdown:       Dict of {category: amount} from Gemini.
        total_budget:       Total event budget (INR).
        allowed_categories: Permitted category names.

    Returns:
        List of BudgetItem with corrected allocations.
    """
    raw_items: list[BudgetItem] = []

    for category, amount in ai_breakdown.items():
        cat = str(category).strip()
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            logger.warning("Skipping non-numeric AI budget amount for '%s': %s", cat, amount)
            continue

        if amt < 0:
            logger.warning("Negative AI budget amount for '%s': %.2f — setting to 0", cat, amt)
            amt = 0.0

        raw_items.append(BudgetItem(category=cat, allocated_amount=round(amt, 2)))

    # Compute Python total (not trusted from AI)
    python_total = sum(i.allocated_amount for i in raw_items)

    # Scale down if AI total exceeds budget
    if python_total > total_budget and python_total > 0:
        scale = total_budget / python_total
        logger.info(
            "AI budget total (%.2f) exceeds total_budget (%.2f). Scaling by %.4f.",
            python_total, total_budget, scale,
        )
        scaled_sum = 0.0
        for item in raw_items:
            item.allocated_amount = round(item.allocated_amount * scale, 2)
            scaled_sum += item.allocated_amount

        # Fix any rounding discrepancy on the last item so the sum equals total_budget
        diff = round(total_budget - scaled_sum, 2)
        if diff != 0.0 and raw_items:
            raw_items[-1].allocated_amount = round(raw_items[-1].allocated_amount + diff, 2)

    return raw_items


def calculate_per_guest_cost(total_actual: float, guest_count: int) -> float:
    """
    Calculate the per-guest cost.

    Returns 0.0 if guest_count is zero or non-positive (avoid ZeroDivisionError).
    """
    if isinstance(guest_count, bool) or not isinstance(guest_count, (int, float)) or guest_count <= 0:
        return 0.0
    try:
        actual = float(total_actual)
    except (TypeError, ValueError):
        return 0.0
    return round(actual / guest_count, 2)


def suggest_default_allocation(
    total_budget: float,
    event_type: str,
    categories: list[str],
) -> list[BudgetItem]:
    """
    Generate a rule-based default budget allocation when AI is unavailable.

    Allocation percentages are culturally informed but approximate. Users
    should customise them for their specific event.

    Args:
        total_budget: Total budget in INR.
        event_type:   Event type string (e.g., "Wedding").
        categories:   List of category names to allocate across.

    Returns:
        List of BudgetItem with pre-filled allocated_amount values.
        Total will equal total_budget (rounding applied to last item).
    """
    # Default weight tables by event type (percentage points, must sum to 100)
    _WEIGHTS: dict[str, dict[str, float]] = {
        "Wedding": {
            "Venue": 20.0,
            "Catering": 30.0,
            "Decoration": 12.0,
            "Photography & Videography": 8.0,
            "Music & Entertainment": 5.0,
            "Attire & Grooming": 8.0,
            "Invitations & Stationery": 2.0,
            "Transportation": 3.0,
            "Accommodation": 4.0,
            "Gifts & Favours": 2.0,
            "Mehendi & Makeup": 3.0,
            "Flowers & Garlands": 2.0,
            "Pandit / Officiant": 1.0,
            "Miscellaneous": 0.0,
        },
        "Birthday Party": {
            "Venue": 25.0,
            "Catering": 35.0,
            "Decoration": 15.0,
            "Photography & Videography": 8.0,
            "Music & Entertainment": 8.0,
            "Invitations & Stationery": 2.0,
            "Transportation": 2.0,
            "Gifts & Favours": 3.0,
            "Miscellaneous": 2.0,
        },
    }

    weights = _WEIGHTS.get(event_type, {})
    items: list[BudgetItem] = []

    if not weights or not categories:
        if not categories:
            return []
        per_cat = round(total_budget / len(categories), 2)
        items = [BudgetItem(category=c, allocated_amount=per_cat) for c in categories]
        diff = round(total_budget - sum(i.allocated_amount for i in items), 2)
        if diff != 0.0 and items:
            items[-1].allocated_amount = round(items[-1].allocated_amount + diff, 2)
        return items

    # Only allocate for categories that appear in both the weight table and the request
    matched = [(c, weights[c]) for c in categories if c in weights]
    unmatched = [c for c in categories if c not in weights]

    total_weight = sum(w for _, w in matched)
    if total_weight == 0:
        per_cat = round(total_budget / max(len(categories), 1), 2)
        items = [BudgetItem(category=c, allocated_amount=per_cat) for c in categories]
        diff = round(total_budget - sum(i.allocated_amount for i in items), 2)
        if diff != 0.0 and items:
            items[-1].allocated_amount = round(items[-1].allocated_amount + diff, 2)
        return items

    allocated = 0.0
    for category, weight in matched:
        amount = round((weight / total_weight) * total_budget, 2)
        items.append(BudgetItem(category=category, allocated_amount=amount))
        allocated += amount

    # Distribute remainder equally to unmatched categories
    remainder = round(total_budget - allocated, 2)
    if unmatched:
        per_unmatched = round(remainder / len(unmatched), 2)
        for cat in unmatched:
            items.append(BudgetItem(category=cat, allocated_amount=per_unmatched))
        diff = round(total_budget - sum(i.allocated_amount for i in items), 2)
        if diff != 0.0 and items:
            items[-1].allocated_amount = round(items[-1].allocated_amount + diff, 2)
    elif items:
        # Add rounding remainder to the last matched item
        items[-1].allocated_amount = round(items[-1].allocated_amount + remainder, 2)

    return items


def build_chart_data(
    summary: BudgetSummary,
) -> tuple[list[str], list[float], list[float]]:
    """
    Extract parallel lists of (categories, allocated_amounts, actual_amounts)
    suitable for passing to Plotly chart functions.

    Returns:
        Tuple of (categories, allocated, actual) — three equal-length lists.
    """
    categories = [item.category for item in summary.items]
    allocated  = [item.allocated_amount for item in summary.items]
    actual     = [item.actual_amount for item in summary.items]
    return categories, allocated, actual
