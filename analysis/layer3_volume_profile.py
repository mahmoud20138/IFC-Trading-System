"""
IFC Trading System — Layer 3: Price Intensity (Volume Profile)
Computes POC, VAH, VAL, HVN, LVN from bar/tick data.
"""

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer3")


# ─────────────────────────────────────────────────────────────────────
# VOLUME PROFILE COMPUTATION
# ─────────────────────────────────────────────────────────────────────

@dataclass
class VolumeProfile:
    """Result of a volume profile computation."""
    price_levels: np.ndarray     # centre of each price bin
    volume_at_price: np.ndarray  # volume in each bin
    poc: float                   # Point of Control
    vah: float                   # Value Area High
    val: float                   # Value Area Low
    hvn: List[float]             # High Volume Nodes
    lvn: List[float]             # Low Volume Nodes
    shape: str                   # "P" | "b" | "D" | "Thin"
    total_volume: float


def compute_volume_profile(
    df: pd.DataFrame,
    num_bins: int = None,
    value_area_pct: float = None,
    use_tick_volume: bool = True,
) -> VolumeProfile:
    """
    Build a volume profile from an OHLCV DataFrame.

    For each bar the volume is distributed uniformly across the bar's
    high-low range.  This is a standard approximation when tick data is
    not available.

    Parameters
    ----------
    df : OHLCV DataFrame (must have 'high', 'low', 'close', 'tick_volume' / 'real_volume')
    num_bins : number of price bins (default from settings)
    value_area_pct : fraction of total volume for the value area (default 0.70)
    use_tick_volume : True → use tick_volume, False → use real_volume
    """
    if num_bins is None:
        num_bins = settings.VP_NUM_BINS
    if value_area_pct is None:
        value_area_pct = settings.VALUE_AREA_PCT

    price_min = float(df["low"].min())
    price_max = float(df["high"].max())

    if price_max - price_min == 0:
        mid = price_min
        return VolumeProfile(
            np.array([mid]), np.array([1.0]),
            mid, mid, mid, [], [], "D", 1.0,
        )

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_centres = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_width = bin_edges[1] - bin_edges[0]
    volume_hist = np.zeros(num_bins, dtype=np.float64)

    vol_col = "tick_volume" if use_tick_volume else "real_volume"
    if vol_col not in df.columns:
        vol_col = "tick_volume"

    for _, bar in df.iterrows():
        h, l, v = float(bar["high"]), float(bar["low"]), float(bar[vol_col])
        if v <= 0 or h == l:
            # Assign all volume to the close bar
            idx = int(np.clip(
                np.searchsorted(bin_edges, float(bar["close"])) - 1,
                0, num_bins - 1,
            ))
            volume_hist[idx] += v if v > 0 else 1
            continue
        # Distribute volume across the bar's range
        low_bin = int(np.clip(np.searchsorted(bin_edges, l) - 1, 0, num_bins - 1))
        high_bin = int(np.clip(np.searchsorted(bin_edges, h) - 1, 0, num_bins - 1))
        n_bins_covered = high_bin - low_bin + 1
        vol_per_bin = v / n_bins_covered
        volume_hist[low_bin: high_bin + 1] += vol_per_bin

    # POC
    poc_idx = int(np.argmax(volume_hist))
    poc = float(bin_centres[poc_idx])

    # Value Area (start from POC, expand outward until >= value_area_pct of total)
    total_vol = volume_hist.sum()
    va_vol = volume_hist[poc_idx]
    lo, hi = poc_idx, poc_idx

    while va_vol / total_vol < value_area_pct and (lo > 0 or hi < num_bins - 1):
        vol_above = volume_hist[hi + 1] if hi + 1 < num_bins else 0
        vol_below = volume_hist[lo - 1] if lo - 1 >= 0 else 0
        if vol_above >= vol_below and hi + 1 < num_bins:
            hi += 1
            va_vol += volume_hist[hi]
        elif lo - 1 >= 0:
            lo -= 1
            va_vol += volume_hist[lo]
        else:
            hi = min(hi + 1, num_bins - 1)
            va_vol += volume_hist[hi]

    vah = float(bin_centres[hi])
    val = float(bin_centres[lo])

    # HVN / LVN via peak detection
    if len(volume_hist) > 5:
        smooth = pd.Series(volume_hist).rolling(5, center=True, min_periods=1).mean().values
        hvn_idx, _ = find_peaks(smooth, distance=max(3, num_bins // 20))
        lvn_idx, _ = find_peaks(-smooth, distance=max(3, num_bins // 20))
        hvn = [float(bin_centres[i]) for i in hvn_idx]
        lvn = [float(bin_centres[i]) for i in lvn_idx]
    else:
        hvn, lvn = [poc], []

    # Profile shape detection
    shape = _detect_shape(volume_hist, poc_idx, num_bins)

    return VolumeProfile(
        price_levels=bin_centres,
        volume_at_price=volume_hist,
        poc=poc, vah=vah, val=val,
        hvn=hvn, lvn=lvn,
        shape=shape,
        total_volume=total_vol,
    )


def _detect_shape(hist: np.ndarray, poc_idx: int, num_bins: int) -> str:
    """
    P-shape: most volume in upper half → bullish
    b-shape: most volume in lower half → bearish
    D-shape: balanced around the middle → range
    Thin:    relatively flat → trending
    """
    mid = num_bins // 2
    upper_vol = hist[mid:].sum()
    lower_vol = hist[:mid].sum()
    total = hist.sum()
    if total == 0:
        return "D"

    ratio = abs(upper_vol - lower_vol) / total
    poc_pct = hist[poc_idx] / total

    if poc_pct < 0.02:
        return "Thin"
    if ratio < 0.15:
        return "D"
    if upper_vol > lower_vol:
        return "P"
    return "b"


# ─────────────────────────────────────────────────────────────────────
# SESSION-BASED PROFILES & NAKED POC TRACKING
# ─────────────────────────────────────────────────────────────────────

def compute_session_profiles(
    daily_dfs: List[pd.DataFrame],
) -> List[VolumeProfile]:
    """Compute a VolumeProfile for each session (day)."""
    return [compute_volume_profile(df) for df in daily_dfs if not df.empty]


def find_naked_pocs(
    profiles: List[VolumeProfile],
    current_price: float,
    tolerance_pct: float = 0.001,
) -> List[Dict[str, Any]]:
    """
    Find POCs from prior sessions that have never been revisited.
    """
    naked = []
    for i, prof in enumerate(profiles[:-1]):  # Exclude today's developing
        poc = prof.poc
        was_hit = False
        # Check all subsequent sessions
        for future_prof in profiles[i + 1:]:
            if future_prof.price_levels is None or len(future_prof.price_levels) == 0:
                continue
            price_min = float(future_prof.price_levels.min())
            price_max = float(future_prof.price_levels.max())
            if price_min <= poc <= price_max:
                was_hit = True
                break
        if not was_hit:
            naked.append({
                "session_index": i,
                "poc": poc,
                "distance_from_current": abs(current_price - poc),
            })
    return sorted(naked, key=lambda x: x["distance_from_current"])


def detect_poc_migration(
    profiles: List[VolumeProfile],
) -> str:
    """
    Check if developing POC is migrating UP, DOWN, or FLAT.
    Expects profiles in chronological order (e.g., every 30 min snapshot).
    """
    if len(profiles) < 2:
        return "UNKNOWN"
    pocs = [p.poc for p in profiles]
    ups = sum(1 for i in range(1, len(pocs)) if pocs[i] > pocs[i - 1])
    downs = sum(1 for i in range(1, len(pocs)) if pocs[i] < pocs[i - 1])
    if ups >= 2 and ups > downs:
        return "UP"
    if downs >= 2 and downs > ups:
        return "DOWN"
    return "FLAT"


# ─────────────────────────────────────────────────────────────────────
# LAYER 3 CLASS
# ─────────────────────────────────────────────────────────────────────

class VolumeProfileLayer:
    """
    Layer 3 — Score based on price intensity and VP structure.

    Evaluates:
    - Current price position relative to POC (premium vs. discount)
    - Profile shape alignment with trade direction
    - Naked POC proximity
    - POC migration direction
    """

    def analyze(
        self,
        current_price: float,
        composite_profile: VolumeProfile,
        session_profiles: Optional[List[VolumeProfile]] = None,
        developing_profiles: Optional[List[VolumeProfile]] = None,
        trade_direction: str = "NEUTRAL",
    ) -> LayerSignal:
        """
        Parameters
        ----------
        current_price : latest bid/ask midpoint
        composite_profile : VP over last N sessions
        session_profiles : individual session VPs (for naked POC detection)
        developing_profiles : intraday snapshots for POC migration
        trade_direction : from Layer 2 — "LONG" / "SHORT" / "NEUTRAL"
        """
        score = 5.0
        details: Dict[str, Any] = {}

        vp = composite_profile
        details["poc"] = vp.poc
        details["vah"] = vp.vah
        details["val"] = vp.val
        details["shape"] = vp.shape
        details["hvn"] = vp.hvn[:5]  # Top 5
        details["lvn"] = vp.lvn[:5]

        # ── Price relative to Value Area ──
        if current_price > vp.vah:
            position = "ABOVE_VA"
        elif current_price < vp.val:
            position = "BELOW_VA"
        elif current_price > vp.poc:
            position = "UPPER_VA"
        else:
            position = "LOWER_VA"
        details["price_position"] = position

        # For LONG trades: buying near/below POC (discount) is better
        # For SHORT trades: selling near/above POC (premium) is better
        if trade_direction == "LONG":
            if position in ("BELOW_VA", "LOWER_VA"):
                score += 2.5  # In discount zone — ideal
            elif position == "UPPER_VA":
                score += 1.0
            elif position == "ABOVE_VA":
                score -= 1.0  # Buying in premium — not ideal
        elif trade_direction == "SHORT":
            if position in ("ABOVE_VA", "UPPER_VA"):
                score += 2.5
            elif position == "LOWER_VA":
                score += 1.0
            elif position == "BELOW_VA":
                score -= 1.0

        # ── Profile shape alignment ──
        if vp.shape == "P" and trade_direction == "LONG":
            score += 1.0
        elif vp.shape == "b" and trade_direction == "SHORT":
            score += 1.0
        elif vp.shape == "Thin":
            score += 0.5  # Trending — go with flow
        elif vp.shape == "D":
            score -= 0.5  # Ranging — reduces conviction

        # ── Naked POCs ──
        naked = []
        if session_profiles and len(session_profiles) >= 2:
            naked = find_naked_pocs(session_profiles, current_price)
            details["naked_pocs_nearby"] = len([
                n for n in naked
                if n["distance_from_current"] < abs(vp.vah - vp.val) * 0.5
            ])
            if details["naked_pocs_nearby"] > 0:
                score += 1.0  # Nearby naked POC = magnet / confluence

        # ── POC Migration ──
        if developing_profiles:
            migration = detect_poc_migration(developing_profiles)
            details["poc_migration"] = migration
            if migration == "UP" and trade_direction == "LONG":
                score += 1.5
            elif migration == "DOWN" and trade_direction == "SHORT":
                score += 1.5
            elif migration in ("UP", "DOWN"):
                if (migration == "UP" and trade_direction == "SHORT") or \
                   (migration == "DOWN" and trade_direction == "LONG"):
                    score -= 1.5

        score = max(0.0, min(10.0, score))

        # Direction from VP alone
        if vp.shape == "P":
            vp_direction = "LONG"
        elif vp.shape == "b":
            vp_direction = "SHORT"
        else:
            vp_direction = trade_direction  # Defer to trend

        confidence = min(1.0, (score - 3) / 7) if score > 3 else 0.1

        logger.info(
            "L3 VP: score=%.1f shape=%s pos=%s poc=%.5f vah=%.5f val=%.5f",
            score, vp.shape, position, vp.poc, vp.vah, vp.val,
        )

        return LayerSignal(
            layer_name="L3_VolumeProfile",
            direction=vp_direction,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
