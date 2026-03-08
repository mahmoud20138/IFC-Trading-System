"""
IFC Trading System — AI Evaluator Dashboard Page
Runs the full 11-layer AI evaluation for a selected instrument
and displays the grade report, veto analysis, and layer breakdown.
Compatible with Streamlit 1.12.
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config.instruments import WATCHLIST, INSTRUMENTS
from config import settings


def _inject_css():
    st.markdown("""
    <style>
    .ai-card { border-radius:10px; padding:16px; margin:8px 0; background:#1a1a2e; }
    .ai-grade-aplus { border:2px solid #00c853; }
    .ai-grade-a { border:2px solid #2196f3; }
    .ai-grade-b { border:2px solid #ff9800; }
    .ai-grade-no { border:2px solid #ff1744; }
    .ai-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
    .ai-table th { background:#1a1a2e; color:#e0e0e0; padding:6px 8px; text-align:center;
                   border:1px solid #333; }
    .ai-table td { padding:5px 8px; text-align:center; border:1px solid #333; color:#fff; }
    .veto-hard { background:rgba(255,23,68,0.15); border-left:4px solid #ff1744;
                 padding:6px 12px; margin:4px 0; border-radius:4px; color:#ff8a80; }
    .veto-soft { background:rgba(255,152,0,0.15); border-left:4px solid #ff9800;
                 padding:6px 12px; margin:4px 0; border-radius:4px; color:#ffcc80; }
    .verdict-box { border-radius:8px; padding:12px; margin:8px 0; text-align:center;
                   font-size:18px; font-weight:bold; }
    .verdict-trade { background:rgba(0,200,83,0.2); border:2px solid #00c853; color:#00c853; }
    .verdict-skip { background:rgba(255,23,68,0.2); border:2px solid #ff1744; color:#ff1744; }
    .verdict-wait { background:rgba(255,152,0,0.2); border:2px solid #ff9800; color:#ff9800; }
    </style>
    """, unsafe_allow_html=True)


def _score_bar(normalized, weight):
    """Visual bar for a normalized score."""
    pct = (normalized + 2) / 4 * 100  # -2 to +2 → 0% to 100%
    color = "#00c853" if normalized > 0.5 else "#ff1744" if normalized < -0.5 else "#ff9800"
    return f'<div style="background:#333; border-radius:3px; height:12px; width:80px; display:inline-block;">' \
           f'<div style="background:{color}; width:{pct:.0f}%; height:100%; border-radius:3px;"></div></div>'


def render():
    _inject_css()
    st.markdown("## AI Evaluation Engine (Layer 11)")
    st.markdown("---")

    try:
        from analysis.layer1_intermarket import IntermarketLayer, LayerSignal
        from analysis.layer2_trend import TrendLayer
        from analysis.layer3_volume_profile import VolumeProfileLayer, compute_volume_profile
        from analysis.layer4_candle_density import CandleDensityLayer
        from analysis.layer5_liquidity import LiquidityLayer
        from analysis.layer6_fvg_ob import FVGOrderBlockLayer
        from analysis.layer7_order_flow import OrderFlowLayer
        from analysis.layer8_killzone import KillzoneLayer
        from analysis.layer9_correlation import CorrelationLayer
        from analysis.layer10_sentiment import SentimentLayer
        from analysis.layer11_ai_evaluation import AIEvaluationLayer, full_evaluation
        from data.intermarket import IntermarketData
        from data.mt5_connector import MT5Connector
    except Exception as e:
        st.error(f"Import error: {e}")
        return

    # ── Instrument selection ──
    inst_names = []
    inst_keys = []
    for inst in WATCHLIST:
        if inst.active:
            inst_names.append(f"{inst.display_name} ({inst.mt5_symbol})")
            inst_keys.append(inst.mt5_symbol)

    selected_idx = st.selectbox("Select instrument to evaluate", range(len(inst_names)),
                                format_func=lambda i: inst_names[i])

    if st.button("Run Full 11-Layer AI Evaluation"):
        if selected_idx is None:
            st.warning("Select an instrument first.")
            return

        key = inst_keys[selected_idx]
        inst = INSTRUMENTS[key]

        with st.spinner(f"Running 11-layer evaluation for {inst.display_name}..."):
            try:
                mt5 = MT5Connector()
                mt5.ensure_connected()
                im = IntermarketData()
                snapshot = im.get_full_snapshot()

                # Fetch data
                d1 = mt5.get_ohlcv(key, "D1", bars=200)
                h4 = mt5.get_ohlcv(key, "H4", bars=200)
                w1 = mt5.get_ohlcv(key, "W1", bars=100)
                h1 = mt5.get_ohlcv(key, "H1", bars=200)
                m15 = mt5.get_ohlcv(key, "M15", bars=200)

                if d1 is None or d1.empty:
                    st.error(f"No data for {key}")
                    return

                current_price = float(d1["close"].iloc[-1])

                # Compute ATR
                from analysis.regime_detector import compute_atr
                atr = compute_atr(d1) if len(d1) >= 14 else 0

                signals = []

                # L1: Intermarket
                try:
                    l1 = IntermarketLayer(im)
                    signals.append(l1.analyze(inst, snapshot))
                except Exception as e:
                    signals.append(LayerSignal("L1_Intermarket", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L2: Trend
                try:
                    l2 = TrendLayer()
                    signals.append(l2.analyze(w1, d1, h4))
                except Exception as e:
                    signals.append(LayerSignal("L2_Trend", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L3: Volume Profile
                try:
                    vp = VolumeProfileLayer()
                    m1 = mt5.get_ohlcv(key, "M1", bars=2000)
                    if m1 is not None and not m1.empty:
                        profile = compute_volume_profile(m1)
                        sig3 = vp.analyze(current_price, profile)
                    else:
                        sig3 = LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {"note": "No M1 data"})
                    signals.append(sig3)
                except Exception as e:
                    signals.append(LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L4: Candle Density
                try:
                    l4 = CandleDensityLayer()
                    signals.append(l4.analyze(h1, [], [], current_price))
                except Exception as e:
                    signals.append(LayerSignal("L4_CandleDensity", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L5: Liquidity
                try:
                    l5 = LiquidityLayer()
                    signals.append(l5.analyze(h1, atr, current_price))
                except Exception as e:
                    signals.append(LayerSignal("L5_Liquidity", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L6: FVG+OB — use L2 direction for proper filtering
                trade_dir = signals[1].direction if len(signals) >= 2 else "NEUTRAL"
                try:
                    l6 = FVGOrderBlockLayer()
                    # Pass VP confluence levels from L3 if available
                    conf_levels = None
                    if profile is not None:
                        conf_levels = [profile.poc, profile.vah, profile.val] + list(profile.hvn[:3])
                    signals.append(l6.analyze(h1, atr, current_price, trade_direction=trade_dir, confluence_levels=conf_levels))
                except Exception as e:
                    signals.append(LayerSignal("L6_FVG_OrderBlock", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L7: Order Flow — use L2 direction
                try:
                    l7 = OrderFlowLayer()
                    signals.append(l7.analyze(m15, trade_dir))
                except Exception as e:
                    signals.append(LayerSignal("L7_OrderFlow", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L8: Killzone
                try:
                    l8 = KillzoneLayer()
                    signals.append(l8.analyze(key))
                except Exception as e:
                    signals.append(LayerSignal("L8_Killzone", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L9: Correlation
                try:
                    l9 = CorrelationLayer()
                    signals.append(l9.analyze(key, snapshot))
                except Exception as e:
                    signals.append(LayerSignal("L9_Correlation", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L10: Sentiment
                try:
                    l10 = SentimentLayer()
                    signals.append(l10.analyze(key, inst.category, snapshot))
                except Exception as e:
                    signals.append(LayerSignal("L10_Sentiment", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # L11: Regime
                try:
                    l11 = AIEvaluationLayer()
                    vix = snapshot.get("VIX", {}).get("level", 20.0) if snapshot else 20.0
                    vp_obj = None
                    try:
                        m1_data = mt5.get_ohlcv(key, "M1", bars=2000)
                        if m1_data is not None and not m1_data.empty:
                            vp_obj = compute_volume_profile(m1_data)
                    except:
                        pass
                    signals.append(l11.analyze(d1, vp_obj, vix))
                except Exception as e:
                    signals.append(LayerSignal("L11_Regime", "NEUTRAL", 5.0, 0.3, {"error": str(e)}))

                # ── Run full evaluation ──
                evaluation = full_evaluation(signals)

                # ── Display Results ──
                grade = evaluation["grade"]
                grade_css = {
                    "A+": "ai-grade-aplus", "A": "ai-grade-a",
                    "B": "ai-grade-b",
                }.get(grade, "ai-grade-no")
                grade_color = {
                    "A+": "#00c853", "A": "#2196f3",
                    "B": "#ff9800",
                }.get(grade, "#ff1744")

                # Verdict box
                verdict = evaluation["verdict"]
                if "TRADE" in verdict:
                    v_css = "verdict-trade"
                elif "WAIT" in verdict:
                    v_css = "verdict-wait"
                else:
                    v_css = "verdict-skip"

                st.markdown(f'<div class="verdict-box {v_css}">{verdict}</div>', unsafe_allow_html=True)

                # Grade card
                st.markdown(f"""
                <div class="ai-card {grade_css}">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <span style="font-size:24px; font-weight:bold; color:white;">
                                {inst.display_name}
                            </span>
                            <span style="background:{grade_color}; color:white; padding:4px 12px;
                                         border-radius:6px; margin-left:12px; font-size:18px; font-weight:bold;">
                                {grade}
                            </span>
                        </div>
                        <div style="text-align:right;">
                            <div style="color:#aaa; font-size:12px;">Direction</div>
                            <div style="color:{'#00c853' if evaluation['direction']=='LONG' else '#ff1744' if evaluation['direction']=='SHORT' else '#666'};
                                        font-size:18px; font-weight:bold;">{evaluation['direction']}</div>
                        </div>
                    </div>
                    <hr style="border-color:#333;">
                    <div style="display:flex; gap:30px; color:white;">
                        <div>
                            <div style="color:#aaa; font-size:12px;">TWS</div>
                            <div style="font-size:16px; font-weight:bold;">{evaluation['tws']:.3f}</div>
                        </div>
                        <div>
                            <div style="color:#aaa; font-size:12px;">QAS</div>
                            <div style="font-size:16px; font-weight:bold;">{evaluation['qas']:.3f}</div>
                        </div>
                        <div>
                            <div style="color:#aaa; font-size:12px;">Avg Confidence</div>
                            <div style="font-size:16px; font-weight:bold;">{evaluation['avg_confidence']:.2f}</div>
                        </div>
                        <div>
                            <div style="color:#aaa; font-size:12px;">Size Multiplier</div>
                            <div style="font-size:16px; font-weight:bold;">{evaluation['size_multiplier']:.2f}x</div>
                        </div>
                        <div>
                            <div style="color:#aaa; font-size:12px;">Aggressiveness</div>
                            <div style="font-size:16px; font-weight:bold;">{evaluation['aggressiveness']}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Vetos
                if evaluation["hard_vetos"]:
                    st.markdown("### Hard Vetos")
                    for v in evaluation["hard_vetos"]:
                        st.markdown(f'<div class="veto-hard">🚫 {v}</div>', unsafe_allow_html=True)

                if evaluation["soft_vetos"]:
                    st.markdown("### Soft Vetos")
                    for v in evaluation["soft_vetos"]:
                        st.markdown(f'<div class="veto-soft">⚠️ {v}</div>', unsafe_allow_html=True)

                if not evaluation["hard_vetos"] and not evaluation["soft_vetos"]:
                    st.markdown("### Veto Check: ✅ All Clear")

                st.markdown("---")

                # Layer breakdown table
                st.markdown("### 11-Layer Breakdown")
                breakdown = evaluation.get("layer_breakdown", [])
                if breakdown:
                    html = '<table class="ai-table">'
                    html += '<tr><th>Layer</th><th>Raw (0-10)</th><th>Norm (-2/+2)</th><th>Weight</th><th>Weighted</th><th>Dir</th><th>Conf</th></tr>'

                    for layer in breakdown:
                        raw = layer["raw_score"]
                        norm = layer["normalized"]
                        w = layer["weight"]
                        ws = layer["weighted_score"]
                        d = layer["direction"]
                        c = layer["confidence"]

                        # Color
                        if raw >= 7:
                            bg = "rgba(0,200,83,0.2)"
                        elif raw <= 3:
                            bg = "rgba(255,23,68,0.2)"
                        else:
                            bg = "rgba(255,152,0,0.1)"

                        dir_c = "#00c853" if d == "LONG" else "#ff1744" if d == "SHORT" else "#666"

                        html += f'<tr style="background:{bg};">'
                        html += f'<td style="text-align:left;">{layer["layer"]}</td>'
                        html += f'<td>{raw:.1f}</td>'
                        html += f'<td>{norm:+.2f}</td>'
                        html += f'<td>{w:.0%}</td>'
                        html += f'<td style="font-weight:bold;">{ws:+.4f}</td>'
                        html += f'<td style="color:{dir_c};">{d}</td>'
                        html += f'<td>{c:.2f}</td>'
                        html += '</tr>'

                    html += '</table>'
                    st.markdown(html, unsafe_allow_html=True)

                # Strongest / Weakest
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Strongest Layers:**")
                    for l in evaluation.get("strongest_layers", [])[:3]:
                        st.markdown(f"- {l['layer']}: {l['normalized']:+.2f}")
                with col2:
                    st.markdown("**Weakest Layers:**")
                    for l in evaluation.get("weakest_layers", [])[:3]:
                        st.markdown(f"- {l['layer']}: {l['normalized']:+.2f}")

            except Exception as e:
                st.error(f"Evaluation failed: {e}")
                import traceback
                st.code(traceback.format_exc())
