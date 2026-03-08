"""
IFC Dashboard — Analysis Page
Run live analysis on any instrument. View all 8 layers + confluence score.
"""

import streamlit as st
import pandas as pd


def render():
    st.title("🔍 Live Analysis")

    try:
        from config.instruments import INSTRUMENTS
        from data.mt5_connector import MT5Connector
    except ImportError:
        st.error("Config or MT5 connector not loaded")
        return

    symbol_names = list(INSTRUMENTS.keys())
    selected = st.selectbox("Select Instrument", symbol_names)

    if st.button("Run Full Analysis"):
        with st.spinner(f"Analyzing {selected}..."):
            _run_analysis(selected)


def _run_analysis(instrument_key: str):
    """Run all 8 layers and display results."""
    try:
        from config.instruments import INSTRUMENTS
        from data.mt5_connector import MT5Connector
        from data.intermarket import IntermarketData
        from data.sentiment import SentimentData
        from data.economic_calendar import get_high_impact_events
        from analysis.layer1_intermarket import IntermarketLayer
        from analysis.layer2_trend import TrendLayer
        from analysis.layer3_volume_profile import VolumeProfileLayer, compute_volume_profile
        from analysis.layer4_candle_density import CandleDensityLayer
        from analysis.layer5_liquidity import LiquidityLayer
        from analysis.layer6_fvg_ob import FVGOrderBlockLayer
        from analysis.layer7_order_flow import OrderFlowLayer
        from analysis.layer8_killzone import KillzoneLayer
        from analysis.confluence_scorer import ConfluenceScorer
        from analysis.regime_detector import RegimeDetector
    except ImportError as e:
        st.error(f"Import error: {e}")
        return

    inst = INSTRUMENTS[instrument_key]
    mt5 = MT5Connector()
    im = IntermarketData()

    try:
        mt5.connect()
    except Exception as e:
        st.error(f"MT5 connection failed: {e}")
        return

    symbol = inst.mt5_symbol

    # Fetch data
    df_d = mt5.get_ohlcv(symbol, "D1", bars=200)
    df_4h = mt5.get_ohlcv(symbol, "H4", bars=200)
    df_1h = mt5.get_ohlcv(symbol, "H1", bars=200)
    df_15m = mt5.get_ohlcv(symbol, "M15", bars=200)

    if df_d.empty:
        st.error("No data returned from MT5")
        return

    current_price = df_15m["close"].iloc[-1] if not df_15m.empty else df_d["close"].iloc[-1]

    # ── Run each layer ───────────────────────────────────────────────
    results = {}

    # Fetch intermarket snapshot (used by L1 and Regime)
    snap = None
    try:
        snap = im.get_full_snapshot()
    except Exception:
        pass

    # Layer 1: Intermarket
    try:
        l1 = IntermarketLayer(im)
        results["L1_Intermarket"] = l1.analyze(inst, snap)
    except Exception as e:
        st.warning(f"Layer 1 error: {e}")

    # Layer 2: Trend
    try:
        l2 = TrendLayer()
        results["L2_Trend"] = l2.analyze(df_d, df_4h, df_1h)
    except Exception as e:
        st.warning(f"Layer 2 error: {e}")

    # Layer 3: Volume Profile
    vp_result = None
    try:
        l3 = VolumeProfileLayer()
        vp_result = compute_volume_profile(df_d)
        results["L3_Volume_Profile"] = l3.analyze(
            current_price=current_price,
            composite_profile=vp_result,
        )
    except Exception as e:
        st.warning(f"Layer 3 error: {e}")

    # Layer 4: Candle Density
    try:
        l4 = CandleDensityLayer()
        hvn = list(vp_result.hvn) if vp_result else []
        lvn = list(vp_result.lvn) if vp_result else []
        results["L4_Candle_Density"] = l4.analyze(
            df_d,
            vp_hvn=hvn,
            vp_lvn=lvn,
            current_price=current_price,
        )
    except Exception as e:
        st.warning(f"Layer 4 error: {e}")

    # Layer 5: Liquidity
    try:
        l5 = LiquidityLayer()
        # Compute ATR from daily data
        import numpy as np
        tr = np.maximum(
            df_d["high"] - df_d["low"],
            np.maximum(
                abs(df_d["high"] - df_d["close"].shift(1)),
                abs(df_d["low"] - df_d["close"].shift(1)),
            ),
        )
        atr = float(tr.rolling(14).mean().iloc[-1])
        results["L5_Liquidity"] = l5.analyze(
            df_d,
            atr=atr,
            current_price=current_price,
        )
    except Exception as e:
        st.warning(f"Layer 5 error: {e}")

    # Layer 6: FVG / OB
    try:
        l6 = FVGOrderBlockLayer()
        tr6 = np.maximum(
            df_1h["high"] - df_1h["low"],
            np.maximum(
                abs(df_1h["high"] - df_1h["close"].shift(1)),
                abs(df_1h["low"] - df_1h["close"].shift(1)),
            ),
        )
        atr_1h = float(tr6.rolling(14).mean().iloc[-1])
        results["L6_FVG_OB"] = l6.analyze(
            df_1h,
            atr=atr_1h,
            current_price=current_price,
            trade_direction="NEUTRAL",
        )
    except Exception as e:
        st.warning(f"Layer 6 error: {e}")

    # Layer 7: Order Flow
    try:
        l7 = OrderFlowLayer()
        results["L7_Order_Flow"] = l7.analyze(df_15m, inst)
    except Exception as e:
        st.warning(f"Layer 7 error: {e}")

    # Layer 8: Killzone
    try:
        l8 = KillzoneLayer()
        results["L8_Killzone"] = l8.analyze(symbol)
    except Exception as e:
        st.warning(f"Layer 8 error: {e}")

    # ── Display Layer Results ────────────────────────────────────────
    st.markdown("---")
    st.subheader("Layer Results")

    layer_data = []
    signals = []
    for name, sig in results.items():
        layer_data.append({
            "Layer": name,
            "Direction": sig.direction,
            "Score": f"{sig.score:.1f}/10",
            "Confidence": f"{sig.confidence:.0%}",
        })
        signals.append(sig)

    st.dataframe(pd.DataFrame(layer_data))

    # ── Confluence Score ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Confluence Score")

    try:
        scorer = ConfluenceScorer()
        confluence = scorer.score(signals)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Grade", confluence["grade"])
        c2.metric("Layers Passed", f"{confluence.get('layers_passed', confluence.get('total_passes', 0))}/{confluence.get('total_layers', 8)}")
        c3.metric("Direction", confluence["direction"])
        c4.metric("Tradeable", "✅ Yes" if confluence["tradeable"] else "❌ No")

        if confluence["tradeable"]:
            st.success(f"Setup qualifies for trading! Risk multiplier: {confluence['risk_multiplier']:.2f}")
        else:
            st.warning("Insufficient confluence — no trade.")
    except Exception as e:
        st.error(f"Confluence scoring error: {e}")

    # ── Regime ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Market Regime")

    try:
        rd = RegimeDetector()
        regime = rd.detect(
            daily_df=df_d,
            volume_profile=vp_result,
            vix_level=snap.get("VIX", {}).get("level", 20.0) if snap else 20.0,
        )
        st.write(f"**Regime:** {regime['regime']}")
        st.write(f"**Best Setups:** {', '.join(regime['best_setups'])}")
        st.write(f"**Size Adjustment:** {regime['size_adjustment']:.1%}")
    except Exception as e:
        st.warning(f"Regime detection error: {e}")

    # ── Layer Details Expander ───────────────────────────────────────
    st.markdown("---")
    with st.expander("Show Full Layer Details"):
        for name, sig in results.items():
            st.write(f"### {name}")
            st.json(sig.details if hasattr(sig, "details") else {})
