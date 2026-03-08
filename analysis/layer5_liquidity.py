"""
IFC Trading System — Layer 5: Liquidity Pool Identification
Detects EQH, EQL, swing points, trendlines, and liquidity sweeps.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from scipy.signal import argrelextrema

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer5")


# ─────────────────────────────────────────────────────────────────────
# SWING POINT DETECTION (shared with Layer 2 but kept self-contained)
# ─────────────────────────────────────────────────────────────────────

def find_swings(
    df: pd.DataFrame, order: int = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Return swing highs and swing lows as dicts with index, price, bar_time.
    """
    if order is None:
        order = settings.SWING_LOOKBACK

    highs_idx = argrelextrema(df["high"].values, np.greater_equal, order=order)[0]
    lows_idx = argrelextrema(df["low"].values, np.less_equal, order=order)[0]

    swing_highs = [
        {"idx": int(i), "price": float(df["high"].iloc[i]),
         "time": df.index[i] if hasattr(df.index[i], "isoformat") else i}
        for i in highs_idx
    ]
    swing_lows = [
        {"idx": int(i), "price": float(df["low"].iloc[i]),
         "time": df.index[i] if hasattr(df.index[i], "isoformat") else i}
        for i in lows_idx
    ]
    return swing_highs, swing_lows


# ─────────────────────────────────────────────────────────────────────
# EQUAL HIGHS / EQUAL LOWS
# ─────────────────────────────────────────────────────────────────────

def find_equal_highs(
    swing_highs: List[Dict],
    atr: float,
    tolerance_frac: float = None,
) -> List[Dict[str, Any]]:
    """
    Find clusters of 2+ swing highs whose prices are within tolerance.
    Retail traders place stops just above these → liquidity pool.
    """
    if tolerance_frac is None:
        tolerance_frac = settings.EQH_EQL_TOLERANCE_ATR
    tolerance = atr * tolerance_frac

    clusters = []
    used = set()

    for i, sh in enumerate(swing_highs):
        if i in used:
            continue
        group = [sh]
        for j, sh2 in enumerate(swing_highs[i + 1:], start=i + 1):
            if j in used:
                continue
            if abs(sh["price"] - sh2["price"]) <= tolerance:
                group.append(sh2)
                used.add(j)
        if len(group) >= 2:
            used.add(i)
            avg_price = np.mean([g["price"] for g in group])
            clusters.append({
                "type": "EQH",
                "level": float(avg_price),
                "count": len(group),
                "touches": group,
            })

    return clusters


def find_equal_lows(
    swing_lows: List[Dict],
    atr: float,
    tolerance_frac: float = None,
) -> List[Dict[str, Any]]:
    """Find clusters of equal lows (stops rest below)."""
    if tolerance_frac is None:
        tolerance_frac = settings.EQH_EQL_TOLERANCE_ATR
    tolerance = atr * tolerance_frac

    clusters = []
    used = set()

    for i, sl in enumerate(swing_lows):
        if i in used:
            continue
        group = [sl]
        for j, sl2 in enumerate(swing_lows[i + 1:], start=i + 1):
            if j in used:
                continue
            if abs(sl["price"] - sl2["price"]) <= tolerance:
                group.append(sl2)
                used.add(j)
        if len(group) >= 2:
            used.add(i)
            avg_price = np.mean([g["price"] for g in group])
            clusters.append({
                "type": "EQL",
                "level": float(avg_price),
                "count": len(group),
                "touches": group,
            })

    return clusters


# ─────────────────────────────────────────────────────────────────────
# LIQUIDITY SWEEP DETECTION
# ─────────────────────────────────────────────────────────────────────

def detect_liquidity_sweep(
    df: pd.DataFrame,
    liquidity_pools: List[Dict[str, Any]],
    lookback: int = 10,
    confirm_bars: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Check if price recently swept a liquidity pool and reversed.

    A sweep is when:
    - A wick (not body) exceeds the pool level
    - The candle body closes back inside the prior range

    Enhancement #17: Requires 2-3 candle confirmation — at least 2 of
    the next `confirm_bars` candles must close back inside the range
    for the sweep to be considered confirmed.

    Returns the sweep info or None.
    """
    if df.empty or len(df) < 2:
        return None

    recent = df.iloc[-lookback:]

    for pool in liquidity_pools:
        level = pool["level"]
        pool_type = pool["type"]  # "EQH" or "EQL"

        for i in range(len(recent)):
            bar = recent.iloc[i]
            body_high = max(float(bar["open"]), float(bar["close"]))
            body_low = min(float(bar["open"]), float(bar["close"]))
            wick_high = float(bar["high"])
            wick_low = float(bar["low"])

            if pool_type == "EQH":
                # Price wicked above EQH but body closed below
                if wick_high > level and body_high <= level:
                    # #17: Check 2-3 candle confirmation window
                    confirm_count = 0
                    max_check = min(confirm_bars, len(recent) - i - 1)
                    for j in range(1, max_check + 1):
                        next_close = float(recent.iloc[i + j]["close"])
                        if next_close < level:
                            confirm_count += 1

                    confirmed = confirm_count >= min(2, max_check)
                    if confirmed:
                        return {
                            "type": "SWEEP_HIGH",
                            "pool": pool,
                            "sweep_bar_idx": recent.index[i],
                            "wick_high": wick_high,
                            "reversal_confirmed": True,
                            "confirm_bars": confirm_count,
                        }
            elif pool_type == "EQL":
                # Price wicked below EQL but body closed above
                if wick_low < level and body_low >= level:
                    # #17: Check 2-3 candle confirmation window
                    confirm_count = 0
                    max_check = min(confirm_bars, len(recent) - i - 1)
                    for j in range(1, max_check + 1):
                        next_close = float(recent.iloc[i + j]["close"])
                        if next_close > level:
                            confirm_count += 1

                    confirmed = confirm_count >= min(2, max_check)
                    if confirmed:
                        return {
                            "type": "SWEEP_LOW",
                            "pool": pool,
                            "sweep_bar_idx": recent.index[i],
                            "wick_low": wick_low,
                            "reversal_confirmed": True,
                            "confirm_bars": confirm_count,
                        }

    return None


# ─────────────────────────────────────────────────────────────────────
# TRENDLINE DETECTION  (Enhancement Plan #7)
# ─────────────────────────────────────────────────────────────────────

def detect_trendlines(
    swing_highs: List[Dict],
    swing_lows: List[Dict],
    min_touches: int = None,
    tolerance_pct: float = 0.001,
) -> List[Dict[str, Any]]:
    """
    Detect trendlines via linear regression on swing points.
    Trendlines with >= min_touches are liquidity magnets.

    Returns list of trendline dicts with type, slope, intercept, touches, current_level.
    """
    if min_touches is None:
        min_touches = getattr(settings, "MIN_TRENDLINE_TOUCHES", 3)

    trendlines = []

    # Rising trendlines (connecting swing lows)
    if len(swing_lows) >= min_touches:
        lows_arr = np.array([(s["idx"], s["price"]) for s in swing_lows])
        tl = _fit_trendline(lows_arr, min_touches, tolerance_pct)
        if tl is not None:
            tl["type"] = "RISING_TRENDLINE"
            trendlines.append(tl)

    # Falling trendlines (connecting swing highs)
    if len(swing_highs) >= min_touches:
        highs_arr = np.array([(s["idx"], s["price"]) for s in swing_highs])
        tl = _fit_trendline(highs_arr, min_touches, tolerance_pct)
        if tl is not None:
            tl["type"] = "FALLING_TRENDLINE"
            trendlines.append(tl)

    return trendlines


def _fit_trendline(
    points: np.ndarray,
    min_touches: int,
    tolerance_pct: float,
) -> Optional[Dict[str, Any]]:
    """Fit a line through swing points and count touches within tolerance."""
    if len(points) < 2:
        return None

    x = points[:, 0]
    y = points[:, 1]

    # Simple linear regression
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs[0], coeffs[1]

    # Count how many points touch the line (within tolerance)
    fitted = slope * x + intercept
    tolerance = np.mean(np.abs(y)) * tolerance_pct
    touches = int(np.sum(np.abs(y - fitted) <= tolerance))

    if touches < min_touches:
        return None

    # Current projected level (at last bar index)
    current_level = slope * x[-1] + intercept

    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "touches": touches,
        "current_level": float(current_level),
        "start_idx": int(x[0]),
        "end_idx": int(x[-1]),
    }


# ─────────────────────────────────────────────────────────────────────
# PDH / PDL DETECTION  (Enhancement Plan #7)
# ─────────────────────────────────────────────────────────────────────

def detect_pdh_pdl(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    Detect Previous Day's High (PDH) and Previous Day's Low (PDL).
    These are key liquidity pools that institutional traders target.

    Works by grouping bars into calendar days and taking yesterday's range.
    """
    result = {"pdh": None, "pdl": None, "session_open": None}

    if df is None or df.empty or len(df) < 2:
        return result

    try:
        # Try to group by date
        if hasattr(df.index, "date"):
            df_copy = df.copy()
            df_copy["_date"] = df_copy.index.date
        elif "time" in df.columns:
            df_copy = df.copy()
            df_copy["_date"] = pd.to_datetime(df_copy["time"]).dt.date
        else:
            return result

        daily_groups = df_copy.groupby("_date")
        dates = sorted(daily_groups.groups.keys())

        if len(dates) >= 2:
            prev_day = dates[-2]
            prev_data = daily_groups.get_group(prev_day)
            result["pdh"] = float(prev_data["high"].max())
            result["pdl"] = float(prev_data["low"].min())

            # Today's session open
            today = dates[-1]
            today_data = daily_groups.get_group(today)
            result["session_open"] = float(today_data["open"].iloc[0])

    except Exception as e:
        logger.debug("PDH/PDL detection failed: %s", e)

    return result


# ─────────────────────────────────────────────────────────────────────
# LAYER 5 CLASS
# ─────────────────────────────────────────────────────────────────────

class LiquidityLayer:
    """
    Layer 5 — Map liquidity pools and detect sweeps.

    Score depends on:
    - Clear EQH/EQL present in trade direction
    - Recent sweep of liquidity (highest score)
    - Proximity of liquidity to current price
    """

    def analyze(
        self,
        df: pd.DataFrame,
        atr: float,
        current_price: float,
        trade_direction: str = "NEUTRAL",
    ) -> LayerSignal:
        swing_highs, swing_lows = find_swings(df)
        eqh = find_equal_highs(swing_highs, atr)
        eql = find_equal_lows(swing_lows, atr)

        all_pools = eqh + eql
        # Also add raw swing highs/lows as minor liquidity
        major_swings = []
        if swing_highs:
            major_swings.append({
                "type": "EQH", "level": swing_highs[-1]["price"], "count": 1
            })
        if swing_lows:
            major_swings.append({
                "type": "EQL", "level": swing_lows[-1]["price"], "count": 1
            })

        sweep = detect_liquidity_sweep(df, all_pools + major_swings)

        details: Dict[str, Any] = {
            "equal_highs": [{"level": e["level"], "count": e["count"]} for e in eqh],
            "equal_lows": [{"level": e["level"], "count": e["count"]} for e in eql],
            "swing_highs": [sh["price"] for sh in swing_highs[-5:]],
            "swing_lows": [sl["price"] for sl in swing_lows[-5:]],
            "sweep": sweep,
        }

        score = 5.0
        direction = trade_direction

        # ── Sweep detected = highest conviction ──
        if sweep:
            if sweep["type"] == "SWEEP_LOW" and trade_direction in ("LONG", "NEUTRAL"):
                score += 3.0
                direction = "LONG"
                details["sweep_signal"] = "BULLISH — stops grabbed below, reversal up"
            elif sweep["type"] == "SWEEP_HIGH" and trade_direction in ("SHORT", "NEUTRAL"):
                score += 3.0
                direction = "SHORT"
                details["sweep_signal"] = "BEARISH — stops grabbed above, reversal down"
            elif sweep["type"] == "SWEEP_LOW" and trade_direction == "SHORT":
                score -= 1.0  # Against our direction
                details["sweep_signal"] = "WARNING — sweep against trade direction"
            elif sweep["type"] == "SWEEP_HIGH" and trade_direction == "LONG":
                score -= 1.0
                details["sweep_signal"] = "WARNING — sweep against trade direction"

        # ── Liquidity target in profit direction ──
        if trade_direction == "LONG":
            targets_above = [e for e in eqh if e["level"] > current_price]
            if targets_above:
                score += 1.0
                details["target_liquidity"] = targets_above[0]["level"]
        elif trade_direction == "SHORT":
            targets_below = [e for e in eql if e["level"] < current_price]
            if targets_below:
                score += 1.0
                details["target_liquidity"] = targets_below[-1]["level"]

        # ── Clear liquidity pool identified ──
        if len(eqh) + len(eql) > 0:
            score += 0.5

        # ── Trendline detection & scoring ──
        trendlines = detect_trendlines(swing_highs, swing_lows)
        details["trendlines"] = trendlines
        if trendlines:
            for tl in trendlines:
                tl_level = tl.get("current_level", 0)
                if tl_level <= 0:
                    continue
                distance_pct = abs(current_price - tl_level) / current_price * 100
                if distance_pct < 0.5:  # Price near trendline
                    if tl["type"] == "support" and trade_direction in ("LONG", "NEUTRAL"):
                        score += 0.8
                        details["trendline_signal"] = f"Near rising support @ {tl_level:.5f}"
                    elif tl["type"] == "resistance" and trade_direction in ("SHORT", "NEUTRAL"):
                        score += 0.8
                        details["trendline_signal"] = f"Near falling resistance @ {tl_level:.5f}"
                    elif tl["type"] == "support" and trade_direction == "SHORT":
                        score -= 0.3
                        details["trendline_warning"] = "Price near support — caution for SHORT"
                    elif tl["type"] == "resistance" and trade_direction == "LONG":
                        score -= 0.3
                        details["trendline_warning"] = "Price near resistance — caution for LONG"

        # ── PDH / PDL detection & scoring ──
        pdh_pdl = detect_pdh_pdl(df)
        details["pdh_pdl"] = pdh_pdl
        pdh = pdh_pdl.get("pdh")
        pdl = pdh_pdl.get("pdl")
        session_open = pdh_pdl.get("session_open")

        if pdh and pdl:
            # Add PDH/PDL as liquidity targets
            pdh_dist = abs(current_price - pdh) / current_price * 100
            pdl_dist = abs(current_price - pdl) / current_price * 100

            if trade_direction == "LONG" and current_price < pdh and pdh_dist < 2.0:
                score += 0.5
                details["pdh_target"] = f"PDH @ {pdh:.5f} — upside liquidity target"
            elif trade_direction == "SHORT" and current_price > pdl and pdl_dist < 2.0:
                score += 0.5
                details["pdl_target"] = f"PDL @ {pdl:.5f} — downside liquidity target"

            # Sweep of PDH/PDL is high conviction
            if current_price > pdh and pdh_dist < 0.3:
                if trade_direction in ("SHORT", "NEUTRAL"):
                    score += 1.0
                    details["pdh_sweep"] = "Price swept above PDH — reversal SHORT signal"
            elif current_price < pdl and pdl_dist < 0.3:
                if trade_direction in ("LONG", "NEUTRAL"):
                    score += 1.0
                    details["pdl_sweep"] = "Price swept below PDL — reversal LONG signal"

        if session_open:
            details["session_open"] = session_open

        score = max(0.0, min(10.0, score))
        confidence = 0.8 if sweep else 0.4
        # Boost confidence if trendline or PDH/PDL confirms
        if trendlines and any(
            abs(current_price - tl.get("current_level", 0)) / current_price * 100 < 0.5
            for tl in trendlines
        ):
            confidence = min(1.0, confidence + 0.1)
        if pdh and pdl:
            confidence = min(1.0, confidence + 0.05)

        logger.info(
            "L5 Liquidity: score=%.1f eqh=%d eql=%d sweep=%s trendlines=%d pdh=%s pdl=%s",
            score, len(eqh), len(eql), sweep["type"] if sweep else "none",
            len(trendlines), pdh, pdl,
        )

        return LayerSignal(
            layer_name="L5_Liquidity",
            direction=direction,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
