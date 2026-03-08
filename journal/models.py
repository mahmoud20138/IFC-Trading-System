"""
IFC Trading System — Journal Models
SQLAlchemy ORM models for the trade journal.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Boolean, Text, Enum, create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
import enum

Base = declarative_base()


class TradeDirection(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class SetupType(enum.Enum):
    LIQ_SWEEP = "LIQ_SWEEP"
    POC_BOUNCE = "POC_BOUNCE"
    VA_BREAKOUT = "VA_BREAKOUT"
    NAKED_POC = "NAKED_POC"
    POC_MIGRATION = "POC_MIGRATION"
    GENERIC_FVG = "GENERIC_FVG"
    MANUAL = "MANUAL"


class Grade(enum.Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    NO_TRADE = "NO_TRADE"


class TradeOutcome(enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    OPEN = "OPEN"


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    group_id = Column(String(64), index=True)
    symbol = Column(String(32), index=True, nullable=False)
    direction = Column(String(4), nullable=False)
    setup_type = Column(String(32))
    grade = Column(String(4))

    # Entry details
    entry_time = Column(DateTime, default=datetime.utcnow, index=True)
    entry_price = Column(Float)
    entry_volume = Column(Float)

    # Exit details
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_volume = Column(Float, nullable=True)

    # Stops and targets
    initial_sl = Column(Float)
    initial_tp1 = Column(Float)
    initial_tp2 = Column(Float)
    initial_tp3 = Column(Float, nullable=True)

    # Risk
    risk_pct = Column(Float)               # Risk % allocated
    risk_amount = Column(Float)            # Risk $ amount
    position_lots = Column(Float)
    stop_distance_pips = Column(Float)

    # Outcome
    outcome = Column(String(10), default="OPEN")
    pnl = Column(Float, default=0.0)       # Net P&L in $
    pnl_pips = Column(Float, default=0.0)
    r_multiple = Column(Float, default=0.0)
    holding_time_min = Column(Float, default=0.0)

    # MFE / MAE tracking
    mfe_pips = Column(Float, default=0.0)  # Maximum Favorable Excursion
    mae_pips = Column(Float, default=0.0)  # Maximum Adverse Excursion

    # Scaling details
    tp1_hit = Column(Boolean, default=False)
    tp2_hit = Column(Boolean, default=False)
    volume_closed_tp1 = Column(Float, default=0.0)
    volume_closed_tp2 = Column(Float, default=0.0)

    # Confluence details (JSON-like)
    confluence_score = Column(Float)        # Total confluence score
    layers_passed = Column(Integer)
    layer_scores = Column(Text, nullable=True)   # JSON string of layer scores

    # Regime info
    market_regime = Column(String(32), nullable=True)  # STRONG_TREND, RANGE, etc.
    killzone = Column(String(32), nullable=True)       # Which session

    # Multiplier breakdown
    setup_mult = Column(Float, default=1.0)
    vol_mult = Column(Float, default=1.0)
    streak_mult = Column(Float, default=1.0)
    time_mult = Column(Float, default=1.0)
    im_mult = Column(Float, default=1.0)

    # Notes
    notes = Column(Text, nullable=True)
    tags = Column(String(256), nullable=True)          # comma-separated tags
    screenshot_path = Column(String(512), nullable=True)

    # MT5 references
    mt5_tickets = Column(String(256), nullable=True)   # comma-separated
    magic_number = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return (
            f"<Trade {self.id} | {self.symbol} {self.direction} "
            f"| {self.outcome} | R={self.r_multiple:.2f}>"
        )


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, unique=True, index=True)
    trades_taken = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    breakevens = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    total_r = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    risk_used_pct = Column(Float, default=0.0)

    a_plus_setups = Column(Integer, default=0)
    a_setups = Column(Integer, default=0)
    b_setups = Column(Integer, default=0)

    best_trade_r = Column(Float, default=0.0)
    worst_trade_r = Column(Float, default=0.0)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"

    id = Column(Integer, primary_key=True)
    week_start = Column(DateTime, index=True)
    week_end = Column(DateTime)
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    total_r = Column(Float, default=0.0)
    expectancy_r = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    avg_winner_r = Column(Float, default=0.0)
    avg_loser_r = Column(Float, default=0.0)
    best_day = Column(String(16), nullable=True)
    worst_day = Column(String(16), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    balance = Column(Float)
    equity = Column(Float)
    margin = Column(Float)
    free_margin = Column(Float)
    margin_level = Column(Float, nullable=True)
    open_positions = Column(Integer, default=0)
    daily_pnl = Column(Float, default=0.0)


def init_db(db_path: str = "ifc_journal.db"):
    """Create engine and tables."""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session
