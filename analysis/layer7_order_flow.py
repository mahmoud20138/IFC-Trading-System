"""
IFC Trading System — Layer 7: Order Flow / Delta Confirmation
Uses tick-volume delta proxy + optional supplementary futures data.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer7")


# ─────────────────────────────────────────────────────────────────────
# DELTA COMPUTATION (tick volume proxy)
# ─────────────────────────────────────────────────────────────────────

def compute_bar_delta(df: pd.DataFrame) -> pd.Series:
    """
    Proxy delta from OHLCV bars.
    If close > open → assign tick_volume as buy volume (positive delta)
    If close < open → assign tick_volume as sell volume (negative delta)
    If close == open → 0
    """
    vol_col = "tick_volume" if "tick_volume" in df.columns else "real_volume"
    vol = df[vol_col].values.astype(np.float64)
    direction = np.sign(df["close"].values - df["open"].values)
    return pd.Series(direction * vol, index=df.index, name="delta")


def compute_cumulative_delta(
    df: pd.DataFrame,
    lookback: int = None,
) -> pd.Series:
    """Cumulative delta over the last *lookback* bars."""
    if lookback is None:
        lookback = settings.DELTA_LOOKBACK_BARS
    delta = compute_bar_delta(df)
    return delta.iloc[-lookback:].cumsum()


def detect_delta_divergence(
    df: pd.DataFrame,
    lookback: int = None,
    threshold: float = None,
) -> Dict[str, Any]:
    """
    Detect divergence between price and delta:
    - Bearish div: price makes new high but cumulative delta declining
    - Bullish div: price makes new low but cumulative delta rising

    Returns dict with divergence type and strength.
    """
    if lookback is None:
        lookback = settings.DELTA_LOOKBACK_BARS
    if threshold is None:
        threshold = settings.DELTA_DIVERGENCE_THRESHOLD

    if len(df) < lookback:
        return {"type": "NONE", "strength": 0}

    window = df.iloc[-lookback:]
    cum_delta = compute_cumulative_delta(df, lookback)

    price_high = window["high"].values
    price_low = window["low"].values
    delta_vals = cum_delta.values

    result = {"type": "NONE", "strength": 0.0}

    # Split into two halves and compare
    mid = lookback // 2
    first_half_max = price_high[:mid].max()
    second_half_max = price_high[mid:].max()
    first_half_delta_max = delta_vals[:mid].max() if len(delta_vals[:mid]) > 0 else 0
    second_half_delta_max = delta_vals[mid:].max() if len(delta_vals[mid:]) > 0 else 0

    first_half_min = price_low[:mid].min()
    second_half_min = price_low[mid:].min()
    first_half_delta_min = delta_vals[:mid].min() if len(delta_vals[:mid]) > 0 else 0
    second_half_delta_min = delta_vals[mid:].min() if len(delta_vals[mid:]) > 0 else 0

    # Bearish divergence: higher price high, lower delta high
    if second_half_max > first_half_max and second_half_delta_max < first_half_delta_max:
        delta_range = abs(first_half_delta_max - second_half_delta_max)
        max_delta = max(abs(first_half_delta_max), 1)
        strength = min(1.0, delta_range / max_delta)
        if strength >= threshold:
            result = {"type": "BEARISH", "strength": round(strength, 3)}

    # Bullish divergence: lower price low, higher delta low
    elif second_half_min < first_half_min and second_half_delta_min > first_half_delta_min:
        delta_range = abs(first_half_delta_min - second_half_delta_min)
        max_delta = max(abs(first_half_delta_min), 1)
        strength = min(1.0, delta_range / max_delta)
        if strength >= threshold:
            result = {"type": "BULLISH", "strength": round(strength, 3)}

    return result


def detect_absorption(
    df: pd.DataFrame,
    level: float,
    atr: float,
    window: int = 5,
) -> Dict[str, Any]:
    """
    Check for absorption at a price level:
    high volume at the level with minimal price movement (held).
    """
    tolerance = atr * 0.3
    near_level = df[
        (df["low"] <= level + tolerance) & (df["high"] >= level - tolerance)
    ].tail(window)

    if near_level.empty:
        return {"detected": False}

    vol_col = "tick_volume" if "tick_volume" in df.columns else "real_volume"
    avg_vol = df[vol_col].mean()
    level_vol = near_level[vol_col].mean()

    # Absorption = high volume but price didn't break through
    vol_ratio = level_vol / avg_vol if avg_vol > 0 else 0
    price_range = near_level["high"].max() - near_level["low"].min()
    avg_range = (df["high"] - df["low"]).mean()
    range_ratio = price_range / avg_range if avg_range > 0 else 1

    absorbed = vol_ratio > 1.3 and range_ratio < 1.0

    return {
        "detected": absorbed,
        "volume_ratio": round(vol_ratio, 2),
        "range_ratio": round(range_ratio, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# LAYER 7 CLASS
# ─────────────────────────────────────────────────────────────────────

class OrderFlowLayer:
    """
    Layer 7 — Delta / order flow confirmation.

    Uses tick-volume proxy (close > open = buy, close < open = sell).
    Score depends on:
    - Current delta direction aligning with trade
    - Divergence detection at key levels
    - Absorption at S/R
    """

    def analyze(
        self,
        df: pd.DataFrame,
        trade_direction: str,
        key_level: Optional[float] = None,
        atr: float = 0.0,
        supplementary_df: Optional[pd.DataFrame] = None,
    ) -> LayerSignal:
        """
        Parameters
        ----------
        df : LTF OHLCV from MT5 (M15/M5)
        trade_direction : "LONG" / "SHORT" from prior layers
        key_level : a price to check for absorption (e.g. POC, FVG CE)
        atr : current ATR
        supplementary_df : optional futures OHLCV from yfinance for real volume
        """
        details: Dict[str, Any] = {"data_source": "tick_volume_proxy"}
        score = 5.0  # Neutral base — proxy data has uncertainty

        if df.empty or len(df) < settings.DELTA_LOOKBACK_BARS:
            return LayerSignal("L7_OrderFlow", "NEUTRAL", 5.0, 0.2, {
                "note": "Insufficient data for delta analysis"
            })

        # ── Current delta direction ──
        cum_delta = compute_cumulative_delta(df)
        last_delta_val = cum_delta.iloc[-1]
        delta_direction = "POSITIVE" if last_delta_val > 0 else "NEGATIVE"
        details["cumulative_delta"] = float(last_delta_val)
        details["delta_direction"] = delta_direction

        # Recent delta trend (last 5 bars)
        recent_delta = compute_bar_delta(df).iloc[-5:]
        recent_sum = recent_delta.sum()
        details["recent_5bar_delta"] = float(recent_sum)

        # ── Alignment with trade direction ──
        if trade_direction == "LONG":
            if recent_sum > 0:
                score += 1.5
                details["alignment"] = "CONFIRMING"
            else:
                score -= 1.0
                details["alignment"] = "DIVERGING"
        elif trade_direction == "SHORT":
            if recent_sum < 0:
                score += 1.5
                details["alignment"] = "CONFIRMING"
            else:
                score -= 1.0
                details["alignment"] = "DIVERGING"

        # ── Divergence check ──
        divergence = detect_delta_divergence(df)
        details["divergence"] = divergence

        if divergence["type"] == "BULLISH" and trade_direction == "LONG":
            score += 2.0  # Delta divergence confirming reversal
        elif divergence["type"] == "BEARISH" and trade_direction == "SHORT":
            score += 2.0
        elif divergence["type"] != "NONE":
            if (divergence["type"] == "BULLISH" and trade_direction == "SHORT") or \
               (divergence["type"] == "BEARISH" and trade_direction == "LONG"):
                score -= 2.0  # Divergence against our direction

        # ── Absorption check at key level ──
        if key_level and atr > 0:
            absorption = detect_absorption(df, key_level, atr)
            details["absorption"] = absorption
            if absorption["detected"]:
                score += 1.5
                details["absorption_note"] = f"Volume absorption at {key_level:.5f}"

        # ── Supplementary real volume (futures) ──
        if supplementary_df is not None and not supplementary_df.empty:
            try:
                supp_delta = compute_bar_delta(supplementary_df)
                supp_recent = supp_delta.iloc[-5:].sum()
                details["futures_delta_5bar"] = float(supp_recent)
                details["data_source"] = "tick_volume_proxy + futures_real_volume"

                # If futures volume agrees, boost confidence
                if (trade_direction == "LONG" and supp_recent > 0) or \
                   (trade_direction == "SHORT" and supp_recent < 0):
                    score += 0.5
            except Exception as e:
                logger.debug("Supplementary delta failed: %s", e)

        # ── #19: MT5 Market Depth (DOM) ──
        try:
            import MetaTrader5 as mt5
            symbol = df.attrs.get("symbol", "")
            if symbol and mt5.symbol_info(symbol):
                if mt5.market_book_add(symbol):
                    book = mt5.market_book_get(symbol)
                    if book:
                        bid_volume = sum(
                            item.volume for item in book
                            if item.type == mt5.BOOK_TYPE_SELL
                        )
                        ask_volume = sum(
                            item.volume for item in book
                            if item.type == mt5.BOOK_TYPE_BUY
                        )
                        total_vol = bid_volume + ask_volume
                        if total_vol > 0:
                            imbalance = (ask_volume - bid_volume) / total_vol
                            details["dom_bid_volume"] = bid_volume
                            details["dom_ask_volume"] = ask_volume
                            details["dom_imbalance"] = round(imbalance, 4)

                            # Imbalance confirms direction
                            if imbalance > 0.15 and trade_direction == "LONG":
                                score += 0.5
                                details["dom_signal"] = "Buy pressure confirms LONG"
                            elif imbalance < -0.15 and trade_direction == "SHORT":
                                score += 0.5
                                details["dom_signal"] = "Sell pressure confirms SHORT"
                            elif abs(imbalance) > 0.15:
                                score -= 0.3
                                details["dom_signal"] = "DOM pressure against direction"

                    mt5.market_book_release(symbol)
        except Exception as dom_err:
            logger.debug("MT5 DOM unavailable: %s", dom_err)

        # ── Final scoring ──
        # Since we're using a proxy, cap the max bonus / penalty
        score = max(0.0, min(10.0, score))

        # Direction from delta perspective
        if last_delta_val > 0:
            delta_dir = "LONG"
        elif last_delta_val < 0:
            delta_dir = "SHORT"
        else:
            delta_dir = "NEUTRAL"

        # Confidence is lower for tick volume proxy
        confidence = min(0.6, (score - 3) / 10) if score > 3 else 0.15

        logger.info(
            "L7 Delta: score=%.1f dir=%s cumDelta=%.0f div=%s absorption=%s",
            score, delta_dir, last_delta_val,
            divergence["type"],
            details.get("absorption", {}).get("detected", "N/A"),
        )

        return LayerSignal(
            layer_name="L7_OrderFlow",
            direction=delta_dir,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
