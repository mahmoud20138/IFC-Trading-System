"""
IFC Trading System — Layer 9: Correlation Engine
Evaluates cross-asset correlations, divergence signals,
correlation-adjusted risk, and lead-lag relationships.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from analysis.layer1_intermarket import LayerSignal
from config import settings
from config.instruments import WATCHLIST, INTERMARKET_TICKERS
from utils.helpers import setup_logging

logger = setup_logging("ifc.layer9")

# ── Static correlation matrix from plan Part 9A ──────────────────
# Keys are (base_symbol, correlated_symbol) → r value
# base_symbol uses display keys (no 'm' suffix)
_STATIC_CORR = getattr(settings, "CORRELATION_MATRIX", {})

# ── Correlation penalty table from plan Part 9C ──────────────────
_PENALTIES = getattr(settings, "CORRELATION_PENALTIES", {
    "very_strong": {"min_r": 0.85, "multiplier": 0.40},
    "strong":      {"min_r": 0.65, "multiplier": 0.60},
    "moderate":    {"min_r": 0.40, "multiplier": 0.80},
    "weak":        {"min_r": 0.20, "multiplier": 0.90},
    "none":        {"min_r": 0.00, "multiplier": 1.00},
})

# ── Lead-lag pairs ───────────────────────────────────────────────
_LEAD_LAG = getattr(settings, "LEAD_LAG_PAIRS", {})


def _symbol_key(mt5_sym: str) -> str:
    """Strip trailing 'm' from EXNESS symbols for lookup."""
    return mt5_sym.rstrip("m") if mt5_sym.endswith("m") else mt5_sym


def get_correlation(sym_a: str, sym_b: str) -> Optional[float]:
    """
    Look up the static correlation between two symbols.
    Tries both (a,b) and (b,a) orderings.
    Returns None if no mapping exists.
    """
    a = _symbol_key(sym_a)
    b = _symbol_key(sym_b)
    r = _STATIC_CORR.get((a, b))
    if r is not None:
        return r
    r = _STATIC_CORR.get((b, a))
    if r is not None:
        return r
    return None


def get_penalty_multiplier(abs_r: float) -> float:
    """
    Given |r|, return the position-size penalty multiplier.
    Higher correlation → lower multiplier (more penalty).
    """
    sorted_bands = sorted(_PENALTIES.values(), key=lambda x: -x["min_r"])
    for band in sorted_bands:
        if abs_r >= band["min_r"]:
            return band["multiplier"]
    return 1.0


def compute_rolling_correlation(
    df_a: pd.DataFrame, df_b: pd.DataFrame, window: int = 60
) -> Optional[float]:
    """
    Compute the latest rolling Pearson correlation between two daily close DataFrames.
    Returns the most recent value or None if insufficient data.
    """
    try:
        if df_a is None or df_b is None:
            return None
        if len(df_a) < window or len(df_b) < window:
            return None

        close_a = df_a["close"].tail(window).reset_index(drop=True)
        close_b = df_b["close"].tail(window).reset_index(drop=True)
        if len(close_a) != len(close_b):
            min_len = min(len(close_a), len(close_b))
            close_a = close_a.tail(min_len).reset_index(drop=True)
            close_b = close_b.tail(min_len).reset_index(drop=True)

        corr = close_a.corr(close_b)
        return float(corr) if not np.isnan(corr) else None
    except Exception as e:
        logger.debug("Rolling corr failed: %s", e)
        return None


def detect_divergence(
    sym_a: str,
    sym_b: str,
    change_a: float,
    change_b: float,
    expected_r: float,
) -> Dict[str, Any]:
    """
    Detect if two normally correlated assets are diverging.

    Parameters
    ----------
    sym_a, sym_b : symbol names
    change_a, change_b : recent % change for each
    expected_r : the expected correlation between them

    Returns
    -------
    dict with divergence_detected, severity (0-3), description
    """
    if expected_r is None:
        return {"divergence_detected": False, "severity": 0, "description": "No correlation data"}

    # If both move in same direction but correlation is negative (or vice versa)
    same_dir = (change_a > 0 and change_b > 0) or (change_a < 0 and change_b < 0)
    opposite_dir = (change_a > 0 and change_b < 0) or (change_a < 0 and change_b > 0)

    diverging = False
    severity = 0
    desc = "Aligned"

    if expected_r > 0.5 and opposite_dir:
        # Positively correlated but moving opposite
        diverging = True
        severity = min(3, int(abs(change_a - change_b) * 10) + 1)
        desc = f"{sym_a} and {sym_b} diverging (expected r={expected_r:+.2f}, moving opposite)"
    elif expected_r < -0.5 and same_dir:
        # Negatively correlated but moving same direction
        diverging = True
        severity = min(3, int(abs(change_a + change_b) * 10) + 1)
        desc = f"{sym_a} and {sym_b} diverging (expected r={expected_r:+.2f}, moving same way)"
    elif abs(expected_r) > 0.7:
        # High correlation but magnitude very different
        if abs(change_a) > 0.001 and abs(change_b) > 0.001:
            ratio = abs(change_a / change_b) if change_b != 0 else 999
            if ratio > 3.0 or ratio < 0.33:
                diverging = True
                severity = 1
                desc = f"{sym_a} vs {sym_b}: magnitude divergence (ratio {ratio:.1f}x)"

    return {
        "divergence_detected": diverging,
        "severity": severity,
        "description": desc,
    }


def correlation_health_score(
    snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evaluate overall correlation health from the intermarket snapshot.
    Checks DXY/FX alignment, VIX/SPX inverse, Gold/DXY inverse, Oil/CAD.

    Returns dict with health ('HEALTHY'/'CAUTIOUS'/'UNHEALTHY'/'BROKEN'),
    divergence_count, and details.
    """
    checks = []
    divergences = 0

    dxy = snapshot.get("DXY", {})
    spx = snapshot.get("SPX", {})
    vix = snapshot.get("VIX", {})
    gold = snapshot.get("GOLD", {})
    oil = snapshot.get("OIL", {})

    # DXY vs SPX: typically weak inverse in risk-on
    dxy_dir = dxy.get("direction", "UNKNOWN")
    spx_dir = spx.get("direction", "UNKNOWN")
    vix_dir = vix.get("direction", "UNKNOWN")
    gold_dir = gold.get("direction", "UNKNOWN")
    oil_dir = oil.get("direction", "UNKNOWN")

    # VIX should be inverse of SPX
    if vix_dir != "UNKNOWN" and spx_dir != "UNKNOWN":
        if (vix_dir == "RISING" and spx_dir == "RISING") or \
           (vix_dir == "FALLING" and spx_dir == "FALLING"):
            divergences += 1
            checks.append("VIX/SPX same direction (divergence)")
        else:
            checks.append("VIX/SPX aligned (normal)")

    # Gold should be inverse of DXY
    if gold_dir != "UNKNOWN" and dxy_dir != "UNKNOWN":
        if (gold_dir == "RISING" and dxy_dir == "RISING") or \
           (gold_dir == "FALLING" and dxy_dir == "FALLING"):
            divergences += 1
            checks.append("Gold/DXY same direction (divergence)")
        else:
            checks.append("Gold/DXY aligned (normal)")

    # SPX vs DXY: complicated, but generally in risk-on DXY falls
    # Just flag if both strongly rising
    if spx_dir == "RISING" and dxy_dir == "RISING":
        checks.append("SPX+DXY both rising (unusual)")

    # Determine health
    if divergences == 0:
        health = "HEALTHY"
    elif divergences <= 2:
        health = "CAUTIOUS"
    elif divergences <= 3:
        health = "UNHEALTHY"
    else:
        health = "BROKEN"

    return {
        "health": health,
        "divergence_count": divergences,
        "checks": checks,
        "size_adjustment": {
            "HEALTHY": 1.0,
            "CAUTIOUS": 0.80,
            "UNHEALTHY": 0.50,
            "BROKEN": 0.0,
        }.get(health, 1.0),
    }


def portfolio_correlation_risk(
    open_positions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate correlation-adjusted portfolio risk.

    Parameters
    ----------
    open_positions : list of dicts with 'symbol', 'direction', 'risk_pct'

    Returns
    -------
    dict with raw_total_risk, adjusted_total_risk, per-position details
    """
    if not open_positions:
        return {
            "raw_total_risk": 0.0,
            "adjusted_total_risk": 0.0,
            "remaining_capacity": settings.MAX_PORTFOLIO_RISK_PCT,
            "positions": [],
        }

    raw_total = sum(p.get("risk_pct", 0) for p in open_positions)
    adjusted_positions = []

    for i, pos in enumerate(open_positions):
        sym = _symbol_key(pos.get("symbol", ""))
        risk = pos.get("risk_pct", 0)

        # Find max correlation with any earlier position
        max_corr = 0.0
        for j in range(i):
            other_sym = _symbol_key(open_positions[j].get("symbol", ""))
            r = get_correlation(sym, other_sym)
            if r is not None:
                # If positions are in opposite directions, flip correlation sign
                same_dir = pos.get("direction") == open_positions[j].get("direction")
                effective_r = abs(r) if same_dir else abs(r) if r < 0 else 0
                max_corr = max(max_corr, effective_r)

        penalty = get_penalty_multiplier(max_corr)
        adjusted_risk = risk * penalty if i > 0 else risk  # First position = full risk

        adjusted_positions.append({
            "symbol": pos.get("symbol"),
            "direction": pos.get("direction"),
            "raw_risk": risk,
            "max_correlation": max_corr,
            "penalty": penalty,
            "adjusted_risk": round(adjusted_risk, 4),
        })

    adjusted_total = sum(p["adjusted_risk"] for p in adjusted_positions)

    return {
        "raw_total_risk": round(raw_total, 4),
        "adjusted_total_risk": round(adjusted_total, 4),
        "remaining_capacity": round(settings.MAX_PORTFOLIO_RISK_PCT - adjusted_total, 4),
        "over_limit": adjusted_total > settings.MAX_PORTFOLIO_RISK_PCT,
        "positions": adjusted_positions,
    }


class CorrelationLayer:
    """
    Layer 9 — Correlation Engine.

    Evaluates:
    - How current instrument correlates with open positions
    - Whether intermarket correlations are aligned or diverging
    - Lead-lag relationship status
    - Portfolio-level correlation risk

    Output:
    - score 0-10 (higher = healthier correlation picture)
    - direction follows the trade bias (confirms or warns)
    """

    def analyze(
        self,
        instrument_key: str,
        snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
        open_positions: Optional[List[Dict[str, Any]]] = None,
        daily_changes: Optional[Dict[str, float]] = None,
    ) -> LayerSignal:
        """
        Parameters
        ----------
        instrument_key : key into WATCHLIST (e.g. 'EURUSDm')
        snapshot : intermarket snapshot from IntermarketData
        open_positions : list of current positions for portfolio risk check
        daily_changes : dict of symbol → daily % change for divergence detection
        """
        sym = _symbol_key(instrument_key)
        score = 5.0       # Start neutral
        confidence = 3.0   # moderate default
        direction = "NEUTRAL"
        details = {}

        try:
            # ── 1. Correlation Health (from intermarket snapshot) ──
            if snapshot:
                health = correlation_health_score(snapshot)
                details["correlation_health"] = health["health"]
                details["divergence_count"] = health["divergence_count"]
                details["health_checks"] = health["checks"]

                # Adjust score based on health
                health_adj = {
                    "HEALTHY": +2.0,
                    "CAUTIOUS": +0.5,
                    "UNHEALTHY": -1.0,
                    "BROKEN": -2.5,
                }
                score += health_adj.get(health["health"], 0)

            # ── 2. Divergence Detection ──
            if daily_changes and snapshot:
                divergences_found = []
                for (a, b), expected_r in _STATIC_CORR.items():
                    ch_a = daily_changes.get(a, daily_changes.get(a + "m", None))
                    ch_b = daily_changes.get(b, daily_changes.get(b + "m", None))
                    if ch_a is not None and ch_b is not None:
                        div = detect_divergence(a, b, ch_a, ch_b, expected_r)
                        if div["divergence_detected"]:
                            divergences_found.append(div)

                details["divergences"] = divergences_found
                if divergences_found:
                    max_sev = max(d["severity"] for d in divergences_found)
                    score -= max_sev * 0.5
                    confidence = max(1, confidence - 0.5)

            # ── 3. Portfolio Correlation Risk ──
            if open_positions:
                port_risk = portfolio_correlation_risk(open_positions)
                details["portfolio_risk"] = port_risk

                if port_risk["over_limit"]:
                    score = max(0, score - 3.0)
                    details["portfolio_warning"] = "Portfolio risk exceeds limit"
                elif port_risk["adjusted_total_risk"] > settings.MAX_PORTFOLIO_RISK_PCT * 0.8:
                    score -= 1.0
                    details["portfolio_warning"] = "Portfolio risk approaching limit"

                # Check how many correlated trades are already open
                corr_count = sum(
                    1 for p in port_risk["positions"]
                    if p["max_correlation"] > 0.65
                )
                details["correlated_position_count"] = corr_count
                if corr_count >= settings.MAX_CORRELATED_TRADES:
                    score -= 1.5

            # ── 4. Lead-lag signal check ──
            if sym in _LEAD_LAG:
                lag_info = _LEAD_LAG[sym]
                details["leads"] = lag_info["lags"]
                details["lead_delay_min"] = lag_info["delay_min"]
                # Being a leader is slightly positive (can predict followers)
                score += 0.5
                confidence += 0.5

            for leader, info in _LEAD_LAG.items():
                if sym in info["lags"]:
                    details["led_by"] = leader
                    details["lag_delay_min"] = info["delay_min"]
                    # Check if leader is giving a signal via snapshot
                    if snapshot and leader in snapshot:
                        leader_dir = snapshot[leader].get("direction", "UNKNOWN")
                        if leader_dir in ("RISING", "FALLING"):
                            direction = "LONG" if leader_dir == "RISING" else "SHORT"
                            score += 1.0
                            confidence += 0.5
                            details["lead_lag_signal"] = f"{leader} is {leader_dir} → {sym} expected to follow"
                    break

            # ── 4b. Rolling Correlation Blend (Plan #8) ──────────
            # If daily_changes provides DataFrames, compute rolling correlations
            # and blend with static matrix for a more adaptive score.
            if daily_changes:
                rolling_checks = 0
                rolling_aligned = 0
                rolling_details = []
                for (a, b), static_r in _STATIC_CORR.items():
                    if sym not in (a, b):
                        continue
                    # daily_changes may contain DataFrames keyed by symbol
                    df_a = daily_changes.get(f"{a}_df")
                    df_b = daily_changes.get(f"{b}_df")
                    if df_a is not None and df_b is not None:
                        rolling_r = compute_rolling_correlation(df_a, df_b, window=60)
                        if rolling_r is not None:
                            rolling_checks += 1
                            # Blend: 60% rolling + 40% static
                            blended_r = 0.6 * rolling_r + 0.4 * static_r
                            # Check alignment: if blended and static have same sign, aligned
                            if (blended_r > 0) == (static_r > 0):
                                rolling_aligned += 1
                            else:
                                # Correlation flipped — penalize
                                score -= 0.5
                            rolling_details.append({
                                "pair": f"{a}/{b}",
                                "static_r": round(static_r, 3),
                                "rolling_r": round(rolling_r, 3),
                                "blended_r": round(blended_r, 3),
                            })
                if rolling_checks > 0:
                    details["rolling_correlations"] = rolling_details
                    details["rolling_aligned_pct"] = round(rolling_aligned / rolling_checks * 100, 1)
                    if rolling_aligned / rolling_checks >= 0.8:
                        score += 0.5  # Bonus for stable correlations
                    elif rolling_aligned / rolling_checks < 0.5:
                        score -= 0.5  # Penalty for unstable correlations

            # ── 5. Clamp final values ──
            score = max(0.0, min(10.0, score))
            confidence = max(0.0, min(1.0, confidence / 5.0))  # Normalize to 0-1

            if score >= 7.0:
                if direction == "NEUTRAL":
                    direction = "LONG"  # Healthy correlations are generally positive
            elif score <= 3.0:
                direction = "NEUTRAL"

        except Exception as e:
            logger.error("Layer 9 analysis failed: %s", e, exc_info=True)
            details["error"] = str(e)

        return LayerSignal(
            layer_name="L9_Correlation",
            direction=direction,
            score=round(score, 2),
            confidence=round(confidence, 2),
            details=details,
        )
