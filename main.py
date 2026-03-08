"""
IFC Trading System — Main Orchestrator
Ties all components together with APScheduler.

Usage:
    python main.py              # Start the system
    python main.py --mode demo  # Dry-run / paper mode (no real orders)
"""

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# ── Project imports ──────────────────────────────────────────────────
from config import settings
from config.instruments import INSTRUMENTS
from data.mt5_connector import MT5Connector
from data.intermarket import IntermarketData
from data.sentiment import SentimentData
from data.economic_calendar import get_high_impact_events, is_news_blackout

from analysis.layer1_intermarket import IntermarketLayer
from analysis.layer2_trend import TrendLayer
from analysis.layer3_volume_profile import VolumeProfileLayer
from analysis.layer4_candle_density import CandleDensityLayer
from analysis.layer5_liquidity import LiquidityLayer
from analysis.layer6_fvg_ob import FVGOrderBlockLayer
from analysis.layer7_order_flow import OrderFlowLayer
from analysis.layer8_killzone import KillzoneLayer
from analysis.confluence_scorer import ConfluenceScorer
from analysis.setup_detector import SetupDetector
from analysis.regime_detector import RegimeDetector
from analysis.pipeline import AnalysisPipeline

from execution.risk_manager import RiskManager
from execution.order_manager import OrderManager
from execution.scaling import ScalingManager
from execution.trade_manager import TradeManager

from journal.database import JournalDB
from journal.analytics import JournalAnalytics
from alerts.notifier import Notifier
from utils.helpers import (
    setup_logging, current_killzone, now_utc, now_est,
    is_lunch_break, is_friday_cutoff,
)

logger = setup_logging("ifc.main")


class IFCSystem:
    """
    Main system orchestrator.
    Manages the full lifecycle: scan → analyze → detect → risk → execute → manage.
    """

    def __init__(self, mode: str = "live"):
        self.mode = mode  # "live" or "demo"
        self.running = False

        # ── Components ───────────────────────────────────────────────
        self.mt5 = MT5Connector()
        self.intermarket = IntermarketData()
        self.sentiment = SentimentData()

        # Analysis layers
        self.layer1 = IntermarketLayer(self.intermarket)
        self.layer2 = TrendLayer()
        self.layer3 = VolumeProfileLayer()
        self.layer4 = CandleDensityLayer()
        self.layer5 = LiquidityLayer()
        self.layer6 = FVGOrderBlockLayer()
        self.layer7 = OrderFlowLayer()
        self.layer8 = KillzoneLayer()
        self.scorer = ConfluenceScorer()
        self.setup_detector = SetupDetector()
        self.regime_detector = RegimeDetector()
        self.pipeline = AnalysisPipeline()

        # Execution
        self.risk_mgr = RiskManager()
        self.order_mgr = OrderManager(self.mt5)
        self.scaling_mgr = ScalingManager(self.order_mgr)
        self.trade_mgr = TradeManager(self.mt5, self.order_mgr, self.scaling_mgr)

        # Journal
        self.journal = JournalDB()
        self.analytics = JournalAnalytics(self.journal)

        # Alerts
        self.notifier = Notifier()

        # Scheduler
        self.scheduler = BackgroundScheduler()

        # State
        self._intermarket_cache = {}
        self._sentiment_cache = {}
        self._last_scan_time = {}

    # ── Startup / Shutdown ───────────────────────────────────────────

    def start(self):
        """Initialize connections and start the scheduler."""
        logger.info("=" * 60)
        logger.info("IFC Trading System starting — mode: %s", self.mode)
        logger.info("=" * 60)

        # Connect MT5
        if not self.mt5.connect():
            logger.error("Failed to connect to MT5. Exiting.")
            sys.exit(1)

        acct = self.mt5.get_account_info()
        logger.info(
            "MT5 connected: Account #%s | Balance: $%.2f | Server: %s",
            acct.get("login"), acct.get("balance", 0), acct.get("server", "?"),
        )

        # Pre-load intermarket data
        self._refresh_intermarket()

        # ── Schedule jobs ────────────────────────────────────────────
        # Position management — every 30 seconds
        self.scheduler.add_job(
            self._manage_positions,
            IntervalTrigger(seconds=30),
            id="manage_positions",
            name="Position Management",
        )

        # Main analysis scan — every 5 minutes during killzones
        self.scheduler.add_job(
            self._scan_all_instruments,
            IntervalTrigger(minutes=5),
            id="scan_instruments",
            name="Instrument Scan",
        )

        # Intermarket refresh — every 15 minutes
        self.scheduler.add_job(
            self._refresh_intermarket,
            IntervalTrigger(minutes=15),
            id="refresh_intermarket",
            name="Intermarket Refresh",
        )

        # Sentiment refresh — every 4 hours
        self.scheduler.add_job(
            self._refresh_sentiment,
            IntervalTrigger(hours=4),
            id="refresh_sentiment",
            name="Sentiment Refresh",
        )

        # Account snapshot — every hour
        self.scheduler.add_job(
            self._log_account_snapshot,
            IntervalTrigger(hours=1),
            id="account_snapshot",
            name="Account Snapshot",
        )

        # Daily reset — 00:01 EST
        self.scheduler.add_job(
            self._daily_reset,
            CronTrigger(hour=0, minute=1, timezone="US/Eastern"),
            id="daily_reset",
            name="Daily Reset",
        )

        # Daily summary — 17:00 EST (after NY close)
        self.scheduler.add_job(
            self._daily_summary,
            CronTrigger(hour=17, minute=0, timezone="US/Eastern"),
            id="daily_summary",
            name="Daily Summary",
        )

        self.scheduler.start()
        self.running = True

        self.notifier.send("🟢 *IFC Trading System started*\nMode: " + self.mode)
        logger.info("Scheduler started — %d jobs registered", len(self.scheduler.get_jobs()))

    def stop(self):
        """Graceful shutdown."""
        logger.info("Shutting down IFC System...")
        self.running = False
        self.scheduler.shutdown(wait=False)
        self.mt5.disconnect()
        self.notifier.send("🔴 *IFC Trading System stopped*")
        logger.info("System stopped.")

    # ── Core Scan Logic ──────────────────────────────────────────────

    def _scan_all_instruments(self):
        """Scan all instruments during active killzones."""
        kz = current_killzone()
        if kz is None:
            return  # Outside killzone — skip scanning

        if is_lunch_break():
            logger.debug("Lunch break — skipping scan")
            return

        if is_friday_cutoff():
            logger.info("Friday cutoff — no new trades")
            return

        # Circuit breaker check
        breaker = self.risk_mgr.check_circuit_breakers()
        if not breaker["can_trade"]:
            logger.warning("Circuit breaker active: %s", breaker["reason"])
            return

        logger.info("Scanning %d instruments (KZ: %s)...", len(INSTRUMENTS), kz)

        for inst_key, inst in INSTRUMENTS.items():
            try:
                self._analyze_instrument(inst_key, inst)
            except Exception as e:
                logger.error("Error scanning %s: %s", inst_key, e, exc_info=True)

    def _analyze_instrument(self, inst_key: str, inst):
        """Run full 11-layer pipeline analysis on one instrument."""
        symbol = inst.mt5_symbol

        # Fetch multi-timeframe data
        df_w = self.mt5.get_ohlcv(symbol, "W1", bars=100)
        df_d = self.mt5.get_ohlcv(symbol, "D1", bars=200)
        df_4h = self.mt5.get_ohlcv(symbol, "H4", bars=200)
        df_1h = self.mt5.get_ohlcv(symbol, "H1", bars=200)
        df_15m = self.mt5.get_ohlcv(symbol, "M15", bars=200)

        if df_d.empty or df_15m.empty:
            logger.debug("No data for %s — skipping", symbol)
            return

        # Optional M1 for volume profile precision
        df_m1 = None
        try:
            df_m1 = self.mt5.get_ohlcv(symbol, "M1", bars=2000)
        except Exception:
            pass

        # Run the full 11-layer pipeline
        pipe_result = self.pipeline.run(
            instrument=inst,
            intermarket_layer=self.layer1,
            df_w1=df_w,
            df_d1=df_d,
            df_h4=df_4h,
            df_h1=df_1h,
            df_m15=df_15m,
            df_m1=df_m1,
            intermarket_snapshot=self._intermarket_cache,
            sentiment_cache=self._sentiment_cache,
            portfolio_risk_pct=self.risk_mgr._daily_risk_used if hasattr(self.risk_mgr, '_daily_risk_used') else 0.0,
            daily_losses=getattr(self.risk_mgr, '_daily_losses', 0),
        )

        if not pipe_result.tradeable:
            return

        signals = pipe_result.signals
        confluence = pipe_result.confluence
        regime = pipe_result.regime
        current_price = pipe_result.current_price

        logger.info(
            "TRADEABLE: %s | Grade=%s | Dir=%s | Layers=%d/11",
            inst_key, pipe_result.grade, pipe_result.direction,
            confluence.get("layers_passed", confluence.get("total_passes", 0)),
        )

        # ── Setup Detection ──────────────────────────────────────────
        setup = self.setup_detector.detect(
            symbol=symbol,
            direction=pipe_result.direction,
            layer_signals=signals,
            df_15m=df_15m,
            df_1h=df_1h,
            pip_size=inst.pip_size,
        )

        if setup is None:
            logger.debug("No valid setup pattern for %s", inst_key)
            return

        # ── Risk Calculation ─────────────────────────────────────────
        # ATR ratio for volatility multiplier
        import numpy as np
        atr_values = df_d["high"].tail(20) - df_d["low"].tail(20)
        current_atr = float(atr_values.iloc[-1])
        avg_atr = float(atr_values.mean())
        atr_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

        risk_result = self.risk_mgr.calculate_risk_pct(
            setup_grade=confluence["grade"],
            atr_ratio=atr_ratio,
            intermarket_alignment=self._get_alignment(sig1),
        )

        if risk_result["final_risk_pct"] <= 0:
            return

        # Apply regime size adjustment
        adj_risk = risk_result["final_risk_pct"] * regime["size_adjustment"]

        # Position sizing
        acct = self.mt5.get_account_info()
        sym_info = self.mt5.get_symbol_info(symbol)
        stop_pips = abs(setup.entry_price - setup.stop_loss) / inst.pip_size

        sizing = self.risk_mgr.calculate_position_size(
            account_balance=acct["balance"],
            risk_pct=adj_risk,
            stop_distance_pips=stop_pips,
            pip_value_per_lot=inst.pip_value_per_lot,
            volume_step=sym_info.get("volume_step", 0.01),
            volume_min=sym_info.get("volume_min", 0.01),
            volume_max=sym_info.get("volume_max", 100.0),
        )

        if sizing["lots"] <= 0:
            return

        # ── Build setup info ─────────────────────────────────────────
        setup_info = {
            "symbol": symbol,
            "instrument": inst_key,
            "direction": confluence["direction"],
            "setup_type": setup.setup_type,
            "grade": confluence["grade"],
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "tp1": setup.tp1,
            "tp2": setup.tp2,
            "rr_ratio": setup.rr_ratio,
            "risk_pct": adj_risk,
            "lots": sizing["lots"],
            "layers_passed": confluence["layers_passed"],
            "layer_scores": json.dumps({s.layer_name: s.score for s in signals}),
            "regime": regime["regime"],
            "killzone": current_killzone(),
        }

        # ── Execute or Confirm ───────────────────────────────────────
        self.notifier.alert_setup_detected(setup_info)

        if settings.TRADING_MODE == "FULL_AUTO" and self.mode == "live":
            self._execute_trade(setup_info, setup, sizing, signals, risk_result)
        elif settings.TRADING_MODE == "SEMI_AUTO":
            logger.info("SEMI-AUTO: Awaiting confirmation for %s %s", symbol, setup.setup_type)
            # In semi-auto, the dashboard or Telegram handles confirmation

    def _execute_trade(
        self,
        setup_info: Dict,
        setup,
        sizing: Dict,
        signals: list,
        risk_result: Dict,
    ):
        """Place the trade via scaling manager."""
        symbol = setup_info["symbol"]
        direction = setup_info["direction"]
        direction_mt5 = "BUY" if direction == "BULLISH" else "SELL"

        # Calculate 3 entry levels for scaling
        entry_ce = setup.entry_price
        entry_fvg = setup.details.get("fvg_low", entry_ce)
        entry_poc = setup.details.get("poc_edge", entry_ce)

        result = self.scaling_mgr.open_scaled_entry(
            symbol=symbol,
            direction=direction_mt5,
            total_volume=sizing["lots"],
            entry_ce=entry_ce,
            entry_fvg_low=entry_fvg,
            entry_poc_edge=entry_poc,
            stop_loss=setup.stop_loss,
            tp1=setup.tp1,
            tp2=setup.tp2,
        )

        if result["success"]:
            # Log to journal
            self.risk_mgr.record_trade(setup_info["risk_pct"])

            trade_data = {
                "group_id": result["group_id"],
                "symbol": symbol,
                "direction": direction_mt5,
                "setup_type": setup.setup_type,
                "grade": setup_info["grade"],
                "entry_time": datetime.utcnow(),
                "entry_price": setup.entry_price,
                "entry_volume": sizing["lots"],
                "initial_sl": setup.stop_loss,
                "initial_tp1": setup.tp1,
                "initial_tp2": setup.tp2,
                "risk_pct": setup_info["risk_pct"],
                "risk_amount": sizing["risk_amount"],
                "position_lots": sizing["lots"],
                "stop_distance_pips": sizing["stop_distance_pips"],
                "confluence_score": sum(s.score for s in signals),
                "layers_passed": setup_info["layers_passed"],
                "layer_scores": setup_info["layer_scores"],
                "market_regime": setup_info["regime"],
                "killzone": setup_info["killzone"],
                "setup_mult": risk_result.get("setup_multiplier", 1),
                "vol_mult": risk_result.get("volatility_multiplier", 1),
                "streak_mult": risk_result.get("streak_multiplier", 1),
                "time_mult": risk_result.get("time_multiplier", 1),
                "im_mult": risk_result.get("intermarket_multiplier", 1),
                "mt5_tickets": ",".join(str(t) for t in result.get("orders", [])),
                "magic_number": settings.MAGIC_NUMBER,
            }
            trade_id = self.journal.log_trade_open(trade_data)

            self.notifier.alert_trade_opened({
                "symbol": symbol,
                "direction": direction_mt5,
                "volume": sizing["lots"],
                "price": setup.entry_price,
                "sl": setup.stop_loss,
                "tp": setup.tp1,
                "risk_pct": setup_info["risk_pct"],
            })

            logger.info("TRADE PLACED: %s #%d | %s %s %.2f lots",
                        result["group_id"], trade_id, direction_mt5, symbol, sizing["lots"])
        else:
            logger.warning("Trade placement failed for %s", symbol)

    # ── Background jobs ──────────────────────────────────────────────

    def _manage_positions(self):
        """Called every 30 seconds — manage open positions."""
        try:
            self.trade_mgr.manage_all_positions()
        except Exception as e:
            logger.error("Position management error: %s", e, exc_info=True)

    def _refresh_intermarket(self):
        """Refresh intermarket data cache."""
        try:
            self._intermarket_cache = self.intermarket.get_full_snapshot()
            logger.debug("Intermarket data refreshed")
        except Exception as e:
            logger.error("Intermarket refresh error: %s", e)

    def _refresh_sentiment(self):
        """Refresh sentiment data cache."""
        try:
            self._sentiment_cache = self.sentiment.get_sentiment_snapshot()
            logger.debug("Sentiment data refreshed")
        except Exception as e:
            logger.error("Sentiment refresh error: %s", e)

    def _log_account_snapshot(self):
        """Log account state to journal."""
        try:
            acct = self.mt5.get_account_info()
            positions = self.mt5.get_open_positions()
            self.journal.log_snapshot({
                "balance": acct.get("balance", 0),
                "equity": acct.get("equity", 0),
                "margin": acct.get("margin", 0),
                "free_margin": acct.get("margin_free", 0),
                "margin_level": acct.get("margin_level", 0),
                "open_positions": len(positions),
                "daily_pnl": acct.get("equity", 0) - acct.get("balance", 0),
            })
        except Exception as e:
            logger.error("Snapshot error: %s", e)

    def _daily_reset(self):
        """Reset daily counters."""
        self.risk_mgr.reset_daily()
        logger.info("Daily counters reset")

    def _daily_summary(self):
        """Generate and send daily summary."""
        try:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0)
            trades = self.journal.get_trades_range(today)
            closed = [t for t in trades if t["outcome"] != "OPEN"]
            wins = [t for t in closed if t["outcome"] == "WIN"]

            stats = {
                "trades": len(trades),
                "wins": len(wins),
                "losses": len(closed) - len(wins),
                "win_rate": len(wins) / len(closed) * 100 if closed else 0,
                "total_pnl": sum(t["pnl"] for t in closed),
                "total_r": sum(t["r_multiple"] for t in closed),
                "risk_used": self.risk_mgr._daily_risk_used,
            }

            self.journal.log_daily_stats({
                "date": today,
                "trades_taken": stats["trades"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": stats["win_rate"],
                "total_pnl": stats["total_pnl"],
                "total_r": stats["total_r"],
                "risk_used_pct": stats["risk_used"],
            })

            self.notifier.alert_daily_summary(stats)
            logger.info("Daily summary — %d trades, P&L $%.2f", stats["trades"], stats["total_pnl"])
        except Exception as e:
            logger.error("Daily summary error: %s", e)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _get_alignment(sig) -> str:
        """Convert intermarket signal to alignment string."""
        if sig.score >= 7:
            return "fully_aligned"
        if sig.score >= 5:
            return "mostly_aligned"
        if sig.score >= 3:
            return "partially_aligned"
        return "conflicting"


# ── Entry Point ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IFC Trading System")
    parser.add_argument(
        "--mode",
        choices=["live", "demo"],
        default="live",
        help="Trading mode (live = real orders, demo = paper/log only)",
    )
    args = parser.parse_args()

    system = IFCSystem(mode=args.mode)

    def shutdown_handler(signum, frame):
        system.stop()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
    except ValueError:
        pass  # Not in main thread (e.g. Streamlit runner)

    system.start()

    logger.info("System running. Press Ctrl+C to stop.")
    try:
        while system.running:
            time.sleep(1)
    except KeyboardInterrupt:
        system.stop()


if __name__ == "__main__":
    main()
