"""
IFC Trading System — Risk Manager
Dynamic position sizing with 5 multipliers, drawdown circuit breakers.
"""

import math
from typing import Dict, Any, Optional

from config import settings
from utils.helpers import setup_logging, day_of_week_multiplier

logger = setup_logging("ifc.risk")


class RiskManager:
    """
    Implements the 5-multiplier dynamic position sizing algorithm.

    FINAL RISK % = Base Risk × Setup × Volatility × Streak × Time × Intermarket
    Capped at MAX_RISK_PCT, floored at MIN_RISK_PCT.
    """

    def __init__(self):
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        self._daily_risk_used = 0.0
        self._daily_trades = 0
        self._monthly_drawdown_pct = 0.0

    # ── State tracking ───────────────────────────────────────────────
    def record_win(self):
        self._consecutive_wins += 1
        self._consecutive_losses = 0

    def record_loss(self, risk_pct: float):
        self._consecutive_losses += 1
        self._consecutive_wins = 0
        self._monthly_drawdown_pct += risk_pct

    def record_trade(self, risk_pct: float):
        self._daily_risk_used += risk_pct
        self._daily_trades += 1

    def reset_daily(self):
        self._daily_risk_used = 0.0
        self._daily_trades = 0

    def reset_monthly(self):
        self._monthly_drawdown_pct = 0.0
        self._consecutive_wins = 0
        self._consecutive_losses = 0

    # ── Circuit breakers ─────────────────────────────────────────────
    def check_circuit_breakers(self) -> Dict[str, Any]:
        """Check if any drawdown circuit breaker is triggered."""
        result = {"can_trade": True, "action": None, "reason": None}

        if self._consecutive_losses >= 5:
            result = {
                "can_trade": False,
                "action": "HARD_STOP",
                "reason": f"5 consecutive losses — stop trading",
            }
        elif self._daily_risk_used >= settings.DAILY_MAX_RISK_PCT:
            result = {
                "can_trade": False,
                "action": "DAILY_LIMIT",
                "reason": f"Daily risk limit reached: {self._daily_risk_used:.1f}% / {settings.DAILY_MAX_RISK_PCT}%",
            }
        elif self._daily_trades >= settings.MAX_TRADES_PER_DAY:
            result = {
                "can_trade": False,
                "action": "MAX_TRADES",
                "reason": f"Max daily trades reached: {self._daily_trades}",
            }
        elif self._monthly_drawdown_pct >= 15:
            result = {
                "can_trade": False,
                "action": "FULL_STOP",
                "reason": f"15% monthly drawdown — full stop, system audit needed",
            }
        elif self._monthly_drawdown_pct >= 10:
            result = {
                "can_trade": False,
                "action": "PAUSE_LIVE",
                "reason": f"10% monthly drawdown — switch to demo for 1 week",
            }
        elif self._monthly_drawdown_pct >= 5:
            result = {
                "can_trade": True,
                "action": "HALF_SIZE",
                "reason": f"5% monthly drawdown — cut size 50%, A+ setups only",
            }

        if not result["can_trade"]:
            logger.warning("CIRCUIT BREAKER: %s — %s", result["action"], result["reason"])

        return result

    # ── Multipliers ──────────────────────────────────────────────────
    def _streak_multiplier(self) -> float:
        if self._consecutive_losses >= 5:
            return settings.STREAK_MULTIPLIERS["loss_5"]
        if self._consecutive_losses >= 3:
            return settings.STREAK_MULTIPLIERS["loss_3plus"]
        if self._consecutive_losses >= 2:
            return settings.STREAK_MULTIPLIERS["loss_2"]
        if self._consecutive_wins >= 3:
            return settings.STREAK_MULTIPLIERS["win_3plus"]
        return settings.STREAK_MULTIPLIERS["normal"]

    @staticmethod
    def _volatility_multiplier(atr_ratio: float) -> float:
        """atr_ratio = current ATR / 20-day avg ATR."""
        if atr_ratio < 0.5:
            return settings.VOLATILITY_MULTIPLIERS["quiet"]
        if atr_ratio > 2.0:
            return settings.VOLATILITY_MULTIPLIERS["extreme"]
        if atr_ratio > 1.5:
            return settings.VOLATILITY_MULTIPLIERS["high"]
        return settings.VOLATILITY_MULTIPLIERS["normal"]

    @staticmethod
    def _intermarket_multiplier(alignment: str) -> float:
        return settings.INTERMARKET_MULTIPLIERS.get(alignment, 1.0)

    @staticmethod
    def _time_multiplier() -> float:
        return day_of_week_multiplier()

    # ── Main calculation ─────────────────────────────────────────────
    def calculate_risk_pct(
        self,
        setup_grade: str,
        atr_ratio: float = 1.0,
        intermarket_alignment: str = "mostly_aligned",
    ) -> Dict[str, Any]:
        """
        Calculate the final risk percentage for this trade.

        Returns dict with final_risk_pct, position adjustments, and breakdown.
        """
        base = settings.BASE_RISK_PCT

        setup_mult = settings.SETUP_QUALITY_MULTIPLIERS.get(setup_grade, 0.0)
        vol_mult = self._volatility_multiplier(atr_ratio)
        streak_mult = self._streak_multiplier()
        time_mult = self._time_multiplier()
        im_mult = self._intermarket_multiplier(intermarket_alignment)

        raw = base * setup_mult * vol_mult * streak_mult * time_mult * im_mult

        # Circuit breaker adjustments
        breaker = self.check_circuit_breakers()
        if not breaker["can_trade"]:
            raw = 0.0
        elif breaker.get("action") == "HALF_SIZE":
            raw *= 0.5

        # Cap and floor
        final = max(settings.MIN_RISK_PCT, min(settings.MAX_RISK_PCT, raw))
        if raw == 0:
            final = 0

        breakdown = {
            "base_risk": base,
            "setup_multiplier": setup_mult,
            "volatility_multiplier": vol_mult,
            "streak_multiplier": streak_mult,
            "time_multiplier": time_mult,
            "intermarket_multiplier": im_mult,
            "raw_risk": round(raw, 4),
            "final_risk_pct": round(final, 4),
            "circuit_breaker": breaker,
        }

        logger.info(
            "RISK: base=%.1f%% × setup=%.1f × vol=%.1f × streak=%.1f × time=%.1f × im=%.1f = %.2f%% → capped=%.2f%%",
            base, setup_mult, vol_mult, streak_mult, time_mult, im_mult, raw, final,
        )

        return breakdown

    def calculate_position_size(
        self,
        account_balance: float,
        risk_pct: float,
        stop_distance_pips: float,
        pip_value_per_lot: float,
        volume_step: float = 0.01,
        volume_min: float = 0.01,
        volume_max: float = 100.0,
    ) -> Dict[str, Any]:
        """
        Convert risk % and stop distance into a lot size.

        Parameters
        ----------
        account_balance : current balance in account currency
        risk_pct : from calculate_risk_pct
        stop_distance_pips : distance from entry to stop in pips
        pip_value_per_lot : $ value of 1 pip per 1.0 standard lot
        volume_step : minimum lot increment (broker-specific)
        volume_min / volume_max : broker limits
        """
        if risk_pct <= 0 or stop_distance_pips <= 0:
            return {"lots": 0, "risk_amount": 0, "reason": "zero risk or stop"}

        risk_amount = account_balance * (risk_pct / 100)
        pip_cost = stop_distance_pips * pip_value_per_lot

        if pip_cost <= 0:
            return {"lots": 0, "risk_amount": risk_amount, "reason": "zero pip cost"}

        raw_lots = risk_amount / pip_cost

        # Round down to nearest volume_step
        lots = math.floor(raw_lots / volume_step) * volume_step
        lots = max(volume_min, min(volume_max, lots))
        lots = round(lots, 2)

        actual_risk = lots * pip_cost
        actual_risk_pct = (actual_risk / account_balance) * 100 if account_balance > 0 else 0

        result = {
            "lots": lots,
            "risk_amount": round(risk_amount, 2),
            "actual_risk_amount": round(actual_risk, 2),
            "actual_risk_pct": round(actual_risk_pct, 4),
            "stop_distance_pips": stop_distance_pips,
            "pip_value_per_lot": pip_value_per_lot,
        }

        logger.info(
            "POSITION SIZE: %.2f lots | risk $%.2f (%.2f%%) | stop %.1f pips",
            lots, actual_risk, actual_risk_pct, stop_distance_pips,
        )

        return result
