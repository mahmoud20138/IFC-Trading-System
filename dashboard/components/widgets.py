"""
IFC Dashboard — Widget Components
Small reusable UI blocks.
"""

import streamlit as st
from typing import Dict, Any, Optional


def status_badge(label: str, status: str):
    """
    Display a colored status badge.
    status: "ok" / "warning" / "error" / "info"
    """
    colors = {
        "ok": "🟢",
        "warning": "🟡",
        "error": "🔴",
        "info": "🔵",
    }
    icon = colors.get(status, "⚪")
    st.write(f"{icon} **{label}**")


def metric_card(label: str, value: str, delta: Optional[str] = None):
    """Display a metric with optional delta."""
    st.metric(label, value, delta)


def confluence_gauge(grade: str, layers_passed: int, total_layers: int = 8):
    """
    Display a visual gauge for confluence strength.
    """
    grade_colors = {
        "A+": "🟢",
        "A": "🔵",
        "B": "🟡",
        "NO_TRADE": "🔴",
    }
    icon = grade_colors.get(grade, "⚪")

    bar_filled = "█" * layers_passed
    bar_empty = "░" * (total_layers - layers_passed)
    bar = bar_filled + bar_empty

    st.write(f"{icon} **Grade: {grade}** | {bar} {layers_passed}/{total_layers} layers")


def layer_signal_card(layer_name: str, direction: str, score: float, confidence: float):
    """Display a single layer signal as a compact card."""
    if score >= 7:
        color = "🟢"
    elif score >= 5:
        color = "🟡"
    else:
        color = "🔴"

    dir_icon = "⬆️" if direction == "BULLISH" else "⬇️" if direction == "BEARISH" else "➡️"
    st.write(
        f"{color} **{layer_name}** | {dir_icon} {direction} | "
        f"Score: {score:.1f}/10 | Conf: {confidence:.0%}"
    )


def trade_setup_card(setup: Dict[str, Any]):
    """Display a trade setup candidate."""
    st.write(f"### {setup.get('setup_type', 'SETUP')} — {setup.get('symbol', '?')}")

    c1, c2, c3 = st.columns(3)
    c1.write(f"**Direction:** {setup.get('direction', '?')}")
    c2.write(f"**Grade:** {setup.get('grade', '?')}")
    c3.write(f"**R:R Ratio:** {setup.get('rr_ratio', 0):.1f}")

    c4, c5, c6 = st.columns(3)
    c4.write(f"**Entry:** {setup.get('entry_price', 0):.5f}")
    c5.write(f"**SL:** {setup.get('stop_loss', 0):.5f}")
    c6.write(f"**TP1:** {setup.get('tp1', 0):.5f}")


def circuit_breaker_display(breaker: Dict[str, Any]):
    """Show circuit breaker status."""
    if breaker.get("can_trade"):
        if breaker.get("action") == "HALF_SIZE":
            st.warning(f"⚠️ {breaker['reason']}")
        else:
            st.success("✅ All clear — no circuit breakers triggered")
    else:
        st.error(f"🛑 CIRCUIT BREAKER: {breaker.get('action', '')} — {breaker.get('reason', '')}")
