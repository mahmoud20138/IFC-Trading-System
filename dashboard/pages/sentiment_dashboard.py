"""
IFC Trading System — Sentiment Dashboard Page
Displays composite sentiment scores, component breakdown,
alert system, and sentiment-price action matrix.
Compatible with Streamlit 1.12 (no tabs, divider, rerun, etc.)
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config.instruments import WATCHLIST


def _inject_css():
    st.markdown("""
    <style>
    .sent-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
    .sent-table th { background:#1a1a2e; color:#e0e0e0; padding:6px 8px; text-align:center;
                     border:1px solid #333; }
    .sent-table td { padding:5px 8px; text-align:center; border:1px solid #333; color:#fff; }
    .sent-bull { background:rgba(0,200,83,0.25); }
    .sent-bear { background:rgba(255,23,68,0.25); }
    .sent-neutral { background:rgba(100,100,100,0.15); }
    .sent-extreme { background:rgba(255,152,0,0.3); border:1px solid #ff9800; }
    .alert-box { border-radius:6px; padding:8px 12px; margin:4px 0; font-size:13px; }
    .alert-red { background:rgba(255,23,68,0.15); border-left:4px solid #ff1744; color:#ff8a80; }
    .alert-yellow { background:rgba(255,152,0,0.15); border-left:4px solid #ff9800; color:#ffcc80; }
    .alert-green { background:rgba(0,200,83,0.15); border-left:4px solid #00c853; color:#a5d6a7; }
    .gauge-bar { height:20px; border-radius:10px; margin:4px 0;
                 background:linear-gradient(to right, #ff1744, #ff9800, #666, #2196f3, #00c853); }
    .gauge-marker { width:4px; height:28px; background:white; position:relative; margin-top:-24px;
                    border-radius:2px; }
    </style>
    """, unsafe_allow_html=True)


def _score_td(score, is_composite=False):
    """Color a score cell -3 to +3."""
    if score > 1.0:
        css = "sent-bull"
    elif score < -1.0:
        css = "sent-bear"
    else:
        css = "sent-neutral"
    if abs(score) >= 2.0 and is_composite:
        css = "sent-extreme"
    return f'<td class="{css}">{score:+.2f}</td>'


def _zone_html(zone):
    """Colored badge for sentiment zone."""
    colors = {
        "EXTREME_BULLISH": "#ff9800",
        "MODERATE_BULLISH": "#00c853",
        "NEUTRAL": "#666",
        "MODERATE_BEARISH": "#ff1744",
        "EXTREME_BEARISH": "#ff9800",
    }
    c = colors.get(zone, "#666")
    return f'<span style="background:{c}; color:white; padding:2px 8px; border-radius:4px; font-size:12px;">{zone}</span>'


def render():
    _inject_css()
    st.markdown("## Sentiment Dashboard (Layer 10)")
    st.markdown("---")

    try:
        from analysis.layer10_sentiment import compute_sentiment_composite, SentimentLayer
        from data.intermarket import IntermarketData
        im = IntermarketData()
        snapshot = im.get_full_snapshot()
    except Exception as e:
        st.error(f"Import error: {e}")
        return

    # ── Category filter ──
    categories = ["forex", "index", "commodity", "crypto", "stock"]
    cat_filter = st.radio("Category", categories, horizontal=False)

    instruments = [
        (inst.mt5_symbol, inst) for inst in WATCHLIST
        if inst.active and inst.category == cat_filter
    ]

    if not instruments:
        st.info(f"No active {cat_filter} instruments.")
        return

    st.markdown("---")

    # ── Compute sentiment for each instrument ──
    results = []
    for key, inst in instruments:
        try:
            result = compute_sentiment_composite(
                symbol=key, category=inst.category, snapshot=snapshot
            )
            result["symbol"] = key
            result["display"] = inst.display_name
            results.append(result)
        except Exception as e:
            results.append({
                "symbol": key,
                "display": inst.display_name,
                "composite_score": 0,
                "zone": "ERROR",
                "sources_available": 0,
                "sources_total": 0,
                "components": {},
                "direction": "NEUTRAL",
                "error": str(e),
            })

    # ── Summary Table ──
    st.markdown("### Sentiment Overview")
    html = '<table class="sent-table">'
    html += '<tr><th>Instrument</th><th>Composite</th><th>Zone</th><th>Direction</th><th>Sources</th></tr>'

    for r in results:
        comp = r["composite_score"]
        zone = r.get("zone", "—")
        direction = r.get("direction", "—")
        sources = f'{r.get("sources_available", 0)}/{r.get("sources_total", 0)}'

        html += f'<tr><td style="text-align:left;"><b>{r["display"]}</b></td>'
        html += _score_td(comp, is_composite=True)
        html += f'<td>{_zone_html(zone)}</td>'

        dir_color = "#00c853" if direction == "LONG" else "#ff1744" if direction == "SHORT" else "#666"
        html += f'<td style="color:{dir_color}; font-weight:bold;">{direction}</td>'
        html += f'<td>{sources}</td></tr>'

    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

    st.markdown("---")

    # ── Detail View for selected instrument ──
    st.markdown("### Component Breakdown")
    symbol_names = [f"{inst.display_name} ({key})" for key, inst in instruments]
    selected_idx = st.selectbox("Select instrument", range(len(symbol_names)),
                                format_func=lambda i: symbol_names[i])

    if selected_idx is not None and selected_idx < len(results):
        detail = results[selected_idx]
        comp = detail.get("components", {})

        if comp:
            html = '<table class="sent-table">'
            html += '<tr><th>Source</th><th>Score (-3/+3)</th><th>Confidence</th><th>Available</th><th>Details</th></tr>'

            for name, data in comp.items():
                available = "✅" if data.get("available") else "❌"
                score = data.get("score", 0)
                conf = data.get("confidence", 0)
                # Build details string
                detail_parts = []
                if "value" in data:
                    detail_parts.append(f"F&G={data['value']}")
                if "zone" in data:
                    detail_parts.append(data["zone"])
                if "vix_level" in data:
                    detail_parts.append(f"VIX={data['vix_level']:.1f}")
                if "long_pct" in data:
                    detail_parts.append(f"L:{data['long_pct']:.0f}% S:{data.get('short_pct', 0):.0f}%")
                if "commercial_bias" in data:
                    detail_parts.append(f"Comm={data['commercial_bias']}")
                if data.get("proxy"):
                    detail_parts.append("(proxy)")
                details_str = ", ".join(detail_parts) or "—"

                html += f'<tr><td style="text-align:left;">{name.replace("_", " ").title()}</td>'
                html += _score_td(score)
                html += f'<td>{conf}/5</td>'
                html += f'<td>{available}</td>'
                html += f'<td style="text-align:left; color:#aaa; font-size:12px;">{details_str}</td></tr>'

            html += "</table>"
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("---")

    # ── VIX Sentiment Gauge ──
    st.markdown("### Market Fear Gauge (VIX)")
    vix = snapshot.get("VIX", {})
    vix_level = vix.get("level")
    if vix_level:
        # Gauge: 0 to 50 scale
        pct = min(100, max(0, (vix_level / 50) * 100))
        color = "#00c853" if vix_level < 15 else "#ff9800" if vix_level < 25 else "#ff1744"
        st.markdown(f"""
        <div style="margin:10px 0;">
            <div style="display:flex; justify-content:space-between; color:#aaa; font-size:11px;">
                <span>Calm (0)</span><span>Normal (15-20)</span><span>Fear (25-30)</span><span>Extreme (40+)</span>
            </div>
            <div class="gauge-bar"></div>
            <div style="width:4px; height:28px; background:{color};
                        margin-top:-24px; margin-left:{pct}%;
                        border-radius:2px; position:relative;"></div>
            <div style="text-align:center; color:{color}; font-size:18px; font-weight:bold; margin-top:4px;">
                VIX: {vix_level:.1f}
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("VIX data unavailable.")

    st.markdown("---")

    # ── Sentiment Alert Conditions ──
    st.markdown("### Active Alerts")
    alerts_found = False

    if vix_level and vix_level > 30:
        st.markdown(
            '<div class="alert-box alert-red">🔴 VIX > 30 — Reduce all positions 50%, widen stops 1.5x</div>',
            unsafe_allow_html=True
        )
        alerts_found = True

    if vix_level and vix_level < 12:
        st.markdown(
            '<div class="alert-box alert-yellow">🟡 VIX extremely low — Complacency detected, breakout risk elevated</div>',
            unsafe_allow_html=True
        )
        alerts_found = True

    # Check for extreme retail sentiment
    for r in results:
        comp = r.get("components", {})
        broker = comp.get("broker_sentiment", {})
        if broker.get("available"):
            if broker.get("long_pct", 0) > 80 or broker.get("short_pct", 0) > 80:
                st.markdown(
                    f'<div class="alert-box alert-red">🔴 Extreme retail positioning on {r["display"]} — Strong contrarian signal</div>',
                    unsafe_allow_html=True
                )
                alerts_found = True

    # Check for extreme Fear & Greed
    for r in results:
        comp = r.get("components", {})
        fg = comp.get("fear_greed", {})
        if fg.get("available"):
            val = fg.get("value", 50)
            if val <= 15:
                st.markdown(
                    '<div class="alert-box alert-green">🟢 Extreme Fear — Historic buying opportunity, look for sweep setups</div>',
                    unsafe_allow_html=True
                )
                alerts_found = True
            elif val >= 85:
                st.markdown(
                    '<div class="alert-box alert-red">🔴 Extreme Greed — Reduce exposure, tighten stops</div>',
                    unsafe_allow_html=True
                )
                alerts_found = True

    if not alerts_found:
        st.markdown(
            '<div class="alert-box alert-green">🟢 No extreme alerts — Normal trading conditions</div>',
            unsafe_allow_html=True
        )
