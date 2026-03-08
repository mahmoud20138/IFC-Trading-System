"""
IFC Trading System — Correlation Dashboard Page
Shows the correlation matrix, health status, divergence alerts,
portfolio heat map, and lead-lag relationships.
Compatible with Streamlit 1.12 (no tabs, divider, rerun, etc.)
"""

import streamlit as st
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config.instruments import WATCHLIST
from config import settings


def _inject_css():
    st.markdown("""
    <style>
    .corr-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
    .corr-table th { background:#1a1a2e; color:#e0e0e0; padding:6px 8px; text-align:center;
                     border:1px solid #333; }
    .corr-table td { padding:5px 8px; text-align:center; border:1px solid #333; color:#fff; }
    .corr-pos { background:rgba(0,200,83,0.25); }
    .corr-neg { background:rgba(255,23,68,0.25); }
    .corr-neutral { background:rgba(100,100,100,0.15); }
    .health-box { border-radius:8px; padding:12px 16px; margin:6px 0; }
    .health-healthy { background:rgba(0,200,83,0.15); border:1px solid #00c853; }
    .health-cautious { background:rgba(255,152,0,0.15); border:1px solid #ff9800; }
    .health-unhealthy { background:rgba(255,87,34,0.15); border:1px solid #ff5722; }
    .health-broken { background:rgba(255,23,68,0.15); border:1px solid #ff1744; }
    .lead-lag { background:#1a1a2e; border:1px solid #333; border-radius:6px;
                padding:10px; margin:4px 0; }
    </style>
    """, unsafe_allow_html=True)


def _corr_cell(r):
    """Colored cell for correlation value."""
    if r is None:
        return '<td class="corr-neutral">—</td>'
    css = "corr-pos" if r > 0.2 else "corr-neg" if r < -0.2 else "corr-neutral"
    return f'<td class="{css}">{r:+.2f}</td>'


def render():
    _inject_css()
    st.markdown("## Correlation Dashboard (Layer 9)")
    st.markdown("---")

    # Safe imports
    try:
        from analysis.layer9_correlation import (
            get_correlation, correlation_health_score,
            portfolio_correlation_risk, get_penalty_multiplier,
        )
        from data.intermarket import IntermarketData
        im = IntermarketData()
    except Exception as e:
        st.error(f"Import error: {e}")
        return

    # ── 1. Correlation Health ──
    st.markdown("### Intermarket Correlation Health")
    try:
        snapshot = im.get_full_snapshot()
        health = correlation_health_score(snapshot)
        h = health["health"]
        css_class = f"health-{h.lower()}"
        icon = {"HEALTHY": "🟢", "CAUTIOUS": "🟡", "UNHEALTHY": "🟠", "BROKEN": "🔴"}.get(h, "⚪")
        size_adj = health["size_adjustment"]

        st.markdown(f"""
        <div class="health-box {css_class}">
            <span style="font-size:24px;">{icon}</span>
            <span style="font-size:20px; font-weight:bold; color:white;"> {h}</span>
            <span style="color:#aaa; margin-left:16px;">
                Divergences: {health['divergence_count']} |
                Size adjustment: {size_adj:.0%}
            </span>
        </div>
        """, unsafe_allow_html=True)

        if health["checks"]:
            for check in health["checks"]:
                st.markdown(f"- {check}")
    except Exception as e:
        st.warning(f"Could not fetch intermarket data: {e}")
        snapshot = {}

    st.markdown("---")

    # ── 2. Correlation Matrix (key pairs) ──
    st.markdown("### Cross-Instrument Correlation Matrix")

    corr_matrix = getattr(settings, "CORRELATION_MATRIX", {})
    if corr_matrix:
        # Get unique symbols
        all_syms = set()
        for (a, b) in corr_matrix:
            all_syms.add(a)
            all_syms.add(b)
        syms = sorted(all_syms)

        # Build HTML table
        header = "<tr><th></th>" + "".join(f"<th>{s[:6]}</th>" for s in syms) + "</tr>"
        rows = ""
        for s1 in syms:
            row = f"<tr><th>{s1[:8]}</th>"
            for s2 in syms:
                if s1 == s2:
                    row += '<td style="background:#333;">1.00</td>'
                else:
                    r = get_correlation(s1, s2)
                    row += _corr_cell(r)
            row += "</tr>"
            rows += row

        st.markdown(f'<table class="corr-table">{header}{rows}</table>', unsafe_allow_html=True)
    else:
        st.info("No correlation matrix configured in settings.")

    st.markdown("---")

    # ── 3. Correlation Penalty Table ──
    st.markdown("### Position Size Penalty by Correlation")
    penalties = getattr(settings, "CORRELATION_PENALTIES", {})
    if penalties:
        html = '<table class="corr-table"><tr><th>Band</th><th>|r| Range</th><th>Multiplier</th><th>Reduction</th></tr>'
        sorted_p = sorted(penalties.items(), key=lambda x: -x[1]["min_r"])
        for name, info in sorted_p:
            mult = info["multiplier"]
            pct_reduce = (1 - mult) * 100
            html += f'<tr><td>{name.title()}</td><td>≥ {info["min_r"]:.2f}</td>'
            html += f'<td>{mult:.2f}x</td><td style="color:#ff9800;">{pct_reduce:.0f}%</td></tr>'
        html += "</table>"
        st.markdown(html, unsafe_allow_html=True)

    st.markdown("---")

    # ── 4. Lead-Lag Relationships ──
    st.markdown("### Lead-Lag Relationships")
    lead_lag = getattr(settings, "LEAD_LAG_PAIRS", {})
    if lead_lag:
        for leader, info in lead_lag.items():
            lags = ", ".join(info["lags"])
            delay = info["delay_min"]
            st.markdown(f"""
            <div class="lead-lag">
                <span style="color:#2196f3; font-weight:bold;">{leader}</span>
                <span style="color:#aaa;"> → leads → </span>
                <span style="color:#00c853; font-weight:bold;">{lags}</span>
                <span style="color:#aaa; margin-left:12px;">(~{delay} min delay)</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No lead-lag pairs configured.")

    st.markdown("---")

    # ── 5. Portfolio Correlation Risk (placeholder) ──
    st.markdown("### Portfolio Heat Map")
    try:
        from data.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        mt5.ensure_connected()
        positions = mt5.get_open_positions()
        if positions and len(positions) > 0:
            pos_list = []
            for pos in positions:
                pos_list.append({
                    "symbol": pos.symbol if hasattr(pos, "symbol") else str(pos),
                    "direction": "LONG" if (hasattr(pos, "type") and pos.type == 0) else "SHORT",
                    "risk_pct": 1.0,  # Default estimate
                })
            port_risk = portfolio_correlation_risk(pos_list)
            st.markdown(f"""
            **Raw Total Risk:** {port_risk['raw_total_risk']:.2f}%  
            **Adjusted Total Risk:** {port_risk['adjusted_total_risk']:.2f}%  
            **Remaining Capacity:** {port_risk['remaining_capacity']:.2f}%
            """)
            if port_risk.get("positions"):
                html = '<table class="corr-table"><tr><th>Symbol</th><th>Dir</th><th>Raw Risk</th><th>Corr</th><th>Penalty</th><th>Adj Risk</th></tr>'
                for p in port_risk["positions"]:
                    html += f'<tr><td>{p["symbol"]}</td><td>{p["direction"]}</td>'
                    html += f'<td>{p["raw_risk"]:.2f}%</td><td>{p["max_correlation"]:.2f}</td>'
                    html += f'<td>{p["penalty"]:.2f}x</td>'
                    html += f'<td style="color:#ff9800;">{p["adjusted_risk"]:.2f}%</td></tr>'
                html += "</table>"
                st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("No open positions — portfolio heat map is empty.")
    except Exception as e:
        st.info(f"MT5 not connected — showing empty portfolio heat map. ({e})")
