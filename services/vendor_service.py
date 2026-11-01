"""
services/vendor_service.py
───────────────────────────
Vendor checklist generation and management for UtsavAI.

Responsibilities:
- Convert AI-generated vendor checklists into structured dicts.
- Provide rule-based default vendor categories when AI is unavailable.
- Expose helper functions for vendor status tracking.

Layer contract: services/ may import from utils/ and the standard library.
                services/ must NOT import from modules/ or streamlit.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Default vendor templates ──────────────────────────────────────────────────

_DEFAULT_VENDORS: dict[str, list[dict[str, str]]] = {
    "Wedding": [
        {"category": "Venue",                       "name": "Wedding Hall / Kalyana Mandapam",    "notes": "Check capacity, parking, catering policy, restrooms"},
        {"category": "Catering",                    "name": "Wedding Caterer",                    "notes": "Confirm menu (veg/non-veg), staff count, service style"},
        {"category": "Photography & Videography",   "name": "Wedding Photographer",               "notes": "Review portfolio, ask about full-day package, RAW files"},
        {"category": "Decoration",                  "name": "Event Decorator",                    "notes": "Discuss theme, floral vs fabric, stage/mandap design"},
        {"category": "Music & Entertainment",       "name": "Band / DJ / Nadaswaram",             "notes": "Confirm song list, equipment, backup plans"},
        {"category": "Mehendi & Makeup",            "name": "Bridal Mehendi Artist",              "notes": "Check portfolio, confirm trial session, allergies"},
        {"category": "Mehendi & Makeup",            "name": "Bridal Makeup Artist",               "notes": "Request trial, discuss looks, confirm travel policy"},
        {"category": "Attire & Grooming",           "name": "Bridal Boutique / Saree House",      "notes": "Confirm alterations timeline, blouse stitching"},
        {"category": "Flowers & Garlands",          "name": "Flower Supplier / Florist",          "notes": "Confirm fresh flower availability, garland types"},
        {"category": "Pandit / Officiant",          "name": "Pandit / Purohit",                   "notes": "Discuss rituals, muhurtham timing, dakshina"},
        {"category": "Invitations & Stationery",    "name": "Invitation Designer / Printer",      "notes": "Confirm template, language, delivery date"},
        {"category": "Transportation",              "name": "Car Rental / Baraat Arrangement",    "notes": "Confirm vehicle count, driver details, decoration"},
        {"category": "Accommodation",               "name": "Hotel / Guest House",                "notes": "Room blocks for outstation guests, check-in/out policy"},
    ],
    "Birthday Party": [
        {"category": "Venue",                      "name": "Party Hall / Home Setup",   "notes": "Capacity, décor policy, backup rain plan"},
        {"category": "Catering",                   "name": "Caterer / Restaurant",      "notes": "Cake, snacks, beverages — confirm dietary restrictions"},
        {"category": "Decoration",                 "name": "Party Decorator",           "notes": "Balloons, theme props, table setup"},
        {"category": "Photography & Videography",  "name": "Event Photographer",        "notes": "Coverage duration, candid vs posed shots"},
        {"category": "Music & Entertainment",      "name": "DJ / Entertainer",          "notes": "Age-appropriate music, games, activity hosts"},
        {"category": "Invitations & Stationery",   "name": "Digital / Print Invites",   "notes": "Send at least 3 weeks in advance"},
        {"category": "Gifts & Favours",            "name": "Return Gift Supplier",      "notes": "Personalised items preferred, confirm quantity"},
    ],
    "College Event": [
        {"category": "Venue",                      "name": "College Auditorium / Open Ground",  "notes": "Booking form, permission letters, capacity"},
        {"category": "Catering",                   "name": "Canteen / External Caterer",        "notes": "Stall setup, food court vs seated"},
        {"category": "Music & Entertainment",      "name": "Student Band / Guest Artist",       "notes": "Sound system, stage requirements, rehearsal slot"},
        {"category": "Decoration",                 "name": "Art / Decoration Committee",        "notes": "Theme, signage, entry arch"},
        {"category": "Photography & Videography",  "name": "College Media Team / Hired Crew",   "notes": "Permission for drone, livestream setup"},
        {"category": "Invitations & Stationery",   "name": "Poster / Brochure Designer",        "notes": "Social media banners, print schedule"},
        {"category": "Sponsors",                   "name": "Corporate / Local Sponsors",        "notes": "Sponsorship deck, contra deals, logo placement"},
    ],
}


def get_default_vendors(event_type: str) -> list[dict[str, str]]:
    """
    Return the default vendor list for a given event type.

    Falls back to a generic minimal list if event_type is not recognised.

    Args:
        event_type: Event type string (e.g., "Wedding").

    Returns:
        List of dicts with keys: category, name, notes.
    """
    vendors = _DEFAULT_VENDORS.get(event_type)
    if vendors is None:
        logger.info("No default vendor template for event type '%s'. Using generic list.", event_type)
        vendors = [
            {"category": "Venue",         "name": "Event Venue",    "notes": "Check capacity and facilities"},
            {"category": "Catering",      "name": "Caterer",        "notes": "Confirm menu and headcount"},
            {"category": "Decoration",    "name": "Decorator",      "notes": "Discuss theme and setup time"},
            {"category": "Photography",   "name": "Photographer",   "notes": "Portfolio review and package confirmation"},
            {"category": "Miscellaneous", "name": "Other Services", "notes": "Identify any additional requirements"},
        ]
    return [v.copy() for v in vendors]  # Return copies to prevent mutation


def parse_ai_vendor_checklist(
    ai_vendors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Convert AI-generated vendor entries into a standardised format.

    AI vendor entries are expected to have:
        category (required), name_suggestion (optional), notes (optional)

    Returns a list of dicts with: category, name, notes.
    Invalid entries are logged and skipped.
    """
    result: list[dict[str, str]] = []

    for i, item in enumerate(ai_vendors):
        if not isinstance(item, dict):
            logger.warning("vendor_checklist[%d] is not a dict — skipping.", i)
            continue

        category = str(item.get("category", "")).strip()
        if not category:
            logger.warning("vendor_checklist[%d] has empty category — skipping.", i)
            continue

        name  = str(item.get("name_suggestion", "TBD")).strip() or "TBD"
        notes = str(item.get("notes", "")).strip()

        result.append({"category": category, "name": name, "notes": notes})

    return result


def group_vendors_by_category(
    vendors: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Group a flat vendor list by category for display.

    Args:
        vendors: List of vendor dicts (from DB or defaults).

    Returns:
        Dict of {category: [vendor, ...]} sorted alphabetically by category.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for vendor in vendors:
        cat = vendor.get("category", "Other")
        grouped.setdefault(cat, []).append(vendor)
    return dict(sorted(grouped.items()))
