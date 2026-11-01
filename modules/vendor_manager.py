"""
modules/vendor_manager.py
──────────────────────────
Vendor Manager UI module for UtsavAI.

Responsibilities:
- Display vendors for the active event, grouped by category.
- Allow adding, editing (name, contact, status, notes), and deleting vendors.
- Load default vendor lists from vendor_service when no vendors exist.
- Show categorised status summary (how many booked, pending, etc.).

Layer contract: modules/ may import from services/, utils/, and streamlit.
               modules/ must NOT be imported by services/ or utils/.
"""

from __future__ import annotations

import streamlit as st

from services.database_service import (
    get_vendors,
    create_vendor,
    update_vendor,
    delete_vendor,
    get_event,
)
from services.vendor_service import (
    get_default_vendors,
    group_vendors_by_category,
)
from utils.config import VENDOR_STATUSES, BUDGET_CATEGORIES
from utils.formatters import format_date, format_status_badge
from utils.styles import render_metric_card, render_section_header, render_status_pill
from utils.validators import validate_free_text


# ── Status colours and icons ──────────────────────────────────────────────────

_STATUS_ICONS = {
    "pending": "⏳",
    "contacted": "📞",
    "booked": "📋",
    "confirmed": "✅",
    "cancelled": "❌",
}


# ── Public entry point ────────────────────────────────────────────────────────

def render_vendor_manager(config) -> None:
    """Main entry point called by app.py."""
    st.markdown(
        render_section_header(
            "🤝 Vendor Manager",
            "Track and manage all your event vendors and service providers",
        ),
        unsafe_allow_html=True,
    )

    event_id = st.session_state.get("active_event_id")
    if not event_id:
        st.info(
            "💡 **No active event selected.** "
            "Go to **AI Event Planner** to create an event first."
        )
        return

    event = get_event(event_id)
    if not event:
        st.error(f"Event #{event_id} not found.")
        st.session_state["active_event_id"] = None
        return

    _render_vendor_body(event)


# ── Main body ─────────────────────────────────────────────────────────────────

def _render_vendor_body(event: dict) -> None:
    event_id = event["id"]
    event_type = event.get("event_type", "")

    vendors = get_vendors(event_id)

    # If no vendors yet, offer to load defaults
    if not vendors:
        _render_empty_state(event_id, event_type)
        return

    # Summary metrics
    _render_vendor_metrics(vendors)

    st.markdown("---")

    tab_view, tab_add = st.tabs(["📋 All Vendors", "➕ Add Vendor"])

    with tab_view:
        _render_vendors_tab(event_id, vendors, event_type)

    with tab_add:
        _render_add_vendor_tab(event_id)


# ── Empty state ───────────────────────────────────────────────────────────────

def _render_empty_state(event_id: int, event_type: str) -> None:
    st.info(
        f"No vendors added yet for this event. "
        f"Load the default checklist for a **{event_type}**, or add vendors manually."
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            f"📋 Load Default {event_type} Vendors",
            type="primary",
            key="load_defaults",
            use_container_width=True,
        ):
            defaults = get_default_vendors(event_type)
            success_count = 0
            for v in defaults:
                vid = create_vendor(
                    event_id=event_id,
                    category=v.get("category", "Other"),
                    name=v.get("name", "TBD"),
                    contact="",
                    status="pending",
                    notes=v.get("notes", ""),
                )
                if vid:
                    success_count += 1
            if success_count:
                st.success(f"✅ {success_count} default vendors loaded.")
                st.rerun()
            else:
                st.error("Failed to load defaults.")

    with col2:
        st.markdown("*Or use the **Add Vendor** tab below.*")

    # Show add form even in empty state
    st.markdown("---")
    _render_add_vendor_tab(event_id)


# ── Metrics row ───────────────────────────────────────────────────────────────

def _render_vendor_metrics(vendors: list) -> None:
    total = len(vendors)
    by_status: dict[str, int] = {}
    for v in vendors:
        s = v.get("status", "pending")
        by_status[s] = by_status.get(s, 0) + 1

    confirmed = by_status.get("confirmed", 0) + by_status.get("booked", 0)
    pending = by_status.get("pending", 0)
    contacted = by_status.get("contacted", 0)
    cancelled = by_status.get("cancelled", 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            render_metric_card("Total Vendors", str(total), "In checklist", "#C49A55"),
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            render_metric_card("Confirmed / Booked", str(confirmed), "Ready", "#718B72"),
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            render_metric_card("Pending / Contacted", str(pending + contacted), "To follow up", "#C49A55"),
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            render_metric_card("Cancelled", str(cancelled), "", "#542C46"),
            unsafe_allow_html=True,
        )

    # Progress bar: (confirmed + booked) / total
    if total > 0:
        pct = (confirmed / total) * 100
        st.markdown(f"**Confirmed: {pct:.0f}% of vendors**")
        st.progress(pct / 100.0)


# ── Vendors view tab ──────────────────────────────────────────────────────────

def _render_vendors_tab(event_id: int, vendors: list, event_type: str = "Wedding") -> None:
    # Filter controls
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        status_filter = st.multiselect(
            "Filter by status",
            options=VENDOR_STATUSES,
            default=[],
            format_func=lambda s: f"{_STATUS_ICONS.get(s, '')} {s.title()}",
            key="vnd_status_filter",
        )
    with col_f2:
        # Unique categories
        categories = sorted({v.get("category", "Other") for v in vendors})
        cat_filter = st.multiselect(
            "Filter by category",
            options=categories,
            default=[],
            key="vnd_cat_filter",
        )

    filtered = vendors
    if status_filter:
        filtered = [v for v in filtered if v.get("status") in status_filter]
    if cat_filter:
        filtered = [v for v in filtered if v.get("category") in cat_filter]

    if not filtered:
        st.info("No vendors match the selected filters.")
        return

    # Group and display
    grouped = group_vendors_by_category(filtered)

    for category, cat_vendors in grouped.items():
        st.markdown(f"### {category}")
        for vendor in cat_vendors:
            _render_vendor_card(event_id, vendor)
        st.markdown("---")

    # Reset to default vendors with confirmation
    with st.expander("🔄 Reset to Default Vendors", expanded=False):
        st.markdown(
            f"Resetting will delete all current vendors and reload the default checklist for a **{event_type}**."
        )
        confirm_reset = st.checkbox(
            "I understand this will delete all current vendors and replace them with defaults.",
            key=f"confirm_reset_vendors_{event_id}",
        )
        if st.button("Reset to Default Vendors", type="secondary", disabled=not confirm_reset, key=f"btn_reset_vendors_{event_id}"):
            for v in vendors:
                delete_vendor(v["id"])
            defaults = get_default_vendors(event_type)
            for v in defaults:
                create_vendor(
                    event_id=event_id,
                    category=v.get("category", "Other"),
                    name=v.get("name", "TBD"),
                    contact="",
                    status="pending",
                    notes=v.get("notes", ""),
                )
            st.session_state.pop(f"confirm_reset_vendors_{event_id}", None)
            st.success("✅ Vendors reset to defaults.")
            st.rerun()


def _render_vendor_card(event_id: int, vendor: dict) -> None:
    """Render a single vendor card with edit and delete controls."""
    vid = vendor["id"]
    name = vendor.get("name", "Unnamed")
    status = vendor.get("status", "pending")
    contact = vendor.get("contact", "")
    notes = vendor.get("notes", "")
    icon = _STATUS_ICONS.get(status, "❓")

    with st.expander(
        f"{icon} **{name}** — {render_status_pill(status)}",
        expanded=False,
    ):
        col1, col2 = st.columns([2, 1])

        with col1:
            # Edit form
            with st.form(f"edit_vendor_{vid}"):
                new_name = st.text_input("Vendor Name", value=name, max_chars=200, key=f"vname_{vid}")
                new_contact = st.text_input(
                    "Contact (phone / email / website)",
                    value=contact,
                    max_chars=200,
                    placeholder="e.g. +91 98765 43210 or vendor@email.com",
                    key=f"vcontact_{vid}",
                )
                status_idx = VENDOR_STATUSES.index(status) if status in VENDOR_STATUSES else 0
                new_status = st.selectbox(
                    "Status",
                    options=VENDOR_STATUSES,
                    index=status_idx,
                    format_func=lambda s: f"{_STATUS_ICONS.get(s, '')} {s.title()}",
                    key=f"vstatus_{vid}",
                )
                new_notes = st.text_area(
                    "Notes",
                    value=notes,
                    max_chars=500,
                    height=80,
                    key=f"vnotes_{vid}",
                )
                save_btn = st.form_submit_button("💾 Save Changes", use_container_width=True)

            if save_btn:
                errors = []
                if not new_name.strip():
                    errors.append("Vendor name cannot be empty.")
                ok, msg = validate_free_text(new_contact, "Contact")
                if not ok:
                    errors.append(msg)
                ok, msg = validate_free_text(new_notes, "Notes")
                if not ok:
                    errors.append(msg)

                if errors:
                    for e in errors:
                        st.error(f"❌ {e}")
                else:
                    if update_vendor(
                        vid,
                        name=new_name.strip(),
                        contact=new_contact.strip(),
                        status=new_status,
                        notes=new_notes.strip(),
                    ):
                        st.success("✅ Vendor updated.")
                        st.rerun()
                    else:
                        st.error("Failed to save changes.")

        with col2:
            st.markdown(f"**Current Status:**")
            st.markdown(
                render_status_pill(status),
                unsafe_allow_html=True,
            )
            if contact:
                st.markdown(f"**Contact:**  \n{contact}")

            st.markdown("---")
            if st.button("🗑️ Delete", key=f"del_vendor_{vid}", type="secondary"):
                st.session_state[f"confirm_del_vendor_{vid}"] = True

            if st.session_state.get(f"confirm_del_vendor_{vid}"):
                st.warning(f"Delete **{name}**?")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Yes", key=f"confirm_del_yes_{vid}"):
                        if delete_vendor(vid):
                            st.session_state.pop(f"confirm_del_vendor_{vid}", None)
                            st.success(f"'{name}' deleted.")
                            st.rerun()
                        else:
                            st.error("Failed to delete.")
                with c2:
                    if st.button("No", key=f"confirm_del_no_{vid}"):
                        st.session_state.pop(f"confirm_del_vendor_{vid}", None)
                        st.rerun()


# ── Add vendor tab ────────────────────────────────────────────────────────────

def _render_add_vendor_tab(event_id: int) -> None:
    st.markdown("Add a new vendor or service provider to your checklist.")

    # Determine category options — standard list + custom
    custom_label = "Custom…"
    cat_options = BUDGET_CATEGORIES + ["Sponsors", "Other Services", custom_label]

    with st.form("add_vendor_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_cat = st.selectbox(
                "Category *",
                options=cat_options,
                help="Select the type of vendor.",
            )
            custom_cat = ""
            if selected_cat == custom_label:
                custom_cat = st.text_input("Custom Category *", max_chars=100)

            vendor_name = st.text_input(
                "Vendor Name *",
                max_chars=200,
                placeholder="e.g. Sri Lakshmi Catering Services",
            )

        with col2:
            contact = st.text_input(
                "Contact (phone / email / website)",
                max_chars=200,
                placeholder="e.g. +91 98765 43210",
            )
            status = st.selectbox(
                "Initial Status",
                options=VENDOR_STATUSES,
                index=0,
                format_func=lambda s: f"{_STATUS_ICONS.get(s, '')} {s.title()}",
            )

        notes = st.text_area(
            "Notes / What to ask",
            max_chars=500,
            height=80,
            placeholder="e.g. Confirm vegetarian menu, ask about service staff count",
        )

        add_submitted = st.form_submit_button("➕ Add Vendor", use_container_width=True, type="primary")

    if add_submitted:
        final_category = custom_cat.strip() if selected_cat == custom_label else selected_cat
        errors = []

        if not final_category:
            errors.append("Category cannot be empty.")
        if not vendor_name.strip():
            errors.append("Vendor name cannot be empty.")

        ok, msg = validate_free_text(contact, "Contact")
        if not ok:
            errors.append(msg)
        ok, msg = validate_free_text(notes, "Notes")
        if not ok:
            errors.append(msg)

        if errors:
            for e in errors:
                st.error(f"❌ {e}")
        else:
            vid = create_vendor(
                event_id=event_id,
                category=final_category,
                name=vendor_name.strip(),
                contact=contact.strip(),
                status=status,
                notes=notes.strip(),
            )
            if vid:
                st.success(f"✅ Vendor '{vendor_name.strip()}' added under **{final_category}**.")
                st.rerun()
            else:
                st.error("Failed to add vendor. Please try again.")
