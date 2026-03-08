"""
IFC Trading System — Streamlit Dashboard
Main entry point.  Run with:  streamlit run dashboard/app.py
"""

import streamlit as st
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

st.set_page_config(
    page_title="IFC Trading System",
    page_icon="�",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Sidebar navigation ──────────────────────────────────────────────
st.sidebar.markdown("## IFC Trading")
page = st.sidebar.radio(
    "Navigate",
    [
        "📡 Pro Monitor",
        "📊 Full Monitor",
        "🧪 LLM Evaluator",
        "📒 Journal",
        "⚙️ Settings",
    ],
    label_visibility="collapsed",
)

# ── Route to pages ──────────────────────────────────────────────────
if page == "📡 Pro Monitor":
    from dashboard.pages.pro_monitor import render
    render()
elif page == "📊 Full Monitor":
    from dashboard.pages.full_monitor import render
    render()
elif page == "🧪 LLM Evaluator":
    from dashboard.pages.llm_dashboard import render
    render()
elif page == "📒 Journal":
    from dashboard.pages.trade_journal import render
    render()
elif page == "⚙️ Settings":
    from dashboard.pages.settings_page import render
    render()
