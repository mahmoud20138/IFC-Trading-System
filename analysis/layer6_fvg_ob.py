"""
IFC Trading System — Layer 6: FVG + Order Block Entry
Detects Fair Value Gaps, Order Blocks, and computes Consequent Encroachment.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer6")


# ─────────────────────────────────────────────────────────────────────
# FVG DETECTION
# ─────────────────────────────────────────────────────────────────────

def detect_fvgs(
    df: pd.DataFrame,
    atr: float,
    min_size_atr: float = None,
) -> List[Dict[str, Any]]:
    """
    Detect Fair Value Gaps (3-candle imbalance).

    Bullish FVG: candle[i-2].high < candle[i].low  (gap up)
    Bearish FVG: candle[i-2].low  > candle[i].high (gap down)

    Returns list of FVG dicts with:
        type, top, bottom, ce (Consequent Encroachment = 50%),
        bar_index, filled (bool)
    """
    if min_size_atr is None:
        min_size_atr = settings.FVG_MIN_SIZE_ATR

    min_size = atr * min_size_atr
    fvgs: List[Dict[str, Any]] = []

    if len(df) < 3:
        return fvgs

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    for i in range(2, len(df)):
        # Bullish FVG
        gap_bottom = highs[i - 2]
        gap_top = lows[i]
        if gap_top > gap_bottom and (gap_top - gap_bottom) >= min_size:
            ce = (gap_top + gap_bottom) / 2
            fvgs.append({
                "type": "BULLISH",
                "top": float(gap_top),
                "bottom": float(gap_bottom),
                "ce": float(ce),
                "size": float(gap_top - gap_bottom),
                "bar_index": i,
                "bar_time": df.index[i] if hasattr(df.index[i], "isoformat") else i,
                "filled": False,
            })

        # Bearish FVG
        gap_top_b = lows[i - 2]
        gap_bottom_b = highs[i]
        if gap_top_b > gap_bottom_b and (gap_top_b - gap_bottom_b) >= min_size:
            ce = (gap_top_b + gap_bottom_b) / 2
            fvgs.append({
                "type": "BEARISH",
                "top": float(gap_top_b),
                "bottom": float(gap_bottom_b),
                "ce": float(ce),
                "size": float(gap_top_b - gap_bottom_b),
                "bar_index": i,
                "bar_time": df.index[i] if hasattr(df.index[i], "isoformat") else i,
                "filled": False,
            })

    # Mark filled FVGs (price traded through them after creation)
    for fvg in fvgs:
        subsequent = df.iloc[fvg["bar_index"] + 1:] if fvg["bar_index"] + 1 < len(df) else pd.DataFrame()
        if subsequent.empty:
            continue
        if fvg["type"] == "BULLISH":
            # Filled if price dropped below the FVG bottom
            if subsequent["low"].min() <= fvg["bottom"]:
                fvg["filled"] = True
        else:
            # Filled if price rose above the FVG top
            if subsequent["high"].max() >= fvg["top"]:
                fvg["filled"] = True

    return fvgs


def get_unfilled_fvgs(fvgs: List[Dict]) -> List[Dict]:
    """Return only unfilled (active) FVGs."""
    return [f for f in fvgs if not f["filled"]]


# ─────────────────────────────────────────────────────────────────────
# ORDER BLOCK DETECTION
# ─────────────────────────────────────────────────────────────────────

def detect_order_blocks(
    df: pd.DataFrame,
    atr: float,
    impulse_min_atr: float = None,
) -> List[Dict[str, Any]]:
    """
    Detect Order Blocks: the last opposite-colour candle before a strong impulse.

    Bullish OB: last bearish candle before a strong bullish impulse
    Bearish OB: last bullish candle before a strong bearish impulse

    Parameters
    ----------
    impulse_min_atr : minimum body size (in ATR) to qualify as "strong impulse"
    """
    if impulse_min_atr is None:
        impulse_min_atr = settings.OB_IMPULSE_MIN_ATR

    obs: List[Dict[str, Any]] = []
    if len(df) < 3:
        return obs

    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for i in range(1, len(df)):
        body = abs(closes[i] - opens[i])
        if body < atr * impulse_min_atr:
            continue

        if closes[i] > opens[i]:
            # Strong bullish candle — look for bearish candle before it
            if closes[i - 1] < opens[i - 1]:
                obs.append({
                    "type": "BULLISH",
                    "high": float(highs[i - 1]),
                    "low": float(lows[i - 1]),
                    "mid": float((highs[i - 1] + lows[i - 1]) / 2),
                    "bar_index": i - 1,
                    "bar_time": df.index[i - 1] if hasattr(df.index[i - 1], "isoformat") else i - 1,
                })
        elif closes[i] < opens[i]:
            # Strong bearish candle — look for bullish candle before it
            if closes[i - 1] > opens[i - 1]:
                obs.append({
                    "type": "BEARISH",
                    "high": float(highs[i - 1]),
                    "low": float(lows[i - 1]),
                    "mid": float((highs[i - 1] + lows[i - 1]) / 2),
                    "bar_index": i - 1,
                    "bar_time": df.index[i - 1] if hasattr(df.index[i - 1], "isoformat") else i - 1,
                })

    return obs


# ─────────────────────────────────────────────────────────────────────
# BREAKER BLOCK DETECTION (#16)
# ─────────────────────────────────────────────────────────────────────

def detect_breaker_blocks(
    df: pd.DataFrame,
    order_blocks: List[Dict],
) -> List[Dict[str, Any]]:
    """
    Detect breaker blocks — order blocks that have been violated/swept.
    When price sweeps through an OB and closes beyond it, the OB becomes
    a breaker block acting as support/resistance in the opposite direction.

    Bullish OB violated → Bearish breaker (resistance)
    Bearish OB violated → Bullish breaker (support)
    """
    breakers: List[Dict[str, Any]] = []
    if df is None or df.empty or not order_blocks:
        return breakers

    closes = df["close"].values

    for ob in order_blocks:
        idx = ob.get("bar_index", 0)
        if idx + 2 >= len(df):
            continue

        subsequent_closes = closes[idx + 1:]
        if len(subsequent_closes) == 0:
            continue

        if ob["type"] == "BULLISH":
            # Bullish OB violated if price closes below OB low
            if any(c < ob["low"] for c in subsequent_closes):
                breakers.append({
                    "type": "BEARISH_BREAKER",  # Now acts as resistance
                    "high": ob["high"],
                    "low": ob["low"],
                    "mid": ob["mid"],
                    "original_ob_type": "BULLISH",
                    "bar_index": ob["bar_index"],
                })
        else:  # BEARISH OB
            # Bearish OB violated if price closes above OB high
            if any(c > ob["high"] for c in subsequent_closes):
                breakers.append({
                    "type": "BULLISH_BREAKER",  # Now acts as support
                    "high": ob["high"],
                    "low": ob["low"],
                    "mid": ob["mid"],
                    "original_ob_type": "BEARISH",
                    "bar_index": ob["bar_index"],
                })

    return breakers


# ─────────────────────────────────────────────────────────────────────
# TIME-DECAY UTILITY (#15)
# ─────────────────────────────────────────────────────────────────────

def _time_decay_factor(bar_index: int, total_bars: int, half_life: int = 50) -> float:
    """
    Compute exponential time-decay factor based on bar age.
    Returns 1.0 for most recent, decaying toward 0 for oldest.
    half_life: number of bars at which factor = 0.5
    """
    age = max(0, total_bars - bar_index)
    return 2.0 ** (-age / max(1, half_life))


# ─────────────────────────────────────────────────────────────────────
# CONFLUENCE CHECK: FVG + OB + VP zone
# ─────────────────────────────────────────────────────────────────────

def find_fvg_at_confluence(
    fvgs: List[Dict],
    reference_levels: List[float],
    tolerance_atr: float = 0.5,
    atr: float = 1.0,
) -> List[Dict]:
    """
    Filter FVGs that sit near reference levels (POC, MA, OB, etc.).
    """
    tolerance = atr * tolerance_atr
    matches = []
    for fvg in fvgs:
        fvg_mid = fvg["ce"]
        for ref in reference_levels:
            if abs(fvg_mid - ref) <= tolerance:
                fvg_copy = dict(fvg)
                fvg_copy["confluence_level"] = ref
                matches.append(fvg_copy)
                break
    return matches


# ─────────────────────────────────────────────────────────────────────
# LAYER 6 CLASS
# ─────────────────────────────────────────────────────────────────────

class FVGOrderBlockLayer:
    """
    Layer 6 — FVG + Order Block entry identification.

    Score depends on:
    - FVG present in the right direction
    - FVG at confluence zone (POC, MA, OB)
    - OB inside FVG for precision
    - CE level available for entry
    """

    def analyze(
        self,
        df: pd.DataFrame,
        atr: float,
        current_price: float,
        trade_direction: str,
        confluence_levels: Optional[List[float]] = None,
    ) -> LayerSignal:
        """
        Parameters
        ----------
        df : LTF OHLCV (15m or 5m)
        atr : current ATR value
        current_price : latest price
        trade_direction : from prior layers
        confluence_levels : list of prices to check FVG proximity (POC, MAs, etc.)
        """
        if confluence_levels is None:
            confluence_levels = []

        all_fvgs = detect_fvgs(df, atr)
        unfilled = get_unfilled_fvgs(all_fvgs)
        obs = detect_order_blocks(df, atr)
        breakers = detect_breaker_blocks(df, obs)
        total_bars = len(df)

        # Filter by direction
        relevant_fvgs = [
            f for f in unfilled
            if f["type"] == ("BULLISH" if trade_direction == "LONG" else "BEARISH")
        ]

        # Find FVGs at confluence zones
        confluence_fvgs = find_fvg_at_confluence(
            relevant_fvgs, confluence_levels, tolerance_atr=0.5, atr=atr
        )

        # Find OBs inside FVGs
        ob_in_fvg = []
        for fvg in relevant_fvgs:
            for ob in obs:
                if ob["type"] == fvg["type"]:
                    if fvg["bottom"] <= ob["mid"] <= fvg["top"]:
                        ob_in_fvg.append({"fvg": fvg, "ob": ob})

        # Filter breakers relevant to trade direction
        relevant_breakers = [
            b for b in breakers
            if (b["type"] == "BULLISH_BREAKER" and trade_direction in ("LONG", "NEUTRAL"))
            or (b["type"] == "BEARISH_BREAKER" and trade_direction in ("SHORT", "NEUTRAL"))
        ]

        details: Dict[str, Any] = {
            "all_fvgs_count": len(all_fvgs),
            "unfilled_count": len(unfilled),
            "relevant_fvgs": relevant_fvgs[-5:],  # Most recent 5
            "confluence_fvgs": confluence_fvgs[-3:],
            "order_blocks": obs[-5:],
            "ob_inside_fvg": ob_in_fvg[-3:],
            "breaker_blocks": relevant_breakers[-3:],
            "entry_candidates": [],
        }

        score = 2.0  # Low base — FVG presence required for entry
        direction = trade_direction

        # ── Score: Any relevant FVG exists? ──
        if not relevant_fvgs:
            score = 1.0
            details["note"] = "No active FVG in trade direction — WAIT"
        else:
            score = 5.0
            best_fvg = relevant_fvgs[-1]  # Most recent

            # ── #15: Time-decay — older FVGs contribute less ──
            decay = _time_decay_factor(best_fvg["bar_index"], total_bars, half_life=50)
            details["best_fvg_decay"] = round(decay, 3)

            # ── Score: FVG near current price? (decayed) ──
            price_to_ce = abs(current_price - best_fvg["ce"])
            if price_to_ce <= atr * 2:
                score += 1.5 * decay  # Price approaching FVG CE

            # ── Score: FVG at confluence? ──
            if confluence_fvgs:
                score += 2.0 * decay
                best_fvg = confluence_fvgs[-1]

            # ── Score: OB inside FVG? ──
            if ob_in_fvg:
                score += 1.0

            # ── #16: Breaker block bonus ──
            if relevant_breakers:
                # Check if price is near a breaker block
                for bb in relevant_breakers:
                    bb_dist = abs(current_price - bb["mid"])
                    if bb_dist <= atr * 1.5:
                        score += 0.8
                        details["breaker_signal"] = (
                            f"{bb['type']} near price @ {bb['mid']:.5f}"
                        )
                        break

            # ── Build entry candidate ──
            entry = {
                "entry_price": best_fvg["ce"],
                "fvg_top": best_fvg["top"],
                "fvg_bottom": best_fvg["bottom"],
                "type": best_fvg["type"],
                "time_decay": round(decay, 3),
            }
            if best_fvg["type"] == "BULLISH":
                entry["stop_loss"] = best_fvg["bottom"] - atr * 0.1
            else:
                entry["stop_loss"] = best_fvg["top"] + atr * 0.1

            if ob_in_fvg:
                entry["refined_entry"] = ob_in_fvg[-1]["ob"]["mid"]

            details["entry_candidates"].append(entry)

        score = max(0.0, min(10.0, score))
        confidence = 0.7 if confluence_fvgs else (0.5 if relevant_fvgs else 0.1)

        logger.info(
            "L6 FVG/OB: score=%.1f fvgs=%d confluence=%d ob_in_fvg=%d",
            score, len(relevant_fvgs), len(confluence_fvgs), len(ob_in_fvg),
        )

        return LayerSignal(
            layer_name="L6_FVG_OrderBlock",
            direction=direction,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
