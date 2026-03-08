"""
IFC Trading System — Confluence Scorer
Aggregates all layer signals into a single trade grade.
Supports both the legacy 8-layer pass/fail mode and the
new 11-layer weighted QAS mode (from Part 15 of the plan).
"""

from typing import List, Dict, Any, Optional
from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.confluence")


GRADE_MAP = {
    8: "A+",
    7: "A",
    6: "A",
    5: "B",
}


class ConfluenceScorer:
    """
    Aggregates LayerSignals → final trade grade, direction, and risk multiplier.

    Two modes:
    - Legacy (pass_threshold based): count layers with score >= threshold
    - Weighted QAS (11-layer): use per-layer weights and Quality-Adjusted Score

    The mode is auto-detected based on whether LAYER_WEIGHTS exists in settings.
    """

    def __init__(self, pass_threshold: float = None):
        self.pass_threshold = pass_threshold or settings.LAYER_PASS_THRESHOLD
        self._use_weighted = hasattr(settings, "LAYER_WEIGHTS") and len(getattr(settings, "LAYER_WEIGHTS", {})) > 0

    def score(self, signals: List[LayerSignal]) -> Dict[str, Any]:
        """
        Parameters
        ----------
        signals : list of LayerSignals (8 or 11)

        Returns
        -------
        dict with:
            grade : 'A+' | 'A' | 'B' | 'NO_TRADE'
            direction : 'LONG' | 'SHORT' | 'NEUTRAL'
            total_passes / total_layers / avg_score
            risk_multiplier : float
            signals_summary : list of per-layer summaries
            tradeable : bool
            (if weighted): tws, qas, layer_weights_used
        """
        if self._use_weighted:
            return self._score_weighted(signals)
        else:
            return self._score_legacy(signals)

    def _score_weighted(self, signals: List[LayerSignal]) -> Dict[str, Any]:
        """11-layer weighted scoring with QAS from Part 15."""
        from analysis.layer11_ai_evaluation import compute_tws, compute_qas, determine_grade

        passes = 0
        direction_votes = {"LONG": 0, "SHORT": 0, "NEUTRAL": 0}
        total_score = 0.0
        summaries = []
        weights = getattr(settings, "LAYER_WEIGHTS", {})

        for sig in signals:
            passed = sig.score >= self.pass_threshold
            if passed:
                passes += 1
            if sig.direction in ("LONG", "SHORT"):
                direction_votes[sig.direction] += 1
            else:
                direction_votes["NEUTRAL"] += 1
            total_score += sig.score
            summaries.append({
                "layer": sig.layer_name,
                "score": sig.score,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "passed": passed,
                "weight": weights.get(sig.layer_name, 0.0),
            })

        avg_score = total_score / len(signals) if signals else 0.0

        # Compute TWS and QAS
        tws_result = compute_tws(signals)
        tws = tws_result["tws"]
        qas = compute_qas(tws, signals)
        grade = determine_grade(qas)

        # Direction: weighted consensus
        long_votes = direction_votes["LONG"]
        short_votes = direction_votes["SHORT"]
        if long_votes > short_votes:
            direction = "LONG"
        elif short_votes > long_votes:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        # Size multiplier from QAS grades
        qas_sizes = getattr(settings, "QAS_SIZE_MULTIPLIERS", settings.SETUP_QUALITY_MULTIPLIERS)
        risk_mult = qas_sizes.get(grade, 0.0)

        tradeable = (
            grade != "NO_TRADE"
            and direction != "NEUTRAL"
            and risk_mult > 0
        )

        result = {
            "grade": grade,
            "direction": direction,
            "total_passes": passes,
            "layers_passed": passes,
            "total_layers": len(signals),
            "avg_score": round(avg_score, 2),
            "risk_multiplier": risk_mult,
            "tradeable": tradeable,
            "direction_votes": direction_votes,
            "signals_summary": summaries,
            "tws": tws,
            "qas": qas,
            "weighted_mode": True,
        }

        logger.info(
            "CONFLUENCE(weighted): %s grade=%s QAS=%.3f TWS=%.3f passes=%d/%d dir=%s",
            "✓ TRADEABLE" if tradeable else "✗ NO TRADE",
            grade, qas, tws, passes, len(signals), direction,
        )

        return result

    def _score_legacy(self, signals: List[LayerSignal]) -> Dict[str, Any]:
        """Original 8-layer pass/fail scoring."""
        passes = 0
        direction_votes = {"LONG": 0, "SHORT": 0, "NEUTRAL": 0}
        total_score = 0.0
        summaries = []

        for sig in signals:
            passed = sig.score >= self.pass_threshold
            if passed:
                passes += 1
            if sig.direction in ("LONG", "SHORT"):
                direction_votes[sig.direction] += 1
            else:
                direction_votes["NEUTRAL"] += 1
            total_score += sig.score
            summaries.append({
                "layer": sig.layer_name,
                "score": sig.score,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "passed": passed,
            })

        avg_score = total_score / len(signals) if signals else 0.0

        # Grade
        grade = "NO_TRADE"
        for threshold, g in sorted(settings.GRADE_THRESHOLDS.items(), key=lambda x: -x[1]):
            if passes >= settings.GRADE_THRESHOLDS[threshold]:
                grade = threshold
                break

        # Direction consensus
        long_votes = direction_votes["LONG"]
        short_votes = direction_votes["SHORT"]
        directional_count = long_votes + short_votes

        if directional_count == 0:
            direction = "NEUTRAL"
        elif long_votes > short_votes:
            direction = "LONG"
        elif short_votes > long_votes:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        # Risk multiplier
        risk_mult = settings.SETUP_QUALITY_MULTIPLIERS.get(grade, 0.0)

        # Tradeable?
        tradeable = (
            grade != "NO_TRADE"
            and direction != "NEUTRAL"
            and risk_mult > 0
        )

        result = {
            "grade": grade,
            "direction": direction,
            "total_passes": passes,
            "layers_passed": passes,
            "total_layers": len(signals),
            "avg_score": round(avg_score, 2),
            "risk_multiplier": risk_mult,
            "tradeable": tradeable,
            "direction_votes": direction_votes,
            "signals_summary": summaries,
            "weighted_mode": False,
        }

        logger.info(
            "CONFLUENCE(legacy): %s grade=%s passes=%d/%d dir=%s risk_mult=%.1f avg=%.1f",
            "✓ TRADEABLE" if tradeable else "✗ NO TRADE",
            grade, passes, len(signals), direction, risk_mult, avg_score,
        )

        return result
