"""
IFC Trading System — Layer 11: AI Composite Evaluation Engine
Combines regime context detection with the full 11-layer weighted scoring
matrix, QAS algorithm, veto system, and trade grade output.

This is the DECISION ENGINE from Part 15 of the plan.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer11")

# ── Layer weights from settings ──────────────────────────────────
_LAYER_WEIGHTS = getattr(settings, "LAYER_WEIGHTS", {
    "L1_Intermarket": 0.12, "L2_Trend": 0.16, "L3_VolumeProfile": 0.12,
    "L4_CandleDensity": 0.06, "L5_Liquidity": 0.10, "L6_FVG_OrderBlock": 0.14,
    "L7_OrderFlow": 0.10, "L8_Killzone": 0.08, "L9_Correlation": 0.05,
    "L10_Sentiment": 0.04, "L11_Regime": 0.03,
})

_QAS_GRADES = getattr(settings, "QAS_GRADE_THRESHOLDS", {
    "A+": 1.2, "A": 0.5, "B": 0.2,
})

_QAS_SIZES = getattr(settings, "QAS_SIZE_MULTIPLIERS", {
    "A+": 1.5, "A": 1.0, "B": 0.5, "NO": 0.0,
})

_HARD_VETO_LAYERS = getattr(settings, "HARD_VETO_LAYERS", ["L2_Trend", "L8_Killzone"])
_MAX_CORE_FAIL = getattr(settings, "MAX_CORE_LAYERS_FAILING", 2)
_SOFT_MIN_CONF = getattr(settings, "SOFT_VETO_MIN_CONFIDENCE", 3.0)

# Core layers (L1-L4) — structural foundation
_CORE_LAYERS = {"L1_Intermarket", "L2_Trend", "L3_VolumeProfile", "L4_CandleDensity"}


def _normalize_score(raw_score: float) -> float:
    """
    Convert a 0-10 layer score to the plan's -2 to +2 scale.
    0 → -2, 5 → 0, 10 → +2
    """
    return (raw_score - 5.0) / 2.5


def _confidence_to_5(confidence_01: float) -> float:
    """Convert 0-1 confidence to the plan's 1-5 scale."""
    return max(1.0, min(5.0, confidence_01 * 5.0))


def compute_tws(signals: List[LayerSignal], regime: str = "NORMAL") -> Dict[str, Any]:
    """
    Compute Total Weighted Score (TWS) from all layer signals.

    Each signal's 0-10 score is normalized to -2/+2, then multiplied
    by its layer weight (adjusted for regime). Sum = TWS.

    Parameters
    ----------
    signals : list of LayerSignals
    regime : current market regime (STRONG_TREND, VOLATILE, RANGE,
             TRANSITIONAL, NORMAL). Multipliers adjust layer weights
             so trending markets favour L2/L4 while ranging markets
             favour L3/L5/L6.
    """
    # Apply regime multipliers to layer weights
    regime_mults = settings.REGIME_WEIGHT_MULTIPLIERS.get(regime, {})
    adjusted_weights = {}
    for layer_name, base_weight in _LAYER_WEIGHTS.items():
        mult = regime_mults.get(layer_name, 1.0)
        adjusted_weights[layer_name] = base_weight * mult

    total = 0.0
    breakdown = []
    total_weight = 0.0

    for sig in signals:
        weight = adjusted_weights.get(sig.layer_name, 0.0)
        normalized = _normalize_score(sig.score)
        weighted = normalized * weight
        total += weighted
        total_weight += weight

        breakdown.append({
            "layer": sig.layer_name,
            "raw_score": sig.score,
            "normalized": round(normalized, 3),
            "weight": weight,
            "weighted_score": round(weighted, 4),
            "confidence": sig.confidence,
            "direction": sig.direction,
        })

    return {
        "tws": round(total, 4),
        "total_weight": round(total_weight, 3),
        "breakdown": breakdown,
        "regime": regime,
        "regime_multipliers_applied": bool(regime_mults),
    }


def compute_qas(tws: float, signals: List[LayerSignal]) -> float:
    """
    Quality-Adjusted Score = TWS × (avg_confidence / 5)
    where confidence is on 1-5 scale.
    """
    if not signals:
        return 0.0

    avg_conf_01 = sum(s.confidence for s in signals) / len(signals)
    avg_conf_5 = _confidence_to_5(avg_conf_01)
    return round(tws * (avg_conf_5 / 5.0), 4)


def determine_grade(qas: float) -> str:
    """Map QAS to trade grade."""
    if qas > _QAS_GRADES["A+"]:
        return "A+"
    elif qas >= _QAS_GRADES["A"]:
        return "A"
    elif qas >= _QAS_GRADES["B"]:
        return "B"
    else:
        return "NO_TRADE"


def check_hard_vetos(
    signals: List[LayerSignal],
    portfolio_risk_pct: float = 0.0,
    daily_losses: int = 0,
    daily_drawdown_pct: float = 0.0,
) -> List[str]:
    """
    Check hard veto conditions — any triggered = automatic NO TRADE.

    Returns list of triggered veto descriptions. Empty = no vetos.
    """
    vetos = []
    sig_map = {s.layer_name: s for s in signals}

    # 1. Key layers at minimum score (score <= 1 maps to normalized -2)
    for layer_name in _HARD_VETO_LAYERS:
        sig = sig_map.get(layer_name)
        if sig and sig.score <= 1.0:
            vetos.append(f"HARD VETO: {layer_name} score={sig.score:.1f} (≤1.0)")

    # 2. Portfolio risk exceeds limit
    max_port = getattr(settings, "MAX_PORTFOLIO_RISK_PCT", 5.0)
    if portfolio_risk_pct > max_port:
        vetos.append(f"HARD VETO: Portfolio risk {portfolio_risk_pct:.1f}% > {max_port}%")

    # 3. Daily loss limit
    max_losses = getattr(settings, "MAX_DAILY_LOSSES", 2)
    if daily_losses >= max_losses:
        vetos.append(f"HARD VETO: Daily losses {daily_losses} >= {max_losses}")

    max_dd = getattr(settings, "DAILY_LOSS_LIMIT_PCT", 3.0)
    if daily_drawdown_pct >= max_dd:
        vetos.append(f"HARD VETO: Daily drawdown {daily_drawdown_pct:.1f}% >= {max_dd}%")

    # 4. Two or more core layers at minimum
    core_failures = sum(
        1 for ln in _CORE_LAYERS
        if sig_map.get(ln) and sig_map[ln].score <= 1.0
    )
    if core_failures >= _MAX_CORE_FAIL:
        vetos.append(f"HARD VETO: {core_failures} core layers failing (≥{_MAX_CORE_FAIL})")

    return vetos


def check_soft_vetos(
    signals: List[LayerSignal],
    trade_direction: str = "LONG",
    correlated_open_count: int = 0,
    news_within_30min: bool = False,
) -> List[str]:
    """
    Check soft veto conditions — each reduces size by 50%.

    Returns list of triggered soft veto descriptions.
    """
    vetos = []
    sig_map = {s.layer_name: s for s in signals}

    # 1. Extreme opposing sentiment
    l10 = sig_map.get("L10_Sentiment")
    if l10:
        sent_details = l10.details or {}
        composite = sent_details.get("composite_score", 0)
        if trade_direction == "LONG" and composite < -2.0:
            vetos.append("SOFT VETO: Extreme bearish sentiment opposing LONG trade")
        elif trade_direction == "SHORT" and composite > 2.0:
            vetos.append("SOFT VETO: Extreme bullish sentiment opposing SHORT trade")

    # 2. Too many correlated open trades
    max_corr = getattr(settings, "MAX_CORRELATED_TRADES", 2)
    if correlated_open_count >= max_corr:
        vetos.append(f"SOFT VETO: {correlated_open_count} correlated trades open (≥{max_corr})")

    # 3. Low confidence
    avg_conf = sum(s.confidence for s in signals) / len(signals) if signals else 0
    conf_5 = _confidence_to_5(avg_conf)
    if conf_5 < _SOFT_MIN_CONF:
        vetos.append(f"SOFT VETO: Avg confidence {conf_5:.1f} < {_SOFT_MIN_CONF}")

    # 4. Order flow opposing
    l7 = sig_map.get("L7_OrderFlow")
    if l7 and l7.score <= 2.5:
        vetos.append(f"SOFT VETO: L7 OrderFlow score {l7.score:.1f} — flow opposing")

    # 5. News within 30 min
    if news_within_30min:
        vetos.append("SOFT VETO: High-impact news within 30 minutes")

    return vetos


def full_evaluation(
    signals: List[LayerSignal],
    portfolio_risk_pct: float = 0.0,
    daily_losses: int = 0,
    daily_drawdown_pct: float = 0.0,
    correlated_open_count: int = 0,
    news_within_30min: bool = False,
    regime: str = "NORMAL",
) -> Dict[str, Any]:
    """
    Run the complete AI evaluation from Part 15 of the plan.

    Parameters
    ----------
    signals : list of up to 11 LayerSignals
    portfolio_risk_pct : current total portfolio risk %
    daily_losses : number of losses today
    daily_drawdown_pct : today's drawdown %
    correlated_open_count : highly correlated open positions
    news_within_30min : whether high-impact news is imminent
    regime : current market regime for adaptive weight adjustment

    Returns
    -------
    dict with grade, qas, tws, direction, size_multiplier, tradeable,
    vetos, recommendations, layer breakdown, etc.
    """
    # ── 1. Compute TWS (regime-adaptive weights) ──
    tws_result = compute_tws(signals, regime=regime)
    tws = tws_result["tws"]

    # ── 2. Compute QAS ──
    qas = compute_qas(tws, signals)

    # ── 3. Determine grade ──
    grade = determine_grade(qas)

    # ── 4. Direction consensus (weighted) ──
    long_weight = 0.0
    short_weight = 0.0
    for sig in signals:
        w = _LAYER_WEIGHTS.get(sig.layer_name, 0.0)
        norm = _normalize_score(sig.score)
        if sig.direction == "LONG":
            long_weight += abs(norm) * w
        elif sig.direction == "SHORT":
            short_weight += abs(norm) * w

    if long_weight > short_weight * 1.2:
        direction = "LONG"
    elif short_weight > long_weight * 1.2:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # ── 5. Check vetos ──
    hard_vetos = check_hard_vetos(
        signals, portfolio_risk_pct, daily_losses, daily_drawdown_pct
    )
    soft_vetos = check_soft_vetos(
        signals, direction, correlated_open_count, news_within_30min
    )

    # ── 6. Final sizing ──
    base_mult = _QAS_SIZES.get(grade, 0.0)
    if hard_vetos:
        final_mult = 0.0
        grade = "NO_TRADE"
        tradeable = False
    elif soft_vetos:
        final_mult = base_mult * (0.5 ** len(soft_vetos))
        tradeable = final_mult > 0 and direction != "NEUTRAL"
    else:
        final_mult = base_mult
        tradeable = grade != "NO_TRADE" and direction != "NEUTRAL"

    # ── 7. Find strongest and weakest layers ──
    sorted_layers = sorted(
        tws_result["breakdown"],
        key=lambda x: x["normalized"],
        reverse=True,
    )
    strongest = sorted_layers[:3]
    weakest = sorted_layers[-3:]

    # ── 8. Average confidence ──
    avg_confidence = (
        sum(s.confidence for s in signals) / len(signals) if signals else 0
    )

    # ── 9. Build verdict ──
    if grade == "A+" and not hard_vetos and not soft_vetos:
        verdict = "TRADE — Full size (A+, no vetos)"
    elif grade == "A+" and soft_vetos:
        verdict = "TRADE — Reduced size (A+ with soft vetos)"
    elif grade == "A" and not hard_vetos and not soft_vetos:
        verdict = "TRADE — Normal size (A, no vetos)"
    elif grade == "A" and soft_vetos:
        verdict = "TRADE — Reduced size (A with soft vetos)"
    elif grade == "B" and not hard_vetos:
        verdict = "TRADE — Half size (B grade)"
    elif hard_vetos:
        verdict = f"SKIP — Veto triggered: {hard_vetos[0]}"
    elif direction == "NEUTRAL":
        verdict = "SKIP — No directional consensus"
    else:
        verdict = "SKIP — Score too low"

    # ── 10. Aggressiveness level ──
    if grade == "A+" and not hard_vetos and not soft_vetos and avg_confidence > 0.7:
        aggressiveness = "AGGRESSIVE"
    elif grade in ("A+", "A") and not hard_vetos:
        aggressiveness = "NORMAL"
    elif grade == "B" or soft_vetos:
        aggressiveness = "CAUTIOUS"
    elif hard_vetos:
        aggressiveness = "DEFENSIVE"
    else:
        aggressiveness = "CASH"

    result = {
        "grade": grade,
        "tws": tws,
        "qas": qas,
        "direction": direction,
        "size_multiplier": round(final_mult, 3),
        "tradeable": tradeable,
        "verdict": verdict,
        "aggressiveness": aggressiveness,
        "avg_confidence": round(avg_confidence, 3),
        "hard_vetos": hard_vetos,
        "soft_vetos": soft_vetos,
        "strongest_layers": strongest,
        "weakest_layers": weakest,
        "layer_breakdown": tws_result["breakdown"],
        "long_weight": round(long_weight, 4),
        "short_weight": round(short_weight, 4),
        "signals_count": len(signals),
    }

    logger.info(
        "AI EVAL: %s grade=%s QAS=%.3f TWS=%.3f dir=%s mult=%.2f vetos=%d/%d",
        "✓ TRADE" if tradeable else "✗ SKIP",
        grade, qas, tws, direction, final_mult,
        len(hard_vetos), len(soft_vetos),
    )

    return result


class AIEvaluationLayer:
    """
    Layer 11 — Regime Context / AI Evaluation.

    For the Layer Evaluator, this provides a regime-based score.
    The full AI evaluation (full_evaluation) is run separately
    with all 11 signals as input.
    """

    def __init__(self):
        try:
            from analysis.regime_detector import RegimeDetector
            self.regime_detector = RegimeDetector()
        except ImportError:
            self.regime_detector = None

    def analyze(
        self,
        daily_df=None,
        volume_profile=None,
        vix_level: float = 20.0,
        htf_choch: bool = False,
    ) -> LayerSignal:
        """
        Generate a regime-context LayerSignal.

        Parameters
        ----------
        daily_df : Daily OHLCV DataFrame
        volume_profile : VolumeProfile object (composite)
        vix_level : Current VIX level
        htf_choch : Whether higher-timeframe CHoCH detected
        """
        score = 5.0
        confidence = 0.5
        direction = "NEUTRAL"
        details = {}

        try:
            if self.regime_detector and daily_df is not None and volume_profile is not None:
                regime_result = self.regime_detector.detect(
                    daily_df, volume_profile, vix_level, htf_choch
                )
                regime = regime_result.get("regime", "UNKNOWN")
                size_adj = regime_result.get("size_adjustment", 1.0)
                details = regime_result.get("details", {})
                details["regime"] = regime
                details["best_setups"] = regime_result.get("best_setups", [])
                details["size_adjustment"] = size_adj

                # Score based on regime clarity and tradability
                regime_scores = {
                    "STRONG_TREND": 8.0,
                    "NORMAL": 6.5,
                    "RANGE": 5.0,
                    "TRANSITIONAL": 3.5,
                    "VOLATILE": 2.0,
                    "UNKNOWN": 5.0,
                }
                score = regime_scores.get(regime, 5.0)
                confidence = 0.7 if regime != "UNKNOWN" else 0.3

                # Direction from regime
                if regime == "STRONG_TREND":
                    adx = details.get("adx", 0)
                    direction = "LONG" if details.get("vp_shape") in ("P",) else "SHORT" if details.get("vp_shape") in ("b",) else "NEUTRAL"
                elif regime == "VOLATILE":
                    direction = "NEUTRAL"  # No clear direction
            else:
                # No data — provide neutral reading
                details["regime"] = "UNKNOWN"
                details["note"] = "Insufficient data for regime detection"

        except Exception as e:
            logger.error("Layer 11 analysis failed: %s", e, exc_info=True)
            details["error"] = str(e)

        return LayerSignal(
            layer_name="L11_Regime",
            direction=direction,
            score=round(score, 2),
            confidence=round(confidence, 2),
            details=details,
        )
