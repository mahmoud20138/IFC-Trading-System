"""
IFC Trading System — Pro Monitor v2
Professional-grade live dashboard: account, trade signals with deep reasoning,
all instruments grid, open positions, and per-instrument LLM deep analysis.
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import asdict

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ═══════════════════════════════════════════════════════════════════════
# CSS — dark institutional theme
# ═══════════════════════════════════════════════════════════════════════
_CSS = """
<style>
/* ── global ─────────────────────────────────────────────── */
.main .block-container{padding-top:.8rem;max-width:100%}
section[data-testid="stSidebar"]{width:210px!important}
h1,h2,h3{letter-spacing:-.3px}

/* ── account bar ────────────────────────────────────────── */
.acct-box{background:linear-gradient(135deg,#0d1b2a,#1b2838);border:1px solid #1b3a5a;
  border-radius:10px;padding:10px 14px;text-align:center}
.acct-val{font-size:20px;font-weight:800;color:#fff}
.acct-lbl{font-size:10px;color:#78909c;text-transform:uppercase;letter-spacing:.6px}

/* ── signal cards ───────────────────────────────────────── */
.sig-card{background:linear-gradient(135deg,#0d2137,#0a1929);
  border:1px solid #1a4a7a;border-radius:14px;padding:18px 22px;margin:10px 0}
.sig-card.hot{border-color:#00e676;box-shadow:0 0 20px rgba(0,230,118,.12)}
.sig-card.warm{border-color:#ffc107;box-shadow:0 0 14px rgba(255,193,7,.08)}
.sig-card.watch{border-color:#455a64}

.sig-header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap}
.sig-sym{font-size:22px;font-weight:800}
.sig-price{font-size:18px;font-weight:700;color:#fff}

/* ── grade / direction badges ───────────────────────────── */
.badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;
  letter-spacing:.4px;margin:0 3px}
.g-aplus{background:#00c853;color:#000}.g-a{background:#00e676;color:#000}
.g-b{background:#ffc107;color:#000}.g-no{background:#37474f;color:#78909c}
.d-long{color:#00e676;font-weight:800}.d-short{color:#ff5252;font-weight:800}
.d-neut{color:#607d8b}

/* ── layer mini bars ────────────────────────────────────── */
.lbar{display:inline-block;width:26px;height:18px;border-radius:3px;margin:1px;
  text-align:center;font-size:9px;line-height:18px;font-weight:600}
.lbar.p{background:#1b5e20;color:#69f0ae}
.lbar.f{background:rgba(183,28,28,.19);color:#ef9a9a}
.lbar.m{background:#e65100;color:#ffcc02}

/* ── scalping cards ─────────────────────────────────────── */
.scalp-card{background:linear-gradient(135deg,#1a0a2e,#0d1b2a);
  border:1px solid #7c4dff;border-radius:12px;padding:14px 18px;margin:8px 0}
.scalp-card.strong{border-color:#00e5ff;box-shadow:0 0 16px rgba(0,229,255,.1)}
.scalp-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;
  font-weight:700;letter-spacing:.3px;margin:0 3px}
.scalp-bull{background:#1b5e20;color:#69f0ae}
.scalp-bear{background:#b71c1c;color:#ef9a9a}

/* ── execution panel ────────────────────────────────────── */
.exec-box{background:linear-gradient(135deg,#0d2137,#0a1929);
  border:1px solid #1a4a7a;border-radius:12px;padding:16px 20px;margin:8px 0}
.exec-buy{background:linear-gradient(135deg,#004d00,#003300);border-color:#00e676}
.exec-sell{background:linear-gradient(135deg,#4d0000,#330000);border-color:#ff5252}
.exec-result{border:2px solid #4fc3f7;border-radius:10px;padding:12px;margin:8px 0;
  background:#0b1929}

/* ── reasoning block ────────────────────────────────────── */
.reason-block{background:#0a1520;border:1px solid #1a3a5a;border-radius:8px;
  padding:12px 14px;margin-top:10px;font-size:13px;line-height:1.7;color:#b0bec5}
.reason-block b{color:#90caf9}
.reason-block .row-lbl{color:#78909c;font-size:11px;text-transform:uppercase;letter-spacing:.5px}

/* ── setup box ──────────────────────────────────────────── */
.setup-box{background:#0b1e10;border:1px solid #1b5e20;border-radius:8px;
  padding:12px 14px;margin-top:8px;font-size:13px;color:#a5d6a7}
.setup-box b{color:#69f0ae}
.setup-box.short-setup{background:#1e0b0e;border-color:#b71c1c}
.setup-box.short-setup b{color:#ef9a9a}

/* ── sentiment row ──────────────────────────────────────── */
.sent-row{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}
.sent-chip{background:#102030;border:1px solid #1a3a5a;border-radius:6px;
  padding:4px 10px;font-size:12px;color:#90a4ae}
.sent-chip b{color:#4fc3f7}

/* ── grid / table ───────────────────────────────────────── */
.stDataFrame{font-size:13px!important}
.stTabs [data-baseweb="tab-list"]{gap:2px}
.stTabs [data-baseweb="tab"]{background:#1a1a2e;border-radius:8px 8px 0 0;
  padding:8px 16px;color:#90a4ae}
.stTabs [aria-selected="true"]{background:#16213e;color:#4a9eff;border-bottom:2px solid #4a9eff}
</style>
"""


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def _grade_html(g: str) -> str:
    c = {"A+": "g-aplus", "A": "g-a", "B": "g-b"}.get(g, "g-no")
    return f'<span class="badge {c}">{g}</span>'

def _dir_html(d: str) -> str:
    if d == "LONG":
        return '<span class="d-long">▲ LONG</span>'
    if d == "SHORT":
        return '<span class="d-short">▼ SHORT</span>'
    return '<span class="d-neut">— NEUTRAL</span>'

def _score_color(s: float) -> str:
    if s >= 7.5: return "#00e676"
    if s >= 6.0: return "#66bb6a"
    if s >= 4.5: return "#ffc107"
    if s >= 3.0: return "#ff9800"
    return "#ff5252"

def _fmt_price(price: float, pip_size: float) -> str:
    if pip_size >= 1.0: return f"{price:,.1f}"
    if pip_size >= 0.01: return f"{price:,.2f}"
    if pip_size >= 0.001: return f"{price:,.3f}"
    return f"{price:,.5f}"

def _layer_bars(signals) -> str:
    html = ""
    for sig in signals:
        if sig.score >= 6.0:
            cls = "p"
        elif sig.score >= 4.5:
            cls = "m"
        else:
            cls = "f"
        label = sig.layer_name.replace("L", "").split("_")[0]
        html += f'<span class="lbar {cls}" title="{sig.layer_name}: {sig.score:.1f}/10">{label}</span>'
    return html


def _sanitize_detail(key: str, val) -> str:
    """Convert a layer detail value to a clean display string."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        if key == "sweep" and isinstance(val, dict):
            stype = val.get("type", "SWEEP")
            confirmed = "confirmed" if val.get("reversal_confirmed") else "pending"
            return f"{stype} ({confirmed})"
        if key == "pool" and isinstance(val, dict):
            return f"{val.get('type', '')} @ {val.get('level', ''):.5g}" if val.get("level") else str(val.get("type", ""))
        if isinstance(val, list):
            return f"{len(val)} items"
        return str(next(iter(val.values()), ""))
    # Guard against Timestamp or other complex types
    s = str(val)
    if len(s) > 80:
        return s[:77] + "..."
    return s


def _build_deep_reasons(data: Dict) -> str:
    """Build rich HTML reasoning narrative from signal details."""
    signals = data.get("signals", [])
    if not signals:
        return ""

    lines = []

    # ── Strengths
    strong = sorted([s for s in signals if s.score >= 6.0], key=lambda x: x.score, reverse=True)
    if strong:
        lines.append('<b style="color:#81c784">✓ Strengths</b>')
        for s in strong[:5]:
            detail_str = ""
            if s.details:
                for k in [
                    "trend_alignment", "note", "regime", "session", "killzone",
                    "sentiment_direction", "correlation_status", "delta_status",
                    "price_position", "fvg_count", "sweep",
                ]:
                    v = s.details.get(k)
                    if v:
                        detail_str = f" — {_sanitize_detail(k, v)}"
                        break
            lines.append(f'  <span style="color:#a5d6a7">{s.layer_name}: <b>{s.score:.1f}</b>/10{detail_str}</span>')

    # ── Risks
    weak = sorted([s for s in signals if s.score < 5.0], key=lambda x: x.score)
    if weak:
        lines.append('<b style="color:#ef9a9a;margin-top:4px;display:block">⚠ Risks</b>')
        for s in weak[:4]:
            detail_str = ""
            if s.details:
                for k in ["note", "reason", "regime", "session", "killzone"]:
                    v = s.details.get(k)
                    if v:
                        detail_str = f" — {_sanitize_detail(k, v)}"
                        break
            lines.append(f'  <span style="color:#ef9a9a">{s.layer_name}: <b>{s.score:.1f}</b>/10{detail_str}</span>')

    # ── Regime
    regime = data.get("regime", "?")
    if regime and regime != "?":
        lines.append(f'<span class="row-lbl">Regime</span> <b>{regime}</b>')

    # ── Price context highlights
    pc = data.get("price_context", {})
    if pc:
        parts = []
        if pc.get("current_price"):
            parts.append(f'Price: <b>{pc["current_price"]}</b>')
        if pc.get("ema_alignment") or pc.get("ma_alignment"):
            parts.append(f'MA Align: <b>{pc.get("ema_alignment") or pc.get("ma_alignment")}</b>')
        atr_raw = pc.get("atr_14") or pc.get("atr_pips")
        if atr_raw:
            # Show ATR as $ value if available, otherwise pips
            if pc.get("atr_14"):
                parts.append(f'ATR: <b>${pc["atr_14"]:.2f}</b>')
            else:
                parts.append(f'ATR: <b>{pc["atr_pips"]:.0f} pips</b>')
        if pc.get("rsi_14"):
            parts.append(f'RSI: <b>{pc["rsi_14"]:.0f}</b>')
        if pc.get("daily_range_pips"):
            dr = pc["daily_range_pips"]
            if dr > 500:
                # For commodities/crypto show $ value
                dr_dollar = dr * 0.001  # rough pip_size estimate
                parts.append(f'D-Range: <b>${pc.get("daily_high", 0) - pc.get("daily_low", 0):.2f}</b>')
            else:
                parts.append(f'D-Range: <b>{dr:.0f} pips</b>')
        if parts:
            lines.append('<span class="row-lbl">Technical</span> ' + " · ".join(parts))

    # ── Intermarket
    intermarket = data.get("intermarket", {})
    if intermarket:
        im_parts = []
        for k, v in list(intermarket.items())[:4]:
            if isinstance(v, dict):
                p = v.get("price", "")
                t = v.get("trend", "")
                if p:
                    im_parts.append(f'{k}: <b>{p}</b>{(" " + t) if t else ""}')
            elif v:
                im_parts.append(f'{k}: <b>{v}</b>')
        if im_parts:
            lines.append('<span class="row-lbl">Intermarket</span> ' + " · ".join(im_parts))

    return "<br>".join(lines)


def _setup_html(setup_obj) -> str:
    """Render TradeSetup as a compact card."""
    if not setup_obj:
        return ""
    try:
        s = setup_obj
        d = s.direction
        cls = "short-setup" if d == "SHORT" else ""
        arrow = "▼" if d == "SHORT" else "▲"
        tp3 = f" &nbsp; TP3: <b>{s.tp3}</b>" if s.tp3 else " &nbsp; TP3: trail"
        return (
            f'<div class="setup-box {cls}">'
            f'<b>{arrow} {s.setup_type.replace("_", " ")}</b> · R:R <b>{s.rr_ratio:.1f}</b> · Grade <b>{s.grade}</b><br>'
            f'Entry: <b>{s.entry_price}</b> &nbsp; SL: <b>{s.stop_loss}</b> &nbsp;'
            f'TP1: <b>{s.tp1}</b> &nbsp; TP2: <b>{s.tp2}</b>{tp3}'
            f'</div>'
        )
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
# Scanner — runs the full pipeline on all instruments
# ═══════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=55, show_spinner=False)
def _scan_all() -> Dict[str, Any]:
    """Analyse all active instruments via the full pipeline. Cached 55s."""
    from config.instruments import get_active_instruments
    from data.mt5_connector import MT5Connector
    from data.intermarket import IntermarketData
    from analysis.layer1_intermarket import IntermarketLayer
    from analysis.pipeline import AnalysisPipeline

    mt5 = MT5Connector()
    mt5.connect()

    im = IntermarketData()
    snapshot: Dict = {}
    try:
        snapshot = im.get_full_snapshot()
    except Exception:
        pass

    intermarket_layer = IntermarketLayer(im)
    instruments = get_active_instruments()
    results: Dict[str, Any] = {}

    for inst in instruments:
        sym = inst.mt5_symbol
        try:
            pipeline = AnalysisPipeline()

            # Multi-TF data
            df_d1  = mt5.get_ohlcv(sym, "D1",  200)
            df_h4  = mt5.get_ohlcv(sym, "H4",  200)
            df_h1  = mt5.get_ohlcv(sym, "H1",  300)
            df_m15 = mt5.get_ohlcv(sym, "M15", 300)
            df_m5  = mt5.get_ohlcv(sym, "M5",  200)
            df_m1  = mt5.get_ohlcv(sym, "M1",  500)

            if df_d1 is None or df_d1.empty:
                results[sym] = _empty_result(inst, "No D1 data")
                continue

            pipe = pipeline.run(
                instrument=inst,
                intermarket_layer=intermarket_layer,
                df_d1=df_d1,
                df_h4=df_h4,
                df_h1=df_h1,
                df_m15=df_m15,
                df_m5=df_m5,
                df_m1=df_m1,
                intermarket_snapshot=snapshot,
            )

            signals   = pipe.signals
            avg_score = sum(s.score for s in signals) / len(signals) if signals else 0
            pass_cnt  = sum(1 for s in signals if s.score >= 6.0) if signals else 0

            results[sym] = {
                "instrument":    inst,
                "price":         pipe.current_price,
                "signals":       signals,
                "grade":         pipe.grade,
                "direction":     pipe.direction,
                "tradeable":     pipe.tradeable,
                "avg_score":     avg_score,
                "pass_count":    pass_cnt,
                "total_layers":  len(signals),
                "regime":        pipe.regime.get("regime", "?"),
                "confluence":    pipe.confluence,
                "evaluation":    pipe.evaluation,
                "setup":         pipe.setup,
                "price_context": pipe.price_context,
                "atr":           pipe.atr,
                "qas":           pipe.confluence.get("qas", 0),
                "tws":           pipe.confluence.get("tws", 0),
                "elapsed_ms":    pipe.elapsed_ms,
                "intermarket":   snapshot,
                "df_m5":         df_m5,
                "df_m1":         df_m1,
                "error":         None,
            }
        except Exception as e:
            results[sym] = _empty_result(inst, str(e))

    return results


def _empty_result(inst, err: str) -> Dict:
    return {
        "instrument": inst, "price": 0, "signals": [], "grade": "ERR",
        "direction": "NEUTRAL", "tradeable": False, "avg_score": 0,
        "pass_count": 0, "total_layers": 0, "regime": "?",
        "confluence": {}, "evaluation": {}, "setup": None,
        "price_context": {}, "atr": 0, "qas": 0, "tws": 0, "elapsed_ms": 0,
        "intermarket": {}, "df_m5": None, "df_m1": None, "error": err,
    }


# ═══════════════════════════════════════════════════════════════════════
# LLM Deep Analysis (on-demand per instrument)
# ═══════════════════════════════════════════════════════════════════════
def _run_llm_analysis(sym: str, data: Dict) -> Dict:
    """Fire the LLM evaluator for a single instrument."""
    from analysis.llm_evaluator import evaluate_with_llm
    try:
        setup_dict = None
        if data.get("setup"):
            try:
                setup_dict = asdict(data["setup"])
            except Exception:
                setup_dict = None

        result = evaluate_with_llm(
            symbol=sym,
            signals=data.get("signals", []),
            evaluation=data.get("evaluation", {}),
            regime={"regime": data.get("regime", "?")},
            intermarket_snapshot=data.get("intermarket"),
            price_data=data.get("price_context"),
            setup=setup_dict,
            force_refresh=True,
        )
        return result
    except Exception as e:
        return {"error": str(e), "verdict": f"LLM error: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# Account Bar
# ═══════════════════════════════════════════════════════════════════════
def _render_account():
    try:
        from data.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        mt5.connect()
        acct = mt5.get_account_info()
        positions = mt5.get_open_positions()

        balance  = acct.get("balance", 0)
        equity   = acct.get("equity", 0)
        floating = equity - balance
        margin_l = acct.get("margin_level", 0)

        cols = st.columns([2, 2, 2, 2, 2, 1])
        _acct_box(cols[0], f"${balance:,.0f}", "Balance")
        _acct_box(cols[1], f"${equity:,.0f}", "Equity")

        fl_color = "#00e676" if floating >= 0 else "#ff5252"
        with cols[2]:
            st.markdown(
                f'<div class="acct-box"><div class="acct-val" style="color:{fl_color}">'
                f'{floating:+,.0f}</div><div class="acct-lbl">Floating P&L</div></div>',
                unsafe_allow_html=True,
            )

        _acct_box(cols[3], str(len(positions)), "Open Trades")

        # Killzone
        with cols[4]:
            try:
                from utils.helpers import current_killzone, now_est
                kz = current_killzone() or "Off Session"
                est = now_est().strftime("%H:%M")
                st.markdown(
                    f'<div class="acct-box"><div class="acct-val" style="font-size:15px">'
                    f'{kz}</div><div class="acct-lbl">Killzone · {est} EST</div></div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                _acct_box(cols[4], "—", "Killzone")

        # VIX
        with cols[5]:
            try:
                from data.intermarket import IntermarketData
                snap = IntermarketData().get_full_snapshot()
                vix = snap.get("VIX", {}).get("price", "—")
                st.markdown(
                    f'<div class="acct-box"><div class="acct-val" style="font-size:15px">'
                    f'{vix}</div><div class="acct-lbl">VIX</div></div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                _acct_box(cols[5], "—", "VIX")
    except Exception:
        st.error("⛔ MT5 not connected")


def _acct_box(col, value: str, label: str):
    with col:
        st.markdown(
            f'<div class="acct-box"><div class="acct-val">{value}</div>'
            f'<div class="acct-lbl">{label}</div></div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════
# Tab 1 — Trade Signals
# ═══════════════════════════════════════════════════════════════════════
def _render_signals(results: Dict[str, Any]):
    """Render trade signal cards with deep reasoning & LLM button."""

    ranked = [
        (sym, d) for sym, d in results.items()
        if not (d.get("error") and not d.get("signals"))
    ]
    ranked.sort(key=lambda x: (x[1].get("tradeable", False), x[1].get("qas", 0)), reverse=True)

    hot  = [(s, d) for s, d in ranked if d.get("tradeable")]
    warm = [(s, d) for s, d in ranked
            if not d.get("tradeable") and d.get("avg_score", 0) >= 5.0 and d.get("direction") != "NEUTRAL"]

    if not hot and not warm:
        st.info("📡 Monitoring all instruments — no actionable signals right now.")
        return

    # ── Active Signals ──
    if hot:
        st.markdown(f"### 🟢 Active Signals — {len(hot)}")
        for sym, data in hot:
            _signal_card(sym, data, "hot")

    # ── Watchlist ──
    if warm:
        st.markdown(f"### 🟡 Watchlist — {len(warm)}")
        for sym, data in warm[:8]:
            _signal_card(sym, data, "warm")


def _signal_card(sym: str, data: Dict, tier: str):
    """Render one signal card with reasoning, setup, and LLM button."""
    inst      = data["instrument"]
    grade     = data["grade"]
    direction = data["direction"]
    qas       = data.get("qas", 0)
    tws       = data.get("tws", 0)

    dir_color = "#00e676" if direction == "LONG" else "#ff5252" if direction == "SHORT" else "#607d8b"
    dir_arrow = "▲" if direction == "LONG" else "▼" if direction == "SHORT" else "—"

    # Layer mini bars
    bars_html = _layer_bars(data.get("signals", []))

    # Reasoning
    reasoning_html = _build_deep_reasons(data)

    # Setup
    setup_html = _setup_html(data.get("setup"))

    # Sentiment chips (from evaluation if available)
    sent_html = ""
    evaluation = data.get("evaluation", {})
    if evaluation:
        chips = []
        for k in ["sentiment_read", "timing_assessment", "market_structure_assessment"]:
            v = evaluation.get(k)
            if v:
                chips.append(f'<span class="sent-chip"><b>{k.replace("_", " ").title()}:</b> {v}</span>')
        if chips:
            sent_html = f'<div class="sent-row">{"".join(chips)}</div>'

    # Score summary line
    summary = (
        f'QAS: <b>{qas:.3f}</b> · TWS: <b>{tws:.3f}</b> · '
        f'Avg: <b>{data.get("avg_score", 0):.1f}</b>/10 · '
        f'Pass: <b>{data.get("pass_count", 0)}/{data.get("total_layers", 0)}</b> · '
        f'Regime: <b>{data.get("regime", "?")}</b> · '
        f'{data.get("elapsed_ms", 0):.0f}ms'
    )

    card_html = (
        f'<div class="sig-card {tier}">'
        f'<div class="sig-header"><div>'
        f'<span class="sig-sym" style="color:{dir_color}">{dir_arrow} {inst.display_name}</span>'
        f'<span style="color:#546e7a;margin-left:8px;font-size:12px">{sym}</span>'
        f'<span style="margin-left:10px">{_grade_html(grade)}</span>'
        f'</div>'
        f'<div class="sig-price">{_fmt_price(data.get("price", 0), inst.pip_size)}</div>'
        f'</div>'
        f'<div style="margin:6px 0">{bars_html}</div>'
        f'{setup_html}'
        f'<div class="reason-block">{reasoning_html}</div>'
        f'{sent_html}'
        f'<div style="color:#546e7a;font-size:11px;margin-top:6px">{summary}</div>'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # ── LLM Deep Analysis button (per instrument) ──
    btn_key = f"llm_{sym}"
    if st.button(f"🧠 Deep LLM Analysis — {inst.display_name}", key=btn_key, type="secondary"):
        with st.spinner(f"Running deep LLM analysis on {inst.display_name}..."):
            llm_result = _run_llm_analysis(sym, data)

        if llm_result.get("error") and not llm_result.get("verdict"):
            st.error(f"LLM Error: {llm_result['error']}")
        else:
            # Display LLM result
            verdict    = llm_result.get("verdict", "")
            confidence = llm_result.get("confidence", 0)
            narrative  = llm_result.get("trade_narrative", "")
            st_assess  = llm_result.get("market_structure_assessment", "")
            inst_lvl   = llm_result.get("institutional_level_quality", "")
            best_entry = llm_result.get("best_entry_zone", "")
            timing     = llm_result.get("timing_assessment", "")
            sent_read  = llm_result.get("sentiment_read", "")
            im_align   = llm_result.get("intermarket_alignment", "")
            risk_note  = llm_result.get("risk_note", "")

            conf_cls = (
                "g-aplus" if confidence >= 80 else
                "g-a" if confidence >= 60 else
                "g-b" if confidence >= 40 else "g-no"
            )

            grid_items = ""
            for label, val in [
                ("Structure", st_assess), ("Inst. Levels", inst_lvl),
                ("Entry Zone", best_entry), ("Timing", timing),
                ("Sentiment", sent_read), ("Intermarket", im_align),
            ]:
                if val:
                    grid_items += f'<div><b style="color:#4fc3f7">{label}:</b> {val}</div>'

            narr_html = f'<div style="color:#b0bec5;font-size:13px;margin-top:8px;line-height:1.6">{narrative}</div>' if narrative else ''
            risk_html = f'<div style="color:#ef9a9a;font-size:12px;margin-top:8px">⚠ {risk_note}</div>' if risk_note else ''
            cache_html = '<div style="color:#37474f;font-size:10px;margin-top:6px">cached</div>' if llm_result.get("cached") else ''
            llm_html = (
                f'<div style="background:#0b1929;border:1px solid #1a4a7a;border-radius:10px;padding:16px;margin:8px 0">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:16px;font-weight:800;color:#4fc3f7">🧠 LLM Verdict</span>'
                f'<span class="badge {conf_cls}">Confidence {confidence}%</span>'
                f'</div>'
                f'<div style="color:#e0e0e0;font-size:14px;margin-top:8px;font-weight:600">{verdict}</div>'
                f'{narr_html}'
                f'<div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;color:#90a4ae">{grid_items}</div>'
                f'{risk_html}{cache_html}'
                f'</div>'
            )
            st.markdown(llm_html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# Tab 2 — All Instruments Grid
# ═══════════════════════════════════════════════════════════════════════
def _render_grid(results: Dict[str, Any], cat: str = "ALL"):
    items = []
    for sym, data in results.items():
        inst = data.get("instrument")
        if not inst:
            continue
        if cat != "ALL" and inst.category.lower() != cat.lower():
            continue
        items.append((sym, data))

    items.sort(key=lambda x: (x[1].get("tradeable", False), x[1].get("avg_score", 0)), reverse=True)

    if not items:
        st.caption("No instruments in this category")
        return

    rows = []
    for sym, data in items:
        inst = data["instrument"]
        d = data.get("direction", "NEUTRAL")
        g = data.get("grade", "---")
        signals = data.get("signals", [])

        dir_str = {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT"}.get(d, "⚪ —")
        grade_str = {"A+": "🏆 A+", "A": "✅ A", "B": "🟡 B"}.get(g, "⛔ NO")

        top_sig = ""
        if signals:
            best = max(signals, key=lambda s: s.score)
            top_sig = f"{best.layer_name.split('_')[0]}:{best.score:.0f}"
        weak_sig = ""
        if signals:
            worst = min(signals, key=lambda s: s.score)
            weak_sig = f"{worst.layer_name.split('_')[0]}:{worst.score:.0f}"

        setup_str = ""
        if data.get("setup"):
            s = data["setup"]
            setup_str = f"{s.setup_type} R:{s.rr_ratio:.1f}"

        rows.append({
            "✓": "✅" if data.get("tradeable") else "",
            "Instrument": inst.display_name,
            "Category": inst.category.upper(),
            "Price": _fmt_price(data.get("price", 0), inst.pip_size),
            "Dir": dir_str,
            "Grade": grade_str,
            "Avg": f"{data.get('avg_score', 0):.1f}",
            "Pass": f"{data.get('pass_count', 0)}/{data.get('total_layers', 0)}",
            "QAS": f"{data.get('qas', 0):.3f}" if data.get("qas") else "—",
            "Regime": data.get("regime", "?"),
            "Setup": setup_str,
            "Best": top_sig,
            "Weak": weak_sig,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True,
                 height=min(len(rows) * 38 + 40, 720))


# ═══════════════════════════════════════════════════════════════════════
# Tab 3 — Open Positions
# ═══════════════════════════════════════════════════════════════════════
def _render_positions():
    try:
        from data.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        mt5.connect()
        positions = mt5.get_open_positions()
        if positions:
            df = pd.DataFrame(positions)
            want = ["ticket", "symbol", "type", "volume", "open_price",
                    "current_price", "sl", "tp", "profit", "comment"]
            cols = [c for c in want if c in df.columns]
            st.dataframe(df[cols] if cols else df, width="stretch", hide_index=True)
        else:
            st.caption("No open positions")
    except Exception as e:
        st.caption(f"Cannot fetch positions: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Tab 4 — Sentiment & Intermarket Overview
# ═══════════════════════════════════════════════════════════════════════
def _render_sentiment(results: Dict[str, Any]):
    """Show sentiment + intermarket overview for top instruments."""
    snapshot = {}
    for d in results.values():
        if d.get("intermarket"):
            snapshot = d["intermarket"]
            break

    if snapshot:
        st.markdown("#### Intermarket Snapshot")
        im_rows = []
        for key, val in snapshot.items():
            if isinstance(val, dict):
                im_rows.append({
                    "Asset": key,
                    "Price": val.get("price", "—"),
                    "Change %": val.get("change_pct", "—"),
                    "Trend": val.get("trend", "—"),
                })
            else:
                im_rows.append({"Asset": key, "Price": val, "Change %": "—", "Trend": "—"})
        if im_rows:
            st.dataframe(pd.DataFrame(im_rows), width="stretch", hide_index=True)

    # Sentiment from layer signals (L10)
    st.markdown("#### Instrument Sentiment Signals")
    sent_rows = []
    for sym, data in results.items():
        signals = data.get("signals", [])
        l10 = next((s for s in signals if "L10" in s.layer_name or "entiment" in s.layer_name), None)
        if l10:
            sent_rows.append({
                "Instrument": data.get("instrument", type("", (), {"display_name": sym})).display_name,
                "Sentiment Score": f"{l10.score:.1f}/10",
                "Direction": l10.details.get("sentiment_direction", "—") if l10.details else "—",
                "Source": l10.details.get("source", "—") if l10.details else "—",
            })
    if sent_rows:
        st.dataframe(pd.DataFrame(sent_rows), width="stretch", hide_index=True)
    else:
        st.caption("No sentiment data available")


# ═══════════════════════════════════════════════════════════════════════
# Tab 5 — Scalping Opportunities (M5/M1)
# ═══════════════════════════════════════════════════════════════════════
def _render_scalping(results: Dict[str, Any]):
    """Show M5/M1 scalping opportunities — momentum + quick-flip setups."""
    st.markdown("#### ⚡ M5/M1 Scalping Scanner")
    st.caption("Fast momentum signals aligned with higher-TF bias. Short-hold, tight SL.")

    scalp_opps = []
    for sym, data in results.items():
        if data.get("error") and not data.get("signals"):
            continue
        inst = data.get("instrument")
        if not inst:
            continue

        df_m5 = data.get("df_m5")
        df_m1 = data.get("df_m1")
        htf_dir = data.get("direction", "NEUTRAL")
        price = data.get("price", 0)
        atr = data.get("atr", 0)

        if df_m5 is None or df_m5.empty:
            continue

        try:
            m5_close = df_m5["close"].values
            m5_high = df_m5["high"].values
            m5_low = df_m5["low"].values
            m5_vol = df_m5["tick_volume"].values if "tick_volume" in df_m5.columns else df_m5.get("volume", pd.Series([0])).values

            ema8 = pd.Series(m5_close).ewm(span=8).mean().iloc[-1]
            ema21 = pd.Series(m5_close).ewm(span=21).mean().iloc[-1]
            ema8_prev = pd.Series(m5_close).ewm(span=8).mean().iloc[-2]
            ema21_prev = pd.Series(m5_close).ewm(span=21).mean().iloc[-2]

            m5_bullish_cross = ema8_prev <= ema21_prev and ema8 > ema21
            m5_bearish_cross = ema8_prev >= ema21_prev and ema8 < ema21
            m5_ema_spread = abs(ema8 - ema21)

            delta = pd.Series(m5_close).diff()
            gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
            loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
            rsi_m5 = 100 - (100 / (1 + gain / loss)) if loss > 0 else 50

            last3_range = sum(m5_high[-3:] - m5_low[-3:]) / 3
            avg20_range = np.mean(m5_high[-20:] - m5_low[-20:]) if len(m5_high) >= 20 else last3_range
            momentum_ratio = last3_range / avg20_range if avg20_range > 0 else 1.0

            vol_last3 = np.mean(m5_vol[-3:]) if len(m5_vol) >= 3 else 0
            vol_avg20 = np.mean(m5_vol[-20:]) if len(m5_vol) >= 20 else vol_last3
            vol_surge = vol_last3 / vol_avg20 if vol_avg20 > 0 else 1.0

            m1_micro = "—"
            if df_m1 is not None and not df_m1.empty and len(df_m1) >= 10:
                m1c = df_m1["close"].values
                m1_ema5 = pd.Series(m1c).ewm(span=5).mean().iloc[-1]
                m1_ema13 = pd.Series(m1c).ewm(span=13).mean().iloc[-1]
                if m1_ema5 > m1_ema13:
                    m1_micro = "🟢 Bull"
                elif m1_ema5 < m1_ema13:
                    m1_micro = "🔴 Bear"
                else:
                    m1_micro = "⚪ Flat"

            scalp_dir = "NEUTRAL"
            scalp_score = 0
            reasons = []

            if m5_bullish_cross:
                scalp_dir = "LONG"
                scalp_score += 3
                reasons.append("M5 EMA8×21 bullish cross")
            elif m5_bearish_cross:
                scalp_dir = "SHORT"
                scalp_score += 3
                reasons.append("M5 EMA8×21 bearish cross")
            elif ema8 > ema21:
                scalp_dir = "LONG"
                scalp_score += 1
                reasons.append("M5 EMA8 > EMA21")
            elif ema8 < ema21:
                scalp_dir = "SHORT"
                scalp_score += 1
                reasons.append("M5 EMA8 < EMA21")

            if scalp_dir == "LONG" and rsi_m5 > 50 and rsi_m5 < 75:
                scalp_score += 1
                reasons.append(f"RSI {rsi_m5:.0f} bullish")
            elif scalp_dir == "SHORT" and rsi_m5 < 50 and rsi_m5 > 25:
                scalp_score += 1
                reasons.append(f"RSI {rsi_m5:.0f} bearish")

            if vol_surge > 1.5:
                scalp_score += 1
                reasons.append(f"Vol surge {vol_surge:.1f}x")

            if momentum_ratio > 1.3:
                scalp_score += 1
                reasons.append(f"Momentum {momentum_ratio:.1f}x")

            if htf_dir == scalp_dir and htf_dir != "NEUTRAL":
                scalp_score += 2
                reasons.append(f"HTF aligned {htf_dir}")
            elif htf_dir != "NEUTRAL" and htf_dir != scalp_dir:
                scalp_score -= 1
                reasons.append(f"⚠ Counter-HTF ({htf_dir})")

            if scalp_score >= 3 and scalp_dir != "NEUTRAL":
                pip_val = inst.pip_size if inst.pip_size > 0 else 0.0001
                scalp_sl_dist = max(m5_ema_spread * 1.5, atr * 0.3) if atr > 0 else m5_ema_spread * 2
                scalp_tp1_dist = scalp_sl_dist * 1.5
                scalp_tp2_dist = scalp_sl_dist * 2.5

                if scalp_dir == "LONG":
                    sl = price - scalp_sl_dist
                    tp1 = price + scalp_tp1_dist
                    tp2 = price + scalp_tp2_dist
                else:
                    sl = price + scalp_sl_dist
                    tp1 = price - scalp_tp1_dist
                    tp2 = price - scalp_tp2_dist

                scalp_opps.append({
                    "sym": sym, "inst": inst, "direction": scalp_dir,
                    "score": scalp_score, "price": price, "rsi": rsi_m5,
                    "vol_surge": vol_surge, "momentum": momentum_ratio,
                    "m1_micro": m1_micro, "htf_dir": htf_dir,
                    "reasons": reasons, "sl": sl, "tp1": tp1, "tp2": tp2,
                    "sl_pips": abs(scalp_sl_dist / pip_val),
                    "grade": data.get("grade", "—"), "atr": atr,
                })
        except Exception:
            continue

    scalp_opps.sort(key=lambda x: x["score"], reverse=True)

    if not scalp_opps:
        st.info("📡 No scalping opportunities right now. Waiting for M5/M1 momentum...")
        return

    st.markdown(f"**{len(scalp_opps)} scalp signal{'s' if len(scalp_opps) != 1 else ''}**")

    for opp in scalp_opps:
        tier = "strong" if opp["score"] >= 5 else ""
        d = opp["direction"]
        d_cls = "scalp-bull" if d == "LONG" else "scalp-bear"
        d_arrow = "▲ LONG" if d == "LONG" else "▼ SHORT"
        reasons_html = " · ".join(opp["reasons"])
        pip_s = opp["inst"].pip_size if opp["inst"].pip_size > 0 else 0.0001
        dg = max(2, len(str(pip_s).rstrip('0').split('.')[-1])) if pip_s < 1 else 2

        card_html = (
            f'<div class="scalp-card {tier}">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<div>'
            f'<span style="font-size:18px;font-weight:800;color:{"#00e5ff" if d == "LONG" else "#ff5252"}">'
            f'{opp["inst"].display_name}</span>'
            f'<span class="scalp-badge {d_cls}" style="margin-left:8px">{d_arrow}</span>'
            f'<span style="color:#546e7a;margin-left:8px;font-size:11px">Score {opp["score"]}/7</span>'
            f'</div>'
            f'<span style="font-size:16px;font-weight:700;color:#fff">{opp["price"]:.{dg}f}</span>'
            f'</div>'
            f'<div style="color:#90a4ae;font-size:12px;margin:6px 0">{reasons_html}</div>'
            f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;font-size:11px;color:#78909c;margin-top:6px">'
            f'<div>RSI: <b style="color:#fff">{opp["rsi"]:.0f}</b></div>'
            f'<div>Vol: <b style="color:#fff">{opp["vol_surge"]:.1f}x</b></div>'
            f'<div>Mom: <b style="color:#fff">{opp["momentum"]:.1f}x</b></div>'
            f'<div>M1: <b>{opp["m1_micro"]}</b></div>'
            f'<div>HTF: <b>{opp["htf_dir"]}</b></div>'
            f'</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:11px;margin-top:6px;color:#b0bec5">'
            f'<div>SL: <b style="color:#ff5252">{opp["sl"]:.{dg}f}</b> ({opp["sl_pips"]:.0f}p)</div>'
            f'<div>TP1: <b style="color:#00e676">{opp["tp1"]:.{dg}f}</b></div>'
            f'<div>TP2: <b style="color:#00e676">{opp["tp2"]:.{dg}f}</b></div>'
            f'</div></div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# Tab 6 — Execute Trade (BUY / SELL with SL/TP/Trailing)
# ═══════════════════════════════════════════════════════════════════════
def _render_execution(results: Dict[str, Any]):
    """Live trade execution panel with auto-sizing, SL/TP, and position management."""

    st.markdown("#### 🔥 Trade Execution Panel")
    st.caption("Execute trades directly from analysis. Auto lot sizing · Risk management · Trailing stops")

    st.markdown("---")
    st.markdown("##### 📤 Open New Trade")

    trade_options = {}
    for sym, data in results.items():
        if data.get("error") and not data.get("signals"):
            continue
        inst = data.get("instrument")
        if not inst:
            continue
        grade = data.get("grade", "?")
        direction = data.get("direction", "NEUTRAL")
        tag = "✅" if data.get("tradeable") else "🟡" if data.get("avg_score", 0) >= 5.0 else "⚪"
        label = f"{tag} {inst.display_name} ({sym}) — {direction} {grade}"
        trade_options[label] = (sym, data)

    if not trade_options:
        st.warning("No instruments available")
        return

    col_sel, col_dir = st.columns([3, 1])
    with col_sel:
        selected_label = st.selectbox("Instrument", list(trade_options.keys()), key="exec_instrument")
    sym, data = trade_options[selected_label]
    inst = data["instrument"]

    with col_dir:
        sys_dir = data.get("direction", "NEUTRAL")
        dir_options = ["BUY", "SELL"]
        default_idx = 0 if sys_dir == "LONG" else 1 if sys_dir == "SHORT" else 0
        direction = st.selectbox("Direction", dir_options, index=default_idx, key="exec_direction")

    try:
        from data.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        mt5.connect()
        sym_info = mt5.get_symbol_info(sym)
        acct = mt5.get_account_info()
        balance = acct.get("balance", 50000)
        tick = mt5.get_current_tick(sym)
        live_price = tick.get("ask", data.get("price", 0)) if direction == "BUY" else tick.get("bid", data.get("price", 0))
    except Exception:
        sym_info = {}
        balance = 50000
        live_price = data.get("price", 0)

    point = sym_info.get("point", inst.pip_size if inst.pip_size else 0.0001)
    vol_min = sym_info.get("volume_min", 0.01)
    vol_max = sym_info.get("volume_max", 100.0)
    vol_step = sym_info.get("volume_step", 0.01)
    spread = sym_info.get("spread", 0)
    digits = sym_info.get("digits", 5)

    price_color = "#00e676" if direction == "BUY" else "#ff5252"
    st.markdown(
        f'<div class="exec-box">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<div><span style="font-size:16px;font-weight:700">{inst.display_name}</span>'
        f' <span style="color:#546e7a;font-size:12px">({sym})</span></div>'
        f'<div><span style="font-size:22px;font-weight:800;color:{price_color}">{live_price:.{digits}f}</span>'
        f' <span style="color:#546e7a;font-size:11px">spread: {spread}</span></div>'
        f'</div>'
        f'<div style="color:#78909c;font-size:11px;margin-top:4px">'
        f'System: {sys_dir} · Grade: {data.get("grade", "?")} · QAS: {data.get("qas", 0):.3f}'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    setup = data.get("setup")
    atr = data.get("atr", 0)
    pip = inst.pip_size if inst.pip_size > 0 else point

    if setup and hasattr(setup, "stop_loss"):
        default_sl = setup.stop_loss
        default_tp1 = setup.tp1
        default_tp2 = setup.tp2 if setup.tp2 else (setup.tp1 * 1.5 if setup.tp1 else 0)
        default_tp3 = setup.tp3 if setup.tp3 else 0
    elif atr > 0:
        if direction == "BUY":
            default_sl = round(live_price - atr * 1.5, digits)
            default_tp1 = round(live_price + atr * 2.0, digits)
            default_tp2 = round(live_price + atr * 3.5, digits)
            default_tp3 = round(live_price + atr * 5.0, digits)
        else:
            default_sl = round(live_price + atr * 1.5, digits)
            default_tp1 = round(live_price - atr * 2.0, digits)
            default_tp2 = round(live_price - atr * 3.5, digits)
            default_tp3 = round(live_price - atr * 5.0, digits)
    else:
        default_sl = 0.0
        default_tp1 = 0.0
        default_tp2 = 0.0
        default_tp3 = 0.0

    col_sl, col_tp1, col_tp2, col_tp3 = st.columns(4)
    with col_sl:
        sl_price = st.number_input("Stop Loss", value=float(default_sl), format=f"%.{digits}f", key="exec_sl")
    with col_tp1:
        tp1_price = st.number_input("TP1 (40%)", value=float(default_tp1), format=f"%.{digits}f", key="exec_tp1")
    with col_tp2:
        tp2_price = st.number_input("TP2 (30%)", value=float(default_tp2), format=f"%.{digits}f", key="exec_tp2")
    with col_tp3:
        tp3_price = st.number_input("TP3 (30%)", value=float(default_tp3), format=f"%.{digits}f", key="exec_tp3")

    col_risk, col_lots, col_trail = st.columns(3)

    with col_risk:
        try:
            from execution.risk_manager import RiskManager
            rm = RiskManager()
            risk_info = rm.calculate_risk_pct(
                setup_grade=data.get("grade", "NO"),
                atr_ratio=1.0,
                intermarket_alignment="mostly_aligned",
            )
            auto_risk = risk_info.get("final_risk_pct", 1.0)
        except Exception:
            auto_risk = 1.0
        safe_risk = round(max(0.1, float(auto_risk)), 1)
        # Purge ALL old risk keys that may hold stale 0.0
        for _old in ["exec_risk", "exec_risk_v2", "exec_risk_v3"]:
            if _old in st.session_state:
                try:
                    del st.session_state[_old]
                except Exception:
                    pass
        risk_pct = st.number_input("Risk %", value=safe_risk, min_value=0.1, max_value=5.0, step=0.1)

    with col_lots:
        stop_dist = abs(live_price - sl_price) if sl_price > 0 else 0
        stop_pips = stop_dist / pip if pip > 0 else 0
        pip_val_lot = inst.pip_value_per_lot if hasattr(inst, "pip_value_per_lot") and inst.pip_value_per_lot > 0 else 10.0

        if stop_pips > 0:
            try:
                from execution.risk_manager import RiskManager
                rm2 = RiskManager()
                size_info = rm2.calculate_position_size(
                    account_balance=balance, risk_pct=risk_pct,
                    stop_distance_pips=stop_pips, pip_value_per_lot=pip_val_lot,
                    volume_step=vol_step, volume_min=vol_min, volume_max=vol_max,
                )
                auto_lots = size_info.get("lots", vol_min)
            except Exception:
                auto_lots = vol_min
        else:
            auto_lots = vol_min
        lots = st.number_input("Volume (lots)", value=float(auto_lots), min_value=float(vol_min), max_value=float(vol_max), step=float(vol_step), key="exec_lots")

    with col_trail:
        trailing_on = st.checkbox("Trailing Stop", value=True, key="exec_trail")
        order_type = st.radio("Order Type", ["Market", "Limit"], horizontal=True, key="exec_otype")

    risk_amt = balance * (risk_pct / 100)
    rr_tp1 = abs(tp1_price - live_price) / stop_dist if stop_dist > 0 else 0
    rr_tp2 = abs(tp2_price - live_price) / stop_dist if stop_dist > 0 else 0

    st.markdown(
        f'<div style="background:#0d1b2a;border:1px solid #1b3a5a;border-radius:8px;padding:10px;font-size:12px;color:#90a4ae">'
        f'Balance: <b style="color:#fff">${balance:,.0f}</b> · '
        f'Risk: <b style="color:#ff9800">${risk_amt:,.0f}</b> ({risk_pct:.1f}%) · '
        f'Lots: <b style="color:#fff">{lots:.2f}</b> · '
        f'SL: <b style="color:#ff5252">{stop_pips:.0f}p</b> · '
        f'R:R TP1 <b style="color:#00e676">{rr_tp1:.1f}</b> · TP2 <b style="color:#00e676">{rr_tp2:.1f}</b> · '
        f'Trail: <b>{"ON" if trailing_on else "OFF"}</b></div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    col_buy, col_sell, col_space = st.columns([1, 1, 2])
    with col_buy:
        buy_clicked = st.button("🟢 EXECUTE BUY", key="exec_buy_btn", type="primary",
                                disabled=(direction != "BUY"), use_container_width=True)
    with col_sell:
        sell_clicked = st.button("🔴 EXECUTE SELL", key="exec_sell_btn", type="primary",
                                 disabled=(direction != "SELL"), use_container_width=True)

    if buy_clicked or sell_clicked:
        exec_dir = "BUY" if buy_clicked else "SELL"
        with st.spinner(f"Placing {exec_dir} order on {sym}..."):
            try:
                from data.mt5_connector import MT5Connector
                from execution.order_manager import OrderManager
                mt5_conn = MT5Connector()
                mt5_conn.connect()
                om = OrderManager(mt5_conn)

                if order_type == "Market":
                    result = om.place_market_order(
                        symbol=sym, direction=exec_dir, volume=lots,
                        sl=sl_price, tp=tp1_price,
                        comment=f"IFC_{data.get('grade', 'M')}_{exec_dir[:1]}",
                    )
                else:
                    otype = "BUY_LIMIT" if exec_dir == "BUY" else "SELL_LIMIT"
                    result = om.place_pending_order(
                        symbol=sym, direction=exec_dir, order_type=otype,
                        price=live_price, volume=lots, sl=sl_price, tp=tp1_price,
                        comment=f"IFC_{data.get('grade', 'M')}_{exec_dir[:1]}",
                    )

                if result.get("success"):
                    ticket = result.get("ticket", "?")
                    fill_price = result.get("price", live_price)
                    st.markdown(
                        f'<div class="exec-result">'
                        f'<div style="font-size:16px;font-weight:800;color:#00e676">✅ ORDER FILLED</div>'
                        f'<div style="font-size:13px;color:#e0e0e0;margin-top:6px">'
                        f'Ticket: <b>#{ticket}</b> · {exec_dir} {lots:.2f} lots @ {fill_price:.{digits}f}<br>'
                        f'SL: {sl_price:.{digits}f} · TP1: {tp1_price:.{digits}f} · Trail: {"ON" if trailing_on else "OFF"}'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                    st.balloons()
                else:
                    st.error(f"❌ Order failed: {result.get('error', 'Unknown')}")
            except Exception as e:
                st.error(f"❌ Execution error: {e}")

    # ── Manage Open Positions ──
    st.markdown("---")
    st.markdown("##### 💼 Manage Open Positions")

    try:
        from data.mt5_connector import MT5Connector
        from execution.order_manager import OrderManager
        mt5_mgr = MT5Connector()
        mt5_mgr.connect()
        positions = mt5_mgr.get_open_positions()
        om_mgr = OrderManager(mt5_mgr)

        if not positions:
            st.caption("No open positions")
        else:
            for pos in positions:
                ticket = pos.get("ticket", 0)
                p_sym = pos.get("symbol", "?")
                p_type = "BUY" if pos.get("type") == 0 else "SELL"
                p_vol = pos.get("volume", 0)
                p_profit = pos.get("profit", 0)
                p_sl = pos.get("sl", 0)
                p_tp = pos.get("tp", 0)
                p_open = pos.get("open_price", 0)
                p_cur = pos.get("current_price", 0)
                pnl_color = "#00e676" if p_profit >= 0 else "#ff5252"

                pos_html = (
                    f'<div class="exec-box" style="padding:10px 14px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center">'
                    f'<div><span style="font-size:14px;font-weight:700">#{ticket}</span>'
                    f' <span style="color:{"#00e676" if p_type == "BUY" else "#ff5252"};font-weight:700">{p_type}</span>'
                    f' {p_sym} · {p_vol} lots</div>'
                    f'<span style="font-size:16px;font-weight:800;color:{pnl_color}">{p_profit:+,.2f}</span>'
                    f'</div>'
                    f'<div style="font-size:11px;color:#78909c;margin-top:4px">'
                    f'Open: {p_open} · Current: {p_cur} · SL: {p_sl} · TP: {p_tp}</div></div>'
                )
                st.markdown(pos_html, unsafe_allow_html=True)

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    if st.button("Close Full", key=f"close_{ticket}"):
                        res = om_mgr.close_position(ticket)
                        if res.get("success"):
                            st.success(f"Closed #{ticket}")
                            st.rerun()
                        else:
                            st.error(f"Failed: {res.get('error')}")
                with c2:
                    if st.button("Close 50%", key=f"partial_{ticket}"):
                        half = round(p_vol / 2, 2)
                        if half >= 0.01:
                            res = om_mgr.close_partial(ticket, half)
                            if res.get("success"):
                                st.success(f"Partial close #{ticket}")
                                st.rerun()
                            else:
                                st.error(f"Failed: {res.get('error')}")
                        else:
                            st.warning("Volume too small")
                with c3:
                    if st.button("SL → BE", key=f"be_{ticket}"):
                        res = om_mgr.modify_position(ticket, new_sl=p_open)
                        if res.get("success"):
                            st.success(f"SL → breakeven #{ticket}")
                        else:
                            st.error(f"Failed: {res.get('error')}")
                with c4:
                    if st.button("Trail SL", key=f"trail_{ticket}"):
                        if p_type == "BUY" and p_cur > p_open:
                            new_sl = round(p_cur - (p_cur - p_open) * 0.3, 5)
                            new_sl = max(new_sl, p_open)
                        elif p_type == "SELL" and p_cur < p_open:
                            new_sl = round(p_cur + (p_open - p_cur) * 0.3, 5)
                            new_sl = min(new_sl, p_open)
                        else:
                            new_sl = p_sl
                        res = om_mgr.modify_position(ticket, new_sl=new_sl)
                        if res.get("success"):
                            st.success(f"Trail updated #{ticket}")
                        else:
                            st.error(f"Failed: {res.get('error')}")
    except Exception as e:
        st.caption(f"Cannot manage positions: {e}")

    # ── Smart Recommendation ──
    st.markdown("---")
    st.markdown("##### 🎯 Smart Order Recommendation")

    best_sym, best_data, best_qas = None, None, 0
    for sym_r, d_r in results.items():
        if d_r.get("tradeable") and d_r.get("qas", 0) > best_qas:
            best_qas = d_r.get("qas", 0)
            best_sym = sym_r
            best_data = d_r

    if best_data:
        try:
            from execution.smart_orders import generate_recommendation, format_card_html
            from data.mt5_connector import MT5Connector
            from execution.order_manager import OrderManager
            mt5_rec = MT5Connector()
            mt5_rec.connect()
            acct_rec = mt5_rec.get_account_info()

            rec = generate_recommendation(
                instrument=best_data["instrument"],
                current_price=best_data.get("price", 0),
                atr=best_data.get("atr", 0),
                signals=best_data.get("signals", []),
                evaluation=best_data.get("evaluation", {}),
                account_balance=acct_rec.get("balance", 50000),
            )
            if rec:
                card_html = format_card_html(rec)
                st.markdown(card_html, unsafe_allow_html=True)

                if st.button("⚡ Execute Recommendation", key="exec_rec_btn", type="primary"):
                    with st.spinner("Executing..."):
                        try:
                            om_rec = OrderManager(mt5_rec)
                            rec_dir = "BUY" if rec.direction == "LONG" else "SELL"
                            res = om_rec.place_market_order(
                                symbol=best_data["instrument"].mt5_symbol,
                                direction=rec_dir, volume=rec.position_size,
                                sl=rec.stop_loss, tp=rec.tp1,
                                comment=f"IFC_REC_{rec.grade}",
                            )
                            if res.get("success"):
                                st.success(f"✅ Executed! Ticket #{res.get('ticket')}")
                                st.balloons()
                            else:
                                st.error(f"❌ {res.get('error')}")
                        except Exception as e:
                            st.error(f"❌ {e}")
            else:
                st.caption("No recommendation for current conditions")
        except Exception as e:
            st.caption(f"Recommendation unavailable: {e}")
    else:
        st.caption("No tradeable instruments for recommendation")


# ═══════════════════════════════════════════════════════════════════════
# Main Render Entry Point
# ═══════════════════════════════════════════════════════════════════════
def render():
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Header ──
    hdr_l, hdr_r = st.columns([6, 1])
    with hdr_l:
        st.markdown(
            '<h1 style="margin:0;padding:0;font-size:26px;letter-spacing:-.5px">'
            '📡 IFC Pro Monitor</h1>',
            unsafe_allow_html=True,
        )
    with hdr_r:
        auto_on = st.toggle("Auto", value=True, key="pro_auto")

    # ── Account bar ──
    _render_account()
    st.markdown("")

    # ── Run pipeline scan ──
    placeholder = st.empty()
    with placeholder:
        with st.spinner("Scanning all instruments..."):
            results = _scan_all()
    placeholder.empty()

    # ── Summary stats ──
    total          = len(results)
    tradeable_cnt  = sum(1 for d in results.values() if d.get("tradeable"))
    long_cnt       = sum(1 for d in results.values() if d.get("direction") == "LONG"  and d.get("avg_score", 0) >= 5.0)
    short_cnt      = sum(1 for d in results.values() if d.get("direction") == "SHORT" and d.get("avg_score", 0) >= 5.0)
    err_cnt        = sum(1 for d in results.values() if d.get("error") and not d.get("signals"))
    has_setup      = sum(1 for d in results.values() if d.get("setup"))
    scan_times     = [d.get("elapsed_ms", 0) for d in results.values() if d.get("elapsed_ms", 0) > 0]
    avg_ms         = np.mean(scan_times) if scan_times else 0

    cols = st.columns([1, 1, 1, 1, 1, 1, 2])
    with cols[0]: st.metric("Scanned", f"{total - err_cnt}/{total}")
    with cols[1]: st.metric("Tradeable", str(tradeable_cnt))
    with cols[2]: st.metric("Long", str(long_cnt))
    with cols[3]: st.metric("Short", str(short_cnt))
    with cols[4]: st.metric("Setups", str(has_setup))
    with cols[5]: st.metric("Avg Scan", f"{avg_ms:.0f}ms")
    with cols[6]: st.caption(f"Last scan: {datetime.now().strftime('%H:%M:%S')}")

    st.markdown("---")

    # ── Tabs ──
    tab_sig, tab_grid, tab_scalp, tab_exec, tab_pos, tab_sent = st.tabs([
        "🎯 Trade Signals", "📊 All Instruments", "⚡ Scalping", "🔥 Execute Trade",
        "💼 Positions", "📰 Sentiment & Intermarket",
    ])

    with tab_sig:
        _render_signals(results)

    with tab_grid:
        cat = st.radio(
            "Category", ["ALL", "forex", "index", "commodity", "crypto", "stock"],
            horizontal=True, key="grid_cat",
        )
        _render_grid(results, cat)

    with tab_scalp:
        _render_scalping(results)

    with tab_exec:
        _render_execution(results)

    with tab_pos:
        _render_positions()

    with tab_sent:
        _render_sentiment(results)

    # ── Auto-refresh ──
    if auto_on:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=60_000, limit=None, key="pro_auto_counter")
        except ImportError:
            st.sidebar.caption("Install `streamlit-autorefresh` for auto-refresh")
            time.sleep(60)
            st.rerun()
