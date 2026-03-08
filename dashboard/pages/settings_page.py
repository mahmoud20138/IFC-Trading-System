"""
IFC Dashboard — Settings Page
View and modify system configuration.
"""

import streamlit as st


def render():
    st.title("⚙️ Settings")

    try:
        from config import settings
    except ImportError:
        st.error("Cannot load settings")
        return

    # ── Trading Mode ─────────────────────────────────────────────────
    st.subheader("Trading Mode")
    mode = st.radio(
        "Automation Level",
        ["SEMI_AUTO", "FULL_AUTO"],
        index=0 if settings.TRADING_MODE == "SEMI_AUTO" else 1,
        help="SEMI_AUTO = requires confirmation before each trade. FULL_AUTO = executes immediately.",
    )
    if mode != settings.TRADING_MODE:
        st.warning(f"Mode change will take effect on next scan cycle. (Current: {settings.TRADING_MODE})")

    st.markdown("---")

    # ── Risk Parameters ──────────────────────────────────────────────
    st.subheader("Risk Parameters")
    c1, c2, c3 = st.columns(3)
    c1.number_input("Base Risk %", value=settings.BASE_RISK_PCT, step=0.1, disabled=True)
    c2.number_input("Max Risk %", value=settings.MAX_RISK_PCT, step=0.1, disabled=True)
    c3.number_input("Daily Max Risk %", value=settings.DAILY_MAX_RISK_PCT, step=0.5, disabled=True)

    c4, c5, c6 = st.columns(3)
    c4.number_input("Min Risk %", value=settings.MIN_RISK_PCT, step=0.05, disabled=True)
    c5.number_input("Max Trades/Day", value=settings.MAX_TRADES_PER_DAY, step=1, disabled=True)
    c6.number_input("Min R:R Ratio", value=settings.MIN_RR_RATIO, step=0.5, disabled=True)

    st.info("💡 To change risk parameters, edit `config/settings.py` and restart the system.")

    st.markdown("---")

    # ── Confluence Thresholds ────────────────────────────────────────
    st.subheader("Confluence Thresholds")
    st.write(f"**Layer pass threshold:** {settings.LAYER_PASS_THRESHOLD}/10")
    st.write(f"**A+ grade:** ≥ {settings.GRADE_THRESHOLDS['A+']} layers passing")
    st.write(f"**A grade:** ≥ {settings.GRADE_THRESHOLDS['A']} layers passing")
    st.write(f"**B grade:** ≥ {settings.GRADE_THRESHOLDS['B']} layers passing")

    st.markdown("---")

    # ── Scaling Rules ────────────────────────────────────────────────
    st.subheader("Scaling Configuration")
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Entry Scale:**")
        st.write(f"- Entry 1 (CE): {settings.ENTRY_SCALE[0]*100:.0f}%")
        st.write(f"- Entry 2 (FVG low): {settings.ENTRY_SCALE[1]*100:.0f}%")
        st.write(f"- Entry 3 (POC edge): {settings.ENTRY_SCALE[2]*100:.0f}%")
    with c2:
        st.write("**Exit Scale:**")
        st.write(f"- TP1: {settings.EXIT_SCALE['TP1_pct']*100:.0f}%")
        st.write(f"- TP2: {settings.EXIT_SCALE['TP2_pct']*100:.0f}%")
        st.write(f"- TP3 (runner): {settings.EXIT_SCALE['TP3_pct']*100:.0f}%")

    st.markdown("---")

    # ── Killzone Times ───────────────────────────────────────────────
    st.subheader("Killzone Windows (EST)")
    for kz_name, kz_time in settings.KILLZONES.items():
        st.write(f"**{kz_name}:** {kz_time['start']} — {kz_time['end']}")

    st.markdown("---")

    # ── Instruments ──────────────────────────────────────────────────
    st.subheader("Active Instruments")
    try:
        from config.instruments import INSTRUMENTS
        import pandas as pd
        inst_data = [
            {
                "Name": k,
                "MT5 Symbol": v.mt5_symbol,
                "Category": v.category,
                "Pip Size": v.pip_size,
                "Typical Spread": v.typical_spread,
            }
            for k, v in INSTRUMENTS.items()
        ]
        st.dataframe(pd.DataFrame(inst_data))
    except Exception:
        st.info("Could not load instruments")

    st.markdown("---")

    # ── System Info ──────────────────────────────────────────────────
    st.subheader("System Info")
    st.write(f"**Magic Number:** {settings.MAGIC_NUMBER}")
    st.write(f"**Version:** IFC Trading System v1.0")
    st.write(f"**Database:** ifc_journal.db (SQLite)")
