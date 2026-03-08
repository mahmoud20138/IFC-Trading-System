"""
IFC Trading System — Scaling Manager
Handles entry scaling (50/30/20) and exit scaling (TP1/TP2/TP3 runner).
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from config import settings
from execution.order_manager import OrderManager
from utils.helpers import setup_logging

logger = setup_logging("ifc.scaling")


@dataclass
class TradeGroup:
    """Tracks a group of related orders for one trade setup."""
    group_id: str               # Unique identifier (e.g., "IFC_20260212_EURUSD_1")
    symbol: str
    direction: str              # "BUY" | "SELL"
    total_volume: float         # Full planned volume
    entry_prices: List[float]   # [CE_price, FVG_low_price, POC_edge_price]
    stop_loss: float
    tp1: float
    tp2: float
    tp3: Optional[float]        # None → trail
    # State tracking
    entry_tickets: List[int] = field(default_factory=list)
    filled_entries: int = 0
    filled_volume: float = 0.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    be_moved: bool = False
    trailing_active: bool = False


class ScalingManager:
    """
    Manages entry and exit scaling as defined in the strategy.

    Entry: 3 limit orders at progressively better prices, same SL.
    Exit: TP1 (40%), TP2 (30%), TP3 runner (30%) with trailing stop.
    """

    def __init__(self, order_manager: OrderManager):
        self.om = order_manager
        self.active_groups: Dict[str, TradeGroup] = {}

    # ── ENTRY SCALING ────────────────────────────────────────────────

    def open_scaled_entry(
        self,
        symbol: str,
        direction: str,
        total_volume: float,
        entry_ce: float,
        entry_fvg_low: float,
        entry_poc_edge: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: Optional[float] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Place 3 limit orders at scaled entry prices.

        Entry 1: 50% at CE (Consequent Encroachment)
        Entry 2: 30% at FVG low (or OB)
        Entry 3: 20% at POC edge (deepest level)
        """
        if group_id is None:
            from datetime import datetime
            group_id = f"IFC_{datetime.utcnow().strftime('%Y%m%d%H%M')}_{symbol}"

        volumes = [
            round(total_volume * settings.ENTRY_SCALE[0], 2),
            round(total_volume * settings.ENTRY_SCALE[1], 2),
            round(total_volume * settings.ENTRY_SCALE[2], 2),
        ]
        prices = [entry_ce, entry_fvg_low, entry_poc_edge]
        order_type = "BUY_LIMIT" if direction == "BUY" else "SELL_LIMIT"

        group = TradeGroup(
            group_id=group_id,
            symbol=symbol,
            direction=direction,
            total_volume=total_volume,
            entry_prices=prices,
            stop_loss=stop_loss,
            tp1=tp1, tp2=tp2, tp3=tp3,
        )

        results = []
        for i, (vol, price) in enumerate(zip(volumes, prices)):
            if vol < 0.01:
                continue
            res = self.om.place_pending_order(
                symbol=symbol,
                direction=direction,
                order_type=order_type,
                price=price,
                volume=vol,
                sl=stop_loss,
                tp=tp1,  # Initial TP on all entries is TP1
                magic=settings.MAGIC_NUMBER,
                comment=f"{group_id}_E{i+1}",
            )
            if res["success"]:
                group.entry_tickets.append(res["ticket"])
            results.append(res)

        self.active_groups[group_id] = group

        logger.info(
            "SCALED ENTRY: %s %s %s | vol=[%.2f, %.2f, %.2f] @ [%.5f, %.5f, %.5f]",
            group_id, direction, symbol,
            volumes[0], volumes[1], volumes[2],
            prices[0], prices[1], prices[2],
        )

        return {
            "group_id": group_id,
            "orders": results,
            "success": any(r["success"] for r in results),
        }

    # ── EXIT SCALING ─────────────────────────────────────────────────

    def execute_tp1(self, group_id: str) -> Dict[str, Any]:
        """Close 40% of position at TP1, move remainder to breakeven."""
        group = self.active_groups.get(group_id)
        if not group or group.tp1_hit:
            return {"success": False, "reason": "Group not found or TP1 already hit"}

        positions = self.om.mt5.get_open_positions(symbol=group.symbol)
        our_positions = [
            p for p in positions
            if p["magic"] == settings.MAGIC_NUMBER
            and group_id in (p.get("comment", "") or "")
        ]

        total_vol = sum(p["volume"] for p in our_positions)
        close_vol = round(total_vol * settings.EXIT_SCALE["TP1_pct"], 2)

        results = []
        remaining_close = close_vol
        for pos in our_positions:
            if remaining_close <= 0:
                break
            to_close = min(pos["volume"], remaining_close)
            res = self.om.close_partial(pos["ticket"], to_close)
            results.append(res)
            if res["success"]:
                remaining_close -= to_close

        # Move stop to breakeven for remaining positions
        for pos in our_positions:
            current_pos = self.om.mt5.get_open_positions(symbol=group.symbol)
            for cp in current_pos:
                if cp["ticket"] == pos["ticket"] and cp["volume"] > 0:
                    entry_price = cp["open_price"]
                    # Move SL to entry (breakeven)
                    self.om.modify_position(
                        cp["ticket"],
                        new_sl=entry_price,
                        new_tp=group.tp2,  # Next target
                    )

        group.tp1_hit = True
        group.be_moved = True

        logger.info(
            "TP1 HIT: %s | Closed %.2f lots | Remaining moved to BE, targeting TP2",
            group_id, close_vol - remaining_close,
        )

        return {"success": True, "closed_volume": close_vol - remaining_close, "results": results}

    def execute_tp2(self, group_id: str) -> Dict[str, Any]:
        """Close 30% at TP2, set runner with trailing stop."""
        group = self.active_groups.get(group_id)
        if not group or group.tp2_hit:
            return {"success": False, "reason": "Group not found or TP2 already hit"}

        positions = self.om.mt5.get_open_positions(symbol=group.symbol)
        our_positions = [
            p for p in positions
            if p["magic"] == settings.MAGIC_NUMBER
            and group_id in (p.get("comment", "") or "")
        ]

        total_vol = sum(p["volume"] for p in our_positions)

        # TP2 closes 30% of the ORIGINAL position = ~half of remaining after TP1
        close_vol = round(group.total_volume * settings.EXIT_SCALE["TP2_pct"], 2)

        results = []
        remaining_close = close_vol
        for pos in our_positions:
            if remaining_close <= 0:
                break
            to_close = min(pos["volume"], remaining_close)
            res = self.om.close_partial(pos["ticket"], to_close)
            results.append(res)
            if res["success"]:
                remaining_close -= to_close

        # Set trailing for runner
        group.tp2_hit = True
        group.trailing_active = True

        # Remove fixed TP on runner — let trail manage it
        for pos in our_positions:
            current_pos = self.om.mt5.get_open_positions(symbol=group.symbol)
            for cp in current_pos:
                if cp["ticket"] == pos["ticket"] and cp["volume"] > 0:
                    self.om.modify_position(cp["ticket"], new_tp=0.0)

        logger.info(
            "TP2 HIT: %s | Closed %.2f lots | Runner active with trailing stop",
            group_id, close_vol - remaining_close,
        )

        return {"success": True, "results": results, "runner_active": True}

    def get_active_groups(self) -> Dict[str, Dict[str, Any]]:
        """Return summary of all active trade groups."""
        return {
            gid: {
                "symbol": g.symbol,
                "direction": g.direction,
                "entries": g.filled_entries,
                "tp1_hit": g.tp1_hit,
                "tp2_hit": g.tp2_hit,
                "trailing": g.trailing_active,
            }
            for gid, g in self.active_groups.items()
        }
