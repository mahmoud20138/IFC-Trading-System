"""
IFC Dashboard — Command Center (Fast)
All symbols monitored with live prices, spreads, trend, and quick grades.
Optimised: single D1 fetch per symbol, batch positions, progress bar.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time as _time


def render():
    st.title("🎯 Command Center — All Symbols")

    try:
        from config.instruments import INSTRUMENTS, get_active_instruments
        from data.mt5_connector import MT5Connector
        from utils.helpers import current_killzone, now_est, is_lunch_break
    except ImportError as e:
        st.error(f"Import error: {e}")
        return

    # ── Connect MT5 ──────────────────────────────────────────────────
    mt5 = MT5Connector()
    try:
        mt5.connect()
    except Exception as e:
        st.error(f"MT5 connection failed: {e}")
        return

    # ── Controls ─────────────────────────────────────────────────────
    c1, c2 = st.columns([3, 1])
    with c1:
        cat_filter = st.radio("Filter", ["ALL", "FOREX", "INDEX", "COMMODITY", "CRYPTO", "STOCK"], horizontal=True)
    with c2:
        refresh_btn = st.button("Refresh")

    # Use cached data unless refresh clicked
    need_load = refresh_btn or "cc_rows" not in st.session_state

    if need_load:
        # ── Account bar (fast — single MT5 call) ────────────────────
        acct = mt5.get_account_info()
        st.session_state["cc_acct"] = acct

        # ── Batch: get ALL open positions once ───────────────────────
        all_pos = []
        try:
            all_pos = mt5.get_open_positions() or []
        except Exception:
            pass
        st.session_state["cc_positions"] = all_pos

        # Count positions per symbol
        pos_map = {}
        for p in all_pos:
            s = p.get("symbol", "")
            pos_map[s] = pos_map.get(s, 0) + 1

        # ── Build symbol table with progress ─────────────────────────
        instruments = get_active_instruments()
        total = len(instruments)
        progress = st.progress(0)
        status = st.empty()

        rows = []
        for idx, inst in enumerate(instruments):
            sym = inst.mt5_symbol
            status.text(f"Loading {inst.display_name} ({idx+1}/{total})")

            # Tick (fast — cached by MT5)
            tick = mt5.get_current_tick(sym)
            info = mt5.get_symbol_info(sym)
            digits = info["digits"] if info else 5

            bid = tick["bid"] if tick else 0
            ask = tick["ask"] if tick else 0
            spread_pts = (ask - bid) / inst.pip_size if tick and inst.pip_size else 0

            # ONE D1 fetch → derive daily change + ATR
            daily_chg = 0.0
            atr_val = 0.0
            try:
                df_d = mt5.get_ohlcv(sym, "D1", bars=20)
                if not df_d.empty and len(df_d) >= 2:
                    prev_c = df_d["close"].iloc[-2]
                    cur_c = df_d["close"].iloc[-1]
                    if prev_c != 0:
                        daily_chg = ((cur_c - prev_c) / prev_c) * 100
                if not df_d.empty and len(df_d) >= 15:
                    tr = np.maximum(
                        df_d["high"] - df_d["low"],
                        np.maximum(
                            abs(df_d["high"] - df_d["close"].shift(1)),
                            abs(df_d["low"] - df_d["close"].shift(1)),
                        ),
                    )
                    atr_val = float(tr.rolling(14).mean().iloc[-1])
            except Exception:
                pass

            # ONE H1 fetch → EMA trend
            trend_str = "—"
            try:
                df_h1 = mt5.get_ohlcv(sym, "H1", bars=60)
                if not df_h1.empty and len(df_h1) >= 50:
                    e10 = df_h1["close"].ewm(span=10, adjust=False).mean().iloc[-1]
                    e50 = df_h1["close"].ewm(span=50, adjust=False).mean().iloc[-1]
                    trend_str = "BULL" if e10 > e50 else "BEAR"
            except Exception:
                pass

            rows.append({
                "Symbol": inst.display_name,
                "MT5": sym,
                "Category": inst.category.upper(),
                "Bid": f"{bid:.{digits}f}" if tick else "—",
                "Ask": f"{ask:.{digits}f}" if tick else "—",
                "Spread": f"{spread_pts:.1f}",
                "Trend (H1)": trend_str,
                "Daily %": f"{daily_chg:+.2f}%",
                "ATR (D1)": f"{atr_val:.{2 if inst.category == 'forex' else 0}f}",
                "Positions": pos_map.get(sym, 0),
            })
            progress.progress((idx + 1) / total)

        status.text(f"Loaded {total} symbols.")
        progress.empty()
        status.empty()

        st.session_state["cc_rows"] = rows
        st.session_state["cc_time"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    # ── Display ──────────────────────────────────────────────────────
    acct = st.session_state.get("cc_acct", {})
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric("Balance", f"${acct.get('balance', 0):,.2f}")
    a2.metric("Equity", f"${acct.get('equity', 0):,.2f}")
    a3.metric("Free Margin", f"${acct.get('free_margin', 0):,.2f}")
    floating = acct.get('equity', 0) - acct.get('balance', 0)
    a4.metric("Float P&L", f"${floating:+,.2f}")
    a5.metric("Leverage", f"1:{acct.get('leverage', 0)}")
    kz = "—"
    try:
        kz = current_killzone() or "Off-Session"
    except Exception:
        pass
    a6.metric("Killzone", kz)

    st.caption(f"Last refresh: {st.session_state.get('cc_time', '—')}")
    st.markdown("---")

    # ── Symbol table ─────────────────────────────────────────────────
    df_overview = pd.DataFrame(st.session_state.get("cc_rows", []))
    if not df_overview.empty:
        if cat_filter != "ALL":
            df_overview = df_overview[df_overview["Category"] == cat_filter]
        st.dataframe(df_overview)
    else:
        st.info("No data — click **Refresh**.")

    st.markdown("---")

    # ── Open Positions ───────────────────────────────────────────────
    st.subheader("Open Positions")
    all_pos = st.session_state.get("cc_positions", [])
    if all_pos:
        pos_df = pd.DataFrame(all_pos)
        display_cols = [
            "ticket", "symbol", "type", "volume", "open_price",
            "current_price", "sl", "tp", "profit", "swap", "comment",
        ]
        available = [c for c in display_cols if c in pos_df.columns]
        st.dataframe(pos_df[available])

        total_pnl = sum(p.get("profit", 0) for p in all_pos)
        total_swap = sum(p.get("swap", 0) for p in all_pos)
        p1, p2, p3 = st.columns(3)
        p1.metric("Total Float P&L", f"${total_pnl:+,.2f}")
        p2.metric("Total Swap", f"${total_swap:+,.2f}")
        p3.metric("Total Positions", str(len(all_pos)))
    else:
        st.info("No open positions")

    st.markdown("---")

    # ── Intermarket Snapshot (only on explicit click — slow yfinance) ─
    st.subheader("Intermarket Overview")
    if st.button("Load Intermarket"):
        with st.spinner("Fetching macro data (DXY, VIX, yields...)"):
            try:
                from data.intermarket import IntermarketData
                im = IntermarketData()
                snap = im.get_full_snapshot()
                st.session_state["cc_intermarket"] = snap
            except Exception as e:
                st.warning(f"Intermarket unavailable: {e}")

    snap = st.session_state.get("cc_intermarket")
    if snap:
        im_rows = []
        for k, v in snap.items():
            if isinstance(v, dict) and "level" in v:
                im_rows.append({
                    "Ticker": k,
                    "Level": v.get("level", "N/A"),
                    "Direction": v.get("direction", "N/A"),
                    "Change %": v.get("change_pct", "N/A"),
                })
        if im_rows:
            st.dataframe(pd.DataFrame(im_rows))
    else:
        st.info("Click **Load Intermarket** to fetch macro data.")

    # ── Auto-refresh ─────────────────────────────────────────────────
    if st.sidebar.checkbox("Auto-refresh (30s)", value=False):
        _time.sleep(30)
        if "cc_rows" in st.session_state:
            del st.session_state["cc_rows"]
        st.experimental_rerun()
