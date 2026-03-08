"""
IFC Trading System — Smart Order Recommendation System
Generates actionable trade recommendation cards with exact
entry zones, stops, targets, scaling, and trigger conditions.
Based on Part 16 of the strategy plan.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

from analysis.layer1_intermarket import LayerSignal
from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.smart_orders")


@dataclass
class TradeRecommendation:
    """A complete trade recommendation card."""
    card_id: int
    timestamp: str
    valid_until: str
    status: str                  # PENDING, TRIGGERED, EXPIRED, CANCELLED

    instrument: str
    display_name: str
    direction: str               # LONG / SHORT
    setup_type: str              # POC_BOUNCE, LIQ_SWEEP, VA_BREAKOUT, etc.
    grade: str                   # A+, A, B
    qas_score: float

    # Entry zone (scaled entries)
    entry_1: float               # 50% of position
    entry_2: float               # 30% of position
    entry_3: float               # 20% of position
    avg_entry: float

    # Risk management
    stop_loss: float
    stop_distance_pips: float
    stop_reason: str

    # Targets
    tp1: float                   # 40% exit
    tp2: float                   # 30% exit
    tp3: float                   # 30% runner

    # R:R ratios
    rr_tp1: float
    rr_tp2: float
    rr_tp3: float

    # Position sizing
    risk_pct: float
    position_size: float
    size_multiplier: float

    # Confluence
    confluence_levels: Dict[str, float] = field(default_factory=dict)
    trigger_conditions: List[str] = field(default_factory=list)
    veto_warnings: List[str] = field(default_factory=list)

    # Layer summary
    layer_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for display."""
        return {
            "card_id": self.card_id,
            "timestamp": self.timestamp,
            "valid_until": self.valid_until,
            "status": self.status,
            "instrument": self.instrument,
            "display_name": self.display_name,
            "direction": self.direction,
            "setup_type": self.setup_type,
            "grade": self.grade,
            "qas_score": self.qas_score,
            "entry_1": self.entry_1,
            "entry_2": self.entry_2,
            "entry_3": self.entry_3,
            "avg_entry": self.avg_entry,
            "stop_loss": self.stop_loss,
            "stop_distance_pips": self.stop_distance_pips,
            "stop_reason": self.stop_reason,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "rr_tp1": self.rr_tp1,
            "rr_tp2": self.rr_tp2,
            "rr_tp3": self.rr_tp3,
            "risk_pct": self.risk_pct,
            "position_size": self.position_size,
            "size_multiplier": self.size_multiplier,
            "confluence_levels": self.confluence_levels,
            "trigger_conditions": self.trigger_conditions,
            "veto_warnings": self.veto_warnings,
            "layer_scores": self.layer_scores,
        }


# Module-level card counter
_card_counter = 0


def _next_card_id() -> int:
    global _card_counter
    _card_counter += 1
    return _card_counter


def _estimate_entry_zone(
    current_price: float,
    direction: str,
    atr: float,
    fvg_level: Optional[float] = None,
    ob_level: Optional[float] = None,
    poc_level: Optional[float] = None,
    pip_size: float = 0.0001,
) -> Dict[str, float]:
    """
    Estimate a 3-part scaled entry zone.

    For LONG: entries are BELOW current price (buy on pullback)
    For SHORT: entries are ABOVE current price (sell on rally)
    """
    buffer = atr * 0.2

    if direction == "LONG":
        # Entry 1: nearest confluence level or slight pullback
        e1 = fvg_level if fvg_level and fvg_level < current_price else current_price - atr * 0.3
        e2 = ob_level if ob_level and ob_level < e1 else e1 - atr * 0.2
        e3 = poc_level if poc_level and poc_level < e2 else e2 - atr * 0.15
        avg = e1 * 0.50 + e2 * 0.30 + e3 * 0.20
    else:  # SHORT
        e1 = fvg_level if fvg_level and fvg_level > current_price else current_price + atr * 0.3
        e2 = ob_level if ob_level and ob_level > e1 else e1 + atr * 0.2
        e3 = poc_level if poc_level and poc_level > e2 else e2 + atr * 0.15
        avg = e1 * 0.50 + e2 * 0.30 + e3 * 0.20

    return {
        "entry_1": round(e1, 5),
        "entry_2": round(e2, 5),
        "entry_3": round(e3, 5),
        "avg_entry": round(avg, 5),
    }


def _estimate_stop(
    avg_entry: float,
    direction: str,
    atr: float,
    swing_level: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Estimate stop loss placement.
    Default: 1.5 ATR behind entry, or beyond swing level with buffer.
    """
    buffer = atr * 0.2

    if direction == "LONG":
        default_stop = avg_entry - atr * 1.5
        if swing_level and swing_level < avg_entry:
            stop = swing_level - buffer
            reason = "Below swing low + buffer"
        else:
            stop = default_stop
            reason = "1.5 ATR below entry"
    else:
        default_stop = avg_entry + atr * 1.5
        if swing_level and swing_level > avg_entry:
            stop = swing_level + buffer
            reason = "Above swing high + buffer"
        else:
            stop = default_stop
            reason = "1.5 ATR above entry"

    distance = abs(avg_entry - stop)
    return {
        "stop_loss": round(stop, 5),
        "distance": distance,
        "reason": reason,
    }


def _estimate_targets(
    avg_entry: float,
    stop_loss: float,
    direction: str,
    min_rr: float = 3.0,
) -> Dict[str, float]:
    """
    Compute TP1, TP2, TP3 based on R multiples.
    TP1 = 2R, TP2 = 3R, TP3 = 5R (runner).
    """
    risk = abs(avg_entry - stop_loss)

    if direction == "LONG":
        tp1 = avg_entry + risk * 2.0
        tp2 = avg_entry + risk * 3.0
        tp3 = avg_entry + risk * 5.0
    else:
        tp1 = avg_entry - risk * 2.0
        tp2 = avg_entry - risk * 3.0
        tp3 = avg_entry - risk * 5.0

    return {
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "rr_tp1": 2.0,
        "rr_tp2": 3.0,
        "rr_tp3": 5.0,
    }


def _compute_position_size(
    account_balance: float,
    risk_pct: float,
    stop_distance: float,
    pip_value_per_lot: float,
    pip_size: float,
    size_multiplier: float = 1.0,
) -> float:
    """
    Compute lot size based on risk percentage.
    position_size = (balance × risk% × multiplier) / (stop_pips × pip_value_per_lot)
    """
    if stop_distance <= 0 or pip_size <= 0 or pip_value_per_lot <= 0:
        return 0.01

    stop_pips = stop_distance / pip_size
    risk_amount = account_balance * (risk_pct / 100) * size_multiplier
    lots = risk_amount / (stop_pips * pip_value_per_lot)
    return round(max(0.01, lots), 2)


def generate_recommendation(
    instrument,
    current_price: float,
    atr: float,
    signals: List[LayerSignal],
    evaluation: Dict[str, Any],
    account_balance: float = 10000.0,
    fvg_level: Optional[float] = None,
    ob_level: Optional[float] = None,
    poc_level: Optional[float] = None,
    swing_level: Optional[float] = None,
    killzone_end: str = "",
) -> Optional[TradeRecommendation]:
    """
    Generate a smart order recommendation card.

    Parameters
    ----------
    instrument : Instrument dataclass
    current_price : current bid/ask midpoint
    atr : current ATR value
    signals : list of LayerSignals
    evaluation : dict from full_evaluation()
    account_balance : account equity
    fvg_level, ob_level, poc_level, swing_level : confluence levels
    killzone_end : time string when current killzone ends

    Returns
    -------
    TradeRecommendation or None if not tradeable
    """
    if not evaluation.get("tradeable"):
        return None

    direction = evaluation["direction"]
    grade = evaluation["grade"]
    qas = evaluation.get("qas", 0)
    size_mult = evaluation.get("size_multiplier", 1.0)

    # Entry zone
    entries = _estimate_entry_zone(
        current_price, direction, atr,
        fvg_level, ob_level, poc_level,
        instrument.pip_size,
    )

    # Stop loss
    stop_info = _estimate_stop(
        entries["avg_entry"], direction, atr, swing_level
    )

    # Targets
    targets = _estimate_targets(
        entries["avg_entry"], stop_info["stop_loss"], direction
    )

    # Position sizing
    risk_pct = settings.BASE_RISK_PCT
    stop_pips = stop_info["distance"] / instrument.pip_size if instrument.pip_size > 0 else 0
    position_size = _compute_position_size(
        account_balance, risk_pct, stop_info["distance"],
        instrument.pip_value_per_lot, instrument.pip_size,
        size_mult,
    )

    # Build trigger conditions
    triggers = []
    if direction == "LONG":
        triggers.append(f"Price must pull back to {entries['entry_1']:.5f} zone")
        triggers.append("Wait for bullish CHoCH on M15 or delta confirmation")
    else:
        triggers.append(f"Price must rally to {entries['entry_1']:.5f} zone")
        triggers.append("Wait for bearish CHoCH on M15 or delta confirmation")
    if poc_level:
        triggers.append(f"POC confluence at {poc_level:.5f}")

    # Layer scores summary
    layer_scores = {s.layer_name: s.score for s in signals}

    # Confluence levels
    confluence = {}
    if fvg_level:
        confluence["FVG"] = fvg_level
    if ob_level:
        confluence["OB"] = ob_level
    if poc_level:
        confluence["POC"] = poc_level
    if swing_level:
        confluence["Swing"] = swing_level

    now = datetime.now()
    valid = killzone_end or (now.strftime("%H:%M") if not killzone_end else killzone_end)

    card = TradeRecommendation(
        card_id=_next_card_id(),
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
        valid_until=valid,
        status="PENDING",
        instrument=instrument.mt5_symbol,
        display_name=instrument.display_name,
        direction=direction,
        setup_type=_detect_setup_type(signals),
        grade=grade,
        qas_score=qas,
        entry_1=entries["entry_1"],
        entry_2=entries["entry_2"],
        entry_3=entries["entry_3"],
        avg_entry=entries["avg_entry"],
        stop_loss=stop_info["stop_loss"],
        stop_distance_pips=round(stop_pips, 1),
        stop_reason=stop_info["reason"],
        tp1=targets["tp1"],
        tp2=targets["tp2"],
        tp3=targets["tp3"],
        rr_tp1=targets["rr_tp1"],
        rr_tp2=targets["rr_tp2"],
        rr_tp3=targets["rr_tp3"],
        risk_pct=risk_pct,
        position_size=position_size,
        size_multiplier=size_mult,
        confluence_levels=confluence,
        trigger_conditions=triggers,
        veto_warnings=evaluation.get("soft_vetos", []),
        layer_scores=layer_scores,
    )

    logger.info(
        "RECOMMENDATION: Card #%d %s %s %s grade=%s QAS=%.3f entry=%.5f SL=%.5f TP1=%.5f size=%.2f",
        card.card_id, card.instrument, card.direction, card.setup_type,
        card.grade, card.qas_score, card.avg_entry, card.stop_loss,
        card.tp1, card.position_size,
    )

    return card


def _detect_setup_type(signals: List[LayerSignal]) -> str:
    """Heuristically detect the most likely setup type from layer signals."""
    sig_map = {s.layer_name: s for s in signals}

    l3 = sig_map.get("L3_VolumeProfile")
    l5 = sig_map.get("L5_Liquidity")
    l6 = sig_map.get("L6_FVG_OrderBlock")

    # Check L3 details for POC/VA signals
    if l3:
        d = l3.details or {}
        if d.get("naked_poc_nearby"):
            return "NAKED_POC"
        if d.get("poc_migration"):
            return "POC_MIGRATION"
        if d.get("at_value_area_edge"):
            return "VA_BREAKOUT"

    # Check L5 for liquidity sweep
    if l5 and l5.score >= 7.0:
        d = l5.details or {}
        if d.get("sweep_detected"):
            return "LIQ_SWEEP"

    # Default: POC bounce if good VP setup
    if l3 and l3.score >= 6.0:
        return "POC_BOUNCE"

    # Check L6 for FVG/OB entry
    if l6 and l6.score >= 6.0:
        return "FVG_OB_ENTRY"

    return "CONFLUENCE"


def format_card_html(card: TradeRecommendation) -> str:
    """Generate an HTML card for dashboard display (Streamlit 1.12 compatible)."""
    dir_color = "#00c853" if card.direction == "LONG" else "#ff1744"
    grade_color = {
        "A+": "#00c853",
        "A": "#2196f3",
        "B": "#ff9800",
    }.get(card.grade, "#757575")

    html = f"""
    <div style="border:2px solid {dir_color}; border-radius:10px; padding:16px;
                margin:8px 0; background:#1a1a2e;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-size:20px; font-weight:bold; color:white;">
                    {card.display_name}
                </span>
                <span style="background:{dir_color}; color:white; padding:2px 10px;
                             border-radius:4px; margin-left:8px; font-weight:bold;">
                    {card.direction}
                </span>
                <span style="background:{grade_color}; color:white; padding:2px 8px;
                             border-radius:4px; margin-left:4px; font-size:14px;">
                    {card.grade} (QAS: {card.qas_score:.2f})
                </span>
            </div>
            <div style="color:#aaa; font-size:12px;">
                Card #{card.card_id} | {card.timestamp}<br>
                Valid until: {card.valid_until} | Setup: {card.setup_type}
            </div>
        </div>

        <hr style="border-color:#333; margin:10px 0;">

        <div style="display:flex; gap:20px;">
            <div style="flex:1;">
                <div style="color:#aaa; font-size:12px;">ENTRY ZONE</div>
                <div style="color:white;">
                    E1 (50%): <b>{card.entry_1:.5f}</b><br>
                    E2 (30%): <b>{card.entry_2:.5f}</b><br>
                    E3 (20%): <b>{card.entry_3:.5f}</b><br>
                    <span style="color:#aaa;">Avg: {card.avg_entry:.5f}</span>
                </div>
            </div>
            <div style="flex:1;">
                <div style="color:#ff1744; font-size:12px;">STOP LOSS</div>
                <div style="color:white;">
                    <b>{card.stop_loss:.5f}</b><br>
                    <span style="color:#aaa;">{card.stop_distance_pips:.1f} pips</span><br>
                    <span style="color:#aaa; font-size:11px;">{card.stop_reason}</span>
                </div>
            </div>
            <div style="flex:1;">
                <div style="color:#00c853; font-size:12px;">TARGETS</div>
                <div style="color:white;">
                    TP1 (40%): <b>{card.tp1:.5f}</b> ({card.rr_tp1:.0f}R)<br>
                    TP2 (30%): <b>{card.tp2:.5f}</b> ({card.rr_tp2:.0f}R)<br>
                    TP3 (30%): <b>{card.tp3:.5f}</b> ({card.rr_tp3:.0f}R)
                </div>
            </div>
            <div style="flex:1;">
                <div style="color:#2196f3; font-size:12px;">SIZING</div>
                <div style="color:white;">
                    Risk: <b>{card.risk_pct:.1f}%</b><br>
                    Size: <b>{card.position_size:.2f} lots</b><br>
                    Mult: {card.size_multiplier:.1f}x
                </div>
            </div>
        </div>
    """

    if card.trigger_conditions:
        html += '<div style="margin-top:10px; color:#ff9800; font-size:12px;">'
        html += "<b>TRIGGERS:</b> " + " | ".join(card.trigger_conditions)
        html += "</div>"

    if card.veto_warnings:
        html += '<div style="margin-top:4px; color:#ff5722; font-size:12px;">'
        html += "<b>WARNINGS:</b> " + " | ".join(card.veto_warnings)
        html += "</div>"

    html += "</div>"
    return html
