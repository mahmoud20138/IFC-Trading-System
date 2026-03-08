"""
IFC Dashboard — Full Pair Monitor (Comprehensive)
ONE master table with all info: rates, multi-TF trends, RSI, MACD,
momentum, key levels, volatility, and scored recommendations.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────

def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _trend(df, fast=10, slow=50):
    if df.empty or len(df) < slow:
        return "—"
    return "BULL" if _ema(df["close"], fast).iloc[-1] > _ema(df["close"], slow).iloc[-1] else "BEAR"


def _ema_stack_label(df):
    if df.empty or len(df) < 200:
        return "—"
    e10 = _ema(df["close"], 10).iloc[-1]
    e21 = _ema(df["close"], 21).iloc[-1]
    e50 = _ema(df["close"], 50).iloc[-1]
    e200 = _ema(df["close"], 200).iloc[-1]
    if e10 > e21 > e50 > e200:
        return "STRONG UP"
    if e10 < e21 < e50 < e200:
        return "STRONG DN"
    if e10 > e50:
        return "UP"
    if e10 < e50:
        return "DOWN"
    return "MIXED"


def _rsi(df, p=14):
    if df.empty or len(df) < p + 1:
        return 50.0
    d = df["close"].diff()
    g = d.where(d > 0, 0).rolling(p).mean()
    l = (-d.where(d < 0, 0)).rolling(p).mean()
    rs = g.iloc[-1] / l.iloc[-1] if l.iloc[-1] != 0 else 100
    return round(100 - 100 / (1 + rs), 1)


def _macd_signal(df, fast=12, slow=26, sig=9):
    """Returns (histogram_value, 'BULLISH'/'BEARISH'/'—')."""
    if df.empty or len(df) < slow + sig:
        return 0.0, "—"
    macd_line = _ema(df["close"], fast) - _ema(df["close"], slow)
    signal_line = _ema(macd_line, sig)
    hist = (macd_line - signal_line).iloc[-1]
    return round(float(hist), 6), ("BULLISH" if hist > 0 else "BEARISH")


def _bb_position(df, p=20):
    """Where price sits in Bollinger Bands: 0–100% (0=lower, 100=upper)."""
    if df.empty or len(df) < p:
        return 50.0
    sma = df["close"].rolling(p).mean()
    std = df["close"].rolling(p).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    bw = upper.iloc[-1] - lower.iloc[-1]
    if bw == 0:
        return 50.0
    return round(((df["close"].iloc[-1] - lower.iloc[-1]) / bw) * 100, 1)


def _atr(df, p=14):
    if df.empty or len(df) < p + 1:
        return 0.0
    tr = np.maximum(df["high"] - df["low"],
                    np.maximum(abs(df["high"] - df["close"].shift(1)),
                               abs(df["low"] - df["close"].shift(1))))
    return float(tr.rolling(p).mean().iloc[-1])


def _change_pct(df):
    if df.empty or len(df) < 2:
        return 0.0
    p, c = df["close"].iloc[-2], df["close"].iloc[-1]
    return ((c - p) / p) * 100 if p != 0 else 0.0


def _vol_ratio(df, p=20):
    if df.empty or len(df) < p or "tick_volume" not in df.columns:
        return 1.0
    avg = df["tick_volume"].rolling(p).mean().iloc[-1]
    return round(df["tick_volume"].iloc[-1] / avg, 2) if avg > 0 else 1.0


def _swing_levels(df, lookback=50):
    if df.empty or len(df) < lookback:
        return None, None
    ch = df.tail(lookback)
    return float(ch["low"].min()), float(ch["high"].max())


def _momentum_score(rsi_h1, rsi_m15, macd_dir, bb_pos):
    """Quick momentum score 0-10."""
    score = 5.0
    # RSI contribution
    if rsi_h1 > 60:
        score += 1
    elif rsi_h1 < 40:
        score -= 1
    if rsi_m15 > 65:
        score += 0.5
    elif rsi_m15 < 35:
        score -= 0.5
    # MACD
    if macd_dir == "BULLISH":
        score += 1.5
    elif macd_dir == "BEARISH":
        score -= 1.5
    # BB position
    if bb_pos > 80:
        score += 0.5  # strong momentum up
    elif bb_pos < 20:
        score -= 0.5
    return max(0, min(10, round(score, 1)))


# ─────────────────────────────────────────────────────────────────────
# RECOMMENDATION ENGINE
# ─────────────────────────────────────────────────────────────────────

def _recommend(trends, stack, rsi_h1, rsi_d1, macd_h1, macd_d1, bb_h1, mom):
    """
    Score-based recommendation from all available data.
    Returns (recommendation_str, confidence_pct, direction_str).
    """
    pts = 0  # positive = bullish, negative = bearish

    # TF trend alignment (weighted: W1=3, D1=3, H4=2, H1=1.5, M15=1, M5=0.5)
    weights = {"W1": 3, "D1": 3, "H4": 2, "H1": 1.5, "M15": 1, "M5": 0.5}
    for tf, w in weights.items():
        t = trends.get(tf, "—")
        if t == "BULL":
            pts += w
        elif t == "BEAR":
            pts -= w

    # EMA stack alignment
    if "STRONG UP" in stack:
        pts += 2
    elif "STRONG DN" in stack:
        pts -= 2
    elif stack == "UP":
        pts += 1
    elif stack == "DOWN":
        pts -= 1

    # RSI divergence bonus
    if rsi_h1 > 55 and rsi_d1 > 55:
        pts += 1
    elif rsi_h1 < 45 and rsi_d1 < 45:
        pts -= 1

    # MACD alignment
    if macd_h1 == "BULLISH" and macd_d1 == "BULLISH":
        pts += 2
    elif macd_h1 == "BEARISH" and macd_d1 == "BEARISH":
        pts -= 2

    # Overbought / oversold (caution)
    if rsi_h1 > 75:
        pts -= 0.5  # overbought caution
    elif rsi_h1 < 25:
        pts += 0.5  # oversold bounce potential

    max_pts = 3 + 3 + 2 + 1.5 + 1 + 0.5 + 2 + 1 + 2  # ~16
    confidence = min(100, int(abs(pts) / max_pts * 100))

    if pts >= 10:
        rec, direction = "STRONG BUY", "LONG"
    elif pts >= 6:
        rec, direction = "BUY", "LONG"
    elif pts >= 3:
        rec, direction = "LEAN BUY", "LONG"
    elif pts <= -10:
        rec, direction = "STRONG SELL", "SHORT"
    elif pts <= -6:
        rec, direction = "SELL", "SHORT"
    elif pts <= -3:
        rec, direction = "LEAN SELL", "SHORT"
    else:
        rec, direction = "NEUTRAL", "FLAT"

    return rec, confidence, direction


# ─────────────────────────────────────────────────────────────────────
# FETCH + BUILD ROW
# ─────────────────────────────────────────────────────────────────────

_TF_BARS = {"W1": 60, "D1": 220, "H4": 100, "H1": 100, "M15": 80, "M5": 60}


def _fetch_all(mt5, sym):
    out = {}
    for tf, bars in _TF_BARS.items():
        try:
            out[tf] = mt5.get_ohlcv(sym, tf, bars=bars)
        except Exception:
            out[tf] = pd.DataFrame()
    return out


def _build_row(inst, data, tick, info, pos_count):
    digits = info["digits"] if info else 5
    bid = tick["bid"] if tick else 0
    ask = tick["ask"] if tick else 0
    spread = (ask - bid) / inst.pip_size if tick and inst.pip_size else 0
    price = bid or (float(data["M15"]["close"].iloc[-1]) if not data.get("M15", pd.DataFrame()).empty else 0)

    df_w = data.get("W1", pd.DataFrame())
    df_d = data.get("D1", pd.DataFrame())
    df_h4 = data.get("H4", pd.DataFrame())
    df_h1 = data.get("H1", pd.DataFrame())
    df_m15 = data.get("M15", pd.DataFrame())
    df_m5 = data.get("M5", pd.DataFrame())

    # Trends
    trends = {}
    for tf, df_tf in [("W1", df_w), ("D1", df_d), ("H4", df_h4), ("H1", df_h1), ("M15", df_m15), ("M5", df_m5)]:
        trends[tf] = _trend(df_tf)

    stack = _ema_stack_label(df_d)

    # RSI
    rsi_d1 = _rsi(df_d)
    rsi_h4 = _rsi(df_h4)
    rsi_h1 = _rsi(df_h1)
    rsi_m15 = _rsi(df_m15)

    # MACD
    macd_d1_val, macd_d1_dir = _macd_signal(df_d)
    macd_h1_val, macd_h1_dir = _macd_signal(df_h1)

    # Bollinger
    bb_h1 = _bb_position(df_h1)

    # ATR
    atr_d = _atr(df_d)
    atr_h1 = _atr(df_h1)

    # Changes
    day_chg = _change_pct(df_d)
    h4_chg = _change_pct(df_h4)

    # Volume
    vol_m15 = _vol_ratio(df_m15)

    # Levels
    d1_low, d1_high = _swing_levels(df_d)
    h4_low, h4_high = _swing_levels(df_h4, 30)

    # O/H/L/C (D1)
    d1_open = float(df_d["open"].iloc[-1]) if not df_d.empty else 0
    d1_high_bar = float(df_d["high"].iloc[-1]) if not df_d.empty else 0
    d1_low_bar = float(df_d["low"].iloc[-1]) if not df_d.empty else 0
    d1_close = float(df_d["close"].iloc[-1]) if not df_d.empty else 0

    # Momentum
    mom = _momentum_score(rsi_h1, rsi_m15, macd_h1_dir, bb_h1)

    # Recommendation
    rec, conf, direction = _recommend(trends, stack, rsi_h1, rsi_d1, macd_h1_dir, macd_d1_dir, bb_h1, mom)

    is_fx = inst.category == "forex"
    fmt = f".{digits}f"

    return {
        # Identity
        "Symbol": inst.display_name,
        "Cat": inst.category[:3].upper(),
        # Rates
        "Bid": f"{bid:{fmt}}" if bid else "—",
        "Ask": f"{ask:{fmt}}" if ask else "—",
        "Spread": f"{spread:.1f}",
        # D1 OHLC
        "D1 Open": f"{d1_open:{fmt}}",
        "D1 High": f"{d1_high_bar:{fmt}}",
        "D1 Low": f"{d1_low_bar:{fmt}}",
        "D1 Close": f"{d1_close:{fmt}}",
        "Day %": f"{day_chg:+.2f}%",
        "H4 %": f"{h4_chg:+.2f}%",
        # TF Trends
        "W1": trends["W1"],
        "D1": trends["D1"],
        "H4": trends["H4"],
        "H1": trends["H1"],
        "M15": trends["M15"],
        "M5": trends["M5"],
        # Structure
        "D1 Stack": stack,
        # RSI
        "RSI D1": rsi_d1,
        "RSI H4": rsi_h4,
        "RSI H1": rsi_h1,
        "RSI M15": rsi_m15,
        # MACD
        "MACD D1": macd_d1_dir,
        "MACD H1": macd_h1_dir,
        # Bollinger
        "BB% H1": bb_h1,
        # Momentum
        "Mom": mom,
        # Volatility
        "ATR D1": f"{atr_d:.{5 if is_fx else 2}f}",
        "ATR H1": f"{atr_h1:.{5 if is_fx else 2}f}",
        "Vol x": vol_m15,
        # Key levels
        "Swing Lo": f"{d1_low:.{digits}f}" if d1_low else "—",
        "Swing Hi": f"{d1_high:.{digits}f}" if d1_high else "—",
        "H4 Lo": f"{h4_low:.{digits}f}" if h4_low else "—",
        "H4 Hi": f"{h4_high:.{digits}f}" if h4_high else "—",
        # Positions
        "Pos": pos_count,
        # RECOMMENDATION
        "Rec": rec,
        "Conf %": conf,
        "Dir": direction,
        # hidden numerics for sorting
        "_conf": conf,
        "_day_chg": day_chg,
        "_rsi_h1": rsi_h1,
        "_mom": mom,
    }


# ─────────────────────────────────────────────────────────────────────
# PAGE
# ─────────────────────────────────────────────────────────────────────

def render():
    st.title("📊 Full Pair Monitor — Rates & Recommendations")

    try:
        from config.instruments import get_active_instruments
        from data.mt5_connector import MT5Connector
    except ImportError as e:
        st.error(f"Import error: {e}")
        return

    mt5 = MT5Connector()
    try:
        mt5.connect()
    except Exception as e:
        st.error(f"MT5 connection failed: {e}")
        return

    instruments = get_active_instruments()

    # ── Controls ─────────────────────────────────────────────────────
    c1, c2 = st.columns([4, 1])
    with c1:
        cat_filter = st.radio(
            "Filter",
            ["ALL", "FOREX", "INDEX", "COMMODITY", "CRYPTO", "STOCK"],
            horizontal=True,
        )
    with c2:
        refresh = st.button("Refresh All Data")

    if cat_filter != "ALL":
        instruments = [i for i in instruments if i.category.upper() == cat_filter]

    # ── Load ─────────────────────────────────────────────────────────
    need_load = refresh or "fm2_rows" not in st.session_state

    if need_load:
        # Batch positions once
        pos_map = {}
        try:
            all_pos = mt5.get_open_positions() or []
            for p in all_pos:
                s = p.get("symbol", "")
                pos_map[s] = pos_map.get(s, 0) + 1
        except Exception:
            pass

        total = len(instruments)
        progress = st.progress(0)
        status = st.empty()

        rows = []
        for idx, inst in enumerate(instruments):
            sym = inst.mt5_symbol
            status.text(f"Loading {inst.display_name} ({idx+1}/{total})")

            tick = mt5.get_current_tick(sym)
            info = mt5.get_symbol_info(sym)
            data = _fetch_all(mt5, sym)
            row = _build_row(inst, data, tick, info, pos_map.get(sym, 0))
            rows.append(row)

            progress.progress((idx + 1) / total)

        progress.empty()
        status.empty()

        st.session_state["fm2_rows"] = rows
        st.session_state["fm2_time"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    rows = st.session_state.get("fm2_rows", [])
    scan_time = st.session_state.get("fm2_time", "—")

    if not rows:
        st.info("Click **Refresh All Data** to load.")
        return

    # Apply category filter to cached results
    if cat_filter != "ALL":
        rows = [r for r in rows if r.get("Cat", "") == cat_filter[:3].upper()]

    st.caption(f"Last update: {scan_time} | {len(rows)} pairs")

    # ── SIGNAL SUMMARY ───────────────────────────────────────────────
    recs = [r.get("Rec", "—") for r in rows]
    sb = sum(1 for x in recs if x == "STRONG BUY")
    b = sum(1 for x in recs if x == "BUY")
    lb = sum(1 for x in recs if x == "LEAN BUY")
    n = sum(1 for x in recs if x == "NEUTRAL")
    ls = sum(1 for x in recs if x == "LEAN SELL")
    s = sum(1 for x in recs if x == "SELL")
    ss = sum(1 for x in recs if x == "STRONG SELL")

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Strong Buy", sb)
    m2.metric("Buy", b)
    m3.metric("Lean Buy", lb)
    m4.metric("Neutral", n)
    m5.metric("Lean Sell", ls)
    m6.metric("Sell", s)
    m7.metric("Strong Sell", ss)

    st.markdown("---")

    # ── MASTER TABLE — EVERYTHING ────────────────────────────────────
    st.subheader("Complete Overview — All Pairs")

    master_cols = [
        "Symbol", "Cat", "Rec", "Dir", "Conf %",
        "Bid", "Ask", "Spread",
        "W1", "D1", "H4", "H1", "M15", "M5",
        "D1 Stack",
        "RSI D1", "RSI H4", "RSI H1", "RSI M15",
        "MACD D1", "MACD H1", "BB% H1", "Mom",
        "Day %", "H4 %",
        "D1 Open", "D1 High", "D1 Low", "D1 Close",
        "ATR D1", "ATR H1", "Vol x",
        "Swing Lo", "Swing Hi", "H4 Lo", "H4 Hi",
        "Pos",
    ]
    df = pd.DataFrame(rows)
    available = [c for c in master_cols if c in df.columns]
    st.dataframe(df[available])

    st.markdown("---")

    # ── TREND HEATMAP ────────────────────────────────────────────────
    st.subheader("Trend Alignment")
    heat = []
    for r in rows:
        hr = {"Symbol": r["Symbol"], "Rec": r["Rec"]}
        for tf in ["W1", "D1", "H4", "H1", "M15", "M5"]:
            t = r.get(tf, "—")
            hr[tf] = ("🟢" if t == "BULL" else "🔴") if t in ("BULL", "BEAR") else "⚪"
        hr["Stack"] = r.get("D1 Stack", "—")
        hr["MACD D1"] = r.get("MACD D1", "—")
        hr["MACD H1"] = r.get("MACD H1", "—")
        heat.append(hr)
    st.dataframe(pd.DataFrame(heat))

    st.markdown("---")

    # ── TOP RECOMMENDATIONS ──────────────────────────────────────────
    st.subheader("Top Recommendations")

    buys = sorted([r for r in rows if r.get("Dir") == "LONG"], key=lambda x: -x["_conf"])
    sells = sorted([r for r in rows if r.get("Dir") == "SHORT"], key=lambda x: -x["_conf"])

    bc, sc = st.columns(2)
    with bc:
        st.markdown("**Bullish**")
        for r in buys[:10]:
            conf = r["_conf"]
            bar = "█" * (conf // 10) + "░" * (10 - conf // 10)
            st.write(
                f"{'🟢' if conf >= 50 else '🔵'} **{r['Symbol']}** — {r['Rec']} "
                f"({conf}%) `{bar}` | "
                f"D1:{r['D1']} H4:{r['H4']} H1:{r['H1']} | RSI:{r['_rsi_h1']}"
            )
        if not buys:
            st.info("No bullish setups")

    with sc:
        st.markdown("**Bearish**")
        for r in sells[:10]:
            conf = r["_conf"]
            bar = "█" * (conf // 10) + "░" * (10 - conf // 10)
            st.write(
                f"{'🔴' if conf >= 50 else '🟠'} **{r['Symbol']}** — {r['Rec']} "
                f"({conf}%) `{bar}` | "
                f"D1:{r['D1']} H4:{r['H4']} H1:{r['H1']} | RSI:{r['_rsi_h1']}"
            )
        if not sells:
            st.info("No bearish setups")

    st.markdown("---")

    # ── RSI + MOMENTUM TABLE ─────────────────────────────────────────
    st.subheader("RSI & Momentum")
    rsi_rows = []
    for r in rows:
        rh1 = r.get("RSI H1", 50)
        rm15 = r.get("RSI M15", 50)
        rd1 = r.get("RSI D1", 50)
        zone_h1 = "OB" if rh1 > 70 else ("OS" if rh1 < 30 else "—")
        zone_d1 = "OB" if rd1 > 70 else ("OS" if rd1 < 30 else "—")
        rsi_rows.append({
            "Symbol": r["Symbol"],
            "RSI D1": rd1, "D1 Zone": zone_d1,
            "RSI H4": r.get("RSI H4", 50),
            "RSI H1": rh1, "H1 Zone": zone_h1,
            "RSI M15": rm15,
            "MACD D1": r.get("MACD D1", "—"),
            "MACD H1": r.get("MACD H1", "—"),
            "BB% H1": r.get("BB% H1", 50),
            "Mom": r.get("Mom", 5),
        })
    st.dataframe(pd.DataFrame(rsi_rows))

    st.markdown("---")

    # ── RATES + LEVELS TABLE ─────────────────────────────────────────
    st.subheader("Rates & Key Levels")
    rate_rows = []
    for r in rows:
        rate_rows.append({
            "Symbol": r["Symbol"],
            "Bid": r["Bid"], "Ask": r["Ask"], "Spread": r["Spread"],
            "D1 Open": r["D1 Open"], "D1 High": r["D1 High"],
            "D1 Low": r["D1 Low"], "D1 Close": r["D1 Close"],
            "Day %": r["Day %"], "H4 %": r["H4 %"],
            "ATR D1": r["ATR D1"], "ATR H1": r["ATR H1"],
            "Swing Lo": r["Swing Lo"], "Swing Hi": r["Swing Hi"],
            "H4 Lo": r["H4 Lo"], "H4 Hi": r["H4 Hi"],
            "Vol x": r["Vol x"],
        })
    st.dataframe(pd.DataFrame(rate_rows))

    st.markdown("---")

    # ── DRILL-DOWN ───────────────────────────────────────────────────
    st.subheader("Pair Detail")
    sym_names = [r["Symbol"] for r in rows]
    selected = st.selectbox("Select pair", sym_names)
    d = next((r for r in rows if r["Symbol"] == selected), None)
    if d:
        # Recommendation banner
        rec = d.get("Rec", "—")
        conf = d.get("Conf %", 0)
        direction = d.get("Dir", "—")
        if "BUY" in rec or "LONG" in direction:
            st.success(f"**{rec}** — Direction: **{direction}** — Confidence: **{conf}%**")
        elif "SELL" in rec or "SHORT" in direction:
            st.error(f"**{rec}** — Direction: **{direction}** — Confidence: **{conf}%**")
        else:
            st.info(f"**{rec}** — Direction: **{direction}** — Confidence: **{conf}%**")

        # Rates
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Bid", d["Bid"])
        r2.metric("Ask", d["Ask"])
        r3.metric("Spread", d["Spread"])
        r4.metric("Positions", d["Pos"])

        # OHLC
        o1, o2, o3, o4, o5 = st.columns(5)
        o1.metric("D1 Open", d["D1 Open"])
        o2.metric("D1 High", d["D1 High"])
        o3.metric("D1 Low", d["D1 Low"])
        o4.metric("D1 Close", d["D1 Close"])
        o5.metric("Day %", d["Day %"])

        # TF trends
        st.markdown("**Timeframe Trends:**")
        tc = st.columns(6)
        for i, tf in enumerate(["W1", "D1", "H4", "H1", "M15", "M5"]):
            tc[i].metric(tf, d.get(tf, "—"))

        # Structure + indicators
        st.markdown("**Indicators:**")
        ic = st.columns(6)
        ic[0].metric("D1 Stack", d.get("D1 Stack", "—"))
        ic[1].metric("MACD D1", d.get("MACD D1", "—"))
        ic[2].metric("MACD H1", d.get("MACD H1", "—"))
        ic[3].metric("BB% H1", d.get("BB% H1", "—"))
        ic[4].metric("Mom Score", d.get("Mom", "—"))
        ic[5].metric("Vol x", d.get("Vol x", "—"))

        # RSI
        st.markdown("**RSI:**")
        rc = st.columns(4)
        rc[0].metric("RSI D1", d.get("RSI D1", "—"))
        rc[1].metric("RSI H4", d.get("RSI H4", "—"))
        rc[2].metric("RSI H1", d.get("RSI H1", "—"))
        rc[3].metric("RSI M15", d.get("RSI M15", "—"))

        # Key levels
        st.markdown("**Key Levels:**")
        lc = st.columns(4)
        lc[0].metric("D1 Swing Low", d.get("Swing Lo", "—"))
        lc[1].metric("D1 Swing High", d.get("Swing Hi", "—"))
        lc[2].metric("H4 Low", d.get("H4 Lo", "—"))
        lc[3].metric("H4 High", d.get("H4 Hi", "—"))

        # ATR
        ac = st.columns(2)
        ac[0].metric("ATR D1", d.get("ATR D1", "—"))
        ac[1].metric("ATR H1", d.get("ATR H1", "—"))

    # ── Auto-refresh ─────────────────────────────────────────────────
    if st.sidebar.checkbox("Auto-refresh (45s)", value=False):
        import time
        time.sleep(45)
        if "fm2_rows" in st.session_state:
            del st.session_state["fm2_rows"]
        st.experimental_rerun()
