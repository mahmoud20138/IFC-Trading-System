"""
IFC Dashboard — Trade Journal Page
Browse, filter, and annotate trade history.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta


def render():
    st.title("📒 Trade Journal")

    try:
        from journal.database import JournalDB
        db = JournalDB()
    except Exception as e:
        st.error(f"Could not load journal database: {e}")
        return

    # ── Filters ──────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        days = st.selectbox("Period", [7, 14, 30, 60, 90, 180, 365], index=2)
    with col2:
        symbol_filter = st.text_input("Symbol filter", "")
    with col3:
        outcome_filter = st.selectbox("Outcome", ["All", "WIN", "LOSS", "BREAKEVEN", "OPEN"])
    with col4:
        setup_filter = st.selectbox(
            "Setup type",
            ["All", "LIQ_SWEEP", "POC_BOUNCE", "VA_BREAKOUT", "NAKED_POC", "POC_MIGRATION", "GENERIC_FVG"],
        )

    start = datetime.utcnow() - timedelta(days=days)
    trades = db.get_trades_range(start, symbol=symbol_filter or None)

    if outcome_filter != "All":
        trades = [t for t in trades if t["outcome"] == outcome_filter]
    if setup_filter != "All":
        trades = [t for t in trades if t.get("setup_type") == setup_filter]

    # ── Summary row ──────────────────────────────────────────────────
    if trades:
        closed = [t for t in trades if t["outcome"] != "OPEN"]
        wins = [t for t in closed if t["outcome"] == "WIN"]
        total_r = sum(t["r_multiple"] for t in closed)
        total_pnl = sum(t["pnl"] for t in closed)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Trades", len(trades))
        m2.metric("Win Rate", f"{len(wins)/len(closed)*100:.1f}%" if closed else "N/A")
        m3.metric("Total R", f"{total_r:+.2f}")
        m4.metric("Total P&L", f"${total_pnl:+,.2f}")
        m5.metric("Avg R", f"{total_r/len(closed):.2f}" if closed else "N/A")

    st.markdown("---")

    # ── Trades table ─────────────────────────────────────────────────
    if not trades:
        st.info("No trades found for the selected filters.")
        return

    df = pd.DataFrame(trades)
    display_cols = [
        "id", "entry_time", "symbol", "direction", "setup_type", "grade",
        "entry_price", "exit_price", "risk_pct", "pnl", "r_multiple",
        "outcome", "holding_time_min", "killzone", "notes",
    ]
    available = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[available],
    )

    # ── Trade detail expander ────────────────────────────────────────
    st.subheader("Trade Detail")
    trade_id = st.number_input("Enter Trade ID to view details", min_value=1, step=1)
    if st.button("Load Trade"):
        trade = db.get_trade(int(trade_id))
        if trade:
            with st.expander(f"Trade #{trade['id']} — {trade['symbol']} {trade['direction']}", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**Entry:**", trade.get("entry_price"))
                    st.write("**Exit:**", trade.get("exit_price"))
                    st.write("**Initial SL:**", trade.get("initial_sl"))
                    st.write("**TP1/TP2:**", trade.get("initial_tp1"), "/", trade.get("initial_tp2"))
                    st.write("**Risk %:**", f"{trade.get('risk_pct', 0):.2f}%")
                with c2:
                    st.write("**P&L:**", f"${trade.get('pnl', 0):.2f}")
                    st.write("**R-Multiple:**", f"{trade.get('r_multiple', 0):.2f}")
                    st.write("**MFE:**", f"{trade.get('mfe_pips', 0):.1f} pips")
                    st.write("**MAE:**", f"{trade.get('mae_pips', 0):.1f} pips")
                    st.write("**Hold time:**", f"{trade.get('holding_time_min', 0):.0f} min")

                # Layer scores
                layers = trade.get("layer_scores")
                if layers and isinstance(layers, dict):
                    st.write("**Layer Scores:**")
                    st.json(layers)

                # Multipliers
                st.write("**Risk Multipliers:**")
                mult_cols = st.columns(5)
                mult_cols[0].write(f"Setup: {trade.get('setup_mult', 1):.1f}")
                mult_cols[1].write(f"Vol: {trade.get('vol_mult', 1):.1f}")
                mult_cols[2].write(f"Streak: {trade.get('streak_mult', 1):.1f}")
                mult_cols[3].write(f"Time: {trade.get('time_mult', 1):.1f}")
                mult_cols[4].write(f"IM: {trade.get('im_mult', 1):.1f}")

                # Notes
                notes = st.text_area("Notes", value=trade.get("notes", "") or "")
                if st.button("Save Notes"):
                    db.update_trade(trade["id"], {"notes": notes})
                    st.success("Notes saved!")
        else:
            st.warning(f"Trade #{trade_id} not found")
