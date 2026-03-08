"""
IFC Trading System — Auto Monitor Dashboard Page
Enhancement Plan Feature B: Auto-Monitoring Every Minute

Re-evaluates all instruments every 60 seconds, shows score changes,
grade flips, direction changes, and alert highlights.
Uses Streamlit's st_autorefresh or manual refresh with session_state history.
"""

import streamlit as st
import sys
import os
import time
import pandas as pd
from datetime import datetime
from collections import deque
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config import settings
from config.instruments import get_active_instruments, Instrument
from analysis.pipeline import AnalysisPipeline
from analysis.layer1_intermarket import IntermarketLayer
from data.intermarket import IntermarketData
from data.mt5_connector import MT5Connector
from utils.helpers import setup_logging

logger = setup_logging("ifc.auto_monitor")

# ── Settings ──
_INTERVAL = getattr(settings, "AUTO_MONITOR_INTERVAL_S", 60)
_HISTORY_SIZE = getattr(settings, "AUTO_MONITOR_HISTORY_SIZE", 30)
_ALERT_GRADE = getattr(settings, "AUTO_MONITOR_ALERT_GRADE_CHANGE", True)
_ALERT_DIR = getattr(settings, "AUTO_MONITOR_ALERT_DIRECTION_FLIP", True)
_SCORE_DELTA = getattr(settings, "AUTO_MONITOR_SCORE_DELTA_THRESHOLD", 1.5)


def _init_session_state():
    """Initialize session state for evaluation history."""
    if "monitor_history" not in st.session_state:
        # {symbol: deque(maxlen=_HISTORY_SIZE) of dicts}
        st.session_state["monitor_history"] = {}
    if "monitor_last_run" not in st.session_state:
        st.session_state["monitor_last_run"] = None
    if "monitor_alerts" not in st.session_state:
        st.session_state["monitor_alerts"] = []
    if "monitor_running" not in st.session_state:
        st.session_state["monitor_running"] = False


def _delta_indicator(current: float, previous: float) -> str:
    """Return ↑/↓/→ indicator with delta value."""
    diff = current - previous
    if abs(diff) < 0.1:
        return "→"
    elif diff > 0:
        return f"↑ +{diff:.1f}"
    else:
        return f"↓ {diff:.1f}"


def _grade_color(grade: str) -> str:
    """Return a color string for grade display."""
    colors = {
        "A+": "🟢",
        "A": "🔵",
        "B": "🟡",
        "NO_TRADE": "🔴",
        "---": "⚪",
    }
    return colors.get(grade, "⚪")


def _run_full_scan(instruments: List[Instrument]) -> Dict[str, Dict[str, Any]]:
    """Run pipeline for all active instruments. Returns {symbol: result_dict}."""
    results = {}

    try:
        mt5 = MT5Connector()
        intermarket = IntermarketData()
        intermarket_layer = IntermarketLayer(intermarket)
        pipeline = AnalysisPipeline()
        snapshot = intermarket.get_full_snapshot()
    except Exception as e:
        st.error(f"Failed to initialize: {e}")
        return results

    progress = st.progress(0)
    status_text = st.empty()

    for idx, inst in enumerate(instruments):
        pct = (idx + 1) / len(instruments)
        status_text.text(f"Analyzing {inst.display_name}... ({idx + 1}/{len(instruments)})")
        progress.progress(pct)

        try:
            df_d1 = mt5.get_ohlcv(inst.mt5_symbol, "D1", 200)
            df_h4 = mt5.get_ohlcv(inst.mt5_symbol, "H4", 200)
            df_h1 = mt5.get_ohlcv(inst.mt5_symbol, "H1", 500)
            df_m15 = mt5.get_ohlcv(inst.mt5_symbol, "M15", 500)

            pipe = pipeline.run(
                instrument=inst,
                intermarket_layer=intermarket_layer,
                df_d1=df_d1,
                df_h4=df_h4,
                df_h1=df_h1,
                df_m15=df_m15,
                intermarket_snapshot=snapshot,
            )

            # Compute average score across all layers
            layer_scores = [s.score for s in pipe.signals]
            avg_score = sum(layer_scores) / len(layer_scores) if layer_scores else 0.0
            pass_count = sum(1 for s in pipe.signals if s.score >= settings.LAYER_PASS_THRESHOLD)

            results[inst.mt5_symbol] = {
                "display_name": inst.display_name,
                "category": inst.category,
                "grade": pipe.grade,
                "direction": pipe.direction,
                "tradeable": pipe.tradeable,
                "avg_score": round(avg_score, 2),
                "qas": pipe.evaluation.get("qas", 0),
                "tws": pipe.evaluation.get("tws", 0),
                "pass_count": pass_count,
                "total_layers": len(pipe.signals),
                "price": pipe.current_price,
                "verdict": pipe.evaluation.get("verdict", "---"),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "elapsed_ms": pipe.elapsed_ms,
                "errors": pipe.errors,
            }
        except Exception as e:
            results[inst.mt5_symbol] = {
                "display_name": inst.display_name,
                "category": inst.category,
                "grade": "---",
                "direction": "NEUTRAL",
                "tradeable": False,
                "avg_score": 0.0,
                "qas": 0,
                "tws": 0,
                "pass_count": 0,
                "total_layers": 0,
                "price": 0,
                "verdict": f"Error: {e}",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "elapsed_ms": 0,
                "errors": {"scan": str(e)},
            }

    progress.empty()
    status_text.empty()
    return results


def _update_history(results: Dict[str, Dict[str, Any]]):
    """Store results in session history and detect alerts."""
    history = st.session_state["monitor_history"]
    alerts = []

    for symbol, data in results.items():
        if symbol not in history:
            history[symbol] = deque(maxlen=_HISTORY_SIZE)

        prev = history[symbol][-1] if history[symbol] else None
        history[symbol].append(data)

        if prev is None:
            continue

        # Grade change alert
        if _ALERT_GRADE and data["grade"] != prev["grade"]:
            alerts.append({
                "type": "grade_change",
                "symbol": symbol,
                "name": data["display_name"],
                "message": f"Grade: {prev['grade']} → {data['grade']}",
                "severity": "high" if data["grade"] in ("A+", "A") else "medium",
                "time": data["timestamp"],
            })

        # Direction flip alert
        if _ALERT_DIR and data["direction"] != prev["direction"] and prev["direction"] != "NEUTRAL":
            alerts.append({
                "type": "direction_flip",
                "symbol": symbol,
                "name": data["display_name"],
                "message": f"Direction: {prev['direction']} → {data['direction']}",
                "severity": "high",
                "time": data["timestamp"],
            })

        # Score delta alert
        score_delta = abs(data["avg_score"] - prev["avg_score"])
        if score_delta >= _SCORE_DELTA:
            alerts.append({
                "type": "score_delta",
                "symbol": symbol,
                "name": data["display_name"],
                "message": f"Score changed by {score_delta:+.1f} ({prev['avg_score']:.1f} → {data['avg_score']:.1f})",
                "severity": "medium",
                "time": data["timestamp"],
            })

    st.session_state["monitor_alerts"] = alerts + st.session_state.get("monitor_alerts", [])
    # Keep only last 50 alerts
    st.session_state["monitor_alerts"] = st.session_state["monitor_alerts"][:50]


def render():
    st.title("📟 Auto Monitor")
    st.caption("Real-time monitoring with automatic re-evaluation")

    _init_session_state()

    # ── Controls ──
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
    with col_ctrl1:
        auto_refresh = st.checkbox(
            f"🔄 Auto-refresh every {_INTERVAL}s",
            value=st.session_state.get("monitor_running", False),
            key="auto_refresh_toggle",
        )
        st.session_state["monitor_running"] = auto_refresh

    with col_ctrl2:
        manual_run = st.button("▶️ Run Now", type="primary", key="manual_scan")

    with col_ctrl3:
        if st.button("🗑️ Clear History", key="clear_history"):
            st.session_state["monitor_history"] = {}
            st.session_state["monitor_alerts"] = []
            st.rerun()

    # Auto-refresh using st_autorefresh (if enabled)
    if auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=_INTERVAL * 1000, limit=None, key="monitor_autorefresh")
        except ImportError:
            st.warning(
                "Install `streamlit-autorefresh` for auto-refresh: "
                "`pip install streamlit-autorefresh`\n\n"
                "Using manual refresh for now."
            )
            auto_refresh = False

    # ── Run scan ──
    should_run = manual_run or (auto_refresh and st.session_state.get("monitor_running", False))

    if should_run or st.session_state.get("monitor_last_run") is None:
        instruments = get_active_instruments()
        results = _run_full_scan(instruments)

        if results:
            _update_history(results)
            st.session_state["monitor_last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["monitor_latest"] = results

    # ── Display alerts ──
    alerts = st.session_state.get("monitor_alerts", [])
    if alerts:
        st.subheader("🚨 Alerts")
        for alert in alerts[:10]:  # Show latest 10
            severity = alert.get("severity", "medium")
            if severity == "high":
                st.error(f"**{alert['name']}** — {alert['message']} ({alert['time']})")
            else:
                st.warning(f"**{alert['name']}** — {alert['message']} ({alert['time']})")

    # ── Main display ──
    results = st.session_state.get("monitor_latest", {})
    history = st.session_state.get("monitor_history", {})
    last_run = st.session_state.get("monitor_last_run")

    if last_run:
        st.caption(f"Last scan: {last_run}")

    if not results:
        st.info("Click **Run Now** or enable auto-refresh to start monitoring.")
        return

    # ── Category filters ──
    categories = sorted(set(r.get("category", "?") for r in results.values()))
    selected_cats = st.multiselect("Filter by category", categories, default=categories, key="cat_filter")

    # ── Build display table ──
    table_data = []
    for symbol, data in sorted(results.items(), key=lambda x: x[1].get("avg_score", 0), reverse=True):
        if data.get("category") not in selected_cats:
            continue

        # Get previous for delta indicators
        prev_entries = history.get(symbol, deque())
        prev = prev_entries[-2] if len(prev_entries) >= 2 else None

        score_delta = _delta_indicator(data["avg_score"], prev["avg_score"]) if prev else ""
        grade_change = f" (was {prev['grade']})" if prev and prev["grade"] != data["grade"] else ""

        table_data.append({
            "Symbol": data["display_name"],
            "Grade": f"{_grade_color(data['grade'])} {data['grade']}{grade_change}",
            "Direction": data["direction"],
            "Avg Score": f"{data['avg_score']:.1f} {score_delta}",
            "Passes": f"{data['pass_count']}/{data['total_layers']}",
            "QAS": f"{data['qas']:.3f}" if data['qas'] else "---",
            "Tradeable": "✅" if data["tradeable"] else "❌",
            "Price": f"{data['price']:.5f}" if data["price"] < 100 else f"{data['price']:.2f}",
            "Updated": data["timestamp"],
        })

    if table_data:
        df_display = pd.DataFrame(table_data)
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.warning("No instruments match the selected filters.")

    # ── Tradeable Opportunities ──
    tradeable = [d for d in results.values() if d.get("tradeable") and d.get("grade") in ("A+", "A")]
    if tradeable:
        st.subheader("🎯 Tradeable Signals")
        for t in sorted(tradeable, key=lambda x: x.get("qas", 0), reverse=True):
            st.success(
                f"**{t['display_name']}** — {t['grade']} {t['direction']} | "
                f"QAS: {t['qas']:.3f} | {t['verdict']}"
            )

    # ── History chart (per selected symbol) ──
    st.markdown("---")
    st.subheader("📈 Score History")
    symbol_options = [f"{r['display_name']} ({s})" for s, r in results.items()]
    symbol_keys = list(results.keys())

    if symbol_options:
        sel = st.selectbox("Select instrument", range(len(symbol_options)),
                           format_func=lambda i: symbol_options[i], key="history_sym")
        sel_symbol = symbol_keys[sel]

        hist = history.get(sel_symbol, deque())
        if len(hist) >= 2:
            hist_list = list(hist)
            chart_data = pd.DataFrame({
                "Avg Score": [h["avg_score"] for h in hist_list],
                "QAS": [h.get("qas", 0) for h in hist_list],
                "Passes": [h["pass_count"] for h in hist_list],
            }, index=[h["timestamp"] for h in hist_list])
            st.line_chart(chart_data)
        else:
            st.caption("Need at least 2 evaluations for history chart. Run another scan.")

    # ── Stats ──
    st.sidebar.markdown("---")
    st.sidebar.subheader("Monitor Stats")
    st.sidebar.metric("Instruments", len(results))
    st.sidebar.metric("Tradeable", sum(1 for r in results.values() if r.get("tradeable")))
    st.sidebar.metric("Alerts", len(alerts))
    st.sidebar.metric("Scans", max(len(v) for v in history.values()) if history else 0)
