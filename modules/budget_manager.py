"""
modules/budget_manager.py
──────────────────────────
Budget Manager UI module for UtsavAI.

Responsibilities:
- Display allocated vs actual spend for the active event.
- Allow users to add, edit actual amounts, and delete budget items.
- Render interactive Plotly charts (allocated vs actual, category donut).
- Request AI optimisation suggestions from gemini_service.
- All financial calculations are delegated to budget_service (never inline).

Layer contract: modules/ may import from services/, utils/, and streamlit.
               modules/ must NOT be imported by services/ or utils/.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from services.database_service import (
    get_budget_items,
    upsert_budget_items,
    update_budget_item_actual,
    get_event,
)
from services.budget_service import (
    compute_budget_summary,
    build_chart_data,
    suggest_default_allocation,
    calculate_per_guest_cost,
)
from services.gemini_service import generate_budget_suggestions
from utils.config import BUDGET_CATEGORIES
from utils.formatters import (
    format_currency,
    format_currency_compact,
    format_percentage,
)
from utils.styles import render_metric_card, render_section_header
from utils.validators import validate_amount


# ── Public entry point ────────────────────────────────────────────────────────

def render_budget_manager(config) -> None:
    """Main entry point called by app.py."""
    st.markdown(
        render_section_header(
            "💰 Budget Manager",
            "Track, allocate and optimise your event budget",
        ),
        unsafe_allow_html=True,
    )

    event_id = st.session_state.get("active_event_id")
    if not event_id:
        _render_no_event_prompt()
        return

    event = get_event(event_id)
    if not event:
        st.error(f"Event #{event_id} not found. Please select a valid event.")
        st.session_state["active_event_id"] = None
        return

    _render_budget_manager_body(config, event)


# ── No-event prompt ───────────────────────────────────────────────────────────

def _render_no_event_prompt() -> None:
    st.info(
        "💡 **No active event selected.** "
        "Go to **AI Event Planner** to create an event, or select an existing event from the planner."
    )


# ── Main body ─────────────────────────────────────────────────────────────────

def _render_budget_manager_body(config, event: dict) -> None:
    event_id = event["id"]
    total_budget = float(event.get("total_budget", 0))
    guest_count = int(event.get("guest_count", 0))
    event_type = event.get("event_type", "")

    # Load items and compute summary
    raw_items = get_budget_items(event_id)
    summary = compute_budget_summary(total_budget, raw_items)

    # Header metrics
    _render_metrics_row(summary, guest_count)

    st.markdown("---")

    # Tabs
    tab_overview, tab_edit, tab_add, tab_ai = st.tabs([
        "📊 Overview & Charts",
        "✏️ Edit Actuals",
        "➕ Add / Manage Items",
        "🤖 AI Suggestions",
    ])

    with tab_overview:
        _render_overview_tab(summary, total_budget)

    with tab_edit:
        _render_edit_actuals_tab(event_id, raw_items)

    with tab_add:
        _render_manage_items_tab(event_id, total_budget, event_type, raw_items)

    with tab_ai:
        _render_ai_suggestions_tab(config, event, summary)


# ── Metrics row ───────────────────────────────────────────────────────────────

def _render_metrics_row(summary, guest_count: int) -> None:
    col1, col2, col3, col4 = st.columns(4)

    status_colour = "#6B2D3E" if summary.is_over_budget else "#15803D"

    with col1:
        st.markdown(
            render_metric_card(
                "Total Budget",
                format_currency_compact(summary.total_budget),
                "Event total",
                "#C9A84C",
            ),
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            render_metric_card(
                "Total Allocated",
                format_currency_compact(summary.total_allocated),
                f"{summary.allocation_pct:.1f}% of budget",
                "#6B2D3E",
            ),
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            render_metric_card(
                "Total Spent",
                format_currency_compact(summary.total_actual),
                f"{summary.utilisation_pct:.1f}% utilised",
                status_colour,
            ),
            unsafe_allow_html=True,
        )
    with col4:
        remaining = summary.total_budget - summary.total_actual
        per_guest = calculate_per_guest_cost(summary.total_actual, guest_count)
        st.markdown(
            render_metric_card(
                "Remaining",
                format_currency_compact(max(0.0, remaining)),
                f"Per guest: {format_currency(per_guest)}" if guest_count > 0 else "",
                "#15803D" if remaining >= 0 else "#6B2D3E",
            ),
            unsafe_allow_html=True,
        )

    # Over-budget banner
    if summary.is_over_budget and summary.overrun_categories:
        cats = ", ".join(summary.overrun_categories)
        st.markdown(
            f'<div class="banner banner-error">⚠️ Over budget by '
            f'<strong>{format_currency(summary.overrun_amount)}</strong> in: {cats}</div>',
            unsafe_allow_html=True,
        )
    elif summary.unallocated > 0:
        st.markdown(
            f'<div class="banner banner-info">ℹ️ '
            f'<strong>{format_currency(summary.unallocated)}</strong> unallocated across categories.</div>',
            unsafe_allow_html=True,
        )


# ── Overview / charts tab ─────────────────────────────────────────────────────

def _render_overview_tab(summary, total_budget: float) -> None:
    if not summary.items:
        st.info("No budget items found. Add items in the **Add / Manage Items** tab.")
        return

    categories, allocated, actual = build_chart_data(summary)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Allocated vs Actual Spend")
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            name="Allocated",
            x=categories,
            y=allocated,
            marker_color="#6B2D3E",
            opacity=0.85,
        ))
        fig_bar.add_trace(go.Bar(
            name="Actual Spent",
            x=categories,
            y=actual,
            marker_color="#C9A84C",
            opacity=0.85,
        ))
        fig_bar.update_layout(
            barmode="group",
            height=380,
            margin=dict(l=10, r=10, t=30, b=80),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis_tickangle=-45,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", size=11),
        )
        fig_bar.update_yaxes(tickprefix="₹", tickformat=",.0f")
        st.plotly_chart(fig_bar, use_container_width=True)

    with col2:
        st.markdown("#### Allocation Breakdown")
        non_zero = [(c, a) for c, a in zip(categories, allocated) if a > 0]
        if non_zero:
            cats_nz, alloc_nz = zip(*non_zero)
            fig_donut = go.Figure(data=[go.Pie(
                labels=list(cats_nz),
                values=list(alloc_nz),
                hole=0.45,
                marker_colors=[
                    "#6B2D3E", "#C9A84C", "#8B3A4E", "#A07830",
                    "#4A1E2B", "#D4A853", "#7A3048", "#B8962E",
                    "#923650", "#C49040", "#5C2436", "#E0B060",
                    "#6E2A3C", "#967030",
                ],
                textinfo="label+percent",
                textfont_size=10,
            )])
            fig_donut.update_layout(
                height=380,
                margin=dict(l=10, r=10, t=30, b=10),
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif", size=11),
                annotations=[dict(
                    text=format_currency_compact(sum(alloc_nz)),
                    x=0.5, y=0.5, font_size=14, showarrow=False,
                    font=dict(color="#4A1E2B", family="Cormorant Garamond, serif"),
                )],
            )
            st.plotly_chart(fig_donut, use_container_width=True)

    # Summary table
    st.markdown("#### Category Summary")
    table_data = []
    for item in summary.items:
        variance = item.variance
        table_data.append({
            "Category": item.category,
            "Allocated": format_currency(item.allocated_amount),
            "Actual": format_currency(item.actual_amount),
            "Variance": ("+" if variance >= 0 else "") + format_currency(variance),
            "Used %": f"{item.utilisation_pct:.1f}%",
            "Status": "⚠️ Over" if item.is_over_budget else "✅ OK",
        })
    st.dataframe(table_data, use_container_width=True, hide_index=True)


# ── Edit actuals tab ──────────────────────────────────────────────────────────

def _render_edit_actuals_tab(event_id: int, raw_items: list) -> None:
    if not raw_items:
        st.info("No budget items found. Add items in the **Add / Manage Items** tab.")
        return

    st.markdown(
        "Update **actual amounts spent** per category. Changes are saved immediately."
    )

    for item in raw_items:
        item_id = item["id"]
        category = item["category"]
        allocated = float(item["allocated_amount"])
        actual = float(item["actual_amount"])

        with st.expander(
            f"{'⚠️' if actual > allocated else '✅'} **{category}** — "
            f"Allocated: {format_currency(allocated)} | Actual: {format_currency(actual)}",
            expanded=(actual > allocated),
        ):
            new_actual = st.number_input(
                f"Actual Spent (₹)",
                min_value=0.0,
                value=actual,
                step=500.0,
                format="%.2f",
                key=f"actual_{item_id}",
                help=f"Allocated: {format_currency(allocated)}",
            )

            if st.button(f"💾 Save", key=f"save_actual_{item_id}"):
                ok, msg = validate_amount(new_actual, "Actual amount")
                if not ok:
                    st.error(f"❌ {msg}")
                else:
                    if update_budget_item_actual(item_id, new_actual):
                        st.success(f"✅ {category} updated to {format_currency(new_actual)}")
                        st.rerun()
                    else:
                        st.error("Failed to update. Please try again.")


# ── Add / manage items tab ────────────────────────────────────────────────────

def _render_manage_items_tab(
    event_id: int, total_budget: float, event_type: str, raw_items: list
) -> None:
    existing_categories = {item["category"] for item in raw_items}

    # ── Add new category item ──────────────────────────────────────────────────
    st.markdown("#### Add New Budget Item")

    available = [c for c in BUDGET_CATEGORIES if c not in existing_categories]
    custom_label = "Custom…"
    add_options = available + [custom_label]

    with st.form("add_budget_item_form"):
        selected_cat = st.selectbox(
            "Category",
            options=add_options,
            help="Choose a standard category or enter a custom one.",
        )
        custom_cat = ""
        if selected_cat == custom_label:
            custom_cat = st.text_input(
                "Custom Category Name",
                max_chars=80,
                placeholder="e.g. Fireworks",
            )
        alloc = st.number_input(
            "Allocated Amount (₹)",
            min_value=0.0,
            value=0.0,
            step=1000.0,
            format="%.2f",
        )
        notes_input = st.text_input("Notes (optional)", max_chars=200)
        add_submitted = st.form_submit_button("➕ Add Item", use_container_width=True)

    if add_submitted:
        category_name = custom_cat.strip() if selected_cat == custom_label else selected_cat
        if not category_name:
            st.error("❌ Please provide a category name.")
        elif category_name in existing_categories:
            st.error(f"❌ Category '{category_name}' already exists.")
        else:
            ok, msg = validate_amount(alloc, "Allocated amount")
            if not ok:
                st.error(f"❌ {msg}")
            else:
                new_items = list(raw_items) + [{
                    "category": category_name,
                    "allocated_amount": float(alloc),
                    "actual_amount": 0.0,
                    "notes": notes_input.strip(),
                }]
                if upsert_budget_items(event_id, new_items):
                    st.success(f"✅ '{category_name}' added.")
                    st.rerun()
                else:
                    st.error("Failed to add item.")

    # ── Regenerate from defaults ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Reset to Default Allocation")
    st.caption(
        "This will **replace all budget items** with a rule-based default allocation "
        f"for a {event_type} event. Actual amounts will be reset to zero."
    )
    if st.button("🔄 Reset to Defaults", key="reset_budget_defaults"):
        default_items = suggest_default_allocation(total_budget, event_type, BUDGET_CATEGORIES)
        new_items = [
            {
                "category": i.category,
                "allocated_amount": i.allocated_amount,
                "actual_amount": 0.0,
                "notes": "",
            }
            for i in default_items
        ]
        if upsert_budget_items(event_id, new_items):
            st.success("✅ Budget reset to defaults.")
            st.rerun()
        else:
            st.error("Failed to reset budget.")

    # ── Delete an item ─────────────────────────────────────────────────────────
    if raw_items:
        st.markdown("---")
        st.markdown("#### Delete a Budget Item")
        del_options = {item["category"]: item for item in raw_items}
        del_cat = st.selectbox("Select category to delete", options=list(del_options.keys()), key="del_cat")

        if st.button("🗑️ Delete Selected Item", key="del_budget_item", type="secondary"):
            remaining = [i for i in raw_items if i["category"] != del_cat]
            if upsert_budget_items(event_id, remaining):
                st.success(f"✅ '{del_cat}' removed.")
                st.rerun()
            else:
                st.error("Failed to remove item.")


# ── AI suggestions tab ────────────────────────────────────────────────────────

def _render_ai_suggestions_tab(config, event: dict, summary) -> None:
    if not config.ai_available:
        st.markdown(
            '<div class="banner banner-warning">⚠️ AI features require a Gemini API key. '
            "Configure it in <code>.streamlit/secrets.toml</code>.</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        "Get AI-powered cost-optimisation suggestions based on your current budget allocation."
    )

    if not summary.items:
        st.info("Add budget items first to get AI suggestions.")
        return

    if st.button("🤖 Get AI Budget Suggestions", type="primary", key="ai_budget_btn"):
        with st.spinner("Analysing your budget with Gemini AI…"):
            allocated_items = [
                {
                    "category": item.category,
                    "allocated_amount": item.allocated_amount,
                    "actual_amount": item.actual_amount,
                }
                for item in summary.items
            ]
            result = generate_budget_suggestions(
                config=config,
                event_type=event.get("event_type", ""),
                total_budget=float(event.get("total_budget", 0)),
                allocated_items=allocated_items,
                overrun_categories=summary.overrun_categories,
            )

        if result.success:
            data = result.data
            st.success("✅ AI suggestions ready!")

            overall = data.get("summary", "")
            if overall:
                st.info(f"💡 **Overall Advice:** {overall}")

            optimizations = data.get("optimizations", [])
            if optimizations:
                st.markdown("#### Category-Specific Suggestions")
                for opt in optimizations:
                    with st.expander(
                        f"📌 **{opt.get('category', 'General')}** — "
                        f"Potential saving: {opt.get('potential_saving', 'N/A')}",
                    ):
                        st.markdown(opt.get("suggestion", "No suggestion provided."))
        else:
            st.error(f"❌ {result.error.message}")
