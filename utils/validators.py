"""
utils/validators.py
────────────────────
Input validation and sanitisation for UtsavAI.

All functions are pure (no side effects) and return a tuple:
    (is_valid: bool, error_message: str)

Where is_valid is True and error_message is "" on success.

Layer contract: utils/ may only import from the Python standard library.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────────
_MAX_TEXT_LENGTH: int = 500
_MAX_NAME_LENGTH: int = 120
_MIN_GUEST_COUNT: int = 1
_MAX_GUEST_COUNT: int = 100_000
_MIN_BUDGET: float = 100.0
_MAX_BUDGET: float = 1_000_000_000.0  # 1 billion


# ── Generic helpers ───────────────────────────────────────────────────────────

def _ok() -> tuple[bool, str]:
    return True, ""


def _err(msg: str) -> tuple[bool, str]:
    return False, msg


# ── Text / name validators ────────────────────────────────────────────────────

def validate_event_name(name: Any) -> tuple[bool, str]:
    """
    Validate a human-readable event name.

    Rules:
    - Must be a non-empty string after stripping whitespace.
    - Maximum 120 characters.
    - Must not consist entirely of special characters or digits.
    """
    if not isinstance(name, str):
        return _err("Event name must be a text string.")
    name = name.strip()
    if not name:
        return _err("Event name cannot be empty.")
    if len(name) > _MAX_NAME_LENGTH:
        return _err(f"Event name must be {_MAX_NAME_LENGTH} characters or fewer.")
    # Must contain at least one letter
    if not re.search(r"[A-Za-z\u0900-\u097F\u0C00-\u0C7F\u0B80-\u0BFF]", name):
        return _err("Event name must contain at least one letter.")
    return _ok()


def validate_location(location: Any) -> tuple[bool, str]:
    """Validate an event location string."""
    if not isinstance(location, str):
        return _err("Location must be a text string.")
    location = location.strip()
    if not location:
        return _err("Location cannot be empty.")
    if len(location) > _MAX_TEXT_LENGTH:
        return _err(f"Location must be {_MAX_TEXT_LENGTH} characters or fewer.")
    return _ok()


def validate_free_text(text: Any, field_name: str = "Text") -> tuple[bool, str]:
    """Validate generic free-text fields (notes, preferences, etc.)."""
    if text is None or text == "":
        return _ok()  # Optional fields are allowed to be empty
    if not isinstance(text, str):
        return _err(f"{field_name} must be a text string.")
    if len(text) > _MAX_TEXT_LENGTH:
        return _err(f"{field_name} must be {_MAX_TEXT_LENGTH} characters or fewer.")
    return _ok()


# ── Numeric validators ────────────────────────────────────────────────────────

def validate_guest_count(count: Any) -> tuple[bool, str]:
    """
    Validate guest count.

    Rules:
    - Must be an integer (or a string representation of one).
    - Between 1 and 100,000 inclusive.
    """
    try:
        value = int(count)
    except (TypeError, ValueError):
        return _err("Guest count must be a whole number.")
    if value < _MIN_GUEST_COUNT:
        return _err(f"Guest count must be at least {_MIN_GUEST_COUNT}.")
    if value > _MAX_GUEST_COUNT:
        return _err(f"Guest count cannot exceed {_MAX_GUEST_COUNT:,}.")
    return _ok()


def validate_budget(budget: Any) -> tuple[bool, str]:
    """
    Validate a monetary budget amount (INR).

    Rules:
    - Must be a positive number.
    - Between 100 and 1,000,000,000.
    - Not NaN or infinite.
    """
    try:
        value = float(budget)
    except (TypeError, ValueError):
        return _err("Budget must be a numeric value.")
    import math
    if math.isnan(value) or math.isinf(value):
        return _err("Budget must be a finite number.")
    if value < _MIN_BUDGET:
        return _err(f"Budget must be at least ₹{_MIN_BUDGET:,.0f}.")
    if value > _MAX_BUDGET:
        return _err(f"Budget cannot exceed ₹{_MAX_BUDGET:,.0f}.")
    return _ok()


def validate_amount(amount: Any, field_name: str = "Amount") -> tuple[bool, str]:
    """Validate a non-negative monetary amount (used for budget_items)."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return _err(f"{field_name} must be a numeric value.")
    import math
    if math.isnan(value) or math.isinf(value):
        return _err(f"{field_name} must be a finite number.")
    if value < 0.0:
        return _err(f"{field_name} cannot be negative.")
    return _ok()


# ── Date validators ───────────────────────────────────────────────────────────

def validate_event_date(event_date: Any) -> tuple[bool, str]:
    """
    Validate an event date.

    Rules:
    - Must be a date or datetime object, or an ISO-format date string (YYYY-MM-DD).
    - Must not be in the past (compared to today's date).
    """
    if isinstance(event_date, datetime):
        event_date = event_date.date()

    if isinstance(event_date, date):
        parsed = event_date
    elif isinstance(event_date, str):
        try:
            parsed = date.fromisoformat(event_date.strip())
        except ValueError:
            return _err("Event date must be in YYYY-MM-DD format.")
    else:
        return _err("Event date must be a date or ISO-format date string.")

    if parsed < date.today():
        return _err("Event date cannot be in the past.")
    return _ok()


def validate_task_deadline(
    deadline: Any, event_date: Any = None
) -> tuple[bool, str]:
    """
    Validate a timeline task deadline.

    Rules:
    - Must be a valid date (ISO string or date object).
    - If event_date is provided, deadline must be on or before the event date.
    """
    if isinstance(deadline, datetime):
        deadline = deadline.date()

    if isinstance(deadline, date):
        parsed_deadline = deadline
    elif isinstance(deadline, str):
        try:
            parsed_deadline = date.fromisoformat(deadline.strip())
        except ValueError:
            return _err("Task deadline must be in YYYY-MM-DD format.")
    else:
        return _err("Task deadline must be a date or ISO-format date string.")

    if event_date is not None:
        if isinstance(event_date, datetime):
            event_date = event_date.date()
        if isinstance(event_date, str):
            try:
                event_date = date.fromisoformat(event_date.strip())
            except ValueError:
                pass  # Cannot cross-validate; skip
        if isinstance(event_date, date) and parsed_deadline > event_date:
            return _err("Task deadline cannot be after the event date.")

    return _ok()


# ── Enum-style validators ─────────────────────────────────────────────────────

def validate_event_type(event_type: Any, allowed: list[str]) -> tuple[bool, str]:
    """Validate that event_type is one of the allowed values."""
    if not isinstance(event_type, str) or event_type.strip() not in allowed:
        return _err(f"Event type must be one of: {', '.join(allowed)}.")
    return _ok()


def validate_vendor_status(status: Any, allowed: list[str]) -> tuple[bool, str]:
    """Validate a vendor status value."""
    if not isinstance(status, str) or status.strip() not in allowed:
        return _err(f"Vendor status must be one of: {', '.join(allowed)}.")
    return _ok()


def validate_priority(priority: Any, allowed: list[str]) -> tuple[bool, str]:
    """Validate a task priority value."""
    if not isinstance(priority, str) or priority.strip() not in allowed:
        return _err(f"Priority must be one of: {', '.join(allowed)}.")
    return _ok()


# ── AI response validators ────────────────────────────────────────────────────

def validate_ai_event_plan(data: Any) -> tuple[bool, str]:
    """
    Schema-validate an AI-generated event plan dict.

    Expected top-level structure:
    {
        "event_summary": str,
        "key_highlights": list,
        "budget_breakdown": {category: amount, ...},
        "timeline_milestones": list[{task, deadline, priority}],
        "vendor_checklist": list[{category, name_suggestion, notes}],
        "cultural_notes": str   (optional)
    }
    """
    if not isinstance(data, dict):
        return _err("AI response must be a JSON object.")

    required = {"event_summary", "key_highlights", "budget_breakdown", "timeline_milestones", "vendor_checklist"}
    missing = required - data.keys()
    if missing:
        return _err(f"AI response missing required fields: {', '.join(sorted(missing))}.")

    if not isinstance(data["event_summary"], str) or not data["event_summary"].strip():
        return _err("'event_summary' must be a non-empty string.")

    if not isinstance(data["key_highlights"], list):
        return _err("'key_highlights' must be a list.")

    if not isinstance(data["budget_breakdown"], dict):
        return _err("'budget_breakdown' must be a JSON object.")

    # Validate each budget entry is numeric
    for category, amount in data["budget_breakdown"].items():
        if not isinstance(amount, (int, float)):
            return _err(f"Budget amount for '{category}' must be numeric.")

    if not isinstance(data["timeline_milestones"], list):
        return _err("'timeline_milestones' must be a list.")

    for i, milestone in enumerate(data["timeline_milestones"]):
        if not isinstance(milestone, dict):
            return _err(f"timeline_milestones[{i}] must be a JSON object.")
        for key in ("task", "deadline", "priority"):
            if key not in milestone:
                return _err(f"timeline_milestones[{i}] missing '{key}'.")

    if not isinstance(data["vendor_checklist"], list):
        return _err("'vendor_checklist' must be a list.")

    for i, vendor in enumerate(data["vendor_checklist"]):
        if not isinstance(vendor, dict):
            return _err(f"vendor_checklist[{i}] must be a JSON object.")
        if "category" not in vendor:
            return _err(f"vendor_checklist[{i}] missing 'category'.")

    return _ok()


def validate_ai_budget_suggestions(data: Any) -> tuple[bool, str]:
    """
    Schema-validate AI-generated budget suggestions.

    Expected structure:
    {
        "optimizations": list[{category, suggestion, potential_saving}],
        "summary": str
    }
    """
    if not isinstance(data, dict):
        return _err("AI budget response must be a JSON object.")

    required = {"optimizations", "summary"}
    missing = required - data.keys()
    if missing:
        return _err(f"AI budget response missing fields: {', '.join(sorted(missing))}.")

    if not isinstance(data["optimizations"], list):
        return _err("'optimizations' must be a list.")

    for i, opt in enumerate(data["optimizations"]):
        if not isinstance(opt, dict):
            return _err(f"optimizations[{i}] must be a JSON object.")
        if "category" not in opt or "suggestion" not in opt:
            return _err(f"optimizations[{i}] missing 'category' or 'suggestion'.")

    return _ok()
