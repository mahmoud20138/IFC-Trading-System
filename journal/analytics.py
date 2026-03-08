"""
IFC Trading System — Journal Analytics
Computes performance metrics from trade history.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import statistics

from journal.database import JournalDB
from utils.helpers import setup_logging

logger = setup_logging("ifc.analytics")


class JournalAnalytics:
    """
    Crunches trade journal data into actionable metrics.
    """

    def __init__(self, db: JournalDB):
        self.db = db

    # ── Core Performance ─────────────────────────────────────────────
    def compute_performance(
        self,
        trades: Optional[List[Dict]] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compute full performance summary.

        Returns dict with win rate, expectancy, profit factor, etc.
        """
        if trades is None:
            start = datetime.utcnow() - timedelta(days=days)
            trades = self.db.get_trades_range(start)

        closed = [t for t in trades if t["outcome"] != "OPEN"]
        if not closed:
            return self._empty_performance()

        wins = [t for t in closed if t["outcome"] == "WIN"]
        losses = [t for t in closed if t["outcome"] == "LOSS"]
        bes = [t for t in closed if t["outcome"] == "BREAKEVEN"]

        total = len(closed)
        win_rate = len(wins) / total * 100 if total > 0 else 0

        # R-multiples
        r_values = [t["r_multiple"] for t in closed]
        win_r = [t["r_multiple"] for t in wins]
        loss_r = [abs(t["r_multiple"]) for t in losses]

        avg_win_r = statistics.mean(win_r) if win_r else 0
        avg_loss_r = statistics.mean(loss_r) if loss_r else 0
        expectancy_r = statistics.mean(r_values) if r_values else 0

        # Profit factor
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # PnL
        total_pnl = sum(t["pnl"] for t in closed)
        total_r = sum(r_values)

        # MFE / MAE
        mfe_values = [t["mfe_pips"] for t in closed if t.get("mfe_pips")]
        mae_values = [t["mae_pips"] for t in closed if t.get("mae_pips")]

        # Streaks
        max_win_streak = self._max_streak(closed, "WIN")
        max_loss_streak = self._max_streak(closed, "LOSS")

        # Holding time
        hold_times = [t["holding_time_min"] for t in closed if t.get("holding_time_min")]
        avg_hold_min = statistics.mean(hold_times) if hold_times else 0

        return {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "breakevens": len(bes),
            "win_rate": round(win_rate, 2),
            "avg_win_r": round(avg_win_r, 2),
            "avg_loss_r": round(avg_loss_r, 2),
            "expectancy_r": round(expectancy_r, 3),
            "profit_factor": round(profit_factor, 2),
            "total_pnl": round(total_pnl, 2),
            "total_r": round(total_r, 2),
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_mfe_pips": round(statistics.mean(mfe_values), 1) if mfe_values else 0,
            "avg_mae_pips": round(statistics.mean(mae_values), 1) if mae_values else 0,
            "avg_hold_min": round(avg_hold_min, 1),
        }

    # ── Breakdown by Setup Type ──────────────────────────────────────
    def performance_by_setup(self, days: int = 90) -> Dict[str, Dict]:
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)

        setups = {}
        for t in trades:
            st = t.get("setup_type", "UNKNOWN") or "UNKNOWN"
            if st not in setups:
                setups[st] = []
            setups[st].append(t)

        return {st: self.compute_performance(tl) for st, tl in setups.items()}

    # ── Breakdown by Symbol ──────────────────────────────────────────
    def performance_by_symbol(self, days: int = 90) -> Dict[str, Dict]:
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)

        symbols = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in symbols:
                symbols[sym] = []
            symbols[sym].append(t)

        return {sym: self.compute_performance(tl) for sym, tl in symbols.items()}

    # ── Breakdown by Session ─────────────────────────────────────────
    def performance_by_session(self, days: int = 90) -> Dict[str, Dict]:
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)

        sessions = {}
        for t in trades:
            kz = t.get("killzone", "Other") or "Other"
            if kz not in sessions:
                sessions[kz] = []
            sessions[kz].append(t)

        return {kz: self.compute_performance(tl) for kz, tl in sessions.items()}

    # ── Breakdown by Grade ───────────────────────────────────────────
    def performance_by_grade(self, days: int = 90) -> Dict[str, Dict]:
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)

        grades = {}
        for t in trades:
            g = t.get("grade", "UNK") or "UNK"
            if g not in grades:
                grades[g] = []
            grades[g].append(t)

        return {g: self.compute_performance(tl) for g, tl in grades.items()}

    # ── Equity Curve ─────────────────────────────────────────────────
    def equity_curve(self, days: int = 90) -> List[Dict]:
        """Cumulative R-multiple over time."""
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)
        closed = [t for t in trades if t["outcome"] != "OPEN"]
        closed.sort(key=lambda x: x["entry_time"])

        curve = []
        cumulative_r = 0
        cumulative_pnl = 0
        for t in closed:
            cumulative_r += t["r_multiple"]
            cumulative_pnl += t["pnl"]
            curve.append({
                "date": t["exit_time"] or t["entry_time"],
                "cumulative_r": round(cumulative_r, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "trade_id": t["id"],
            })
        return curve

    # ── Max Drawdown (R) ─────────────────────────────────────────────
    def max_drawdown_r(self, days: int = 90) -> Dict[str, float]:
        """Peak-to-trough drawdown in R-multiples."""
        curve = self.equity_curve(days)
        if not curve:
            return {"max_dd_r": 0, "max_dd_pnl": 0}

        peak_r = 0
        max_dd = 0
        peak_pnl = 0
        max_dd_pnl = 0

        for pt in curve:
            if pt["cumulative_r"] > peak_r:
                peak_r = pt["cumulative_r"]
            dd = peak_r - pt["cumulative_r"]
            if dd > max_dd:
                max_dd = dd

            if pt["cumulative_pnl"] > peak_pnl:
                peak_pnl = pt["cumulative_pnl"]
            dd_pnl = peak_pnl - pt["cumulative_pnl"]
            if dd_pnl > max_dd_pnl:
                max_dd_pnl = dd_pnl

        return {
            "max_dd_r": round(max_dd, 2),
            "max_dd_pnl": round(max_dd_pnl, 2),
        }

    # ── Day-of-Week Performance ──────────────────────────────────────
    def performance_by_day(self, days: int = 90) -> Dict[str, Dict]:
        start = datetime.utcnow() - timedelta(days=days)
        trades = self.db.get_trades_range(start)

        days_map = {}
        for t in trades:
            entry = t.get("entry_time")
            if not entry:
                continue
            day_name = entry.strftime("%A")
            if day_name not in days_map:
                days_map[day_name] = []
            days_map[day_name].append(t)

        return {d: self.compute_performance(tl) for d, tl in days_map.items()}

    # ── Helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _max_streak(trades: List[Dict], outcome: str) -> int:
        max_s = 0
        current = 0
        for t in trades:
            if t["outcome"] == outcome:
                current += 1
                max_s = max(max_s, current)
            else:
                current = 0
        return max_s

    @staticmethod
    def _empty_performance() -> Dict[str, Any]:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "breakevens": 0,
            "win_rate": 0, "avg_win_r": 0, "avg_loss_r": 0,
            "expectancy_r": 0, "profit_factor": 0, "total_pnl": 0,
            "total_r": 0, "max_win_streak": 0, "max_loss_streak": 0,
            "gross_profit": 0, "gross_loss": 0, "avg_mfe_pips": 0,
            "avg_mae_pips": 0, "avg_hold_min": 0,
        }
