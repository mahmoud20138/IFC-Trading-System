"""
IFC Trading System — Regime Detector
Classifies market into Strong Trend / Range / Volatile / Transitional.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any

from analysis.layer3_volume_profile import VolumeProfile
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.regime")


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Compute current ADX value (simplified)."""
    if len(df) < period * 2:
        return 0.0

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    plus_dm = np.zeros(len(df))
    minus_dm = np.zeros(len(df))
    tr = np.zeros(len(df))

    for i in range(1, len(df)):
        h_diff = high[i] - high[i - 1]
        l_diff = low[i - 1] - low[i]
        plus_dm[i] = max(h_diff, 0) if h_diff > l_diff else 0
        minus_dm[i] = max(l_diff, 0) if l_diff > h_diff else 0
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # Smoothed averages
    atr_s = pd.Series(tr).rolling(period).mean().values
    plus_dm_s = pd.Series(plus_dm).rolling(period).mean().values
    minus_dm_s = pd.Series(minus_dm).rolling(period).mean().values

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * plus_dm_s / np.where(atr_s > 0, atr_s, 1)
        minus_di = 100 * minus_dm_s / np.where(atr_s > 0, atr_s, 1)
        dx = 100 * np.abs(plus_di - minus_di) / np.where(
            (plus_di + minus_di) > 0, plus_di + minus_di, 1
        )

    adx = pd.Series(dx).rolling(period).mean().values
    return float(adx[-1]) if not np.isnan(adx[-1]) else 0.0


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Current ATR value."""
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


class RegimeDetector:
    """
    Classify current market regime per Part 9 of the strategy plan.

    Regimes:
    - STRONG_TREND:  ADX > 25, MAs fanned, VP thin/elongated
    - RANGE:         ADX < 20, MAs flat, VP D-shaped, POC static
    - VOLATILE:      ATR > 150% of avg, VIX elevated, whipsaw signals
    - TRANSITIONAL:  CHoCH on HTF, MAs crossing, VP shape changing
    """

    def detect(
        self,
        daily_df: pd.DataFrame,
        volume_profile: VolumeProfile,
        vix_level: float = 20.0,
        htf_choch: bool = False,
    ) -> Dict[str, Any]:
        """
        Parameters
        ----------
        daily_df : Daily OHLCV
        volume_profile : composite VP
        vix_level : current VIX (from Layer 1)
        htf_choch : whether Layer 2 detected a CHoCH on HTF
        """
        if daily_df.empty or len(daily_df) < 30:
            return {
                "regime": "UNKNOWN",
                "best_setups": [],
                "size_adjustment": 1.0,
                "details": {"note": "Insufficient daily data"},
            }

        adx = compute_adx(daily_df)
        current_atr = compute_atr(daily_df)
        avg_atr_20 = float(
            pd.Series([compute_atr(daily_df.iloc[:i+14])
                       for i in range(14, min(34, len(daily_df)))]
            ).mean()
        ) if len(daily_df) >= 28 else current_atr
        atr_ratio = current_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0
        shape = volume_profile.shape

        details = {
            "adx": round(adx, 1),
            "current_atr": round(current_atr, 6),
            "avg_atr_20": round(avg_atr_20, 6),
            "atr_ratio": round(atr_ratio, 2),
            "vp_shape": shape,
            "vix": vix_level,
            "htf_choch": htf_choch,
        }

        # ── Classification logic ──
        # Priority: Volatile > Transitional > Trend > Range

        if atr_ratio > 1.5 or vix_level > 30:
            regime = "VOLATILE"
            best_setups = ["LIQ_SWEEP"]
            size_adj = 0.4 if atr_ratio > 2.0 else 0.6
            details["note"] = "High volatility — reduce size, only sweep setups"

        elif htf_choch:
            regime = "TRANSITIONAL"
            best_setups = ["LIQ_SWEEP", "NAKED_POC"]
            size_adj = 0.7
            details["note"] = "HTF CHoCH detected — trend may be changing"

        elif adx > 25 and shape in ("Thin", "P", "b"):
            regime = "STRONG_TREND"
            best_setups = ["POC_BOUNCE", "POC_MIGRATION"]
            size_adj = 1.1  # Slightly larger in trending markets
            details["note"] = "Strong trend — trade with trend aggressively"

        elif adx < 20 and shape == "D":
            regime = "RANGE"
            best_setups = ["POC_BOUNCE", "VA_BREAKOUT"]
            size_adj = 0.8
            details["note"] = "Range market — fade extremes, target POC"

        else:
            regime = "NORMAL"
            best_setups = ["POC_BOUNCE", "LIQ_SWEEP", "VA_BREAKOUT", "NAKED_POC", "POC_MIGRATION"]
            size_adj = 1.0
            details["note"] = "Normal conditions — all setups valid"

        result = {
            "regime": regime,
            "best_setups": best_setups,
            "size_adjustment": round(size_adj, 2),
            "details": details,
        }

        logger.info(
            "REGIME: %s (ADX=%.1f ATRratio=%.2f VP=%s VIX=%.1f)",
            regime, adx, atr_ratio, shape, vix_level,
        )

        return result
