"""
IFC Trading System — LLM Evaluator Dashboard Page
Enhancement Plan Feature A: LLM Second Opinion display.

Shows the LLM's second opinion alongside the system's evaluation
for each instrument.
"""

import streamlit as st
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config import settings
from config.instruments import get_active_instruments, Instrument
from analysis.llm_evaluator import (
    evaluate_with_llm,
    is_llm_configured,
    get_available_backends,
    fetch_ollama_models,
    LLM_BACKEND,
    LLM_MODEL,
)
from analysis.pipeline import AnalysisPipeline
from analysis.layer1_intermarket import IntermarketLayer
from data.intermarket import IntermarketData
from data.mt5_connector import MT5Connector


def render():
    st.title("🧠 LLM Second Opinion")
    st.caption("AI-powered second evaluation of each trade signal")

    # ── Check LLM configuration ──
    if not is_llm_configured():
        st.error(
            "⚠️ No LLM backend configured. Add API keys to `config/credentials.py`:\n\n"
            "```python\n"
            "OPENAI_API_KEY = 'sk-...'       # For GPT-4\n"
            "GEMINI_API_KEY = 'AI...'         # For Gemini\n"
            "OLLAMA_ENDPOINT = 'http://localhost:11434'  # For local Ollama\n"
            "```"
        )
        return

    available = get_available_backends()
    st.sidebar.markdown("---")
    st.sidebar.subheader("LLM Settings")

    backend = st.sidebar.selectbox(
        "Backend",
        options=available,
        index=available.index(LLM_BACKEND) if LLM_BACKEND in available else 0,
        key="llm_backend",
    )

    # ── Model selection (dynamic for Ollama) ──
    if backend == "ollama":
        # Fetch installed Ollama models
        ollama_models_raw = fetch_ollama_models()
        if ollama_models_raw:
            ollama_names = [m.get("name", m.get("model", "unknown")) for m in ollama_models_raw]
            # Build display labels with size info
            ollama_labels = []
            for m in ollama_models_raw:
                name = m.get("name", m.get("model", "unknown"))
                size_bytes = m.get("size", 0)
                size_gb = size_bytes / (1024 ** 3) if size_bytes else 0
                label = f"{name}  ({size_gb:.1f} GB)" if size_gb > 0 else name
                ollama_labels.append(label)

            selected_model_idx = st.sidebar.selectbox(
                "Ollama Model",
                range(len(ollama_names)),
                format_func=lambda i: ollama_labels[i],
                key="llm_ollama_model",
            )
            model = ollama_names[selected_model_idx]
        else:
            st.sidebar.warning("⚠️ Could not fetch Ollama models. Is Ollama running?")
            model = st.sidebar.text_input(
                "Model (manual)",
                value="llama3.1",
                key="llm_model_fallback",
            )
    else:
        model_defaults = {
            "openai": "gpt-4o-mini",
            "gemini": "gemini-1.5-flash",
        }
        model = st.sidebar.text_input(
            "Model",
            value=model_defaults.get(backend, LLM_MODEL),
            key="llm_model",
        )

    force_refresh = st.sidebar.checkbox("Force refresh (bypass cache)", key="llm_force")

    # Temporarily override settings for this session
    settings.LLM_BACKEND = backend
    settings.LLM_MODEL = model

    # ── Instrument selection ──
    instruments = get_active_instruments()
    inst_names = [f"{i.display_name} ({i.mt5_symbol})" for i in instruments]
    selected_idx = st.selectbox(
        "Select Instrument",
        range(len(instruments)),
        format_func=lambda i: inst_names[i],
        key="llm_instrument",
    )
    instrument = instruments[selected_idx]

    # ── Run analysis ──
    if st.button("🔍 Evaluate with LLM", type="primary", key="llm_eval_btn"):
        with st.spinner(f"Running 11-layer analysis for {instrument.display_name}..."):
            try:
                mt5 = MT5Connector()
                intermarket = IntermarketData()
                intermarket_layer = IntermarketLayer(intermarket)
                pipeline = AnalysisPipeline()

                # Fetch data
                df_d1 = mt5.get_ohlcv(instrument.mt5_symbol, "D1", 200)
                df_h4 = mt5.get_ohlcv(instrument.mt5_symbol, "H4", 200)
                df_h1 = mt5.get_ohlcv(instrument.mt5_symbol, "H1", 500)
                df_m15 = mt5.get_ohlcv(instrument.mt5_symbol, "M15", 500)
                df_m1 = mt5.get_ohlcv(instrument.mt5_symbol, "M1", 2000)
                snapshot = intermarket.get_full_snapshot()

                # Run pipeline
                pipe_result = pipeline.run(
                    instrument=instrument,
                    intermarket_layer=intermarket_layer,
                    df_d1=df_d1,
                    df_h4=df_h4,
                    df_h1=df_h1,
                    df_m15=df_m15,
                    df_m1=df_m1,
                    intermarket_snapshot=snapshot,
                )

                st.success(
                    f"System: **{pipe_result.grade}** | "
                    f"Direction: **{pipe_result.direction}** | "
                    f"Tradeable: {'✅' if pipe_result.tradeable else '❌'}"
                )

                # ── Display system evaluation ──
                col_sys, col_llm = st.columns(2)

                with col_sys:
                    st.subheader("📊 System Evaluation")
                    ev = pipe_result.evaluation
                    st.metric("Grade", ev.get("grade", "---"))
                    st.metric("QAS", f"{ev.get('qas', 0):.3f}")
                    st.metric("TWS", f"{ev.get('tws', 0):.3f}")
                    st.metric("Direction", ev.get("direction", "---"))
                    st.metric("Size Multiplier", f"{ev.get('size_multiplier', 0):.2f}")

                    if ev.get("hard_vetos"):
                        st.error("Hard Vetos: " + ", ".join(ev["hard_vetos"]))
                    if ev.get("soft_vetos"):
                        st.warning("Soft Vetos: " + ", ".join(ev["soft_vetos"]))

                    st.caption(ev.get("verdict", ""))

                # ── Call LLM ──
                with col_llm:
                    st.subheader("🧠 LLM Opinion")
                    with st.spinner(f"Consulting {backend}/{model}..."):
                        llm_result = evaluate_with_llm(
                            symbol=instrument.mt5_symbol,
                            signals=pipe_result.signals,
                            evaluation=pipe_result.evaluation,
                            regime=pipe_result.regime,
                            intermarket_snapshot=snapshot,
                            force_refresh=force_refresh,
                        )

                    if "error" in llm_result and llm_result.get("agrees") is None:
                        st.error(f"LLM Error: {llm_result['error']}")
                    else:
                        # Agreement indicator
                        agrees = llm_result.get("agrees")
                        if agrees is True:
                            st.success("✅ LLM AGREES with the system")
                        elif agrees is False:
                            st.error("❌ LLM DISAGREES with the system")
                        else:
                            st.warning("⚠️ LLM response unclear")

                        # Metrics
                        risk = llm_result.get("risk_score", 5)
                        risk_color = "🟢" if risk <= 3 else "🟡" if risk <= 6 else "🔴"
                        st.metric("Risk Score", f"{risk_color} {risk}/10")
                        st.metric("LLM Direction", llm_result.get("direction_opinion", "?"))
                        st.metric(
                            "Size Adjustment",
                            f"{llm_result.get('size_adjustment', 1.0):.2f}x",
                        )
                        st.metric(
                            "LLM Confidence",
                            f"{llm_result.get('confidence', 0):.0%}",
                        )

                        # Concerns & Confirmations
                        concerns = llm_result.get("key_concerns", [])
                        if concerns:
                            st.markdown("**⚠️ Key Concerns:**")
                            for c in concerns:
                                st.markdown(f"- {c}")

                        confirms = llm_result.get("confirmations", [])
                        if confirms:
                            st.markdown("**✅ Confirmations:**")
                            for c in confirms:
                                st.markdown(f"- {c}")

                        # Reasoning
                        reasoning = llm_result.get("reasoning", "")
                        if reasoning:
                            st.info(f"**Reasoning:** {reasoning}")

                        # Metadata
                        st.caption(
                            f"Backend: {llm_result.get('backend', '?')} / "
                            f"Model: {llm_result.get('model', '?')} | "
                            f"Latency: {llm_result.get('latency_s', '?')}s | "
                            f"Cached: {'Yes' if llm_result.get('cached') else 'No'}"
                        )

                # ── Layer breakdown ──
                st.markdown("---")
                st.subheader("📋 Layer Breakdown")
                import pandas as pd
                layer_data = []
                for sig in pipe_result.signals:
                    layer_data.append({
                        "Layer": sig.layer_name,
                        "Score": f"{sig.score:.1f}",
                        "Pass": "✅" if sig.score >= settings.LAYER_PASS_THRESHOLD else "❌",
                        "Direction": sig.direction,
                        "Confidence": f"{sig.confidence:.0%}",
                    })
                st.dataframe(pd.DataFrame(layer_data), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())

    # ── Cache status ──
    st.sidebar.markdown("---")
    from analysis.llm_evaluator import _llm_cache
    st.sidebar.caption(f"LLM Cache: {len(_llm_cache)} entries")
