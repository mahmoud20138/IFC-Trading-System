"""
IFC Trading System — Trade Recommendations Page
Generates and displays smart order recommendation cards
with entry zones, stops, targets, and sizing.
Compatible with Streamlit 1.12.
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config.instruments import WATCHLIST
from config import settings


def _inject_css():
    st.markdown("""
    <style>
    .rec-header { font-size:20px; font-weight:bold; color:white; margin-bottom:8px; }
    .no-recs { background:#1a1a2e; border:1px dashed #333; border-radius:8px;
               padding:20px; text-align:center; color:#aaa; }
    </style>
    """, unsafe_allow_html=True)


def render():
    _inject_css()
    st.markdown("## Smart Trade Recommendations (Part 16)")
    st.markdown("---")

    try:
        from analysis.layer1_intermarket import IntermarketLayer, LayerSignal
        from analysis.layer2_trend import TrendLayer
        from analysis.layer3_volume_profile import VolumeProfileLayer
        from analysis.layer4_candle_density import CandleDensityLayer
        from analysis.layer5_liquidity import LiquidityLayer
        from analysis.layer6_fvg_ob import FVGOrderBlockLayer
        from analysis.layer7_order_flow import OrderFlowLayer
        from analysis.layer8_killzone import KillzoneLayer
        from analysis.layer9_correlation import CorrelationLayer
        from analysis.layer10_sentiment import SentimentLayer
        from analysis.layer11_ai_evaluation import AIEvaluationLayer, full_evaluation
        from execution.smart_orders import generate_recommendation, format_card_html
        from data.intermarket import IntermarketData
        from data.mt5_connector import MT5Connector
    except Exception as e:
        st.error(f"Import error: {e}")
        return

    # Category filter
    categories = ["All", "forex", "index", "commodity", "crypto", "stock"]
    cat_filter = st.radio("Category", categories, horizontal=False)

    min_grade = st.selectbox("Minimum grade", ["B", "A", "A+"])

    if st.button("Scan All Instruments for Trade Recommendations"):
        try:
            mt5 = MT5Connector()
            mt5.ensure_connected()
            im = IntermarketData()
            snapshot = im.get_full_snapshot()
            account = mt5.get_account_info()
            balance = account.get("balance", 10000) if account else 10000

            # Get instruments to scan
            instruments = []
            for inst in WATCHLIST:
                if not inst.active:
                    continue
                if cat_filter != "All" and inst.category != cat_filter:
                    continue
                instruments.append((inst.mt5_symbol, inst))

            if not instruments:
                st.info("No instruments matching filter.")
                return

            progress = st.progress(0)
            cards = []
            statuses = []

            for idx, (key, inst) in enumerate(instruments):
                progress.progress((idx + 1) / len(instruments))

                try:
                    d1 = mt5.get_ohlcv(key, "D1", bars=200)
                    if d1 is None or d1.empty:
                        statuses.append(f"{inst.display_name}: No data")
                        continue

                    h4 = mt5.get_ohlcv(key, "H4", bars=200)
                    w1 = mt5.get_ohlcv(key, "W1", bars=100)
                    h1 = mt5.get_ohlcv(key, "H1", bars=200)
                    m15 = mt5.get_ohlcv(key, "M15", bars=200)
                    current_price = float(d1["close"].iloc[-1])

                    from analysis.regime_detector import compute_atr
                    atr = compute_atr(d1) if len(d1) >= 14 else 0

                    signals = []

                    # L1
                    try:
                        l1_layer = IntermarketLayer(im)
                        signals.append(l1_layer.analyze(inst, snapshot))
                    except:
                        signals.append(LayerSignal("L1_Intermarket", "NEUTRAL", 5.0, 0.3, {}))

                    # L2
                    try:
                        signals.append(TrendLayer().analyze(w1, d1, h4))
                    except:
                        signals.append(LayerSignal("L2_Trend", "NEUTRAL", 5.0, 0.3, {}))

                    # L3
                    try:
                        vp = VolumeProfileLayer()
                        m1 = mt5.get_ohlcv(key, "M1", bars=2000)
                        if m1 is not None and not m1.empty:
                            profile = vp.compute_profile(m1)
                            signals.append(vp.analyze(current_price, profile))
                        else:
                            signals.append(LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {}))
                    except:
                        signals.append(LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {}))

                    # L4
                    try:
                        signals.append(CandleDensityLayer().analyze(h1, [], [], current_price))
                    except:
                        signals.append(LayerSignal("L4_CandleDensity", "NEUTRAL", 5.0, 0.3, {}))

                    # L5
                    try:
                        signals.append(LiquidityLayer().analyze(h1, atr, current_price))
                    except:
                        signals.append(LayerSignal("L5_Liquidity", "NEUTRAL", 5.0, 0.3, {}))

                    # L6
                    try:
                        signals.append(FVGOrderBlockLayer().analyze(h1, atr, current_price))
                    except:
                        signals.append(LayerSignal("L6_FVG_OrderBlock", "NEUTRAL", 5.0, 0.3, {}))

                    # L7
                    try:
                        signals.append(OrderFlowLayer().analyze(m15, "NEUTRAL"))
                    except:
                        signals.append(LayerSignal("L7_OrderFlow", "NEUTRAL", 5.0, 0.3, {}))

                    # L8
                    try:
                        signals.append(KillzoneLayer().analyze(key))
                    except:
                        signals.append(LayerSignal("L8_Killzone", "NEUTRAL", 5.0, 0.3, {}))

                    # L9
                    try:
                        signals.append(CorrelationLayer().analyze(key, snapshot))
                    except:
                        signals.append(LayerSignal("L9_Correlation", "NEUTRAL", 5.0, 0.3, {}))

                    # L10
                    try:
                        signals.append(SentimentLayer().analyze(key, inst.category, snapshot))
                    except:
                        signals.append(LayerSignal("L10_Sentiment", "NEUTRAL", 5.0, 0.3, {}))

                    # L11
                    try:
                        l11 = AIEvaluationLayer()
                        vix = snapshot.get("VIX", {}).get("level", 20.0) if snapshot else 20.0
                        signals.append(l11.analyze(d1, None, vix))
                    except:
                        signals.append(LayerSignal("L11_Regime", "NEUTRAL", 5.0, 0.3, {}))

                    # Run evaluation
                    evaluation = full_evaluation(signals)

                    # Filter by minimum grade
                    grade_order = {"A+": 3, "A": 2, "B": 1, "NO_TRADE": 0}
                    min_grade_val = grade_order.get(min_grade, 0)
                    eval_grade_val = grade_order.get(evaluation["grade"], 0)

                    if evaluation["tradeable"] and eval_grade_val >= min_grade_val:
                        card = generate_recommendation(
                            instrument=inst,
                            current_price=current_price,
                            atr=atr,
                            signals=signals,
                            evaluation=evaluation,
                            account_balance=balance,
                        )
                        if card:
                            cards.append(card)
                            statuses.append(f"{inst.display_name}: {evaluation['grade']} ✅")
                        else:
                            statuses.append(f"{inst.display_name}: Not tradeable")
                    else:
                        statuses.append(f"{inst.display_name}: {evaluation['grade']} (filtered)")

                except Exception as e:
                    statuses.append(f"{inst.display_name}: Error - {e}")

            progress.empty()

            # ── Display Results ──
            st.markdown("---")
            st.markdown(f"### Found {len(cards)} Trade Recommendation(s)")

            if not cards:
                st.markdown(
                    '<div class="no-recs">No trade recommendations meet the criteria. '
                    'Try lowering the minimum grade or scanning during killzone hours.</div>',
                    unsafe_allow_html=True
                )
            else:
                # Sort by QAS descending
                cards.sort(key=lambda c: c.qas_score, reverse=True)
                for card in cards:
                    st.markdown(format_card_html(card), unsafe_allow_html=True)

            # Scan summary
            with st.expander("Scan Details"):
                for s in statuses:
                    st.text(s)

        except Exception as e:
            st.error(f"Scan failed: {e}")
            import traceback
            st.code(traceback.format_exc())
