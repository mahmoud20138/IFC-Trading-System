"""
IFC Trading System — Layer 1: Intermarket & Macro Context
Determines risk-on/risk-off environment and correlation alignment.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from config import settings
from config.instruments import Instrument
from data.intermarket import IntermarketData
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer1")


@dataclass
class LayerSignal:
    """Standardised output from every analysis layer."""
    layer_name: str
    direction: str       # "LONG" | "SHORT" | "NEUTRAL"
    score: float         # 0–10
    confidence: float    # 0–1
    details: Dict[str, Any] = field(default_factory=dict)


class IntermarketLayer:
    """
    Layer 1 — Score the macro context.

    Risk On  → favour growth / risk assets (AUD, NZD, indices, crypto)
    Risk Off → favour havens (USD, JPY, CHF, Gold)
    Mixed    → reduce size / neutral score
    """

    def __init__(self, intermarket: IntermarketData):
        self.intermarket = intermarket

    def analyze(
        self,
        instrument: Instrument,
        snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> LayerSignal:
        """
        Run Layer 1 analysis for *instrument*.

        Parameters
        ----------
        instrument : the instrument being evaluated
        snapshot : pre-fetched intermarket snapshot (or will fetch fresh)
        """
        if snapshot is None:
            snapshot = self.intermarket.get_full_snapshot()

        risk_regime = self.intermarket.determine_risk_regime(snapshot)

        # --- Determine implied direction from correlations ---
        corr_score = 0.0
        corr_count = 0
        for ref_name, corr_val in instrument.intermarket_correlations.items():
            ref_data = snapshot.get(ref_name, {})
            ref_dir = ref_data.get("direction", "UNKNOWN")

            if ref_dir == "UNKNOWN" or ref_dir == "ERROR":
                continue

            # Positive correlation: if ref is rising, favour LONG
            # Negative correlation: if ref is rising, favour SHORT
            if ref_dir == "RISING":
                if corr_val > 0:
                    corr_score += abs(corr_val)
                else:
                    corr_score -= abs(corr_val)
            elif ref_dir == "FALLING":
                if corr_val > 0:
                    corr_score -= abs(corr_val)
                else:
                    corr_score += abs(corr_val)
            corr_count += 1

        # Normalise correlation score to [-1, 1]
        if corr_count > 0:
            corr_score /= corr_count

        # --- Risk regime scoring ---
        # Enhanced: category-specific regime sensitivity (Enhancement Plan #5)
        # Risk assets: indices, crypto, AUD/NZD, stocks, oil — benefit from risk-on
        # Haven assets: Gold, Silver, JPY, CHF — benefit from risk-off
        risk_categories = {"index", "crypto", "stock"}
        risk_on_fx = {"AUDUSDm", "NZDUSDm"}
        risk_off_fx = {"USDJPYm", "USDCHFm"}
        haven_commodities = {"XAUUSDm", "XAGUSDm"}    # Gold, Silver are havens
        risk_commodities = {"USOILm"}                  # Oil = risk-on

        regime_bonus = 0.0
        sym = instrument.mt5_symbol

        if instrument.category in risk_categories or sym in risk_on_fx or sym in risk_commodities:
            # Risk assets: benefit from risk-on, penalized by risk-off
            if risk_regime == "RISK_ON":
                regime_bonus = 1.0
            elif risk_regime == "RISK_OFF":
                regime_bonus = -1.0
        elif sym in risk_off_fx or sym in haven_commodities:
            # Haven assets: benefit from risk-off, penalized by risk-on
            if risk_regime == "RISK_OFF":
                regime_bonus = 1.0
            elif risk_regime == "RISK_ON":
                regime_bonus = -1.0

        # Gold has extra DXY inverse sensitivity
        if sym == "XAUUSDm":
            dxy = snapshot.get("DXY", {})
            dxy_dir = dxy.get("direction", "UNKNOWN")
            if dxy_dir == "FALLING":
                regime_bonus += 0.3   # Weak dollar → gold bullish
            elif dxy_dir == "RISING":
                regime_bonus -= 0.3   # Strong dollar → gold bearish
            regime_bonus = max(-1.0, min(1.0, regime_bonus))

        # --- VIX impact on position sizing ---
        vix = snapshot.get("VIX", {})
        vix_regime = vix.get("regime", "normal")

        # --- Aggregate score (0-10) ---
        # corr_score ∈ [-1,1], regime_bonus ∈ [-1,1]
        raw = (corr_score + regime_bonus) / 2   # ∈ [-1, 1]
        score = 5.0 + raw * 5.0                 # map to 0-10
        score = max(0.0, min(10.0, score))

        # Direction
        if raw > 0.15:
            direction = "LONG"
        elif raw < -0.15:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        confidence = abs(raw)

        details = {
            "risk_regime": risk_regime,
            "vix_regime": vix_regime,
            "correlation_score": round(corr_score, 3),
            "regime_bonus": regime_bonus,
            "snapshot_summary": {
                k: f"{v.get('direction', '?')} ({v.get('change_pct', 0):+.1f}%)"
                for k, v in snapshot.items()
            },
        }

        logger.info(
            "L1 %s: %s score=%.1f regime=%s corr=%.2f",
            instrument.display_name, direction, score, risk_regime, corr_score,
        )

        return LayerSignal(
            layer_name="L1_Intermarket",
            direction=direction,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
