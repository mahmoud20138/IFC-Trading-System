"""
IFC Trading System — Setup Detector
Identifies which of the 5 specific trade setups is triggered.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from analysis.layer1_intermarket import LayerSignal
from analysis.layer3_volume_profile import VolumeProfile
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.setup")


@dataclass
class TradeSetup:
    """A fully-defined trade setup ready for execution."""
    setup_type: str          # "POC_BOUNCE" | "LIQ_SWEEP" | "VA_BREAKOUT" | "NAKED_POC" | "POC_MIGRATION"
    direction: str           # "LONG" | "SHORT"
    entry_price: float       # CE of FVG
    stop_loss: float
    tp1: float
    tp2: float
    tp3: Optional[float]     # Runner target (can be None = trail)
    rr_ratio: float          # Reward:Risk
    grade: str               # "A+" | "A" | "B"
    risk_multiplier: float
    confluence_score: Dict[str, Any]
    details: Dict[str, Any] = field(default_factory=dict)


class SetupDetector:
    """
    Examines layer outputs and identifies which predefined setup pattern is active.
    """

    def detect(
        self,
        confluence: Dict[str, Any],
        layer_signals: List[LayerSignal],
        volume_profile: Optional[VolumeProfile] = None,
        current_price: float = 0.0,
        atr: float = 0.0,
    ) -> Optional[TradeSetup]:
        """
        Try to match the current state to one of the 5 setups.
        Returns the best-matching TradeSetup, or None.
        """
        if not confluence.get("tradeable"):
            return None

        direction = confluence["direction"]
        grade = confluence["grade"]
        risk_mult = confluence["risk_multiplier"]

        # Extract layer details
        layer_map = {s.layer_name: s for s in layer_signals}
        l3 = layer_map.get("L3_VolumeProfile")
        l5 = layer_map.get("L5_Liquidity")
        l6 = layer_map.get("L6_FVG_OrderBlock")
        l7 = layer_map.get("L7_OrderFlow")

        # We need FVG entry data (Layer 6) no matter what
        if not l6 or l6.score < 4:
            logger.info("No viable FVG entry — no setup")
            return None

        entry_candidates = l6.details.get("entry_candidates", [])
        if not entry_candidates:
            return None

        best_entry = entry_candidates[0]
        entry_price = best_entry.get("refined_entry", best_entry["entry_price"])
        stop_loss = best_entry["stop_loss"]

        # Calculate risk distance
        risk_distance = abs(entry_price - stop_loss)
        if risk_distance == 0:
            return None

        # ── Try to identify the specific setup type ──
        setup_type = None
        details: Dict[str, Any] = {}

        # 1. Liquidity Sweep + FVG Reversal (highest priority)
        if l5 and l5.details.get("sweep"):
            sweep = l5.details["sweep"]
            if (sweep["type"] == "SWEEP_LOW" and direction == "LONG") or \
               (sweep["type"] == "SWEEP_HIGH" and direction == "SHORT"):
                setup_type = "LIQ_SWEEP"
                details["sweep"] = sweep
                # Tighter stop after sweep (use sweep wick)
                if direction == "LONG" and "wick_low" in sweep:
                    stop_loss = sweep["wick_low"] - atr * 0.05
                elif direction == "SHORT" and "wick_high" in sweep:
                    stop_loss = sweep["wick_high"] + atr * 0.05

        # 2. POC Bounce + FVG
        if setup_type is None and l3 and volume_profile:
            price_pos = l3.details.get("price_position", "")
            if direction == "LONG" and price_pos in ("LOWER_VA", "BELOW_VA"):
                if abs(current_price - volume_profile.poc) <= atr * 1.5:
                    setup_type = "POC_BOUNCE"
                    details["poc"] = volume_profile.poc
            elif direction == "SHORT" and price_pos in ("UPPER_VA", "ABOVE_VA"):
                if abs(current_price - volume_profile.poc) <= atr * 1.5:
                    setup_type = "POC_BOUNCE"
                    details["poc"] = volume_profile.poc

        # 3. Value Area Breakout + Retest
        if setup_type is None and l3 and volume_profile:
            price_pos = l3.details.get("price_position", "")
            if direction == "LONG" and price_pos == "ABOVE_VA":
                # Price broke above VAH — looking for retest
                if abs(current_price - volume_profile.vah) <= atr * 1.0:
                    setup_type = "VA_BREAKOUT"
                    details["breakout_level"] = volume_profile.vah
            elif direction == "SHORT" and price_pos == "BELOW_VA":
                if abs(current_price - volume_profile.val) <= atr * 1.0:
                    setup_type = "VA_BREAKOUT"
                    details["breakout_level"] = volume_profile.val

        # 4. Naked POC + MA Confluence
        if setup_type is None and l3:
            naked_nearby = l3.details.get("naked_pocs_nearby", 0)
            if naked_nearby > 0:
                setup_type = "NAKED_POC"

        # 5. POC Migration Trade
        if setup_type is None and l3:
            migration = l3.details.get("poc_migration", "FLAT")
            if (migration == "UP" and direction == "LONG") or \
               (migration == "DOWN" and direction == "SHORT"):
                setup_type = "POC_MIGRATION"
                details["migration"] = migration

        # Default to best available
        if setup_type is None:
            setup_type = "GENERIC_FVG"

        # ── Calculate targets ──
        risk_distance = abs(entry_price - stop_loss)

        if volume_profile:
            if direction == "LONG":
                tp1 = volume_profile.vah if volume_profile.vah > entry_price else entry_price + risk_distance * 2.5
                tp2 = max(volume_profile.hvn) if volume_profile.hvn and max(volume_profile.hvn) > tp1 else entry_price + risk_distance * 5
            else:
                tp1 = volume_profile.val if volume_profile.val < entry_price else entry_price - risk_distance * 2.5
                tp2 = min(volume_profile.hvn) if volume_profile.hvn and min(volume_profile.hvn) < tp1 else entry_price - risk_distance * 5
        else:
            if direction == "LONG":
                tp1 = entry_price + risk_distance * 2.5
                tp2 = entry_price + risk_distance * 5
            else:
                tp1 = entry_price - risk_distance * 2.5
                tp2 = entry_price - risk_distance * 5

        tp3 = None  # Runner — managed by trailing stop

        # R:R
        tp1_rr = abs(tp1 - entry_price) / risk_distance if risk_distance > 0 else 0
        rr_ratio = round(tp1_rr, 2)

        # Check minimum R:R
        if rr_ratio < settings.MIN_RR_RATIO:
            logger.info("Setup %s rejected: R:R %.2f < minimum %.1f", setup_type, rr_ratio, settings.MIN_RR_RATIO)
            return None

        setup = TradeSetup(
            setup_type=setup_type,
            direction=direction,
            entry_price=round(entry_price, 6),
            stop_loss=round(stop_loss, 6),
            tp1=round(tp1, 6),
            tp2=round(tp2, 6),
            tp3=tp3,
            rr_ratio=rr_ratio,
            grade=grade,
            risk_multiplier=risk_mult,
            confluence_score=confluence,
            details=details,
        )

        logger.info(
            "SETUP DETECTED: %s %s entry=%.5f sl=%.5f tp1=%.5f rr=%.2f grade=%s",
            setup_type, direction, entry_price, stop_loss, tp1, rr_ratio, grade,
        )

        return setup
