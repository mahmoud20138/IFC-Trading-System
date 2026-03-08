"""
IFC Dashboard — Live Monitor Page
Real-time overview of open positions, market state, and alerts.
"""

import streamlit as st
import pandas as pd
from datetime import datetime


def render():
    st.title("🔴 Live Monitor")

    # ── Top metrics row ──────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    try:
        from data.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        mt5.connect()
        acct = mt5.get_account_info()

        col1.metric("Balance", f"${acct.get('balance', 0):,.2f}")
        col2.metric("Equity", f"${acct.get('equity', 0):,.2f}")
        col3.metric("Free Margin", f"${acct.get('margin_free', 0):,.2f}")
        col4.metric(
            "Floating P&L",
            f"${acct.get('equity', 0) - acct.get('balance', 0):,.2f}",
        )
        col5.metric("Open Positions", str(len(mt5.get_open_positions())))
    except Exception as e:
        st.warning(f"MT5 not connected: {e}")
        for c in [col1, col2, col3, col4, col5]:
            c.metric("—", "N/A")

    st.markdown("---")

    # ── Market State ─────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("⏰ Market State")
        try:
            from utils.helpers import current_killzone, now_est, is_lunch_break
            kz = current_killzone()
            est = now_est()
            st.write(f"**EST Time:** {est.strftime('%H:%M:%S')}")
            st.write(f"**Active Killzone:** {kz or 'None (outside session)'}")
            if is_lunch_break():
                st.warning("🍽️ Lunch break — avoid new entries")
        except Exception:
            st.info("Helpers not loaded")

    with col_right:
        st.subheader("🌐 Intermarket Snapshot")
        try:
            from data.intermarket import IntermarketData
            im = IntermarketData()
            snap = im.get_full_snapshot()
            im_df = pd.DataFrame(
                [
                    {"Ticker": k, "Price": v.get("price", "N/A"), "Trend": v.get("trend", "N/A")}
                    for k, v in snap.items()
                    if isinstance(v, dict) and "price" in v
                ]
            )
            if not im_df.empty:
                st.dataframe(im_df)
            regime = snap.get("risk_regime", "N/A")
            st.write(f"**Risk Regime:** {regime}")
        except Exception as e:
            st.info(f"Intermarket data unavailable: {e}")

    st.markdown("---")

    # ── Open Positions Table ─────────────────────────────────────────
    st.subheader("📋 Open Positions")
    try:
        positions = mt5.get_open_positions()
        if positions:
            df = pd.DataFrame(positions)
            display_cols = [
                "ticket", "symbol", "type", "volume", "open_price",
                "current_price", "sl", "tp", "profit", "comment",
            ]
            available = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[available],
            )
        else:
            st.info("No open positions")
    except Exception:
        st.info("Connect to MT5 to see positions")

    # ── Recent Alerts ────────────────────────────────────────────────
    st.subheader("🔔 Recent Signals")
    if "recent_signals" in st.session_state:
        for sig in st.session_state["recent_signals"][-10:]:
            st.write(sig)
    else:
        st.info("No recent signals. System will populate when running.")

    # Auto-refresh
    if st.sidebar.checkbox("Auto-refresh (10s)", value=False):
        import time
        time.sleep(10)
        st.experimental_rerun()
