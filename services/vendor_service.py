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
        {"category": "Venue",                     "name": "Wedding Hall / Kalyana Mandapam",    "notes": "Check capacity, parking, catering policy, restrooms"},
        {"category": "Catering",                  "name": "Wedding Caterer",                    "notes": "Confirm menu (veg/non-veg), staff count, service style"},
        {"category": "Decoration",                "name": "Event Decorator & Florist",          "notes": "Discuss theme, mandap design, stage and entrance lighting"},
        {"category": "Photography",               "name": "Wedding Photographer & Videographer","notes": "Review portfolio, ask about full-day package, RAW files"},
        {"category": "Music & Entertainment",     "name": "Band / DJ / Nadaswaram / Shenhai",   "notes": "Confirm song list, equipment, backup power plans"},
        {"category": "Makeup & Styling",          "name": "Bridal Makeup Artist & Hair Stylist","notes": "Request trial, discuss looks, confirm travel policy"},
        {"category": "Priest & Rituals",          "name": "Pandit / Purohit / Priest",          "notes": "Discuss rituals, muhurtham timing, puja samagri list"},
        {"category": "Transportation",            "name": "Car Rental / Baraat Arrangement",    "notes": "Confirm vehicle count, driver details, decoration"},
        {"category": "Invitation Cards",          "name": "Invitation Cards Designer / Printer","notes": "Confirm physical and digital templates, proof check, delivery date"},
        {"category": "Attire & Grooming",         "name": "Bridal Boutique / Saree House",      "notes": "Confirm alterations timeline, blouse stitching"},
        {"category": "Flowers & Garlands",        "name": "Flower Supplier / Varmala Specialist","notes": "Confirm fresh flower availability, varmala types"},
        {"category": "Accommodation",             "name": "Hotel / Guest House",                "notes": "Room blocks for outstation guests, check-in/out policy"},
    ],
    "Birthday Party": [
        {"category": "Venue",                     "name": "Party Hall / Home Setup",            "notes": "Capacity, décor policy, backup rain plan"},
        {"category": "Catering",                  "name": "Caterer / Bakery",                   "notes": "Custom theme cake, snacks, beverages, dietary restrictions"},
        {"category": "Decoration",                "name": "Party Decorator",                    "notes": "Balloons, theme props, backdrop and table setup"},
        {"category": "Photography",               "name": "Event Photographer",                 "notes": "Coverage duration, candid vs posed shots"},
        {"category": "Music & Entertainment",     "name": "DJ / Entertainer / Game Host",       "notes": "Age-appropriate music, games, activity hosts"},
        {"category": "Invitation Cards",          "name": "Digital / Print Invites",            "notes": "Send at least 3 weeks in advance"},
        {"category": "Gifts & Favours",           "name": "Return Gift Supplier",               "notes": "Personalised items preferred, confirm quantity"},
    ],
    "College Event": [
        {"category": "Venue",                     "name": "College Auditorium / Open Ground",   "notes": "Booking form, permission letters, capacity"},
        {"category": "Catering",                  "name": "Canteen / External Caterer",         "notes": "Stall setup, food court vs seated"},
        {"category": "Music & Entertainment",     "name": "Student Band / Guest Artist",        "notes": "Sound system, stage requirements, rehearsal slot"},
        {"category": "Decoration",                "name": "Art / Decoration Committee",         "notes": "Theme, signage, entry arch"},
        {"category": "Photography",               "name": "College Media Team / Hired Crew",    "notes": "Permission for drone, livestream setup"},
        {"category": "Invitation Cards",          "name": "Poster / Brochure Designer",         "notes": "Social media banners, print schedule"},
        {"category": "Transportation",            "name": "Shuttle / Guest Transportation",     "notes": "Transport for guest speakers and performers"},
        {"category": "Sponsors",                  "name": "Corporate / Local Sponsors",         "notes": "Sponsorship deck, contra deals, logo placement"},
    ],
}


def get_default_vendors(event_type: str) -> list[dict[str, str]]:
    """
    Return the default vendor list for a given event type.

    Covers culturally relevant Indian categories: Catering, Photography,
    Decoration, Venue, Music & Entertainment, Makeup & Styling, Priest & Rituals,
    Transportation, Invitation Cards.

    Falls back to a generic list covering all core categories if event_type is not recognised.

    Args:
        event_type: Event type string (e.g., "Wedding").

    Returns:
        List of dicts with keys: category, name, notes.
    """
    vendors = _DEFAULT_VENDORS.get(event_type)
    if vendors is None:
        logger.info("No default vendor template for event type '%s'. Using generic list.", event_type)
        vendors = [
            {"category": "Venue",                 "name": "Event Venue",                        "notes": "Check capacity, amenities and facilities"},
            {"category": "Catering",              "name": "Caterer / Food Service",             "notes": "Confirm menu, dietary preferences and headcount"},
            {"category": "Decoration",            "name": "Decorator / Florist",                "notes": "Discuss theme, stage setup and lighting"},
            {"category": "Photography",           "name": "Photographer / Videographer",        "notes": "Portfolio review, deliverables and package confirmation"},
            {"category": "Music & Entertainment", "name": "DJ / Sound / Live Performers",        "notes": "Audio equipment, playlist and scheduling"},
            {"category": "Makeup & Styling",      "name": "Makeup Artist / Stylist",            "notes": "Confirm look, trial session and scheduling"},
            {"category": "Priest & Rituals",      "name": "Priest / Pandit / Officiant",        "notes": "Discuss samagri, muhurtham timing and rituals"},
            {"category": "Transportation",        "name": "Travel & Transportation",            "notes": "Guest transfers and logistics"},
            {"category": "Invitation Cards",      "name": "Invitation Cards / Stationery",      "notes": "Design, printing and distribution timeline"},
            {"category": "Miscellaneous",         "name": "Other Services",                     "notes": "Identify any additional celebration requirements"},
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
    Invalid entries or entries without category are logged and skipped.
    """
    if not isinstance(ai_vendors, list):
        return []

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
    Handles empty lists gracefully by returning an empty dict.

    Args:
        vendors: List of vendor dicts (from DB or defaults).

    Returns:
        Dict of {category: [vendor, ...]} sorted alphabetically by category.
    """
    if not vendors:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for vendor in vendors:
        if not isinstance(vendor, dict):
            continue
        cat = str(vendor.get("category", "Other")).strip() or "Other"
        grouped.setdefault(cat, []).append(vendor)
    return dict(sorted(grouped.items()))
