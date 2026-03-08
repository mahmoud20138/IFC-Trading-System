"""
IFC Dashboard — Multi-TF Scanner (Fast)
Runs 8-layer analysis on ALL active symbols across multiple timeframes.
Auto-scans on page load. Pre-fetches intermarket once, batches MT5 data.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    if df.empty or len(df) < period + 1:
        return 0.0
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift(1)),
            abs(df["low"] - df["close"].shift(1)),
        ),
    )
    return float(tr.rolling(period).mean().iloc[-1])


def _grade_emoji(grade: str) -> str:
    return {"A+": "🟢 A+", "A": "🔵 A", "B": "🟡 B"}.get(grade, "⚪ —")


def _direction_emoji(d: str) -> str:
    return {"LONG": "⬆ LONG", "SHORT": "⬇ SHORT"}.get(d, "↔ NEUTRAL")


def _ema_trend(df: pd.DataFrame, fast: int = 10, slow: int = 50) -> str:
    if df.empty or len(df) < slow:
        return "—"
    ema_f = df["close"].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_s = df["close"].ewm(span=slow, adjust=False).mean().iloc[-1]
    return "BULL" if ema_f > ema_s else "BEAR"


# ─────────────────────────────────────────────────────────────────────
# FAST PREFETCH — grab all TF data for one symbol in a batch
# ─────────────────────────────────────────────────────────────────────

_TF_BARS = [("W1", 60), ("D1", 100), ("H4", 100), ("H1", 80), ("M15", 80)]

def _prefetch_symbol_data(mt5, sym):
    """Fetch all timeframe data for one symbol. Returns dict[tf] -> DataFrame."""
    data = {}
    for tf, bars in _TF_BARS:
        try:
            data[tf] = mt5.get_ohlcv(sym, tf, bars=bars)
        except Exception:
            data[tf] = pd.DataFrame()
    return data


# ─────────────────────────────────────────────────────────────────────
# FAST ANALYSIS — one symbol, pre-fetched data + shared snapshot
# ─────────────────────────────────────────────────────────────────────

def _analyze_fast(inst, data, im, snapshot):
    """Run 8-layer analysis using pre-fetched data & shared snapshot."""
    from analysis.layer1_intermarket import IntermarketLayer
    from analysis.layer2_trend import TrendLayer
    from analysis.layer3_volume_profile import VolumeProfileLayer, compute_volume_profile
    from analysis.layer4_candle_density import CandleDensityLayer
    from analysis.layer5_liquidity import LiquidityLayer
    from analysis.layer6_fvg_ob import FVGOrderBlockLayer
    from analysis.layer7_order_flow import OrderFlowLayer
    from analysis.layer8_killzone import KillzoneLayer
    from analysis.confluence_scorer import ConfluenceScorer

    sym = inst.mt5_symbol
    result = {"symbol": inst.display_name, "mt5_symbol": sym, "category": inst.category}

    df_w  = data.get("W1",  pd.DataFrame())
    df_d  = data.get("D1",  pd.DataFrame())
    df_4h = data.get("H4",  pd.DataFrame())
    df_1h = data.get("H1",  pd.DataFrame())
    df_15m = data.get("M15", pd.DataFrame())

    # Current price — first non-empty frame
    current_price = None
    for frame in [df_15m, df_1h, df_4h, df_d]:
        if not frame.empty:
            current_price = float(frame["close"].iloc[-1])
            break
    if current_price is None:
        result["error"] = "No data"
        return result
    result["price"] = current_price

    # Per-TF trends
    for tf_name, df_tf in [("W1", df_w), ("D1", df_d), ("H4", df_4h), ("H1", df_1h), ("M15", df_15m)]:
        result[f"trend_{tf_name}"] = _ema_trend(df_tf)

    signals = []

    # L1 — Intermarket (re-uses shared snapshot)
    try:
        sig = IntermarketLayer(im).analyze(inst, snapshot)
        signals.append(sig); result["L1"] = sig.score
    except Exception:
        result["L1"] = 0.0

    # L2 — Trend
    try:
        w = df_w if not df_w.empty else df_d
        sig = TrendLayer().analyze(w, df_d, df_4h)
        signals.append(sig); result["L2"] = sig.score
    except Exception:
        result["L2"] = 0.0

    # L3 — Volume Profile
    vp = None
    try:
        vp = compute_volume_profile(df_d)
        sig = VolumeProfileLayer().analyze(current_price=current_price, composite_profile=vp)
        signals.append(sig); result["L3"] = sig.score
    except Exception:
        result["L3"] = 0.0

    # L4 — Candle Density
    try:
        hvn = list(vp.hvn) if vp else []
        lvn = list(vp.lvn) if vp else []
        sig = CandleDensityLayer().analyze(df_d, vp_hvn=hvn, vp_lvn=lvn, current_price=current_price)
        signals.append(sig); result["L4"] = sig.score
    except Exception:
        result["L4"] = 0.0

    # L5 — Liquidity
    try:
        sig = LiquidityLayer().analyze(df_d, atr=_compute_atr(df_d), current_price=current_price)
        signals.append(sig); result["L5"] = sig.score
    except Exception:
        result["L5"] = 0.0

    # L6 — FVG / OB
    try:
        sig = FVGOrderBlockLayer().analyze(df_1h, atr=_compute_atr(df_1h), current_price=current_price, trade_direction="NEUTRAL")
        signals.append(sig); result["L6"] = sig.score
    except Exception:
        result["L6"] = 0.0

    # L7 — Order Flow
    try:
        sig = OrderFlowLayer().analyze(df_15m, trade_direction="NEUTRAL")
        signals.append(sig); result["L7"] = sig.score
    except Exception:
        result["L7"] = 0.0

    # L8 — Killzone
    try:
        sig = KillzoneLayer().analyze(sym)
        signals.append(sig); result["L8"] = sig.score
    except Exception:
        result["L8"] = 0.0

    # Confluence
    try:
        conf = ConfluenceScorer().score(signals)
        result["grade"]         = conf.get("grade", "—")
        result["direction"]     = conf.get("direction", "NEUTRAL")
        result["layers_passed"] = conf.get("layers_passed", 0)
        result["avg_score"]     = conf.get("avg_score", 0)
        result["tradeable"]     = conf.get("tradeable", False)
    except Exception:
        result.update(grade="—", direction="NEUTRAL", layers_passed=0, avg_score=0, tradeable=False)

    return result


# ─────────────────────────────────────────────────────────────────────
# PAGE RENDER
# ─────────────────────────────────────────────────────────────────────

def render():
    st.title("📡 Multi-TF Scanner — All Symbols")

    try:
        from config.instruments import get_active_instruments
        from data.mt5_connector import MT5Connector
        from data.intermarket import IntermarketData
    except ImportError as e:
        st.error(f"Import error: {e}")
        return

    mt5 = MT5Connector()
    try:
        mt5.connect()
    except Exception as e:
        st.error(f"MT5 connection failed: {e}")
        return

    im = IntermarketData()
    all_instruments = get_active_instruments()

    # ── Controls ─────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        cat_filter = st.radio(
            "Filter",
            ["ALL", "FOREX", "INDEX", "COMMODITY", "CRYPTO", "STOCK"],
            horizontal=True,
        )
    with c2:
        scan_btn = st.button("Rescan Now")
    with c3:
        auto_scan = st.checkbox("Auto-scan", value=True)

    instruments = all_instruments
    if cat_filter != "ALL":
        instruments = [i for i in instruments if i.category.upper() == cat_filter]

    # ── Decide whether to scan ───────────────────────────────────────
    need_scan = scan_btn
    if auto_scan and "scanner_results" not in st.session_state:
        need_scan = True          # auto-scan on first load

    if not need_scan and "scanner_results" not in st.session_state:
        st.info("Click **Rescan Now** or enable **Auto-scan** to run 8-layer analysis.")
        return

    # ── RUN SCAN ─────────────────────────────────────────────────────
    if need_scan:
        progress = st.progress(0)
        status = st.empty()
        total = len(instruments)

        # 1) Pre-fetch intermarket snapshot ONCE (biggest yfinance cost)
        status.text("Fetching intermarket data...")
        try:
            snapshot = im.get_full_snapshot()
        except Exception:
            snapshot = {}
        progress.progress(0.05)

        # 2) Pre-fetch all MT5 OHLCV data (sequential — MT5 API is single-threaded)
        all_data = {}
        for idx, inst in enumerate(instruments):
            status.text(f"Fetching data: {inst.display_name} ({idx+1}/{total})")
            all_data[inst.mt5_symbol] = _prefetch_symbol_data(mt5, inst.mt5_symbol)
            progress.progress(0.05 + 0.55 * (idx + 1) / total)

        # 3) Run analysis per symbol (CPU-bound, fast with pre-fetched data)
        all_results = []
        for idx, inst in enumerate(instruments):
            status.text(f"Analyzing: {inst.display_name} ({idx+1}/{total})")
            try:
                r = _analyze_fast(inst, all_data[inst.mt5_symbol], im, snapshot)
                all_results.append(r)
            except Exception as e:
                all_results.append({
                    "symbol": inst.display_name, "mt5_symbol": inst.mt5_symbol,
                    "category": inst.category, "error": str(e), "grade": "—",
                })
            progress.progress(0.60 + 0.40 * (idx + 1) / total)

        progress.progress(1.0)
        status.text(f"Scan complete — {len(all_results)} symbols analysed.")
        st.session_state["scanner_results"] = all_results
        st.session_state["scanner_time"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    # ── DISPLAY ──────────────────────────────────────────────────────
    results = st.session_state.get("scanner_results", [])
    scan_time = st.session_state.get("scanner_time", "—")
    if not results:
        return

    # Apply category filter to display
    if cat_filter != "ALL":
        results = [r for r in results if r.get("category", "").upper() == cat_filter]

    st.caption(f"Last scan: {scan_time} | {len(results)} symbols")
    st.markdown("---")

    # ── TRADEABLE SETUPS (top priority) ──────────────────────────────
    tradeable = [r for r in results if r.get("tradeable")]
    if tradeable:
        st.subheader(f"Tradeable Setups ({len(tradeable)})")
        for r in sorted(tradeable, key=lambda x: x.get("avg_score", 0), reverse=True):
            st.success(
                f"**{r['symbol']}** — Grade: **{r.get('grade','—')}** | "
                f"Dir: **{r.get('direction','—')}** | "
                f"Score: **{r.get('avg_score',0):.1f}** | "
                f"Passed: **{r.get('layers_passed',0)}/8**"
            )
        st.markdown("---")
    else:
        st.info("No tradeable setups in current scan.")

    # ── OVERVIEW TABLE ───────────────────────────────────────────────
    st.subheader("Overview")
    rows = []
    for r in results:
        if "error" in r and "price" not in r:
            continue
        is_fx = r.get("category") == "forex"
        price_fmt = (f"{r['price']:.5f}" if is_fx else f"{r['price']:.2f}") if "price" in r else "—"
        row = {
            "Symbol": r.get("symbol", "?"),
            "Cat": r.get("category", "?")[:3].upper(),
            "Price": price_fmt,
            "Grade": _grade_emoji(r.get("grade", "—")),
            "Dir": _direction_emoji(r.get("direction", "NEUTRAL")),
            "Pass": f"{r.get('layers_passed', 0)}/8",
            "Score": f"{r.get('avg_score', 0):.1f}",
            "Trade?": "YES" if r.get("tradeable") else "",
        }
        for tf in ["W1", "D1", "H4", "H1", "M15"]:
            row[tf] = r.get(f"trend_{tf}", "—")
        rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows))
    st.markdown("---")

    # ── LAYER HEATMAP ────────────────────────────────────────────────
    st.subheader("Layer Scores")
    heat = []
    for r in results:
        row = {"Symbol": r.get("symbol", "?")}
        for n in range(1, 9):
            s = r.get(f"L{n}", 0)
            mark = " ✓" if s >= 7 else (" ~" if s >= 5 else " ✗")
            row[f"L{n}"] = f"{s:.1f}{mark}"
        row["Avg"] = f"{r.get('avg_score', 0):.1f}"
        row["Grade"] = r.get("grade", "—")
        heat.append(row)
    if heat:
        st.dataframe(pd.DataFrame(heat))
    st.markdown("---")

    # ── DETAIL DRILL-DOWN ────────────────────────────────────────────
    st.subheader("Symbol Detail")
    sym_names = [r.get("symbol", "?") for r in results]
    if not sym_names:
        return
    selected = st.selectbox("Select symbol", sym_names)
    detail = next((r for r in results if r.get("symbol") == selected), None)
    if detail:
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Grade", _grade_emoji(detail.get("grade", "—")))
        d2.metric("Direction", detail.get("direction", "—"))
        d3.metric("Passed", f"{detail.get('layers_passed', 0)}/8")
        d4.metric("Avg Score", f"{detail.get('avg_score', 0):.1f}/10")

        st.markdown("**Trend by Timeframe:**")
        tc = st.columns(5)
        for i, tf in enumerate(["W1", "D1", "H4", "H1", "M15"]):
            tc[i].metric(tf, detail.get(f"trend_{tf}", "—"))

        st.markdown("**Layer Scores:**")
        lc = st.columns(8)
        names = ["Intermkt", "Trend", "VolProf", "Density", "Liquid", "FVG/OB", "OrdFlow", "KillZn"]
        for i in range(8):
            lc[i].metric(names[i], f"{detail.get(f'L{i+1}', 0):.1f}")

    # ── Auto-refresh ─────────────────────────────────────────────────
    auto_refresh = st.sidebar.checkbox("Auto-refresh scanner (60s)", value=False)
    if auto_refresh:
        import time
        time.sleep(60)
        if "scanner_results" in st.session_state:
            del st.session_state["scanner_results"]
        st.experimental_rerun()
