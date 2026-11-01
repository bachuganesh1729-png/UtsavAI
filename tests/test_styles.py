"""
tests/test_styles.py
────────────────────
Unit tests for style helpers and HTML escaping in utils/styles.py.
"""

import pytest
from utils.styles import (
    render_metric_card,
    render_status_pill,
    render_section_header,
    render_info_banner,
    render_feature_card,
    COLOUR_PLUM,
    COLOUR_GOLD,
)


def test_render_metric_card_escapes_xss():
    html_out = render_metric_card(
        title="<script>alert('xss')</script>",
        value="<b>1000</b>",
        subtitle="<img src=x onerror=alert(1)>",
        colour="#542C46",
    )
    assert "<script>" not in html_out
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_out or "&lt;script&gt;alert('xss')&lt;/script&gt;" in html_out
    assert "<b>" not in html_out
    assert "&lt;b&gt;1000&lt;/b&gt;" in html_out
    assert "<img" not in html_out
    assert "border-top: 3px solid #542C46;" in html_out


def test_render_metric_card_empty_subtitle():
    html_out = render_metric_card(
        title="Total Budget",
        value="₹5,00,000",
    )
    assert "metric-title" in html_out
    assert "Total Budget" in html_out
    assert "₹5,00,000" in html_out
    assert "metric-subtitle" not in html_out


def test_render_status_pill():
    pill = render_status_pill("pending")
    assert 'class="status-pill status-pending"' in pill
    assert ">Pending<" in pill

    pill_completed = render_status_pill("completed")
    assert 'class="status-pill status-completed"' in pill_completed
    assert ">Completed<" in pill_completed

    # XSS injection test in status
    pill_xss = render_status_pill("<script>alert(1)</script>")
    assert "<script>" not in pill_xss
    assert "&lt;script&gt;" in pill_xss


def test_render_section_header():
    header = render_section_header("Plan & Budget", "Overview <test>")
    assert "Plan &amp; Budget" in header or "Plan & Budget" in header
    assert "<test>" not in header
    assert "&lt;test&gt;" in header
    assert "section-title" in header
    assert "section-subtitle" in header

    header_no_sub = render_section_header("Simple Title")
    assert "section-subtitle" not in header_no_sub


def test_render_info_banner():
    banner = render_info_banner("Important message", "warning")
    assert "banner-warning" in banner
    assert "⚠️" in banner
    assert "Important message" in banner

    banner_default = render_info_banner("Info message")
    assert "banner-info" in banner_default
    assert "ℹ️" in banner_default


def test_render_feature_card_escapes_xss():
    card = render_feature_card(
        icon="🎉",
        title="<script>bad()</script>",
        description="A <b>great</b> celebration",
        accent_class="card-gold-top",
    )
    assert "<script>" not in card
    assert "&lt;script&gt;" in card
    assert "<b>" not in card
    assert "&lt;b&gt;" in card
    assert "card-gold-top" in card
