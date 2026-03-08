"""
IFC Trading System — Journal Database
CRUD operations for the trade journal.
"""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session as SASession

from journal.models import (
    Trade, DailyStats, WeeklyReview, AccountSnapshot, init_db,
)
from utils.helpers import setup_logging

logger = setup_logging("ifc.journal")


class JournalDB:
    """
    CRUD layer sitting on top of SQLAlchemy models.
    """

    def __init__(self, db_path: str = "ifc_journal.db"):
        self.engine, self.SessionFactory = init_db(db_path)

    def _session(self) -> SASession:
        return self.SessionFactory()

    # ── Trade CRUD ───────────────────────────────────────────────────
    def log_trade_open(self, trade_data: Dict[str, Any]) -> int:
        """Log a new trade entry. Returns the trade ID."""
        session = self._session()
        try:
            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
            tid = trade.id
            logger.info("Logged trade open: id=%d %s %s", tid, trade.symbol, trade.direction)
            return tid
        finally:
            session.close()

    def update_trade(self, trade_id: int, updates: Dict[str, Any]):
        """Update an existing trade record."""
        session = self._session()
        try:
            trade = session.query(Trade).get(trade_id)
            if trade is None:
                logger.warning("Trade %d not found for update", trade_id)
                return False
            for key, value in updates.items():
                setattr(trade, key, value)
            trade.updated_at = datetime.utcnow()
            session.commit()
            return True
        finally:
            session.close()

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_volume: float,
        pnl: float,
        pnl_pips: float,
        r_multiple: float,
        outcome: str = "WIN",
        mfe_pips: float = 0,
        mae_pips: float = 0,
    ):
        """Mark a trade as closed with exit data."""
        session = self._session()
        try:
            trade = session.query(Trade).get(trade_id)
            if trade is None:
                return False

            trade.exit_time = datetime.utcnow()
            trade.exit_price = exit_price
            trade.exit_volume = exit_volume
            trade.pnl = pnl
            trade.pnl_pips = pnl_pips
            trade.r_multiple = r_multiple
            trade.outcome = outcome
            trade.mfe_pips = mfe_pips
            trade.mae_pips = mae_pips

            if trade.entry_time:
                delta = (trade.exit_time - trade.entry_time).total_seconds() / 60
                trade.holding_time_min = delta

            session.commit()
            logger.info(
                "Trade %d closed: %s %.1fR $%.2f",
                trade_id, outcome, r_multiple, pnl,
            )
            return True
        finally:
            session.close()

    def get_trade(self, trade_id: int) -> Optional[Dict]:
        session = self._session()
        try:
            trade = session.query(Trade).get(trade_id)
            if trade:
                return self._trade_to_dict(trade)
            return None
        finally:
            session.close()

    def get_open_trades(self) -> List[Dict]:
        session = self._session()
        try:
            trades = session.query(Trade).filter(Trade.outcome == "OPEN").all()
            return [self._trade_to_dict(t) for t in trades]
        finally:
            session.close()

    def get_trades_range(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict]:
        session = self._session()
        try:
            q = session.query(Trade).filter(Trade.entry_time >= start)
            if end:
                q = q.filter(Trade.entry_time <= end)
            if symbol:
                q = q.filter(Trade.symbol == symbol)
            trades = q.order_by(Trade.entry_time.desc()).all()
            return [self._trade_to_dict(t) for t in trades]
        finally:
            session.close()

    def get_recent_trades(self, n: int = 50) -> List[Dict]:
        session = self._session()
        try:
            trades = (
                session.query(Trade)
                .order_by(Trade.entry_time.desc())
                .limit(n)
                .all()
            )
            return [self._trade_to_dict(t) for t in trades]
        finally:
            session.close()

    # ── Daily stats ──────────────────────────────────────────────────
    def log_daily_stats(self, stats: Dict[str, Any]):
        session = self._session()
        try:
            ds = DailyStats(**stats)
            session.add(ds)
            session.commit()
        finally:
            session.close()

    def get_daily_stats(self, days: int = 30) -> List[Dict]:
        session = self._session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            rows = (
                session.query(DailyStats)
                .filter(DailyStats.date >= cutoff)
                .order_by(DailyStats.date.desc())
                .all()
            )
            return [self._obj_to_dict(r) for r in rows]
        finally:
            session.close()

    # ── Weekly reviews ───────────────────────────────────────────────
    def log_weekly_review(self, data: Dict[str, Any]):
        session = self._session()
        try:
            wr = WeeklyReview(**data)
            session.add(wr)
            session.commit()
        finally:
            session.close()

    # ── Account snapshots ────────────────────────────────────────────
    def log_snapshot(self, data: Dict[str, Any]):
        session = self._session()
        try:
            snap = AccountSnapshot(**data)
            session.add(snap)
            session.commit()
        finally:
            session.close()

    def get_snapshots(self, days: int = 30) -> List[Dict]:
        session = self._session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            rows = (
                session.query(AccountSnapshot)
                .filter(AccountSnapshot.timestamp >= cutoff)
                .order_by(AccountSnapshot.timestamp.desc())
                .all()
            )
            return [self._obj_to_dict(r) for r in rows]
        finally:
            session.close()

    # ── Helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _trade_to_dict(t: Trade) -> Dict:
        d = {c.name: getattr(t, c.name) for c in Trade.__table__.columns}
        # Parse layer_scores JSON
        if d.get("layer_scores"):
            try:
                d["layer_scores"] = json.loads(d["layer_scores"])
            except json.JSONDecodeError:
                pass
        return d

    @staticmethod
    def _obj_to_dict(obj) -> Dict:
        return {c.name: getattr(obj, c.name) for c in obj.__class__.__table__.columns}
