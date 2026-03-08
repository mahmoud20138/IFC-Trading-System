"""
IFC Trading System — Layer 4: Candle Density Mapping
Detects dense cluster zones (S/R) and thin zones (fast travel).
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer4")


def compute_candle_density(
    df: pd.DataFrame,
    num_bins: int = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Count how many candle *bodies* overlap each price level.

    Returns (price_levels, density_counts).
    Dense zones = many overlapping bodies = S/R.
    Thin zones = few overlapping bodies = fast travel.
    """
    if df.empty:
        return np.array([]), np.array([])

    if num_bins is None:
        num_bins = settings.VP_NUM_BINS

    body_highs = df[["open", "close"]].max(axis=1).values
    body_lows = df[["open", "close"]].min(axis=1).values

    price_min = float(body_lows.min())
    price_max = float(body_highs.max())

    if price_max == price_min:
        return np.array([price_min]), np.array([len(df)])

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_centres = (bin_edges[:-1] + bin_edges[1:]) / 2
    density = np.zeros(num_bins, dtype=np.int32)

    for bh, bl in zip(body_highs, body_lows):
        lo_idx = max(0, int(np.searchsorted(bin_edges, bl)) - 1)
        hi_idx = min(num_bins - 1, int(np.searchsorted(bin_edges, bh)) - 1)
        density[lo_idx: hi_idx + 1] += 1

    return bin_centres, density


def find_dense_zones(
    price_levels: np.ndarray,
    density: np.ndarray,
    min_overlap: int = None,
) -> List[Dict[str, Any]]:
    """
    Identify contiguous price regions where density >= min_overlap.
    Returns list of {'low': float, 'high': float, 'peak_density': int}.
    """
    if min_overlap is None:
        min_overlap = settings.DENSITY_MIN_OVERLAP

    zones = []
    in_zone = False
    zone_start = 0
    peak = 0

    for i, d in enumerate(density):
        if d >= min_overlap:
            if not in_zone:
                in_zone = True
                zone_start = i
                peak = d
            else:
                peak = max(peak, d)
        else:
            if in_zone:
                zones.append({
                    "low": float(price_levels[zone_start]),
                    "high": float(price_levels[i - 1]),
                    "peak_density": int(peak),
                })
                in_zone = False
    if in_zone:
        zones.append({
            "low": float(price_levels[zone_start]),
            "high": float(price_levels[-1]),
            "peak_density": int(peak),
        })

    return zones


def find_thin_zones(
    price_levels: np.ndarray,
    density: np.ndarray,
    max_overlap: int = 2,
) -> List[Dict[str, Any]]:
    """Identify thin (fast-travel) zones where density <= max_overlap."""
    zones = []
    in_zone = False
    zone_start = 0

    for i, d in enumerate(density):
        if d <= max_overlap:
            if not in_zone:
                in_zone = True
                zone_start = i
        else:
            if in_zone:
                zones.append({
                    "low": float(price_levels[zone_start]),
                    "high": float(price_levels[i - 1]),
                })
                in_zone = False
    if in_zone:
        zones.append({
            "low": float(price_levels[zone_start]),
            "high": float(price_levels[-1]),
        })

    return zones


# ─────────────────────────────────────────────────────────────────────
# LAYER 4 CLASS
# ─────────────────────────────────────────────────────────────────────

class CandleDensityLayer:
    """
    Layer 4 — Candle density confirmation.

    Dense clusters confirm institutional zones found by VP (Layer 3).
    If density contradicts VP (dense zone where VP shows LVN), flag it.
    """

    def analyze(
        self,
        df: pd.DataFrame,
        vp_hvn: List[float],
        vp_lvn: List[float],
        current_price: float,
        trade_direction: str = "NEUTRAL",
    ) -> LayerSignal:
        """
        Parameters
        ----------
        df : OHLCV DataFrame (e.g. Daily or 4H)
        vp_hvn : High Volume Nodes from Layer 3
        vp_lvn : Low Volume Nodes from Layer 3
        current_price : latest price
        trade_direction : from Layer 2
        """
        prices, density = compute_candle_density(df)
        if len(prices) == 0:
            return LayerSignal("L4_CandleDensity", "NEUTRAL", 5.0, 0.0, {})

        dense = find_dense_zones(prices, density)
        thin = find_thin_zones(prices, density)

        details: Dict[str, Any] = {
            "dense_zones": dense[:10],
            "thin_zones": thin[:10],
        }

        score = 5.0

        # ── Cross-validate with VP HVN ──
        alignment_count = 0
        contradiction_count = 0

        for dz in dense:
            dz_mid = (dz["low"] + dz["high"]) / 2
            # Check if any HVN falls within this dense zone
            for hvn in vp_hvn:
                if dz["low"] <= hvn <= dz["high"]:
                    alignment_count += 1
                    break
            # Check if any LVN falls within (contradiction)
            for lvn in vp_lvn:
                if dz["low"] <= lvn <= dz["high"]:
                    contradiction_count += 1
                    break

        details["hvn_alignment"] = alignment_count
        details["lvn_contradictions"] = contradiction_count

        if alignment_count > 0:
            score += min(2.0, alignment_count * 0.5)  # Confirmed zones
        if contradiction_count > 0:
            score -= min(2.0, contradiction_count * 0.7)

        # ── Is current price near a dense zone? ──
        near_dense = False
        for dz in dense:
            margin = (dz["high"] - dz["low"]) * 0.2
            if (dz["low"] - margin) <= current_price <= (dz["high"] + margin):
                near_dense = True
                details["price_at_dense_zone"] = dz
                break

        if near_dense:
            # Being near a dense zone can be good (S/R) or bad (breakout needed)
            if trade_direction in ("LONG", "SHORT"):
                score += 1.0  # Potential reaction zone

        # ── Thin zone in profit direction? (fast travel expected) ──
        for tz in thin:
            if trade_direction == "LONG" and tz["low"] > current_price:
                score += 0.5  # Thin zone above = price can travel fast
                details["thin_above"] = tz
                break
            elif trade_direction == "SHORT" and tz["high"] < current_price:
                score += 0.5
                details["thin_below"] = tz
                break

        score = max(0.0, min(10.0, score))
        confidence = min(1.0, alignment_count / max(1, len(dense)))

        logger.info(
            "L4 Density: score=%.1f dense=%d thin=%d align=%d contradict=%d",
            score, len(dense), len(thin), alignment_count, contradiction_count,
        )

        return LayerSignal(
            layer_name="L4_CandleDensity",
            direction=trade_direction,   # Density doesn't change direction
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
