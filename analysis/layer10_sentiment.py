"""
IFC Trading System — Layer 10: Live Sentiment Analysis
Aggregates multiple sentiment sources into a composite score.

Tier 1 (Hard Data — 60% weight): Options PCR, Futures OI, Order Book, Dark Pool
Tier 2 (Flow Data — 25% weight): Funding rates, Exchange flows, Broker, ETF flows
Tier 3 (Soft Data — 15% weight): Social sentiment, Fear & Greed, News flow

Many sources require paid APIs. This implementation provides:
- Fear & Greed Index (free via CNN)
- VIX-based sentiment (from intermarket snapshot)
- Retail broker sentiment (Myfxbook scrape)
- COT positioning (via cot_reports library)
- Funding rate approximation for crypto (VIX-based proxy)
Components without data return 0 (neutral) and are excluded from weighting.

SPEED: Heavy caching at module level — COT file downloaded once per session,
Fear & Greed fetched once, Myfxbook tried once then blacklisted on 403.
"""

import time
from typing import Dict, Any, Optional, List

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer10")

# ══════════════════════════════════════════════════════════════════
# MODULE-LEVEL CACHES  (avoid repeat network calls)
# ══════════════════════════════════════════════════════════════════
_fear_greed_cache: Dict[str, Any] = {"data": None, "ts": 0, "ttl": 600}
_cot_cache: Dict[str, Any] = {"df": None, "ts": 0, "ttl": 1800}  # 30 min
_broker_cache: Dict[str, Any] = {"data": {}, "ts": 0, "ttl": 600, "blocked": False}

# ── Sentiment weight config ──────────────────────────────────────
_WEIGHTS = getattr(settings, "SENTIMENT_WEIGHTS", {
    "options_pcr": 0.15, "futures_oi": 0.15, "order_book": 0.10,
    "dark_pool": 0.10, "funding_rate": 0.10, "exchange_flows": 0.05,
    "broker_sentiment": 0.10, "etf_flows": 0.10,
    "social_sentiment": 0.05, "fear_greed": 0.05, "news_flow": 0.05,
})


# ══════════════════════════════════════════════════════════════════
# INDIVIDUAL SCORERS  (each returns dict with score/confidence/available)
# ══════════════════════════════════════════════════════════════════

def _score_fear_greed() -> Dict[str, Any]:
    """
    Fetch CNN Fear & Greed Index (cached 10 min).
    Contrarian: extreme fear → bullish, extreme greed → bearish.
    """
    now = time.time()
    if _fear_greed_cache["data"] is not None and now - _fear_greed_cache["ts"] < _fear_greed_cache["ttl"]:
        return _fear_greed_cache["data"]

    try:
        from data.sentiment import SentimentData
        fg = SentimentData.fetch_fear_greed()
        if fg.get("status") != "ok":
            result = {"score": 0, "confidence": 0, "available": False, "raw": fg}
            _fear_greed_cache.update(data=result, ts=now)
            return result

        value = fg["value"]
        zone = fg["zone"]

        if value <= 15:
            score = 3.0
        elif value <= 25:
            score = 2.0
        elif value <= 40:
            score = 1.0
        elif value <= 60:
            score = 0.0
        elif value <= 75:
            score = -1.0
        elif value <= 85:
            score = -2.0
        else:
            score = -3.0

        result = {
            "score": score,
            "confidence": 4,
            "available": True,
            "value": value,
            "zone": zone,
        }
        _fear_greed_cache.update(data=result, ts=now)
        return result
    except Exception as e:
        logger.debug("Fear & Greed unavailable: %s", e)
        result = {"score": 0, "confidence": 0, "available": False}
        _fear_greed_cache.update(data=result, ts=now)
        return result


def _score_vix_sentiment(snapshot: Optional[Dict] = None) -> Dict[str, Any]:
    """
    VIX-based sentiment (instant — no network call).
    """
    if not snapshot or "VIX" not in snapshot:
        return {"score": 0, "confidence": 0, "available": False}

    vix = snapshot["VIX"]
    level = vix.get("level")
    regime = vix.get("regime", "normal")

    if level is None:
        return {"score": 0, "confidence": 0, "available": False}

    if level > 35:
        score = 3.0
    elif level > 30:
        score = 2.0
    elif level > 25:
        score = 1.5
    elif level > 20:
        score = 1.0
    elif level > 15:
        score = 0.0
    elif level > 12:
        score = -1.0
    else:
        score = -2.0

    return {
        "score": score,
        "confidence": 4,
        "available": True,
        "vix_level": level,
        "vix_regime": regime,
    }


def _score_broker_sentiment(symbol: str) -> Dict[str, Any]:
    """
    Fetch Myfxbook retail sentiment (cached, skip if 403-blocked).
    """
    if _broker_cache["blocked"]:
        return {"score": 0, "confidence": 0, "available": False}

    clean_sym = symbol.rstrip("m") if symbol.endswith("m") else symbol

    now = time.time()
    if clean_sym in _broker_cache["data"] and now - _broker_cache["ts"] < _broker_cache["ttl"]:
        return _broker_cache["data"][clean_sym]

    try:
        from data.sentiment import SentimentData
        result = SentimentData.fetch_retail_sentiment(clean_sym)
        if result.get("status") != "ok":
            out = {"score": 0, "confidence": 0, "available": False}
            _broker_cache["data"][clean_sym] = out
            _broker_cache["ts"] = now
            return out

        long_pct = result["long_pct"]
        short_pct = result["short_pct"]

        if long_pct > 80:
            score = -3.0
        elif long_pct > 70:
            score = -2.0
        elif long_pct > 60:
            score = -1.0
        elif short_pct > 80:
            score = 3.0
        elif short_pct > 70:
            score = 2.0
        elif short_pct > 60:
            score = 1.0
        else:
            score = 0.0

        out = {
            "score": score,
            "confidence": 3,
            "available": True,
            "long_pct": long_pct,
            "short_pct": short_pct,
            "contrarian": result.get("contrarian_signal", False),
        }
        _broker_cache["data"][clean_sym] = out
        _broker_cache["ts"] = now
        return out
    except Exception as e:
        err_str = str(e)
        if "403" in err_str or "Forbidden" in err_str:
            logger.warning("Myfxbook blocked (403) — disabling for this session")
            _broker_cache["blocked"] = True
        else:
            logger.debug("Broker sentiment unavailable: %s", e)
        out = {"score": 0, "confidence": 0, "available": False}
        _broker_cache["data"][clean_sym] = out
        _broker_cache["ts"] = now
        return out


def _ensure_cot_df():
    """Download COT file ONCE per 30 min, cache as DataFrame."""
    now = time.time()
    if _cot_cache["df"] is not None and now - _cot_cache["ts"] < _cot_cache["ttl"]:
        return _cot_cache["df"]
    try:
        import cot_reports as cot
        from datetime import datetime as dt
        df = cot.cot_year(dt.now().year, cot_report_type="legacy_fut")
        _cot_cache["df"] = df
        _cot_cache["ts"] = now
        return df
    except Exception as e:
        logger.debug("COT download failed: %s", e)
        _cot_cache["ts"] = now  # Don't retry for ttl period
        return None


def _score_cot(instrument_name: str) -> Dict[str, Any]:
    """
    COT data for the instrument (uses cached DataFrame).
    """
    df = _ensure_cot_df()
    if df is None or df.empty:
        return {"score": 0, "confidence": 0, "available": False}

    try:
        mask = df["Market and Exchange Names"].str.contains(
            instrument_name, case=False, na=False
        )
        instrument_df = df[mask].sort_index()
        if instrument_df.empty:
            return {"score": 0, "confidence": 0, "available": False}

        latest = instrument_df.iloc[-1]

        def _get_col(row, candidates, default=0):
            for c in candidates:
                if c in row.index:
                    return int(row[c])
            return default

        _NC_LONG = ["Noncommercial Long", "Noncommercial Positions-Long (All)"]
        _NC_SHORT = ["Noncommercial Short", "Noncommercial Positions-Short (All)"]

        commercial_long = _get_col(latest,
            ["Commercial Long", "Commercial Positions-Long (All)"])
        commercial_short = _get_col(latest,
            ["Commercial Short", "Commercial Positions-Short (All)"])
        commercial_net = commercial_long - commercial_short

        noncommercial_long = _get_col(latest, _NC_LONG)
        noncommercial_short = _get_col(latest, _NC_SHORT)
        noncommercial_net = noncommercial_long - noncommercial_short

        extreme = False
        if len(instrument_df) >= 10:
            nc_long_col = next((c for c in _NC_LONG if c in instrument_df.columns), None)
            nc_short_col = next((c for c in _NC_SHORT if c in instrument_df.columns), None)
            if nc_long_col and nc_short_col:
                recent_nets = (
                    instrument_df[nc_long_col].astype(float)
                    - instrument_df[nc_short_col].astype(float)
                )
                rng = recent_nets.max() - recent_nets.min()
                if rng > 0:
                    pct_rank = (noncommercial_net - recent_nets.min()) / (rng + 1e-9)
                    extreme = pct_rank > 0.9 or pct_rank < 0.1

        if commercial_net > 0:
            score = 2.0 if extreme else 1.0
        elif commercial_net < 0:
            score = -2.0 if extreme else -1.0
        else:
            score = 0.0

        return {
            "score": score,
            "confidence": 4 if extreme else 3,
            "available": True,
            "commercial_net": commercial_net,
            "commercial_bias": "LONG" if commercial_net > 0 else "SHORT",
            "extreme": extreme,
        }
    except Exception as e:
        logger.debug("COT parse failed for %s: %s", instrument_name, e)
        return {"score": 0, "confidence": 0, "available": False}


def _score_crypto_funding(snapshot: Optional[Dict] = None, is_crypto: bool = False) -> Dict[str, Any]:
    """
    Crypto funding rates — tries Binance API first, falls back to VIX proxy.
    Positive funding = longs pay shorts (bearish pressure → score > 0 favours SHORT).
    Negative funding = shorts pay longs (bullish pressure → score < 0 favours LONG).
    """
    if not is_crypto:
        return {"score": 0, "confidence": 0, "available": False}

    # ── Try real Binance funding rate ──
    try:
        import requests as _req
        symbols_to_try = ["BTCUSDT", "ETHUSDT"]
        funding_rates = []
        for fsym in symbols_to_try:
            resp = _req.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": fsym, "limit": 1},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    funding_rates.append(float(data[0]["fundingRate"]))

        if funding_rates:
            avg_rate = sum(funding_rates) / len(funding_rates)
            # Typical range: -0.01 to +0.01 (1%)
            # Extreme: beyond ±0.003 (0.3%) per 8h
            score = 0.0
            if avg_rate > 0.003:
                score = 2.0   # Very high positive = bearish (crowded longs)
            elif avg_rate > 0.001:
                score = 1.0
            elif avg_rate < -0.003:
                score = -2.0  # Very negative = bullish (crowded shorts)
            elif avg_rate < -0.001:
                score = -1.0

            return {
                "score": score,
                "confidence": 3,
                "available": True,
                "proxy": False,
                "funding_rate": round(avg_rate, 6),
                "note": f"Binance avg funding rate: {avg_rate:.6f}",
            }
    except Exception as e:
        logger.debug("Binance funding rate fetch failed: %s", e)

    # ── Fallback: VIX-based proxy ──
    if not snapshot:
        return {"score": 0, "confidence": 0, "available": False}

    vix = snapshot.get("VIX", {})
    btc = snapshot.get("BTC", {})
    vix_level = vix.get("level")
    btc_dir = btc.get("direction", "UNKNOWN")

    if vix_level is None:
        return {"score": 0, "confidence": 0, "available": False}

    score = 0.0
    if vix_level < 15 and btc_dir == "RISING":
        score = -1.5
    elif vix_level < 15 and btc_dir == "FLAT":
        score = -1.0
    elif vix_level > 30 and btc_dir == "FALLING":
        score = 2.0
    elif vix_level > 25 and btc_dir == "FALLING":
        score = 1.0

    return {
        "score": score,
        "confidence": 2,
        "available": True,
        "proxy": True,
        "note": "VIX-based crypto funding proxy (Binance unavailable)",
    }


# ── COT instrument name mapping ─────────────────────────────────
_COT_NAMES = {
    "EURUSD": "EURO FX",
    "GBPUSD": "BRITISH POUND",
    "USDJPY": "JAPANESE YEN",
    "AUDUSD": "AUSTRALIAN DOLLAR",
    "USDCAD": "CANADIAN DOLLAR",
    "NZDUSD": "NEW ZEALAND DOLLAR",
    "USDCHF": "SWISS FRANC",
    "XAUUSD": "GOLD",
    "XAGUSD": "SILVER",
    "USOIL": "CRUDE OIL",
    "US30": "DOW JONES",
    "SPX500": "E-MINI S&P 500",
    "NAS100": "NASDAQ",
    "BTCUSD": "BITCOIN",
}


def compute_sentiment_composite(
    symbol: str,
    category: str = "forex",
    snapshot: Optional[Dict] = None,
    cot_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute the full sentiment composite score for a symbol.
    Returns dict with composite_score (-3 to +3), components, direction, confidence.

    Parameters
    ----------
    cot_name : If provided, overrides the hardcoded _COT_NAMES lookup (Enhancement Plan #11)
    """
    components = {}
    total_weight = 0.0
    weighted_sum = 0.0

    sym_clean = symbol.rstrip("m") if symbol.endswith("m") else symbol

    # 1. Fear & Greed (cached globally — single fetch)
    fg = _score_fear_greed()
    components["fear_greed"] = fg
    if fg["available"]:
        w = _WEIGHTS.get("fear_greed", 0.05)
        weighted_sum += fg["score"] * w
        total_weight += w

    # 2. VIX-based sentiment (instant — no network)
    vix_sent = _score_vix_sentiment(snapshot)
    components["vix_sentiment"] = vix_sent
    if vix_sent["available"]:
        w = _WEIGHTS.get("options_pcr", 0.15)
        weighted_sum += vix_sent["score"] * w
        total_weight += w

    # 3. Broker sentiment — forex only (cached, skipped if blocked)
    if category == "forex":
        broker = _score_broker_sentiment(symbol)
        components["broker_sentiment"] = broker
        if broker["available"]:
            w = _WEIGHTS.get("broker_sentiment", 0.10)
            weighted_sum += broker["score"] * w
            total_weight += w

    # 4. COT data (single file download, cached 30 min)
    # Use instrument's cot_name if provided, else fall back to hardcoded dict
    resolved_cot_name = cot_name or _COT_NAMES.get(sym_clean)
    if resolved_cot_name:
        cot = _score_cot(resolved_cot_name)
        components["cot_positioning"] = cot
        if cot["available"]:
            w = _WEIGHTS.get("futures_oi", 0.15)
            weighted_sum += cot["score"] * w
            total_weight += w

    # 5. Crypto funding proxy (instant)
    is_crypto = category == "crypto"
    funding = _score_crypto_funding(snapshot, is_crypto)
    components["funding_rate"] = funding
    if funding["available"]:
        w = _WEIGHTS.get("funding_rate", 0.10)
        weighted_sum += funding["score"] * w
        total_weight += w

    # Compute composite
    if total_weight > 0:
        composite = weighted_sum / total_weight
    else:
        composite = 0.0

    if composite > 0.5:
        direction = "LONG"
    elif composite < -0.5:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    available_confs = [c["confidence"] for c in components.values() if c.get("available")]
    avg_conf = sum(available_confs) / len(available_confs) if available_confs else 1.0

    if composite >= 2.0:
        zone = "EXTREME_BULLISH"
    elif composite >= 1.0:
        zone = "MODERATE_BULLISH"
    elif composite > -1.0:
        zone = "NEUTRAL"
    elif composite > -2.0:
        zone = "MODERATE_BEARISH"
    else:
        zone = "EXTREME_BEARISH"

    return {
        "composite_score": round(composite, 3),
        "zone": zone,
        "direction": direction,
        "confidence": avg_conf,
        "total_weight_used": round(total_weight, 3),
        "sources_available": sum(1 for c in components.values() if c.get("available")),
        "sources_total": len(components),
        "components": components,
    }


class SentimentLayer:
    """Layer 10 — Live Sentiment Analysis."""

    def analyze(
        self,
        instrument_key: str,
        category: str = "forex",
        snapshot: Optional[Dict] = None,
        cot_name: Optional[str] = None,
    ) -> LayerSignal:
        score = 5.0
        confidence = 0.3
        direction = "NEUTRAL"
        details = {}

        try:
            result = compute_sentiment_composite(
                symbol=instrument_key,
                category=category,
                snapshot=snapshot,
                cot_name=cot_name,
            )
            details = result

            composite = result["composite_score"]
            score = 5.0 + (composite / 3.0) * 5.0
            score = max(0.0, min(10.0, score))

            direction = result["direction"]
            confidence = result["confidence"] / 5.0

            if result["zone"] in ("EXTREME_BULLISH", "EXTREME_BEARISH"):
                details["extreme_warning"] = True
                details["contrarian_alert"] = f"Extreme {result['zone']} — contrarian signal active"

        except Exception as e:
            logger.error("Layer 10 analysis failed: %s", e, exc_info=True)
            details["error"] = str(e)

        return LayerSignal(
            layer_name="L10_Sentiment",
            direction=direction,
            score=round(score, 2),
            confidence=round(max(0.0, min(1.0, confidence)), 2),
            details=details,
        )
