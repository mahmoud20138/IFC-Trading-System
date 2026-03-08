"""
IFC Trading System — Alerts / Notifier
Telegram notifications with inline confirm/skip buttons for semi-auto mode.
"""

import asyncio
from typing import Dict, Any, Optional

from config import settings
from utils.helpers import setup_logging

logger = setup_logging("ifc.alerts")

# Try importing telegram, but don't fail if not installed
try:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CallbackQueryHandler
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.info("python-telegram-bot not installed — Telegram alerts disabled")


class Notifier:
    """
    Send alerts via Telegram.
    In SEMI_AUTO mode, sends inline buttons for confirm/skip.
    """

    def __init__(self):
        self.enabled = False
        self.bot = None
        self.chat_id = None
        self._pending_callbacks = {}

        try:
            from config.credentials import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and TELEGRAM_AVAILABLE:
                self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
                self.chat_id = TELEGRAM_CHAT_ID
                self.enabled = True
                logger.info("Telegram notifier initialized")
        except (ImportError, AttributeError):
            logger.info("Telegram credentials not configured")

    async def _send_message(self, text: str, reply_markup=None):
        """Send a Telegram message."""
        if not self.enabled:
            logger.info("ALERT (no Telegram): %s", text)
            return None
        try:
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
            return msg
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return None

    def send(self, text: str):
        """Synchronous wrapper for sending a message."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._send_message(text))
            else:
                loop.run_until_complete(self._send_message(text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_message(text))

    # ── Specific alert types ─────────────────────────────────────────

    def alert_setup_detected(self, setup: Dict[str, Any]) -> str:
        """Alert: new trade setup detected."""
        msg = (
            f"🎯 *IFC SETUP DETECTED*\n\n"
            f"*{setup.get('setup_type', 'SETUP')}* — {setup.get('symbol', '?')}\n"
            f"Direction: {setup.get('direction', '?')}\n"
            f"Grade: *{setup.get('grade', '?')}*\n"
            f"Entry: `{setup.get('entry_price', 0):.5f}`\n"
            f"SL: `{setup.get('stop_loss', 0):.5f}`\n"
            f"TP1: `{setup.get('tp1', 0):.5f}`\n"
            f"TP2: `{setup.get('tp2', 0):.5f}`\n"
            f"R:R: {setup.get('rr_ratio', 0):.1f}\n"
            f"Risk: {setup.get('risk_pct', 0):.2f}%\n"
            f"Layers: {setup.get('layers_passed', 0)}/8"
        )
        self.send(msg)
        return msg

    def alert_trade_opened(self, trade_info: Dict[str, Any]):
        """Alert: trade placed."""
        msg = (
            f"✅ *TRADE OPENED*\n\n"
            f"{trade_info.get('direction', '?')} {trade_info.get('symbol', '?')}\n"
            f"Volume: {trade_info.get('volume', 0):.2f} lots\n"
            f"Entry: `{trade_info.get('price', 0):.5f}`\n"
            f"SL: `{trade_info.get('sl', 0):.5f}`\n"
            f"TP: `{trade_info.get('tp', 0):.5f}`\n"
            f"Risk: {trade_info.get('risk_pct', 0):.2f}%"
        )
        self.send(msg)

    def alert_trade_closed(self, trade_info: Dict[str, Any]):
        """Alert: trade closed."""
        pnl = trade_info.get("pnl", 0)
        emoji = "💰" if pnl >= 0 else "📉"
        msg = (
            f"{emoji} *TRADE CLOSED*\n\n"
            f"{trade_info.get('symbol', '?')} — {trade_info.get('outcome', '?')}\n"
            f"P&L: ${pnl:+,.2f}\n"
            f"R-Multiple: {trade_info.get('r_multiple', 0):+.2f}\n"
            f"Hold time: {trade_info.get('holding_time_min', 0):.0f} min"
        )
        self.send(msg)

    def alert_tp_hit(self, tp_level: str, trade_info: Dict[str, Any]):
        """Alert: take profit level hit."""
        msg = (
            f"🎯 *{tp_level} HIT*\n\n"
            f"{trade_info.get('symbol', '?')}\n"
            f"Closed: {trade_info.get('volume_closed', 0):.2f} lots\n"
            f"Remaining on trail"
        )
        self.send(msg)

    def alert_circuit_breaker(self, breaker: Dict[str, Any]):
        """Alert: circuit breaker triggered."""
        msg = (
            f"🛑 *CIRCUIT BREAKER*\n\n"
            f"Action: {breaker.get('action', '?')}\n"
            f"Reason: {breaker.get('reason', '?')}"
        )
        self.send(msg)

    def alert_daily_summary(self, stats: Dict[str, Any]):
        """End-of-day summary."""
        msg = (
            f"📊 *DAILY SUMMARY*\n\n"
            f"Trades: {stats.get('trades', 0)}\n"
            f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}\n"
            f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            f"Total P&L: ${stats.get('total_pnl', 0):+,.2f}\n"
            f"Total R: {stats.get('total_r', 0):+.2f}\n"
            f"Daily risk used: {stats.get('risk_used', 0):.1f}%"
        )
        self.send(msg)

    # ── Semi-Auto Confirmation ───────────────────────────────────────

    async def request_confirmation(self, setup: Dict[str, Any]) -> Optional[bool]:
        """
        Send setup with inline CONFIRM/SKIP buttons.
        Returns True if confirmed, False if skipped, None if timeout.
        
        NOTE: For full async button handling, run the Telegram updater
        in the main loop. This provides a simplified version.
        """
        if not self.enabled or not TELEGRAM_AVAILABLE:
            logger.info("CONFIRM REQUEST (no Telegram): %s %s", 
                        setup.get("symbol"), setup.get("setup_type"))
            return None

        group_id = setup.get("group_id", "unknown")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_{group_id}"),
                InlineKeyboardButton("❌ SKIP", callback_data=f"skip_{group_id}"),
            ]
        ])

        msg = (
            f"⚡ *CONFIRM TRADE?*\n\n"
            f"*{setup.get('setup_type')}* — {setup.get('symbol')}\n"
            f"Direction: {setup.get('direction')}\n"
            f"Grade: *{setup.get('grade')}*\n"
            f"Entry: `{setup.get('entry_price', 0):.5f}`\n"
            f"Risk: {setup.get('risk_pct', 0):.2f}%\n\n"
            f"_Reply within 60 seconds_"
        )

        await self._send_message(msg, reply_markup=keyboard)
        # In practice, callback handling needs a running Updater.
        # For simplified flow, return None and handle via dashboard.
        return None
