"""
IFC Trading System — Layer 2: Trend (MAs + Market Structure)
Determines institutional directional bias via EMA stack and BOS/CHoCH.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from scipy.signal import argrelextrema

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer2")


# ─────────────────────────────────────────────────────────────────────
# HELPERS — Moving Averages
# ─────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def compute_mas(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Add all strategy MAs to a DataFrame."""
    close = df["close"]
    return {
        "ema_fast": ema(close, settings.EMA_FAST),
        "ema_slow": ema(close, settings.EMA_SLOW),
        "sma_mid":  sma(close, settings.SMA_MID),
        "sma_long": sma(close, settings.SMA_LONG),
    }


def ma_stack_direction(price: float, mas: Dict[str, float]) -> str:
    """
    Check bullish/bearish/mixed EMA stack.
    Bullish: price > ema_fast > ema_slow > sma_mid > sma_long
    """
    vals = [price, mas["ema_fast"], mas["ema_slow"], mas["sma_mid"], mas["sma_long"]]
    if all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
        return "BULLISH"
    if all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
        return "BEARISH"
    return "MIXED"


# ─────────────────────────────────────────────────────────────────────
# HELPERS — Swing Points & Structure
# ─────────────────────────────────────────────────────────────────────

def find_swing_points(
    df: pd.DataFrame, order: int = None
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    Identify swing highs and swing lows.
    Returns lists of (index_position, price) tuples.
    """
    if order is None:
        order = settings.SWING_LOOKBACK

    highs_idx = argrelextrema(df["high"].values, np.greater_equal, order=order)[0]
    lows_idx = argrelextrema(df["low"].values, np.less_equal, order=order)[0]

    swing_highs = [(int(i), float(df["high"].iloc[i])) for i in highs_idx]
    swing_lows = [(int(i), float(df["low"].iloc[i])) for i in lows_idx]

    return swing_highs, swing_lows


def detect_structure(
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
) -> Dict[str, Any]:
    """
    Analyse swing points for market structure:
    - HH + HL = bullish
    - LH + LL = bearish
    - BOS (Break of Structure) = new swing in trend direction
    - CHoCH (Change of Character) = first swing against trend
    """
    result = {
        "trend": "UNKNOWN",
        "last_bos": None,
        "last_choch": None,
        "higher_highs": False,
        "higher_lows": False,
        "lower_highs": False,
        "lower_lows": False,
    }

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return result

    # Check last two swing highs and lows
    sh1_price = swing_highs[-2][1]
    sh2_price = swing_highs[-1][1]
    sl1_price = swing_lows[-2][1]
    sl2_price = swing_lows[-1][1]

    hh = sh2_price > sh1_price
    hl = sl2_price > sl1_price
    lh = sh2_price < sh1_price
    ll = sl2_price < sl1_price

    result["higher_highs"] = hh
    result["higher_lows"] = hl
    result["lower_highs"] = lh
    result["lower_lows"] = ll

    if hh and hl:
        result["trend"] = "BULLISH"
    elif lh and ll:
        result["trend"] = "BEARISH"
    else:
        result["trend"] = "RANGING"

    # BOS: new higher high (bullish) or new lower low (bearish)
    if hh and result["trend"] == "BULLISH":
        result["last_bos"] = {
            "type": "BULLISH",
            "level": sh2_price,
            "bar_index": swing_highs[-1][0],
        }
    elif ll and result["trend"] == "BEARISH":
        result["last_bos"] = {
            "type": "BEARISH",
            "level": sl2_price,
            "bar_index": swing_lows[-1][0],
        }

    # CHoCH: first sign of trend change
    # E.g., after HH+HL, a LL = bearish CHoCH
    if len(swing_highs) >= 3 and len(swing_lows) >= 3:
        prev_hh = swing_highs[-3][1] < swing_highs[-2][1]  # Was trending up
        if prev_hh and ll:
            result["last_choch"] = {
                "type": "BEARISH",
                "level": sl2_price,
                "bar_index": swing_lows[-1][0],
            }
        prev_ll = swing_lows[-3][1] > swing_lows[-2][1]  # Was trending down
        if prev_ll and hh:
            result["last_choch"] = {
                "type": "BULLISH",
                "level": sh2_price,
                "bar_index": swing_highs[-1][0],
            }

    return result


# ─────────────────────────────────────────────────────────────────────
# LAYER 2 CLASS
# ─────────────────────────────────────────────────────────────────────

class TrendLayer:
    """
    Layer 2 — Determine institutional directional bias from multiple timeframes.

    Checks:
    - EMA stack on Weekly, Daily, 4H
    - Market structure (BOS / CHoCH) on Daily and 4H
    - Agreement across timeframes
    """

    def analyze(
        self,
        weekly_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        h4_df: pd.DataFrame,
    ) -> LayerSignal:
        """
        Parameters
        ----------
        weekly_df, daily_df, h4_df : OHLCV DataFrames from MT5
        """
        scores = []
        directions = []
        details: Dict[str, Any] = {}

        for tf_name, df in [("weekly", weekly_df), ("daily", daily_df), ("4h", h4_df)]:
            if df.empty or len(df) < settings.SMA_LONG:
                details[tf_name] = {"status": "insufficient_data"}
                continue

            mas = compute_mas(df)
            latest_mas = {k: float(v.iloc[-1]) for k, v in mas.items()}
            current_price = float(df["close"].iloc[-1])
            stack = ma_stack_direction(current_price, latest_mas)

            swing_highs, swing_lows = find_swing_points(df)
            structure = detect_structure(swing_highs, swing_lows)

            # Composite score for this timeframe
            tf_score = 5.0
            tf_direction = "NEUTRAL"

            if stack == "BULLISH" and structure["trend"] == "BULLISH":
                tf_score = 9.0
                tf_direction = "LONG"
            elif stack == "BEARISH" and structure["trend"] == "BEARISH":
                tf_score = 9.0
                tf_direction = "SHORT"
            elif stack == "BULLISH" or structure["trend"] == "BULLISH":
                tf_score = 7.0
                tf_direction = "LONG"
            elif stack == "BEARISH" or structure["trend"] == "BEARISH":
                tf_score = 7.0
                tf_direction = "SHORT"
            elif structure.get("last_choch"):
                # CHoCH detected — potential trend change
                choch_type = structure["last_choch"]["type"]
                tf_score = 6.0
                tf_direction = "LONG" if choch_type == "BULLISH" else "SHORT"

            scores.append(tf_score)
            directions.append(tf_direction)

            details[tf_name] = {
                "ma_stack": stack,
                "structure_trend": structure["trend"],
                "last_bos": structure["last_bos"],
                "last_choch": structure["last_choch"],
                "hh": structure["higher_highs"],
                "hl": structure["higher_lows"],
                "lh": structure["lower_highs"],
                "ll": structure["lower_lows"],
                "price": current_price,
                "ema_fast": latest_mas["ema_fast"],
                "ema_slow": latest_mas["ema_slow"],
                "sma_mid": latest_mas["sma_mid"],
                "sma_long": latest_mas["sma_long"],
                "tf_score": tf_score,
                "tf_direction": tf_direction,
            }

        # ── Aggregate across timeframes ──
        if not scores:
            return LayerSignal("L2_Trend", "NEUTRAL", 0.0, 0.0, details)

        # Weighted average: weekly 40%, daily 35%, 4H 25%
        weights = [0.40, 0.35, 0.25][: len(scores)]
        final_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)

        # Direction agreement
        long_count = directions.count("LONG")
        short_count = directions.count("SHORT")
        total = len(directions)

        if long_count == total:
            final_direction = "LONG"
            confidence = 1.0
        elif short_count == total:
            final_direction = "SHORT"
            confidence = 1.0
        elif long_count > short_count:
            final_direction = "LONG"
            confidence = long_count / total
        elif short_count > long_count:
            final_direction = "SHORT"
            confidence = short_count / total
        else:
            final_direction = "NEUTRAL"
            confidence = 0.3
            final_score *= 0.5  # Penalise conflicting signals

        details["direction_votes"] = {
            "LONG": long_count,
            "SHORT": short_count,
            "NEUTRAL": directions.count("NEUTRAL"),
        }

        logger.info(
            "L2 Trend: %s score=%.1f conf=%.2f (W:%s D:%s 4H:%s)",
            final_direction, final_score, confidence,
            directions[0] if len(directions) > 0 else "?",
            directions[1] if len(directions) > 1 else "?",
            directions[2] if len(directions) > 2 else "?",
        )

        return LayerSignal(
            layer_name="L2_Trend",
            direction=final_direction,
            score=round(min(10.0, max(0.0, final_score)), 1),
            confidence=round(confidence, 2),
            details=details,
        )
