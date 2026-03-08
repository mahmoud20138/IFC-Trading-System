"""
IFC Trading System — Trade Manager
Manages open positions: trailing stops, breakeven, session-end rules, news.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from analysis.layer2_trend import ema
from config import settings
from data.mt5_connector import MT5Connector
from data.economic_calendar import is_news_blackout
from execution.order_manager import OrderManager
from execution.scaling import ScalingManager, TradeGroup
from utils.helpers import (
    setup_logging, current_killzone, is_lunch_break, now_utc, now_est,
)
import pandas as pd

logger = setup_logging("ifc.trade_mgr")


class TradeManager:
    """
    Manages open positions according to strategy rules.
    Runs on a polling schedule (every 30s).

    Rules enforced:
    1. Never move stop further from entry
    2. Move to BE after TP1 or 1.5R profit on 1H
    3. Trail behind EMA after TP1/TP2
    4. News management (partial close, etc.)
    5. Session-end rules
    """

    def __init__(
        self,
        connector: MT5Connector,
        order_manager: OrderManager,
        scaling_manager: ScalingManager,
    ):
        self.mt5 = connector
        self.om = order_manager
        self.sm = scaling_manager

    def manage_all_positions(self):
        """
        Main polling function — call every 30 seconds.
        Checks all open positions and applies management rules.
        """
        positions = self.mt5.get_open_positions()
        our_positions = [
            p for p in positions if p["magic"] == settings.MAGIC_NUMBER
        ]

        if not our_positions:
            return

        for pos in our_positions:
            try:
                self._manage_single_position(pos)
            except Exception as e:
                logger.error(
                    "Error managing position %d: %s", pos["ticket"], e
                )

    def _manage_single_position(self, pos: Dict[str, Any]):
        """Apply all management rules to a single position."""
        ticket = pos["ticket"]
        symbol = pos["symbol"]
        entry = pos["open_price"]
        current = pos["current_price"]
        sl = pos["sl"]
        direction = pos["type"]  # "BUY" or "SELL"

        # Calculate current R-multiple
        risk_distance = abs(entry - sl) if sl > 0 else 0
        if risk_distance == 0:
            return

        if direction == "BUY":
            profit_pips = current - entry
        else:
            profit_pips = entry - current

        current_r = profit_pips / risk_distance if risk_distance > 0 else 0

        # ── Rule 1: Never move stop further (enforced by not allowing it) ──
        # All modifications below only tighten the stop

        # ── Rule 2: Check if TP levels hit ──
        self._check_tp_levels(pos, current_r)

        # ── Rule 3: Trailing stop ──
        self._update_trailing_stop(pos, current_r)

        # ── Rule 4: News management ──
        self._manage_news(pos, current_r)

        # ── Rule 5: Session-end rules ──
        self._manage_session_end(pos, current_r)

    def _check_tp_levels(self, pos: Dict, current_r: float):
        """Check if any TP level has been reached for scaling."""
        # Find the trade group for this position
        for gid, group in self.sm.active_groups.items():
            if pos["symbol"] != group.symbol:
                continue
            comment = pos.get("comment", "") or ""
            if gid not in comment:
                continue

            # TP1 check
            if not group.tp1_hit:
                tp1_hit = False
                if group.direction == "BUY" and pos["current_price"] >= group.tp1:
                    tp1_hit = True
                elif group.direction == "SELL" and pos["current_price"] <= group.tp1:
                    tp1_hit = True

                if tp1_hit:
                    logger.info("TP1 reached for group %s", gid)
                    self.sm.execute_tp1(gid)

            # TP2 check
            elif not group.tp2_hit:
                tp2_hit = False
                if group.direction == "BUY" and pos["current_price"] >= group.tp2:
                    tp2_hit = True
                elif group.direction == "SELL" and pos["current_price"] <= group.tp2:
                    tp2_hit = True

                if tp2_hit:
                    logger.info("TP2 reached for group %s", gid)
                    self.sm.execute_tp2(gid)

            break

    def _update_trailing_stop(self, pos: Dict, current_r: float):
        """
        Update trailing stop based on EMA.
        After TP1: trail behind 10 EMA on entry TF (15m)
        After TP2: trail behind 10 EMA on 1H
        """
        ticket = pos["ticket"]
        symbol = pos["symbol"]
        direction = pos["type"]
        current_sl = pos["sl"]
        entry = pos["open_price"]

        # Determine if trailing should be active
        should_trail = False
        trail_tf = "M15"

        for group in self.sm.active_groups.values():
            comment = pos.get("comment", "") or ""
            if group.symbol == symbol and group.group_id in comment:
                if group.tp2_hit:
                    should_trail = True
                    trail_tf = settings.TRAIL_EMA_TF_AFTER_TP2
                elif group.tp1_hit:
                    should_trail = True
                    trail_tf = settings.TRAIL_EMA_TF_AFTER_TP1
                break

        if not should_trail:
            # Check if we should move to BE based on R-multiple
            if current_r >= settings.BE_TRIGGER_R:
                if direction == "BUY" and current_sl < entry:
                    self.om.modify_position(ticket, new_sl=entry)
                    logger.info("Moved position %d to breakeven (%.1fR profit)", ticket, current_r)
                elif direction == "SELL" and current_sl > entry:
                    self.om.modify_position(ticket, new_sl=entry)
                    logger.info("Moved position %d to breakeven (%.1fR profit)", ticket, current_r)
            return

        # Fetch recent bars for trailing EMA
        try:
            df = self.mt5.get_ohlcv(symbol, trail_tf, bars=50)
            if df.empty or len(df) < settings.TRAIL_EMA_PERIOD:
                return

            trail_ema = ema(df["close"], settings.TRAIL_EMA_PERIOD)
            ema_value = float(trail_ema.iloc[-1])

            new_sl = current_sl
            if direction == "BUY":
                # Trail below EMA
                trail_level = ema_value
                if trail_level > current_sl and trail_level < pos["current_price"]:
                    new_sl = trail_level
            else:
                # Trail above EMA
                trail_level = ema_value
                if trail_level < current_sl and trail_level > pos["current_price"]:
                    new_sl = trail_level

            # Only tighten, never widen (Rule 1)
            if direction == "BUY" and new_sl > current_sl:
                self.om.modify_position(ticket, new_sl=round(new_sl, 5))
                logger.debug("Trail %d: SL → %.5f (EMA %s)", ticket, new_sl, trail_tf)
            elif direction == "SELL" and new_sl < current_sl:
                self.om.modify_position(ticket, new_sl=round(new_sl, 5))
                logger.debug("Trail %d: SL → %.5f (EMA %s)", ticket, new_sl, trail_tf)

        except Exception as e:
            logger.debug("Trailing stop update failed for %d: %s", ticket, e)

    def _manage_news(self, pos: Dict, current_r: float):
        """
        If high-impact news is upcoming:
        - In profit → partial close
        - At breakeven → close entirely
        - In drawdown → accept whatever happens
        """
        symbol = pos["symbol"]
        try:
            if not is_news_blackout(symbol):
                return
        except Exception:
            return

        ticket = pos["ticket"]
        logger.info("NEWS EVENT approaching for position %d (%s)", ticket, symbol)

        if current_r >= 1.0:
            # In profit → take partial
            close_vol = round(pos["volume"] * 0.5, 2)
            if close_vol >= 0.01:
                self.om.close_partial(ticket, close_vol)
                logger.info("NEWS: Partial closed %.2f lots on %d (in profit)", close_vol, ticket)
        elif abs(current_r) < 0.3:
            # Near breakeven → close
            self.om.close_position(ticket)
            logger.info("NEWS: Closed position %d (at breakeven)", ticket)
        # else: in drawdown → accept it

    def _manage_session_end(self, pos: Dict, current_r: float):
        """
        At end of killzone:
        - >2R → keep with trail
        - <1R profit → close 50%, trail rest
        - At BE → close entirely
        - In loss → close entirely
        """
        kz = current_killzone()
        if kz is not None:
            return  # Still in a killzone, not session end

        # Check if we just exited a killzone (approximate)
        est_now = now_est()
        hour = est_now.hour

        # After NY close (after 16:00 EST)
        if hour < 16:
            return  # Still during potential trading hours

        ticket = pos["ticket"]

        if current_r >= settings.SESSION_END_SIGNIFICANT_R:
            # Strong profit → keep with trail, already handled
            logger.debug("Session end: keeping position %d (%.1fR profit)", ticket, current_r)
        elif 0 < current_r < settings.SESSION_END_SMALL_R:
            # Small profit → close 50%
            close_vol = round(pos["volume"] * 0.5, 2)
            if close_vol >= 0.01:
                self.om.close_partial(ticket, close_vol)
                logger.info("Session end: partial close on %d (small profit %.1fR)", ticket, current_r)
        elif current_r <= 0:
            # At BE or in loss → close
            self.om.close_position(ticket)
            logger.info("Session end: closed %d (%.1fR — at BE or loss)", ticket, current_r)
