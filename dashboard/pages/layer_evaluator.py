"""
IFC Dashboard - Layer Evaluator (FAST + COLORED + GROUPED)
Shows all 11 IFC plan layers across ALL timeframes for every symbol.
Optimised: L1/L2/L8/L9/L10/L11 computed ONCE per symbol, colored HTML tables,
           symbols grouped by category with colored headers.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from config import settings

# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------

_TFS = ["W1", "D1", "H4", "H1", "M15"]
_TF_BARS = {"W1": 52, "D1": 200, "H4": 80, "H1": 80, "M15": 80}
_PASS = settings.LAYER_PASS_THRESHOLD  # 6.0 from settings

_LAYER_NAMES = {
    1: "Intermarket & Macro",
    2: "Trend (MAs+Structure)",
    3: "POC + Volume Profile",
    4: "Candle Density",
    5: "Liquidity Pools",
    6: "FVG + Order Block",
    7: "Delta / Order Flow",
    8: "Killzone + Day",
    9: "Correlation Engine",
    10: "Sentiment Composite",
    11: "AI / Regime Eval",
}
_LAYER_SHORT = {
    1: "L1", 2: "L2", 3: "L3", 4: "L4",
    5: "L5", 6: "L6", 7: "L7", 8: "L8",
    9: "L9", 10: "L10", 11: "L11",
}
_LAYER_DESC = {
    1: "DXY, US10Y, VIX, SPX - Risk On/Off regime",
    2: "EMA 10/21/50/200 stack + BOS/CHoCH structure",
    3: "POC, VAH, VAL, HVN, LVN, profile shape",
    4: "Dense clusters (S/R) vs thin zones (fast travel)",
    5: "Equal highs/lows, swing points, stop-hunt sweeps",
    6: "Fair Value Gaps + Order Blocks for entry",
    7: "Cumulative delta, absorption, divergence",
    8: "London/NY killzone, day-of-week filter",
    9: "Cross-instrument correlation, penalties, lead-lag",
    10: "Fear/Greed, VIX, COT, retail sentiment, funding",
    11: "AI regime detection, TWS/QAS composite score",
}

# Category ordering and colors
_CAT_ORDER = ["forex", "index", "commodity", "crypto", "stock"]
_CAT_LABELS = {
    "forex": "FOREX",
    "index": "INDICES",
    "commodity": "COMMODITIES",
    "crypto": "CRYPTO",
    "stock": "STOCKS",
}
_CAT_COLORS = {
    "forex": "#1e3a5f",
    "index": "#4a1e5f",
    "commodity": "#5f4a1e",
    "crypto": "#1e5f3a",
    "stock": "#5f1e2a",
}
_CAT_TEXT = {
    "forex": "#7dd3fc",
    "index": "#c4b5fd",
    "commodity": "#fcd34d",
    "crypto": "#6ee7b7",
    "stock": "#fca5a5",
}


# ---------------------------------------------------------------
# CSS Injection
# ---------------------------------------------------------------

def _inject_css():
    css = """
    <style>
    .le-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        margin-bottom: 16px;
    }
    .le-table th {
        background: #1e1e2e;
        color: #cdd6f4;
        padding: 6px 8px;
        text-align: center;
        border-bottom: 2px solid #45475a;
        position: sticky;
        top: 0;
        z-index: 10;
    }
    .le-table td {
        padding: 4px 6px;
        text-align: center;
        border-bottom: 1px solid #313244;
    }
    .le-table tr:hover td {
        background: #313244 !important;
    }
    .le-table .sym {
        text-align: left;
        font-weight: 600;
        color: #f5f5f5;
        background: #1e1e2e;
        position: sticky;
        left: 0;
        z-index: 5;
    }
    /* Category header row */
    .cat-row td {
        background: #262637;
        font-weight: bold;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        padding: 8px 12px;
        text-align: left;
        border-left: 4px solid;
    }
    /* Score colors */
    .sc-pass { background: #0d3320; color: #4ade80; font-weight: 600; }
    .sc-near { background: #3d2e0a; color: #fbbf24; }
    .sc-fail { background: #3b1111; color: #f87171; }
    .sc-zero { background: #1e1e2e; color: #6b7280; }
    /* Grade badges */
    .gr-aplus { background: #166534; color: #4ade80; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .gr-a { background: #1e40af; color: #60a5fa; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .gr-b { background: #854d0e; color: #fbbf24; padding: 2px 6px; border-radius: 4px; }
    .gr-no { background: #374151; color: #9ca3af; padding: 2px 6px; border-radius: 4px; }
    /* Direction */
    .dir-long { color: #4ade80; }
    .dir-short { color: #f87171; }
    .dir-neutral { color: #9ca3af; }
    /* Alt rows */
    .le-table tbody tr:nth-child(odd) td:not(.cat-row td) { background: #1a1a2e; }
    .le-table tbody tr:nth-child(even) td:not(.cat-row td) { background: #16162a; }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _atr(df, p=14):
    if df is None or df.empty or len(df) < p + 1:
        return 0.0
    try:
        tr = np.maximum(df["high"] - df["low"],
                        np.maximum(abs(df["high"] - df["close"].shift(1)),
                                   abs(df["low"] - df["close"].shift(1))))
        return float(tr.rolling(p).mean().iloc[-1])
    except Exception:
        return 0.0


def _price(frames):
    for f in frames:
        if f is not None and not f.empty:
            return float(f["close"].iloc[-1])
    return None


def _sort_by_category(results):
    """Sort results by category order, then by symbol name within each category."""
    def sort_key(r):
        cat = r.get("category", "stock").lower()
        try:
            cat_idx = _CAT_ORDER.index(cat)
        except ValueError:
            cat_idx = 99
        return (cat_idx, r.get("symbol", ""))
    return sorted(results, key=sort_key)


# ---------------------------------------------------------------
# HTML formatting helpers
# ---------------------------------------------------------------

def _score_td(score):
    """Return a <td> with colored background based on score."""
    if score >= _PASS:
        cls = "sc-pass"
    elif score >= 5:
        cls = "sc-near"
    elif score > 0:
        cls = "sc-fail"
    else:
        cls = "sc-zero"
    return '<td class="{}">{:.1f}</td>'.format(cls, score)


def _grade_html(grade):
    """Return a colored grade badge."""
    if grade == "A+":
        return '<span class="gr-aplus">A+</span>'
    if grade == "A":
        return '<span class="gr-a">A</span>'
    if grade == "B":
        return '<span class="gr-b">B</span>'
    return '<span class="gr-no">---</span>'


def _dir_html(direction):
    """Return colored direction indicator."""
    if direction == "LONG":
        return '<span class="dir-long">&#9650; LONG</span>'
    if direction == "SHORT":
        return '<span class="dir-short">&#9660; SHORT</span>'
    return '<span class="dir-neutral">&#8596; ---</span>'


def _dir_arrow(direction):
    """Return just the arrow."""
    if direction == "LONG":
        return '<span class="dir-long">&#9650;</span>'
    if direction == "SHORT":
        return '<span class="dir-short">&#9660;</span>'
    return '<span class="dir-neutral">-</span>'


def _icon_txt(s):
    """Text icon for markdown contexts."""
    if s >= 8:
        return "+++"
    if s >= _PASS:
        return "++"
    if s >= 5:
        return "+"
    if s > 0:
        return "-"
    return "."


# ---------------------------------------------------------------
# FAST evaluation - one symbol, all TFs
# ---------------------------------------------------------------

def _evaluate_symbol(inst, data, im, snapshot, shared_l1, shared_l2, shared_l8,
                     shared_l9=(5.0, "NEUTRAL"), shared_l10=(5.0, "NEUTRAL"),
                     shared_l11=(5.0, "NEUTRAL")):
    """
    Run layers on each TF. L1/L2/L8/L9/L10/L11 are passed in pre-computed.
    Only L3-L7 vary per TF.
    """
    from analysis.layer3_volume_profile import VolumeProfileLayer, compute_volume_profile
    from analysis.layer4_candle_density import CandleDensityLayer
    from analysis.layer5_liquidity import LiquidityLayer
    from analysis.layer6_fvg_ob import FVGOrderBlockLayer
    from analysis.layer7_order_flow import OrderFlowLayer
    from analysis.confluence_scorer import ConfluenceScorer
    from analysis.layer1_intermarket import LayerSignal

    df_w = data.get("W1", pd.DataFrame())
    df_d = data.get("D1", pd.DataFrame())
    df_h4 = data.get("H4", pd.DataFrame())
    df_h1 = data.get("H1", pd.DataFrame())
    df_m15 = data.get("M15", pd.DataFrame())

    price = _price([df_m15, df_h1, df_h4, df_d, df_w])
    if price is None:
        return None

    # D1 volume profile (compute once)
    d1_vp = None
    try:
        if not df_d.empty and len(df_d) >= 30:
            d1_vp = compute_volume_profile(df_d)
    except Exception:
        pass

    hvn = list(d1_vp.hvn) if d1_vp else []
    lvn = list(d1_vp.lvn) if d1_vp else []

    result = {
        "symbol": inst.display_name,
        "category": inst.category,
        "price": price,
    }

    # Stamp shared layers for ALL TFs
    for tf in _TFS:
        result["{}_L1".format(tf)] = shared_l1[0]
        result["{}_L1d".format(tf)] = shared_l1[1]
        result["{}_L2".format(tf)] = shared_l2[0]
        result["{}_L2d".format(tf)] = shared_l2[1]
        result["{}_L8".format(tf)] = shared_l8[0]
        result["{}_L8d".format(tf)] = shared_l8[1]
        result["{}_L9".format(tf)] = shared_l9[0]
        result["{}_L9d".format(tf)] = shared_l9[1]
        result["{}_L10".format(tf)] = shared_l10[0]
        result["{}_L10d".format(tf)] = shared_l10[1]
        result["{}_L11".format(tf)] = shared_l11[0]
        result["{}_L11d".format(tf)] = shared_l11[1]

    tf_frames = {"W1": df_w, "D1": df_d, "H4": df_h4, "H1": df_h1, "M15": df_m15}

    for tf in _TFS:
        df_tf = tf_frames[tf]
        cur_atr = _atr(df_tf)

        # L3 - Volume Profile
        try:
            tf_vp = d1_vp
            if df_tf is not None and not df_tf.empty and len(df_tf) >= 30 and tf != "D1":
                tf_vp = compute_volume_profile(df_tf)
            if tf_vp is None:
                tf_vp = d1_vp
            if tf_vp is not None:
                s = VolumeProfileLayer().analyze(current_price=price, composite_profile=tf_vp)
                result["{}_L3".format(tf)] = s.score
                result["{}_L3d".format(tf)] = s.direction
            else:
                result["{}_L3".format(tf)] = 0.0
                result["{}_L3d".format(tf)] = "---"
        except Exception:
            result["{}_L3".format(tf)] = 0.0
            result["{}_L3d".format(tf)] = "---"

        # L4 - Candle Density
        try:
            s = CandleDensityLayer().analyze(df_tf, vp_hvn=hvn, vp_lvn=lvn, current_price=price)
            result["{}_L4".format(tf)] = s.score
            result["{}_L4d".format(tf)] = s.direction
        except Exception:
            result["{}_L4".format(tf)] = 0.0
            result["{}_L4d".format(tf)] = "---"

        # L5 - Liquidity
        try:
            s = LiquidityLayer().analyze(df_tf, atr=cur_atr, current_price=price)
            result["{}_L5".format(tf)] = s.score
            result["{}_L5d".format(tf)] = s.direction
        except Exception:
            result["{}_L5".format(tf)] = 0.0
            result["{}_L5d".format(tf)] = "---"

        # L6 - FVG / OB — use L2's direction for proper filtering
        try:
            l2_dir = result.get("{}_L2d".format(tf), "NEUTRAL")
            if l2_dir == "---":
                l2_dir = "NEUTRAL"
            # Pass VP confluence levels if available
            conf_levels = None
            if tf_vp is not None:
                conf_levels = [tf_vp.poc, tf_vp.vah, tf_vp.val] + list(getattr(tf_vp, 'hvn', [])[:3])
            s = FVGOrderBlockLayer().analyze(df_tf, atr=cur_atr, current_price=price, trade_direction=l2_dir, confluence_levels=conf_levels)
            result["{}_L6".format(tf)] = s.score
            result["{}_L6d".format(tf)] = s.direction
        except Exception:
            result["{}_L6".format(tf)] = 0.0
            result["{}_L6d".format(tf)] = "---"

        # L7 - Order Flow — use L2's direction
        try:
            l2_dir = result.get("{}_L2d".format(tf), "NEUTRAL")
            if l2_dir == "---":
                l2_dir = "NEUTRAL"
            s = OrderFlowLayer().analyze(df_tf, trade_direction=l2_dir)
            result["{}_L7".format(tf)] = s.score
            result["{}_L7d".format(tf)] = s.direction
        except Exception:
            result["{}_L7".format(tf)] = 0.0
            result["{}_L7d".format(tf)] = "---"

    # Grade per TF — use settings thresholds
    for tf in _TFS:
        passes = sum(1 for n in range(1, 12) if result.get("{}_L{}".format(tf, n), 0) >= _PASS)
        result["{}_pass".format(tf)] = passes
        if passes >= settings.GRADE_THRESHOLDS['A+']:
            result["{}_grade".format(tf)] = "A+"
        elif passes >= settings.GRADE_THRESHOLDS['A']:
            result["{}_grade".format(tf)] = "A"
        elif passes >= settings.GRADE_THRESHOLDS['B']:
            result["{}_grade".format(tf)] = "B"
        else:
            result["{}_grade".format(tf)] = "---"

    # Overall confluence from H1
    try:
        signals = []
        for n in range(1, 12):
            sc = result.get("H1_L{}".format(n), 0.0)
            dr = result.get("H1_L{}d".format(n), "NEUTRAL")
            signals.append(LayerSignal(
                layer_name="L{}".format(n),
                direction=dr if dr != "---" else "NEUTRAL",
                score=sc, confidence=sc / 10.0, details={},
            ))
        conf = ConfluenceScorer().score(signals)
        result["overall_grade"] = conf.get("grade", "---")
        result["overall_dir"] = conf.get("direction", "NEUTRAL")
        result["overall_passed"] = conf.get("total_passes", 0)
        result["overall_avg"] = conf.get("avg_score", 0)
        result["tradeable"] = conf.get("tradeable", False)
    except Exception:
        result["overall_grade"] = "---"
        result["overall_dir"] = "NEUTRAL"
        result["overall_passed"] = 0
        result["overall_avg"] = 0
        result["tradeable"] = False

    return result


# ---------------------------------------------------------------
# HTML Table Builder
# ---------------------------------------------------------------

def _build_html_table(headers, rows, results, group_by_cat=True):
    """
    Build an HTML table with optional category grouping.
    headers: list of column header strings
    rows: list of dicts with 'symbol', 'category', and 'cells' (list of HTML cell contents)
    """
    html = '<table class="le-table"><thead><tr>'
    for h in headers:
        html += '<th>{}</th>'.format(h)
    html += '</tr></thead><tbody>'

    if group_by_cat:
        sorted_rows = _sort_by_category(rows)
        current_cat = None
        cat_counts = {}
        for r in sorted_rows:
            cat = r.get("category", "stock").lower()
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        for r in sorted_rows:
            cat = r.get("category", "stock").lower()
            if cat != current_cat:
                current_cat = cat
                label = _CAT_LABELS.get(cat, cat.upper())
                color = _CAT_COLORS.get(cat, "#333")
                text_color = _CAT_TEXT.get(cat, "#fff")
                count = cat_counts.get(cat, 0)
                html += '<tr class="cat-row"><td colspan="{}" style="border-left-color: {}; color: {};">{} ({} instruments)</td></tr>'.format(
                    len(headers), color, text_color, label, count)
            html += '<tr>'
            html += '<td class="sym">{}</td>'.format(r.get("symbol", ""))
            for cell in r.get("cells", []):
                html += cell
            html += '</tr>'
    else:
        for r in rows:
            html += '<tr>'
            html += '<td class="sym">{}</td>'.format(r.get("symbol", ""))
            for cell in r.get("cells", []):
                html += cell
            html += '</tr>'

    html += '</tbody></table>'
    return html


# ---------------------------------------------------------------
# PAGE
# ---------------------------------------------------------------

def render():
    st.title("IFC 11-Layer Evaluator")
    st.caption("Institutional Flow Confluence - 11 layers x 5 TFs x all symbols - grouped by category")

    _inject_css()

    # Plan reference
    with st.expander("IFC 11-Layer Plan Reference", expanded=False):
        ref = []
        for n in range(1, 12):
            ref.append({
                "#": "L{}".format(n),
                "Layer": _LAYER_NAMES[n],
                "What It Checks": _LAYER_DESC[n],
                "Pass": ">= {}".format(_PASS),
            })
        st.dataframe(pd.DataFrame(ref))
        st.markdown(
            "**Grading:** {} pass = **A+** | {} pass = **A** | "
            "{} pass = **B** | Below {} = **NO TRADE**".format(
                settings.GRADE_THRESHOLDS['A+'], settings.GRADE_THRESHOLDS['A'],
                settings.GRADE_THRESHOLDS['B'], settings.GRADE_THRESHOLDS['B'],
            )
        )

    try:
        from config.instruments import get_active_instruments
        from data.mt5_connector import MT5Connector
        from data.intermarket import IntermarketData
    except ImportError as e:
        st.error("Import error: {}".format(e))
        return

    mt5 = MT5Connector()
    try:
        mt5.connect()
    except Exception as e:
        st.error("MT5 connection failed: {}".format(e))
        return

    im = IntermarketData()
    instruments = get_active_instruments()

    # Controls
    c1, c2, c3 = st.columns([4, 1, 1])
    with c1:
        cat_filter = st.radio("Category",
            ["ALL", "FOREX", "INDEX", "COMMODITY", "CRYPTO", "STOCK"],
            horizontal=True, key="le_cat")
    with c2:
        rescan = st.button("Evaluate")
    with c3:
        auto = st.checkbox("Auto", value=True)

    if cat_filter != "ALL":
        instruments = [i for i in instruments if i.category.upper() == cat_filter]

    need_scan = rescan or (auto and "le_results" not in st.session_state)

    if not need_scan and "le_results" not in st.session_state:
        st.info("Click **Evaluate** to run all 11 layers on every timeframe.")
        return

    # == SCAN ==
    if need_scan:
        from analysis.layer1_intermarket import IntermarketLayer
        from analysis.layer2_trend import TrendLayer
        from analysis.layer8_killzone import KillzoneLayer
        from analysis.layer9_correlation import CorrelationLayer
        from analysis.layer10_sentiment import SentimentLayer
        from analysis.layer11_ai_evaluation import AIEvaluationLayer

        progress = st.progress(0)
        status = st.empty()
        total = len(instruments)

        status.text("Fetching intermarket snapshot...")
        try:
            snapshot = im.get_full_snapshot()
        except Exception:
            snapshot = {}
        progress.progress(0.05)

        status.text("Checking calendar...")
        try:
            from data.economic_calendar import fetch_economic_calendar
            fetch_economic_calendar()
        except Exception:
            pass
        progress.progress(0.08)

        all_data = {}
        for idx, inst in enumerate(instruments):
            sym = inst.mt5_symbol
            status.text("MT5: {} ({}/{})".format(inst.display_name, idx + 1, total))
            sym_data = {}
            for tf, bars in _TF_BARS.items():
                try:
                    sym_data[tf] = mt5.get_ohlcv(sym, tf, bars=bars)
                except Exception:
                    sym_data[tf] = pd.DataFrame()
            all_data[sym] = sym_data
            progress.progress(0.08 + 0.52 * (idx + 1) / total)

        results = []
        for idx, inst in enumerate(instruments):
            status.text("Eval: {} ({}/{})".format(inst.display_name, idx + 1, total))
            try:
                sym = inst.mt5_symbol
                d = all_data[sym]
                df_w = d.get("W1", pd.DataFrame())
                df_d = d.get("D1", pd.DataFrame())
                df_h4 = d.get("H4", pd.DataFrame())

                try:
                    s1 = IntermarketLayer(im).analyze(inst, snapshot)
                    l1 = (s1.score, s1.direction)
                except Exception:
                    l1 = (0.0, "---")

                try:
                    w = df_w if not df_w.empty else df_d
                    s2 = TrendLayer().analyze(w, df_d, df_h4)
                    l2 = (s2.score, s2.direction)
                except Exception:
                    l2 = (0.0, "---")

                try:
                    s8 = KillzoneLayer().analyze(sym)
                    l8 = (s8.score, s8.direction)
                except Exception:
                    l8 = (0.0, "---")

                try:
                    s9 = CorrelationLayer().analyze(sym, snapshot)
                    l9 = (s9.score, s9.direction)
                except Exception:
                    l9 = (5.0, "NEUTRAL")

                try:
                    s10 = SentimentLayer().analyze(sym, inst.category, snapshot)
                    l10 = (s10.score, s10.direction)
                except Exception:
                    l10 = (5.0, "NEUTRAL")

                try:
                    vix_lvl = snapshot.get("VIX", {}).get("level", 20.0) if snapshot else 20.0
                    s11 = AIEvaluationLayer().analyze(df_d, None, vix_lvl)
                    l11 = (s11.score, s11.direction)
                except Exception:
                    l11 = (5.0, "NEUTRAL")

                r = _evaluate_symbol(inst, d, im, snapshot, l1, l2, l8, l9, l10, l11)
                if r:
                    results.append(r)
            except Exception as e:
                results.append({
                    "symbol": inst.display_name,
                    "category": inst.category,
                    "overall_grade": "ERR",
                    "error": str(e),
                })
            progress.progress(0.60 + 0.40 * (idx + 1) / total)

        progress.empty()
        status.empty()
        st.session_state["le_results"] = results
        st.session_state["le_time"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    results = st.session_state.get("le_results", [])
    scan_time = st.session_state.get("le_time", "---")
    if not results:
        return

    if cat_filter != "ALL":
        results = [r for r in results if r.get("category", "").upper() == cat_filter]

    st.caption("Last scan: {} | {} symbols".format(scan_time, len(results)))

    # =====================================================================
    # TRADEABLE SETUPS (top priority)
    # =====================================================================
    tradeable = [r for r in results if r.get("tradeable")]
    if tradeable:
        st.subheader("Tradeable Setups ({})".format(len(tradeable)))
        for r in sorted(tradeable, key=lambda x: x.get("overall_avg", 0), reverse=True):
            dir_txt = "LONG" if r.get("overall_dir") == "LONG" else ("SHORT" if r.get("overall_dir") == "SHORT" else "---")
            st.success(
                "**{}** | Grade: **{}** | {} | Avg: **{:.1f}** | Passed: **{}/11**".format(
                    r["symbol"],
                    r.get("overall_grade", "---"),
                    dir_txt,
                    r.get("overall_avg", 0),
                    r.get("overall_passed", 0),
                )
            )
        st.markdown("---")
    else:
        st.info("No tradeable setups currently.")
        st.markdown("---")

    # =====================================================================
    # LAYER SCORES BY TIMEFRAME (main view)
    # =====================================================================
    st.subheader("Layer Scores by Timeframe")
    view_tf = st.radio("Select TF", _TFS, horizontal=True, key="le_view_tf")

    headers = ["Symbol", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "Grade", "Pass", "Dir"]
    rows = []
    for r in results:
        if "error" in r and "price" not in r:
            continue
        cells = []
        for n in range(1, 12):
            sc = r.get("{}_L{}".format(view_tf, n), 0.0)
            cells.append(_score_td(sc))
        # Grade
        gr = r.get("{}_grade".format(view_tf), "---")
        cells.append('<td>{}</td>'.format(_grade_html(gr)))
        # Pass count
        ps = r.get("{}_pass".format(view_tf), 0)
        cells.append('<td>{}/11</td>'.format(ps))
        # Direction (use most common from L1-L11)
        dirs = [r.get("{}_L{}d".format(view_tf, n), "NEUTRAL") for n in range(1, 12)]
        long_c = sum(1 for d in dirs if d == "LONG")
        short_c = sum(1 for d in dirs if d == "SHORT")
        if long_c > short_c:
            main_dir = "LONG"
        elif short_c > long_c:
            main_dir = "SHORT"
        else:
            main_dir = "NEUTRAL"
        cells.append('<td>{}</td>'.format(_dir_html(main_dir)))
        rows.append({"symbol": r["symbol"], "category": r.get("category", "stock"), "cells": cells})

    html = _build_html_table(headers, rows, results, group_by_cat=True)
    st.markdown(html, unsafe_allow_html=True)

    st.markdown("---")

    # =====================================================================
    # OVERVIEW - PER-TF GRADES
    # =====================================================================
    st.subheader("Overview - Per-TF Grades")

    headers2 = ["Symbol", "Overall", "W1", "D1", "H4", "H1", "M15", "Dir"]
    rows2 = []
    for r in results:
        if "error" in r and "price" not in r:
            continue
        cells = []
        # Overall grade
        og = r.get("overall_grade", "---")
        cells.append('<td>{}</td>'.format(_grade_html(og)))
        # Per-TF grades
        for tf in _TFS:
            gr = r.get("{}_grade".format(tf), "---")
            cells.append('<td>{}</td>'.format(_grade_html(gr)))
        # Direction
        od = r.get("overall_dir", "NEUTRAL")
        cells.append('<td>{}</td>'.format(_dir_html(od)))
        rows2.append({"symbol": r["symbol"], "category": r.get("category", "stock"), "cells": cells})

    html2 = _build_html_table(headers2, rows2, results, group_by_cat=True)
    st.markdown(html2, unsafe_allow_html=True)

    st.markdown("---")

    # =====================================================================
    # SINGLE LAYER ACROSS ALL TFs
    # =====================================================================
    st.subheader("Single Layer Across All TFs")
    layer_opts = ["L{} - {}".format(n, _LAYER_NAMES[n]) for n in range(1, 12)]
    layer_pick = st.radio("Layer", layer_opts, horizontal=True, key="le_layer")
    layer_num = int(layer_pick.split(" ")[0][1:])

    headers3 = ["Symbol", "W1", "D1", "H4", "H1", "M15", "TF Pass"]
    rows3 = []
    for r in results:
        if "error" in r and "price" not in r:
            continue
        cells = []
        pass_count = 0
        for tf in _TFS:
            sc = r.get("{}_L{}".format(tf, layer_num), 0.0)
            cells.append(_score_td(sc))
            if sc >= _PASS:
                pass_count += 1
        cells.append('<td>{}/{}</td>'.format(pass_count, len(_TFS)))
        rows3.append({"symbol": r["symbol"], "category": r.get("category", "stock"), "cells": cells})

    html3 = _build_html_table(headers3, rows3, results, group_by_cat=True)
    st.markdown(html3, unsafe_allow_html=True)

    st.markdown("---")

    # =====================================================================
    # SYMBOL DRILL-DOWN
    # =====================================================================
    st.subheader("Symbol Drill-Down")
    sym_names = [r["symbol"] for r in _sort_by_category(results) if "error" not in r or "price" in r]
    if not sym_names:
        return
    selected = st.selectbox("Select symbol", sym_names, key="le_sym")
    detail = None
    for r in results:
        if r.get("symbol") == selected:
            detail = r
            break
    if not detail:
        return

    og = detail.get("overall_grade", "---")
    od = detail.get("overall_dir", "NEUTRAL")
    op = detail.get("overall_passed", 0)
    oa = detail.get("overall_avg", 0)

    if og in ("A+", "A"):
        st.success("**{}** | Grade: **{}** | Dir: **{}** | Passed: **{}/11** | Avg: **{:.1f}**".format(
            selected, og, od, op, oa))
    elif og == "B":
        st.warning("**{}** | Grade: **{}** | Dir: **{}** | Passed: **{}/11** | Avg: **{:.1f}**".format(
            selected, og, od, op, oa))
    else:
        st.info("**{}** | Grade: **{}** | Dir: **{}** | Passed: **{}/11** | Avg: **{:.1f}**".format(
            selected, og, od, op, oa))

    # Layer x TF matrix (colored HTML)
    st.markdown("**Layer x Timeframe Matrix:**")
    matrix_html = '<table class="le-table"><thead><tr><th>Layer</th>'
    for tf in _TFS:
        matrix_html += '<th>{}</th>'.format(tf)
    matrix_html += '</tr></thead><tbody>'
    for n in range(1, 12):
        matrix_html += '<tr><td class="sym">L{} - {}</td>'.format(n, _LAYER_NAMES[n])
        for tf in _TFS:
            sc = detail.get("{}_L{}".format(tf, n), 0.0)
            matrix_html += _score_td(sc)
        matrix_html += '</tr>'
    matrix_html += '</tbody></table>'
    st.markdown(matrix_html, unsafe_allow_html=True)

    # Per-TF summary metrics
    st.markdown("**Per-TF Summary:**")
    tf_cols = st.columns(len(_TFS))
    for i, tf in enumerate(_TFS):
        g = detail.get("{}_grade".format(tf), "---")
        p = detail.get("{}_pass".format(tf), 0)
        avg_tf = np.mean([detail.get("{}_L{}".format(tf, nn), 0) for nn in range(1, 12)])
        tf_cols[i].metric(tf, "{} ({}/11)".format(g, p), delta="Avg {:.1f}".format(avg_tf))

    # Layer descriptions
    st.markdown("---")
    st.markdown("**Layer Details (H1 scores):**")
    for n in range(1, 12):
        sc = detail.get("H1_L{}".format(n), 0.0)
        icon = _icon_txt(sc)
        st.write("{} **L{} - {}**: {} | Score: **{:.1f}**".format(
            icon, n, _LAYER_NAMES[n], _LAYER_DESC[n], sc))

    # Auto-refresh
    if st.sidebar.checkbox("Auto-refresh (60s)", value=False, key="le_auto_refresh"):
        import time
        time.sleep(60)
        if "le_results" in st.session_state:
            del st.session_state["le_results"]
        st.experimental_rerun()
