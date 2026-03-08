"""
IFC Trading System — Order Manager
Places, modifies, and closes orders via MT5.
"""

import MetaTrader5 as mt5
from typing import Dict, Any, Optional

from config import settings
from data.mt5_connector import MT5Connector
from utils.helpers import setup_logging

logger = setup_logging("ifc.orders")


class OrderManager:
    """
    Wraps MT5 order_send() for placing, modifying, and closing positions.
    All orders are pre-checked with order_check() before sending.
    """

    def __init__(self, connector: MT5Connector):
        self.mt5 = connector

    # ── Place Market Order ───────────────────────────────────────────
    def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float,
        tp: float,
        magic: int = None,
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        Open a market order.

        Parameters
        ----------
        direction : "BUY" or "SELL"
        """
        self.mt5.ensure_connected()
        if magic is None:
            magic = settings.MAGIC_NUMBER

        info = mt5.symbol_info(symbol)
        if info is None:
            return {"success": False, "error": f"Symbol {symbol} not found"}

        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = info.ask if direction == "BUY" else info.bid
        filling = info.filling_mode  # Broker-specific filling mode

        # Determine filling type
        if filling & mt5.ORDER_FILLING_FOK:
            fill_type = mt5.ORDER_FILLING_FOK
        elif filling & mt5.ORDER_FILLING_IOC:
            fill_type = mt5.ORDER_FILLING_IOC
        else:
            fill_type = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": comment[:31],  # MT5 comment limit
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_type,
        }

        # Pre-flight check
        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            retcode = check.retcode if check else "N/A"
            comment_out = check.comment if check else "check failed"
            logger.error("Order check failed: %s (%s)", comment_out, retcode)
            return {"success": False, "error": comment_out, "retcode": retcode}

        # Send
        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "error": str(mt5.last_error())}

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                "ORDER PLACED: %s %s %.2f lots @ %.5f | SL=%.5f TP=%.5f | ticket=%d",
                direction, symbol, volume, result.price, sl, tp, result.order,
            )
            return {
                "success": True,
                "ticket": result.order,
                "price": result.price,
                "volume": volume,
            }
        else:
            logger.error("Order failed: %s (code %d)", result.comment, result.retcode)
            return {
                "success": False,
                "error": result.comment,
                "retcode": result.retcode,
            }

    # ── Place Limit / Stop Order ─────────────────────────────────────
    def place_pending_order(
        self,
        symbol: str,
        direction: str,
        order_type: str,
        price: float,
        volume: float,
        sl: float,
        tp: float,
        magic: int = None,
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        Place a pending order.

        order_type: "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP"
        """
        self.mt5.ensure_connected()
        if magic is None:
            magic = settings.MAGIC_NUMBER

        type_map = {
            "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
            "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
            "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        }
        mt5_type = type_map.get(order_type)
        if mt5_type is None:
            return {"success": False, "error": f"Unknown order type: {order_type}"}

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            return {"success": False, "error": check.comment if check else "check failed"}

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                "PENDING ORDER: %s %s %.2f lots @ %.5f | ticket=%d",
                order_type, symbol, volume, price, result.order,
            )
            return {"success": True, "ticket": result.order}
        else:
            return {
                "success": False,
                "error": result.comment if result else str(mt5.last_error()),
            }

    # ── Modify Position (SL / TP) ────────────────────────────────────
    def modify_position(
        self,
        ticket: int,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Modify the SL and/or TP of an open position."""
        self.mt5.ensure_connected()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": f"Position {ticket} not found"}

        pos = positions[0]
        sl = new_sl if new_sl is not None else pos.sl
        tp = new_tp if new_tp is not None else pos.tp

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": sl,
            "tp": tp,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("MODIFIED position %d: SL=%.5f TP=%.5f", ticket, sl, tp)
            return {"success": True, "new_sl": sl, "new_tp": tp}
        else:
            return {
                "success": False,
                "error": result.comment if result else str(mt5.last_error()),
            }

    # ── Close Position (full) ────────────────────────────────────────
    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Fully close a position."""
        self.mt5.ensure_connected()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": f"Position {ticket} not found"}

        pos = positions[0]
        direction = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol)
        close_price = price.bid if direction == mt5.ORDER_TYPE_SELL else price.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": direction,
            "position": ticket,
            "price": close_price,
            "deviation": 20,
            "magic": settings.MAGIC_NUMBER,
            "comment": "IFC_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("CLOSED position %d @ %.5f | P&L = %.2f", ticket, result.price, pos.profit)
            return {"success": True, "close_price": result.price, "profit": pos.profit}
        else:
            return {
                "success": False,
                "error": result.comment if result else str(mt5.last_error()),
            }

    # ── Partial Close ────────────────────────────────────────────────
    def close_partial(self, ticket: int, volume_to_close: float) -> Dict[str, Any]:
        """Close part of a position (for TP scaling)."""
        self.mt5.ensure_connected()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": f"Position {ticket} not found"}

        pos = positions[0]
        if volume_to_close > pos.volume:
            volume_to_close = pos.volume

        # Round to volume step
        info = mt5.symbol_info(pos.symbol)
        step = info.volume_step if info else 0.01
        volume_to_close = round(
            int(volume_to_close / step) * step, 2
        )
        if volume_to_close < (info.volume_min if info else 0.01):
            return {"success": False, "error": "Volume too small to partially close"}

        direction = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol)
        close_price = price.bid if direction == mt5.ORDER_TYPE_SELL else price.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": volume_to_close,
            "type": direction,
            "position": ticket,
            "price": close_price,
            "deviation": 20,
            "magic": settings.MAGIC_NUMBER,
            "comment": "IFC_PARTIAL",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                "PARTIAL CLOSE: position %d | %.2f lots closed @ %.5f",
                ticket, volume_to_close, result.price,
            )
            return {
                "success": True,
                "volume_closed": volume_to_close,
                "remaining": round(pos.volume - volume_to_close, 2),
                "close_price": result.price,
            }
        else:
            return {
                "success": False,
                "error": result.comment if result else str(mt5.last_error()),
            }

    # ── Cancel Pending Order ─────────────────────────────────────────
    def cancel_pending(self, ticket: int) -> Dict[str, Any]:
        """Cancel a pending order."""
        self.mt5.ensure_connected()

        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("CANCELLED pending order %d", ticket)
            return {"success": True}
        else:
            return {
                "success": False,
                "error": result.comment if result else str(mt5.last_error()),
            }
