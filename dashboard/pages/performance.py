"""
IFC Dashboard — Performance Page
Charts and metrics for strategy analysis.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta


def render():
    st.title("📈 Performance Analytics")

    try:
        from journal.database import JournalDB
        from journal.analytics import JournalAnalytics
        db = JournalDB()
        analytics = JournalAnalytics(db)
    except Exception as e:
        st.error(f"Analytics not available: {e}")
        return

    days = st.sidebar.selectbox("Analysis Period (days)", [7, 14, 30, 60, 90, 180, 365], index=4)

    # ── Overview KPIs ────────────────────────────────────────────────
    perf = analytics.compute_performance(days=days)
    dd = analytics.max_drawdown_r(days=days)

    st.subheader("Key Performance Indicators")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Win Rate", f"{perf['win_rate']:.1f}%")
    k2.metric("Expectancy (R)", f"{perf['expectancy_r']:.3f}")
    k3.metric("Profit Factor", f"{perf['profit_factor']:.2f}")
    k4.metric("Total R", f"{perf['total_r']:+.1f}")
    k5.metric("Total P&L", f"${perf['total_pnl']:+,.2f}")
    k6.metric("Max Drawdown (R)", f"{dd['max_dd_r']:.1f}")

    st.markdown("---")

    # ── Equity Curve ─────────────────────────────────────────────────
    st.subheader("Equity Curve (Cumulative R)")
    curve = analytics.equity_curve(days=days)
    if curve:
        curve_df = pd.DataFrame(curve)
        st.line_chart(curve_df.set_index("date")["cumulative_r"])
    else:
        st.info("No closed trades to chart.")

    st.markdown("---")

    # ── Breakdown sections ───────────────────────────────────────────
    breakdown = st.radio(
        "Breakdown",
        ["By Setup", "By Symbol", "By Session", "By Grade", "By Day"],
        horizontal=True,
    )

    _breakdown_map = {
        "By Setup":   ("Setup",   analytics.performance_by_setup),
        "By Symbol":  ("Symbol",  analytics.performance_by_symbol),
        "By Session": ("Session", analytics.performance_by_session),
        "By Grade":   ("Grade",   analytics.performance_by_grade),
        "By Day":     ("Day",     analytics.performance_by_day),
    }
    label, fetch_fn = _breakdown_map[breakdown]
    st.subheader(f"Performance {breakdown}")
    data = fetch_fn(days=days)
    if data:
        rows = [
            {label: k, **{mk: mv for mk, mv in v.items() if mk in _metric_keys}}
            for k, v in data.items()
        ]
        st.dataframe(pd.DataFrame(rows))
    else:
        st.info("No data")

    # ── Trade distribution ───────────────────────────────────────────
    st.markdown("---")
    st.subheader("R-Multiple Distribution")
    start = datetime.utcnow() - timedelta(days=days)
    trades = db.get_trades_range(start)
    closed = [t for t in trades if t["outcome"] != "OPEN"]
    if closed:
        r_vals = pd.Series([t["r_multiple"] for t in closed])
        st.bar_chart(r_vals.value_counts().sort_index())

    # ── Additional stats ─────────────────────────────────────────────
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Streak Stats")
        st.write(f"Max Win Streak: **{perf['max_win_streak']}**")
        st.write(f"Max Loss Streak: **{perf['max_loss_streak']}**")
        st.write(f"Avg Hold Time: **{perf['avg_hold_min']:.0f} min**")
    with c2:
        st.subheader("MFE / MAE")
        st.write(f"Avg MFE: **{perf['avg_mfe_pips']:.1f} pips**")
        st.write(f"Avg MAE: **{perf['avg_mae_pips']:.1f} pips**")
        st.write(f"Gross Profit: **${perf['gross_profit']:,.2f}**")
        st.write(f"Gross Loss: **${perf['gross_loss']:,.2f}**")


# Metric keys to display in breakdown tables
_metric_keys = {
    "total_trades", "win_rate", "expectancy_r", "profit_factor",
    "total_r", "total_pnl", "avg_win_r", "avg_loss_r",
}
