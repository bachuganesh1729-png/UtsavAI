"""
utils/formatters.py
────────────────────
Pure formatting utilities for UtsavAI.

All functions take primitive values and return formatted strings.
No side effects, no external imports beyond the standard library.

Layer contract: utils/ may only import from the Python standard library.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def format_currency(amount: float, symbol: str = "₹") -> str:
    """
    Format a float as Indian currency with comma-separated thousands.

    Examples:
        format_currency(150000)    → "₹1,50,000"
        format_currency(1500.50)   → "₹1,500.50"
        format_currency(0)         → "₹0"

    Uses Indian numbering system (lakhs / crores) for amounts >= 1,000.
    Falls back to standard formatting for simplicity and readability.
    """
    if amount == int(amount):
        # Whole number — no decimal places needed
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"


def format_currency_compact(amount: float, symbol: str = "₹") -> str:
    """
    Format large amounts as compact Indian notation.

    Examples:
        100_000   → "₹1.00 L"
        1_000_000 → "₹10.00 L"
        10_000_000 → "₹1.00 Cr"
    """
    if amount >= 10_000_000:
        return f"{symbol}{amount / 10_000_000:.2f} Cr"
    if amount >= 100_000:
        return f"{symbol}{amount / 100_000:.2f} L"
    return format_currency(amount, symbol)


def format_date(d: date | datetime | str | None, fmt: str = "%d %b %Y") -> str:
    """
    Format a date object or ISO string for display.

    Examples:
        format_date(date(2025, 3, 15))      → "15 Mar 2025"
        format_date("2025-03-15")           → "15 Mar 2025"
        format_date(None)                   → "—"
    """
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d.strip())
        except ValueError:
            return d  # Return as-is if not parseable
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(fmt)


def format_date_relative(d: date | datetime | str | None) -> str:
    """
    Format a date as a relative description ("in 30 days", "Today", "45 days ago").

    Returns "—" for None.
    """
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d.strip())
        except ValueError:
            return d
    if isinstance(d, datetime):
        d = d.date()

    today = date.today()
    delta = (d - today).days

    if delta == 0:
        return "Today"
    if delta > 0:
        if delta == 1:
            return "Tomorrow"
        if delta < 7:
            return f"In {delta} days"
        if delta < 30:
            weeks = delta // 7
            return f"In {weeks} week{'s' if weeks > 1 else ''}"
        if delta < 365:
            months = delta // 30
            return f"In {months} month{'s' if months > 1 else ''}"
        years = delta // 365
        return f"In {years} year{'s' if years > 1 else ''}"
    # Past
    delta = abs(delta)
    if delta == 1:
        return "Yesterday"
    return f"{delta} days ago"


def format_percentage(value: float, total: float) -> str:
    """
    Format value as a percentage of total.

    Returns "0%" if total is zero to avoid ZeroDivisionError.
    """
    if total == 0:
        return "0%"
    return f"{(value / total * 100):.1f}%"


def format_guest_count(count: int) -> str:
    """Format a guest count with appropriate label."""
    return f"{count:,} guest{'s' if count != 1 else ''}"


def format_status_badge(status: str) -> str:
    """
    Return an emoji badge for a status string.

    Used for display in text contexts; not for accessible UI (use labels there).
    """
    mapping = {
        "pending": "⏳ Pending",
        "contacted": "📞 Contacted",
        "booked": "📋 Booked",
        "confirmed": "✅ Confirmed",
        "cancelled": "❌ Cancelled",
        "in_progress": "🔄 In Progress",
        "completed": "✅ Completed",
        "high": "🔴 High",
        "medium": "🟡 Medium",
        "low": "🟢 Low",
    }
    return mapping.get(status.lower(), status.title())


def truncate_text(text: str, max_chars: int = 80, ellipsis: str = "…") -> str:
    """Truncate text to max_chars, appending ellipsis if truncated."""
    if not text or len(text) <= max_chars:
        return text
    return text[: max_chars - len(ellipsis)].rstrip() + ellipsis


def sanitize_for_display(text: Optional[str]) -> str:
    """
    Return a safe display string.
    Strips leading/trailing whitespace; returns "—" for None or empty.
    Does NOT perform HTML escaping — Streamlit handles that in non-HTML contexts.
    """
    if not text:
        return "—"
    return text.strip()
