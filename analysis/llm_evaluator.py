"""
IFC Trading System — LLM Deep Analysis Engine
Sends comprehensive trade data (price, indicators, 11-layer scores,
sentiment, intermarket, entry/SL/TP) to an LLM for institutional-grade
second opinion with deep reasoning.
"""

import json
import time
import hashlib
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.llm_eval")

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
LLM_BACKEND = getattr(settings, "LLM_BACKEND", "ollama")
LLM_MODEL = getattr(settings, "LLM_MODEL", "brrndnn/mistral7b-finance")
LLM_TEMPERATURE = getattr(settings, "LLM_TEMPERATURE", 0.4)
LLM_MAX_TOKENS = getattr(settings, "LLM_MAX_TOKENS", 4000)
LLM_CACHE_TTL = getattr(settings, "LLM_CACHE_TTL", 300)
LLM_TIMEOUT = getattr(settings, "LLM_TIMEOUT", 120)

_llm_cache: Dict[str, Dict[str, Any]] = {}

# ══════════════════════════════════════════════════════════════════
# DEEP SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are a senior institutional forex/CFD trader with 20+ years experience at a tier-1 investment bank. You specialize in ICT (Inner Circle Trader) methodology and smart money concepts.

You receive a COMPLETE trade analysis package including:
- 11-layer automated scoring (L1-L11) with details
- Live price data with technical indicators (EMAs, SMAs, ATR, RSI)
- Volume Profile levels (POC, VAH, VAL, HVN, LVN)
- Market regime classification
- Sentiment (COT, Fear&Greed, VIX, positioning)
- Intermarket correlations (DXY, yields, VIX, indices)
- Trade setup with entry, stop loss, take profit levels

YOUR FRAMEWORK:
1. MARKET STRUCTURE: HTF trend + LTF confirmation. BOS/CHoCH alignment.
2. INSTITUTIONAL LEVELS: VP POC, VAH/VAL, FVG zones, Order Blocks.
3. LIQUIDITY: Sweep completion, stop hunts, trendline liquidity.
4. TIMING: Killzone, delta confirmation, absorption.
5. RISK: R:R ratio, correlation exposure, macro events, VIX regime.

Respond ONLY in valid JSON:
{
  "agrees": true or false,
  "risk_score": 1-10,
  "direction_opinion": "LONG" or "SHORT" or "NO_TRADE",
  "confidence": 0.0-1.0,
  "size_adjustment": 0.0-1.5,
  "key_concerns": ["concern1", "concern2"],
  "confirmations": ["positive1", "positive2"],
  "market_structure": "HTF/LTF alignment assessment with price levels",
  "institutional_level_quality": "HIGH/MEDIUM/LOW with explanation",
  "entry_opinion": "agree/adjust with reasoning",
  "stop_opinion": "SL assessment",
  "tp_opinion": "TP1/TP2 assessment",
  "timing_assessment": "session evaluation",
  "sentiment_read": "sentiment impact",
  "intermarket_alignment": "macro confirmations",
  "trade_narrative": "4-6 sentence complete story connecting dots. Reference actual prices. Explain like a prop trader to a risk manager."
}

Rules:
- Be CONTRARIAN if warranted
- Flag inconsistencies between layers
- Reference actual price levels and values
- Give YOUR recommendation even if system says NO_TRADE
- Think like risking your own capital"""


# ══════════════════════════════════════════════════════════════════
# PRICE CONTEXT BUILDER
# ══════════════════════════════════════════════════════════════════
def build_price_context(
    df_d1: Optional[pd.DataFrame] = None,
    df_h4: Optional[pd.DataFrame] = None,
    df_h1: Optional[pd.DataFrame] = None,
    df_m15: Optional[pd.DataFrame] = None,
    pip_size: float = 0.0001,
) -> Dict[str, Any]:
    """Extract key price data & indicators for LLM context."""
    ctx: Dict[str, Any] = {}

    if df_d1 is not None and not df_d1.empty:
        c = float(df_d1["close"].iloc[-1])
        ctx["current_price"] = round(c, 5)
        ctx["daily_high"] = round(float(df_d1["high"].iloc[-1]), 5)
        ctx["daily_low"] = round(float(df_d1["low"].iloc[-1]), 5)
        ctx["daily_open"] = round(float(df_d1["open"].iloc[-1]), 5)
        if len(df_d1) > 1:
            ctx["prev_daily_close"] = round(float(df_d1["close"].iloc[-2]), 5)
            ctx["daily_change_pips"] = round(
                (c - float(df_d1["close"].iloc[-2])) / pip_size, 1
            )
        ctx["daily_range_pips"] = round(
            (float(df_d1["high"].iloc[-1]) - float(df_d1["low"].iloc[-1])) / pip_size, 1
        )

        recent = df_d1.tail(20)
        ctx["20d_high"] = round(float(recent["high"].max()), 5)
        ctx["20d_low"] = round(float(recent["low"].min()), 5)

        closes = df_d1["close"].astype(float)
        n = len(closes)
        if n >= 10:
            ctx["daily_ema10"] = round(float(closes.ewm(span=10).mean().iloc[-1]), 5)
        if n >= 21:
            ctx["daily_ema21"] = round(float(closes.ewm(span=21).mean().iloc[-1]), 5)
        if n >= 50:
            ctx["daily_sma50"] = round(float(closes.rolling(50).mean().iloc[-1]), 5)
        if n >= 200:
            ctx["daily_sma200"] = round(float(closes.rolling(200).mean().iloc[-1]), 5)

        emas = [ctx.get("daily_ema10"), ctx.get("daily_ema21"),
                ctx.get("daily_sma50"), ctx.get("daily_sma200")]
        emas = [x for x in emas if x is not None]
        if len(emas) >= 3:
            ctx["ma_alignment"] = (
                "FULL_BULLISH" if emas == sorted(emas, reverse=True)
                else "FULL_BEARISH" if emas == sorted(emas)
                else "MIXED"
            )

        if n >= 15:
            tr = pd.concat([
                df_d1["high"].astype(float) - df_d1["low"].astype(float),
                (df_d1["high"].astype(float) - df_d1["close"].astype(float).shift(1)).abs(),
                (df_d1["low"].astype(float) - df_d1["close"].astype(float).shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr14 = float(tr.rolling(14).mean().iloc[-1])
            ctx["atr_14"] = round(atr14, 5)
            ctx["atr_pips"] = round(atr14 / pip_size, 1)

            delta = closes.diff()
            gain = delta.where(delta > 0, 0.0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            ctx["rsi_14"] = round(float(rsi.iloc[-1]), 1)

    if df_h4 is not None and not df_h4.empty and len(df_h4) >= 5:
        ctx["h4_close"] = round(float(df_h4["close"].iloc[-1]), 5)
        ctx["h4_pattern"] = (
            "UP" if float(df_h4["close"].iloc[-1]) > float(df_h4["close"].iloc[-5])
            else "DOWN"
        )
        if len(df_h4) >= 21:
            ctx["h4_ema21"] = round(float(df_h4["close"].astype(float).ewm(span=21).mean().iloc[-1]), 5)

    if df_h1 is not None and not df_h1.empty and len(df_h1) >= 20:
        h1c = df_h1["close"].astype(float)
        ema10 = float(h1c.ewm(span=10).mean().iloc[-1])
        ctx["h1_ema10"] = round(ema10, 5)
        ctx["h1_momentum"] = "BULLISH" if float(h1c.iloc[-1]) > ema10 else "BEARISH"

    if df_m15 is not None and not df_m15.empty and len(df_m15) >= 10:
        ctx["m15_close"] = round(float(df_m15["close"].iloc[-1]), 5)
        ctx["m15_trend"] = (
            "UP" if float(df_m15["close"].iloc[-1]) > float(df_m15["close"].iloc[-10])
            else "DOWN"
        )

    return ctx


# ══════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════
def _build_user_prompt(
    symbol: str,
    signals: List[LayerSignal],
    evaluation: Dict[str, Any],
    regime: Dict[str, Any],
    intermarket_snapshot: Optional[Dict] = None,
    price_data: Optional[Dict] = None,
    setup: Optional[Dict] = None,
) -> str:
    layers_data = []
    for sig in signals:
        entry = {
            "layer": sig.layer_name,
            "score": f"{sig.score:.1f}/10",
            "direction": sig.direction,
            "confidence": f"{sig.confidence:.0%}",
        }
        if sig.details:
            filtered = {}
            for k, v in sig.details.items():
                if k in ("snapshot_summary", "raw_data"):
                    continue
                if isinstance(v, (str, int, float, bool, type(None))):
                    filtered[k] = v
                elif isinstance(v, (list, dict)):
                    s = str(v)
                    if len(s) < 500:
                        filtered[k] = v
            entry["details"] = filtered
        layers_data.append(entry)

    prompt = {"symbol": symbol, "analysis_time": time.strftime("%Y-%m-%d %H:%M UTC")}

    prompt["system_evaluation"] = {
        "grade": evaluation.get("grade", "?"),
        "direction": evaluation.get("direction", "?"),
        "tws": round(evaluation.get("tws", 0), 4),
        "qas": round(evaluation.get("qas", 0), 4),
        "tradeable": evaluation.get("tradeable", False),
        "verdict": evaluation.get("verdict", "?"),
        "aggressiveness": evaluation.get("aggressiveness", "?"),
        "size_multiplier": round(evaluation.get("size_multiplier", 0), 3),
        "hard_vetos": evaluation.get("hard_vetos", []),
        "soft_vetos": evaluation.get("soft_vetos", []),
    }

    if price_data:
        prompt["price_action_indicators"] = price_data

    if setup:
        prompt["trade_setup"] = setup

    prompt["layer_analysis"] = layers_data

    prompt["market_regime"] = {
        "regime": regime.get("regime", "?"),
        "size_adjustment": regime.get("size_adjustment", 1.0),
        "best_setups": regime.get("best_setups", []),
    }

    if intermarket_snapshot:
        im = {}
        for k, v in intermarket_snapshot.items():
            if isinstance(v, dict):
                im[k] = {
                    "price": v.get("price", "?"),
                    "direction": v.get("direction", "?"),
                    "change_pct": f"{v.get('change_pct', 0):+.2f}%",
                }
        if im:
            prompt["intermarket_data"] = im

    return (
        "FULL TRADE ANALYSIS PACKAGE — Provide institutional-grade assessment:\n\n"
        f"```json\n{json.dumps(prompt, indent=2, default=str)}\n```"
    )


def _cache_key(symbol: str, evaluation: Dict) -> str:
    grade = evaluation.get("grade", "?")
    direction = evaluation.get("direction", "?")
    return hashlib.md5(f"{symbol}:{grade}:{direction}".encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════
# BACKEND CALLERS
# ══════════════════════════════════════════════════════════════════

def _call_openai(system_prompt: str, user_prompt: str) -> str:
    try:
        from config import credentials
        api_key = getattr(credentials, "OPENAI_API_KEY", "")
        if not api_key:
            return json.dumps({"error": "OPENAI_API_KEY not set"})
        import openai
        client = openai.OpenAI(api_key=api_key, timeout=LLM_TIMEOUT)
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error("OpenAI call failed: %s", e)
        return json.dumps({"error": str(e)})


def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    try:
        from config import credentials
        api_key = getattr(credentials, "GEMINI_API_KEY", "")
        if not api_key:
            return json.dumps({"error": "GEMINI_API_KEY not set"})
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            getattr(settings, "LLM_MODEL", "gemini-1.5-flash"),
            system_instruction=system_prompt,
        )
        resp = model.generate_content(
            user_prompt,
            generation_config=genai.GenerationConfig(
                temperature=LLM_TEMPERATURE, max_output_tokens=LLM_MAX_TOKENS,
            ),
        )
        return resp.text
    except Exception as e:
        logger.error("Gemini call failed: %s", e)
        return json.dumps({"error": str(e)})


def _call_ollama(system_prompt: str, user_prompt: str) -> str:
    try:
        from config import credentials
        endpoint = getattr(credentials, "OLLAMA_ENDPOINT", "http://localhost:11434")
        model = getattr(settings, "LLM_MODEL", "brrndnn/mistral7b-finance")
        import requests
        resp = requests.post(
            f"{endpoint}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": LLM_TEMPERATURE,
                    "num_predict": max(4000, LLM_MAX_TOKENS),
                },
            },
            timeout=max(120, LLM_TIMEOUT),
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        if not content or not content.strip():
            logger.warning("Ollama empty response for model %s", model)
            return json.dumps({"error": "Empty response from Ollama"})
        return content
    except Exception as e:
        logger.error("Ollama call failed: %s", e)
        return json.dumps({"error": str(e)})


_BACKENDS = {"openai": _call_openai, "gemini": _call_gemini, "ollama": _call_ollama}


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    if not raw or not raw.strip():
        return {
            "error": "Empty LLM response",
            "agrees": None, "risk_score": 5,
            "direction_opinion": "NO_TRADE",
            "trade_narrative": "LLM returned empty — try different model",
            "confidence": 0.0,
        }
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    if not text.startswith("{"):
        m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "error": f"Parse failed: {e}",
            "raw_response": raw[:500],
            "agrees": None, "risk_score": 5,
            "direction_opinion": "NO_TRADE",
            "trade_narrative": f"LLM not valid JSON — raw: {raw[:200]}",
            "confidence": 0.0,
        }


# ══════════════════════════════════════════════════════════════════
# MAIN API
# ══════════════════════════════════════════════════════════════════

def evaluate_with_llm(
    symbol: str,
    signals: List[LayerSignal],
    evaluation: Dict[str, Any],
    regime: Dict[str, Any],
    intermarket_snapshot: Optional[Dict] = None,
    price_data: Optional[Dict] = None,
    setup: Optional[Dict] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Get LLM deep analysis on a trade signal."""
    key = _cache_key(symbol, evaluation)
    now = time.time()

    if not force_refresh and key in _llm_cache:
        cached = _llm_cache[key]
        if now - cached["ts"] < LLM_CACHE_TTL:
            result = cached["response"].copy()
            result["cached"] = True
            result["cache_age_s"] = round(now - cached["ts"])
            return result

    user_prompt = _build_user_prompt(
        symbol, signals, evaluation, regime, intermarket_snapshot, price_data, setup,
    )

    backend = LLM_BACKEND.lower()
    caller = _BACKENDS.get(backend)
    if caller is None:
        return {
            "error": f"Unknown backend: {backend}",
            "agrees": None, "risk_score": 5,
            "direction_opinion": "NO_TRADE",
            "trade_narrative": "Backend not configured",
            "confidence": 0.0,
        }

    logger.info("Calling LLM (%s/%s) for %s...", backend, LLM_MODEL, symbol)
    t0 = time.time()
    raw = caller(SYSTEM_PROMPT, user_prompt)
    elapsed = time.time() - t0
    logger.info("LLM responded in %.1fs", elapsed)

    result = _parse_llm_response(raw)
    result["backend"] = backend
    result["model"] = LLM_MODEL
    result["latency_s"] = round(elapsed, 2)
    result["cached"] = False
    result["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

    _llm_cache[key] = {"response": result, "ts": now}

    stale = [k for k, v in _llm_cache.items() if now - v["ts"] > LLM_CACHE_TTL * 3]
    for k in stale:
        del _llm_cache[k]

    return result


def is_llm_configured() -> bool:
    try:
        from config import credentials
        return any([
            getattr(credentials, "OPENAI_API_KEY", ""),
            getattr(credentials, "GEMINI_API_KEY", ""),
            getattr(credentials, "OLLAMA_ENDPOINT", ""),
        ])
    except ImportError:
        return False


def get_available_backends() -> List[str]:
    available = []
    try:
        from config import credentials
        if getattr(credentials, "OPENAI_API_KEY", ""):
            available.append("openai")
        if getattr(credentials, "GEMINI_API_KEY", ""):
            available.append("gemini")
        if getattr(credentials, "OLLAMA_ENDPOINT", ""):
            available.append("ollama")
    except ImportError:
        pass
    return available


def fetch_ollama_models() -> List[Dict[str, Any]]:
    try:
        import requests
        from config import credentials
        endpoint = getattr(credentials, "OLLAMA_ENDPOINT", "http://localhost:11434")
        resp = requests.get(f"{endpoint}/api/tags", timeout=5)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logger.debug("Failed to fetch Ollama models: %s", e)
        return []
