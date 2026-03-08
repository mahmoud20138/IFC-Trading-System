"""
IFC Trading System — Layer 8: Time (Killzone + Day of Week + News)
Determines if now is the right time to trade.
Enhanced with category-specific killzone rules (Enhancement Plan #4).
"""

from typing import Dict, Any, Optional
from datetime import datetime

from analysis.layer1_intermarket import LayerSignal
from config import settings
from config.instruments import Instrument
from data.economic_calendar import is_news_blackout
from utils.helpers import (
    setup_logging, current_killzone, is_lunch_break,
    is_friday_cutoff, day_of_week_multiplier, now_est,
)

logger = setup_logging("ifc.layer8")

# ── Category rule lookups ────────────────────────────────────────
_CAT_RULES = getattr(settings, "KILLZONE_CATEGORY_RULES", {})
_PAIR_BOOSTS = getattr(settings, "KILLZONE_PAIR_BOOSTS", {})


class KillzoneLayer:
    """
    Layer 8 — Time / session / day-of-week filter.

    Scores highest when:
    - Inside an active killzone appropriate for the asset category
    - On the trader's best day of the week
    - No high-impact news within 15 min
    - Not during lunch break (equity/forex only)
    - Not Friday afternoon (forex only)
    """

    def analyze(
        self,
        symbol: str,
        current_time: Optional[datetime] = None,
        instrument: Optional[Instrument] = None,
    ) -> LayerSignal:
        """
        Parameters
        ----------
        symbol : MT5 symbol for news-blackout currency check
        current_time : override for testing (default = now)
        instrument : Instrument object for category-specific rules
        """
        if current_time is None:
            current_time = now_est()

        # Determine category preference
        kz_pref = "forex"  # default
        if instrument is not None:
            kz_pref = getattr(instrument, "killzone_preference", instrument.category)

        cat_rule = _CAT_RULES.get(kz_pref, _CAT_RULES.get("forex", {}))
        weight_mults = cat_rule.get("weight_multipliers", {})
        no_penalty = cat_rule.get("no_penalty_outside_kz", False)

        details: Dict[str, Any] = {
            "current_time_est": current_time.strftime("%Y-%m-%d %H:%M"),
            "day": current_time.strftime("%A"),
            "killzone_category": kz_pref,
        }

        score = 0.0
        reasons = []

        # ── Killzone check ──
        kz = current_killzone()
        details["killzone"] = kz

        if kz is not None:
            # Base killzone scores
            base_kz_scores = {
                "london_ny": 5.0,
                "ny_open": 5.0,
                "london": 4.0,
                "london_close": 4.0,
                "ny_pm": 2.5,
                "asian": 1.5,
            }
            base = base_kz_scores.get(kz, 2.0)

            # Apply category multiplier
            cat_mult = weight_mults.get(kz, 1.0)
            score += base * cat_mult

            # Apply pair-specific boost
            pair_boosts = _PAIR_BOOSTS.get(symbol, {})
            if kz in pair_boosts:
                boost = pair_boosts[kz]
                score *= boost
                reasons.append(f"In {kz} (cat={kz_pref}, mult={cat_mult:.1f}, pair boost={boost:.1f})")
            else:
                reasons.append(f"In {kz} (cat={kz_pref}, mult={cat_mult:.1f})")
        else:
            if no_penalty:
                # Crypto: no penalty for being outside killzones
                score += 3.0
                reasons.append("Outside killzones — no penalty (24/7 market)")
            else:
                score += 0.0
                reasons.append("Outside all killzones — WAIT")

        # ── Day-of-week multiplier ──
        day_mult = day_of_week_multiplier()
        details["day_multiplier"] = day_mult
        if day_mult >= 1.2:
            score += 2.0
            reasons.append(f"Best day ({current_time.strftime('%A')})")
        elif day_mult <= 0.5:
            score -= 2.0
            reasons.append(f"Worst day ({current_time.strftime('%A')})")
        else:
            score += 1.0

        # ── Friday cutoff (forex/commodity only) ──
        if is_friday_cutoff() and kz_pref in ("forex", "commodity"):
            score = 0.0
            reasons.append("Friday cutoff — NO NEW TRADES")
            details["friday_cutoff"] = True
        elif is_friday_cutoff() and kz_pref == "crypto":
            # Crypto doesn't observe Friday cutoff
            details["friday_cutoff"] = False

        # ── Lunch break (equity/forex only) ──
        if is_lunch_break() and kz_pref in ("forex", "equity"):
            score = max(0.0, score - 5.0)
            reasons.append("Lunch break — NO NEW TRADES")
            details["lunch_break"] = True

        # ── News blackout ──
        try:
            if is_news_blackout(symbol):
                score = max(0.0, score - 4.0)
                reasons.append("NEWS BLACKOUT — high-impact event nearby")
                details["news_blackout"] = True
            else:
                details["news_blackout"] = False
                score += 1.0  # Clear calendar is a plus
        except Exception as e:
            logger.debug("News check failed: %s", e)
            details["news_blackout"] = "check_failed"

        # ── Weekend (crypto can trade weekends) ──
        if current_time.strftime("%A") in ("Saturday", "Sunday"):
            if kz_pref == "crypto":
                score = max(0.0, score - 1.0)  # Slight reduction for lower weekend liquidity
                reasons.append("Weekend — reduced crypto liquidity")
            else:
                score = 0.0
                reasons.append("Weekend — market closed")

        score = max(0.0, min(10.0, score))
        details["reasons"] = reasons

        # Direction: time filters don't determine direction
        direction = "NEUTRAL"
        confidence = min(1.0, score / 10)

        logger.info(
            "L8 Time: score=%.1f kz=%s day=%s cat=%s | %s",
            score, kz, current_time.strftime("%A"), kz_pref, "; ".join(reasons),
        )

        return LayerSignal(
            layer_name="L8_Killzone",
            direction=direction,
            score=round(score, 1),
            confidence=round(confidence, 2),
            details=details,
        )
