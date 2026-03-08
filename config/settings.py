"""
IFC Trading System — Master Settings
All strategy parameters, risk rules, killzone times, MA periods, thresholds.
Edit these values to tune the system. No code logic lives here.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# ──────────────────────────────────────────────────────────────────────
# SYSTEM MODE
# ──────────────────────────────────────────────────────────────────────
TRADING_MODE = "SEMI_AUTO"  # "FULL_AUTO" | "SEMI_AUTO"

# ──────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT
# ──────────────────────────────────────────────────────────────────────
BASE_RISK_PCT = 1.5          # Base risk per trade (%)
MAX_RISK_PCT = 3.0           # Absolute cap per single trade (%)
MIN_RISK_PCT = 0.25          # Floor – below this, not worth the trade
DAILY_MAX_RISK_PCT = 5.0     # Max cumulative risk per day (%)
MAX_TRADES_PER_DAY = 3
MIN_RR_RATIO = 3.0           # Minimum reward-to-risk to accept a trade

# ── Setup quality multipliers ──
SETUP_QUALITY_MULTIPLIERS = {
    "A+": 1.5,   # 8/8 layers pass
    "A":  1.0,   # 6-7 layers
    "B":  0.5,   # 5 layers
    "NO": 0.0,   # <5 layers → don't trade
}

# ── Volatility multipliers (ATR ratio to 20-day avg) ──
VOLATILITY_MULTIPLIERS = {
    "quiet":   1.2,   # ATR < 50% of avg
    "normal":  1.0,   # 50-150%
    "high":    0.6,   # 150-200%
    "extreme": 0.3,   # >200%
}

# ── Streak multipliers ──
STREAK_MULTIPLIERS = {
    "win_3plus":  0.8,   # 3+ consecutive wins – overconfidence guard
    "normal":     1.0,
    "loss_2":     0.7,
    "loss_3plus": 0.5,
    "loss_5":     0.0,   # Hard stop – no more trading
}

# ── Intermarket alignment multipliers ──
INTERMARKET_MULTIPLIERS = {
    "all_aligned":    1.2,
    "mostly_aligned": 1.0,
    "mixed":          0.6,
    "contradicting":  0.0,
}

# ── Drawdown circuit breakers (monthly) ──
DRAWDOWN_5_PCT_ACTION = "half_size"       # Cut size 50%, A+ only
DRAWDOWN_10_PCT_ACTION = "pause_live"     # Demo-only for 1 week
DRAWDOWN_15_PCT_ACTION = "full_stop"      # 2-week break, restart Phase 1

# ──────────────────────────────────────────────────────────────────────
# MOVING AVERAGES
# ──────────────────────────────────────────────────────────────────────
EMA_FAST = 10
EMA_SLOW = 21
SMA_MID = 50
SMA_LONG = 200

# ──────────────────────────────────────────────────────────────────────
# VOLUME PROFILE
# ──────────────────────────────────────────────────────────────────────
VALUE_AREA_PCT = 0.70        # 70% of volume = value area
VP_NUM_BINS = 200            # Resolution for price histogram
VP_LOOKBACK_SESSIONS = 10   # Sessions to scan for naked POCs
VP_COMPOSITE_SESSIONS = 20  # Sessions for composite profile

# ──────────────────────────────────────────────────────────────────────
# CANDLE DENSITY
# ──────────────────────────────────────────────────────────────────────
DENSITY_MIN_OVERLAP = 5      # Minimum overlapping bars for "dense"
DENSITY_PRICE_STEP = None    # Auto-detect from instrument pip size

# ──────────────────────────────────────────────────────────────────────
# LIQUIDITY DETECTION
# ──────────────────────────────────────────────────────────────────────
EQH_EQL_TOLERANCE_ATR = 0.1  # Equal highs/lows tolerance as fraction of ATR
SWING_LOOKBACK = 5           # Bars each side for swing point detection
MIN_TRENDLINE_TOUCHES = 3   # Touches needed to mark a trendline

# ──────────────────────────────────────────────────────────────────────
# FVG & ORDER BLOCKS
# ──────────────────────────────────────────────────────────────────────
FVG_MIN_SIZE_ATR = 0.3       # Minimum FVG size as fraction of ATR
OB_IMPULSE_MIN_ATR = 1.5     # Minimum impulse move after OB

# ──────────────────────────────────────────────────────────────────────
# ORDER FLOW / DELTA
# ──────────────────────────────────────────────────────────────────────
DELTA_LOOKBACK_BARS = 20     # Bars for cumulative delta
DELTA_DIVERGENCE_THRESHOLD = 0.3  # Normalized divergence threshold

# ──────────────────────────────────────────────────────────────────────
# KILLZONES  (times in EST / US Eastern)
# ──────────────────────────────────────────────────────────────────────
KILLZONES = {
    "asian":        {"start": "20:00", "end": "00:00", "tz": "US/Eastern"},
    "london":       {"start": "02:00", "end": "05:00", "tz": "US/Eastern"},
    "london_ny":    {"start": "08:30", "end": "09:30", "tz": "US/Eastern"},  # Overlap
    "ny_open":      {"start": "09:30", "end": "11:00", "tz": "US/Eastern"},
    "ny_pm":        {"start": "13:30", "end": "15:00", "tz": "US/Eastern"},
    "london_close": {"start": "10:00", "end": "12:00", "tz": "US/Eastern"},
}

# ── Category-specific killzone overrides (Enhancement Plan #4) ───
# Defines which killzones matter per category and their score multiplier
KILLZONE_CATEGORY_RULES = {
    "forex": {
        # Standard forex killzones — pair-specific boosts below
        "weight_multipliers": {
            "asian": 1.0, "london": 1.0, "london_ny": 1.0,
            "ny_open": 1.0, "ny_pm": 1.0, "london_close": 1.0,
        },
    },
    "equity": {
        # US equity hours: pre-market 9:00, RTH 9:30–16:00 ET
        "weight_multipliers": {
            "ny_open": 1.2, "london_ny": 1.0, "ny_pm": 1.0,
            "london_close": 0.8,
            "asian": 0.0, "london": 0.3,  # Mostly irrelevant for US stocks
        },
    },
    "crypto": {
        # 24/7 — no killzone penalty, slight boost during US hours
        "weight_multipliers": {
            "asian": 0.8, "london": 0.9, "london_ny": 1.0,
            "ny_open": 1.0, "ny_pm": 0.9, "london_close": 0.9,
        },
        "no_penalty_outside_kz": True,  # Don't penalize outside killzones
    },
    "commodity": {
        # Gold follows forex sessions, Oil follows NYMEX (8:00–14:30 CT ≈ 9:00–15:30 ET)
        "weight_multipliers": {
            "asian": 0.5, "london": 1.0, "london_ny": 1.2,
            "ny_open": 1.0, "ny_pm": 0.8, "london_close": 0.9,
        },
    },
}

# Pair-specific killzone boosts (JPY/AUD get Asian boost)
KILLZONE_PAIR_BOOSTS = {
    "USDJPYm": {"asian": 1.5},
    "AUDUSDm": {"asian": 1.3},
    "NZDUSDm": {"asian": 1.3},
}

# No new trades after this time on Friday (EST)
FRIDAY_CUTOFF = "12:00"

# No new trades during lunch
LUNCH_NO_TRADE = {"start": "12:00", "end": "13:30", "tz": "US/Eastern"}

# News blackout window (minutes before and after high-impact event)
NEWS_BLACKOUT_MINUTES = 15

# ── Day-of-week scoring (user should update from journal analytics) ──
DAY_MULTIPLIERS = {
    "Monday":    1.0,
    "Tuesday":   1.2,   # Default best day
    "Wednesday": 1.0,
    "Thursday":  1.0,
    "Friday":    0.5,   # Default worst day
    "Saturday":  0.0,
    "Sunday":    0.0,
}

# ──────────────────────────────────────────────────────────────────────
# CONFLUENCE SCORING
# ──────────────────────────────────────────────────────────────────────
LAYER_PASS_THRESHOLD = 5.5   # Score >= this (out of 10) counts as PASS (realistic for live)
GRADE_THRESHOLDS = {
    "A+": 9,   # 9+/11 layers pass
    "A":  7,   # 7-8 layers
    "B":  5,   # 5-6 layers
}
MIN_GRADE_TO_TRADE = "B"     # Minimum grade to open a position

# ── 11-Layer Weighted Scoring (impact-based) ──
# Rationale:
#   L2  Trend      → 16%  Trend is king; trading against the trend is the #1 killer
#   L6  FVG/OB     → 14%  Entry precision at institutional levels; defines optimal entry
#   L1  Intermarket → 12%  Macro context — DXY, yields, VIX confirm or veto the trade
#   L3  VolProfile  → 12%  Institutional acceptance levels (POC/VA) define S/R
#   L5  Liquidity   → 10%  Identifies smart-money liquidity sweeps & stop hunts
#   L7  OrderFlow   → 10%  Real-time confirmation of intent (delta, absorption)
#   L8  Killzone    →  8%  Session timing — high-probability windows are binary but crucial
#   L4  CandleDens  →  6%  Supplementary confluence; confirms but rarely drives the trade
#   L9  Correlation →  5%  Validates cross-asset alignment; confirmatory filter
#   L10 Sentiment   →  4%  Soft data (COT, F&G); useful at extremes only
#   L11 Regime      →  3%  AI meta-layer; adds context but should not override core layers
LAYER_WEIGHTS = {
    "L1_Intermarket":    0.12,   # 12%  — Macro context
    "L2_Trend":          0.16,   # 16%  — Trend is king
    "L3_VolumeProfile":  0.12,   # 12%  — Institutional levels
    "L4_CandleDensity":  0.06,   #  6%  — Supplementary confluence
    "L5_Liquidity":      0.10,   # 10%  — Liquidity sweeps
    "L6_FVG_OrderBlock": 0.14,   # 14%  — Entry precision
    "L7_OrderFlow":      0.10,   # 10%  — Real-time confirmation
    "L8_Killzone":       0.08,   #  8%  — Session timing
    "L9_Correlation":    0.05,   #  5%  — Cross-asset filter
    "L10_Sentiment":     0.04,   #  4%  — Soft data
    "L11_Regime":        0.03,   #  3%  — AI meta
}

# ── Quality-Adjusted Score (QAS) thresholds ──
QAS_GRADE_THRESHOLDS = {
    "A+": 0.6,     # QAS > 0.6  (realistic with typical confidence 0.3-0.6)
    "A":  0.25,    # 0.25 <= QAS < 0.6
    "B":  0.08,    # 0.08 <= QAS < 0.25
}

# ── Size multipliers for QAS grades ──
QAS_SIZE_MULTIPLIERS = {
    "A+": 1.5,     # Full size × 1.5
    "A":  1.0,     # Normal size
    "B":  0.5,     # Half size
    "NO": 0.0,     # No trade
}

# ── Correlation penalty multipliers (from Part 9C) ──
CORRELATION_PENALTIES = {
    "very_strong": {"min_r": 0.85, "multiplier": 0.40},   # |r| > 0.85 → 60% reduction
    "strong":      {"min_r": 0.65, "multiplier": 0.60},   # |r| 0.65-0.85 → 40% reduction
    "moderate":    {"min_r": 0.40, "multiplier": 0.80},   # |r| 0.40-0.65 → 20% reduction
    "weak":        {"min_r": 0.20, "multiplier": 0.90},   # |r| 0.20-0.40 → 10% reduction
    "none":        {"min_r": 0.00, "multiplier": 1.00},   # |r| < 0.20 → no reduction
}

# ── Master correlation matrix (static references from Part 9A) ──
CORRELATION_MATRIX = {
    ("EURUSD", "GBPUSD"):  +0.85,
    ("EURUSD", "AUDUSD"):  +0.70,
    ("EURUSD", "NZDUSD"):  +0.65,
    ("EURUSD", "USDCHF"):  -0.92,
    ("EURUSD", "USDJPY"):  -0.65,
    ("GBPUSD", "NZDUSD"):  +0.72,
    ("AUDUSD", "NZDUSD"):  +0.92,
    ("AUDUSD", "XAUUSD"):  +0.65,
    ("USDCHF", "USDJPY"):  +0.60,
    ("GBPUSD", "USDCAD"):  -0.70,
    ("XAUUSD", "XAGUSD"):  +0.88,
    ("BTCUSD", "ETHUSD"):  +0.90,
    ("BTCUSD", "SPX500"):  +0.65,
    ("BTCUSD", "NAS100"):  +0.72,
    ("US30",   "NAS100"):  +0.95,
    ("US30",   "SPX500"):  +0.97,
    ("NAS100", "SPX500"):  +0.95,
    ("USOIL",  "USDCAD"):  -0.72,
    # Stock–Index correlations (Phase 6)
    ("AAPL",   "NAS100"):  +0.85,
    ("TSLA",   "NAS100"):  +0.75,
    ("NVDA",   "NAS100"):  +0.80,
    ("MSFT",   "NAS100"):  +0.85,
    ("META",   "NAS100"):  +0.78,
    ("AMZN",   "NAS100"):  +0.82,
    ("GOOGL",  "NAS100"):  +0.80,
    ("AAPL",   "SPX500"):  +0.82,
    ("MSFT",   "SPX500"):  +0.83,
    ("NVDA",   "SPX500"):  +0.75,
    ("AMZN",   "SPX500"):  +0.78,
    ("JPM",    "US30"):    +0.80,
    ("V",      "SPX500"):  +0.75,
    ("WMT",    "US30"):    +0.72,
}

# ── Lead-Lag relationships (from Part 9B) ──
LEAD_LAG_PAIRS = {
    "DXY":  {"lags": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"], "delay_min": 5},
    "US10Y": {"lags": ["XAUUSD", "USDJPY"], "delay_min": 10},
    "BTCUSD": {"lags": ["ETHUSD"], "delay_min": 120},
    "USOIL": {"lags": ["USDCAD"], "delay_min": 15},
    "EURUSD": {"lags": ["GBPUSD"], "delay_min": 3},
}

# ── Sentiment scoring weights (from Part 10B) ──
SENTIMENT_WEIGHTS = {
    "options_pcr":       0.15,
    "futures_oi":        0.15,
    "order_book":        0.10,
    "dark_pool":         0.10,
    "funding_rate":      0.10,
    "exchange_flows":    0.05,
    "broker_sentiment":  0.10,
    "etf_flows":         0.10,
    "social_sentiment":  0.05,
    "fear_greed":        0.05,
    "news_flow":         0.05,
}

# ── Veto conditions (from Part 15B) ──
HARD_VETO_LAYERS = ["L2_Trend"]  # Only trend can veto; killzone is soft weight now
MAX_PORTFOLIO_RISK_PCT = 5.0   # Hard veto if correlated risk exceeds this
MAX_CORE_LAYERS_FAILING = 2    # Hard veto if 2+ core layers (L1-L4) score -2
DAILY_LOSS_LIMIT_PCT = 3.0     # Hard veto if daily drawdown exceeds this
MAX_DAILY_LOSSES = 2           # Hard veto if 2 losses today

# Soft veto conditions
SOFT_VETO_MIN_CONFIDENCE = 3.0  # Reduce size 50% if avg confidence < 3.0
MAX_CORRELATED_TRADES = 2       # Reduce if 2+ highly correlated open trades

# ──────────────────────────────────────────────────────────────────────
# SCALING (Entry & Exit)
# ──────────────────────────────────────────────────────────────────────
ENTRY_SCALE = [0.50, 0.30, 0.20]  # % of position per entry tranche
EXIT_SCALE = {
    "TP1_pct": 0.40,   # Close 40% at TP1
    "TP2_pct": 0.30,   # Close 30% at TP2
    "TP3_pct": 0.30,   # Runner – trail remaining 30%
}

# ── Trailing stop method ──
TRAIL_METHOD = "ema"         # "ema" | "structure" | "hvn"
TRAIL_EMA_PERIOD = 10
TRAIL_EMA_TF_AFTER_TP1 = "M15"
TRAIL_EMA_TF_AFTER_TP2 = "H1"

# ── Breakeven rules ──
BE_TRIGGER_R = 1.5           # Move to BE if 1H close > 1.5R in profit

# ──────────────────────────────────────────────────────────────────────
# SESSION END MANAGEMENT
# ──────────────────────────────────────────────────────────────────────
SESSION_END_SIGNIFICANT_R = 2.0   # Keep runner if profit > this
SESSION_END_SMALL_R = 1.0         # Close 50% if profit < this

# ──────────────────────────────────────────────────────────────────────
# DATA REFRESH INTERVALS (seconds)
# ──────────────────────────────────────────────────────────────────────
REFRESH_BARS = 60            # Check new bar every 60s
REFRESH_POSITIONS = 30       # Manage positions every 30s
REFRESH_ANALYSIS = 300       # Full 11-layer analysis every 5 min during KZ
REFRESH_INTERMARKET = 900    # yfinance fetch every 15 min
REFRESH_POC_MIGRATION = 1800 # POC migration check every 30 min

# ──────────────────────────────────────────────────────────────────────
# TIMEFRAMES
# ──────────────────────────────────────────────────────────────────────
HTF_BIAS = ["D1", "H4"]     # Higher timeframes for bias
LTF_ENTRY = ["M15", "M5"]   # Lower timeframes for entry
VP_TIMEFRAME = "M1"         # Timeframe for volume profile computation

# ──────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE = "ifc_trading.log"
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
LOG_BACKUP_COUNT = 5

# ──────────────────────────────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────────────────────────────
DB_PATH = "ifc_journal.db"

# ──────────────────────────────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────────────────────────────
DASHBOARD_PORT = 8501
DASHBOARD_HOST = "localhost"

# ──────────────────────────────────────────────────────────────────────
# TELEGRAM (optional)
# ──────────────────────────────────────────────────────────────────────
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = ""      # Set in credentials.py
TELEGRAM_CHAT_ID = ""        # Set in credentials.py

# ──────────────────────────────────────────────────────────────────────
# MAGIC NUMBER (unique identifier for our EA orders in MT5)
# ──────────────────────────────────────────────────────────────────────
MAGIC_NUMBER = 20260212

# ──────────────────────────────────────────────────────────────────────
# LLM SECOND EVALUATION  (Enhancement Plan Feature A)
# ──────────────────────────────────────────────────────────────────────
LLM_BACKEND = "ollama"        # "openai" | "gemini" | "ollama"
LLM_MODEL = "brrndnn/mistral7b-finance"   # Finance-specific Ollama model
LLM_TEMPERATURE = 0.4        # Slightly creative for deep reasoning
LLM_MAX_TOKENS = 4000        # Deep analysis needs space
LLM_CACHE_TTL = 300           # Cache LLM responses for 5 minutes
LLM_TIMEOUT = 120             # API timeout in seconds (Ollama local models need more time)

# ──────────────────────────────────────────────────────────────────────
# AUTO-MONITORING  (Enhancement Plan Feature B)
# ──────────────────────────────────────────────────────────────────────
AUTO_MONITOR_INTERVAL_S = 60  # Re-evaluate every 60 seconds
AUTO_MONITOR_HISTORY_SIZE = 30  # Keep last N evaluations per symbol
AUTO_MONITOR_ALERT_GRADE_CHANGE = True  # Alert on grade flip
AUTO_MONITOR_ALERT_DIRECTION_FLIP = True  # Alert on direction change
AUTO_MONITOR_SCORE_DELTA_THRESHOLD = 1.5  # Alert if score changes by this much

# ──────────────────────────────────────────────────────────────────────
# REGIME-ADAPTIVE LAYER WEIGHTS  (Enhancement Plan #9)
# ──────────────────────────────────────────────────────────────────────
REGIME_WEIGHT_MULTIPLIERS = {
    "STRONG_TREND": {
        "L2_Trend": 1.4,        # Boost trend in strong trends
        "L5_Liquidity": 0.8,    # Liquidity sweeps less relevant
        "L6_FVG_OrderBlock": 0.9,
    },
    "VOLATILE": {
        "L8_Killzone": 1.5,     # Timing critical in volatile markets
        "L7_OrderFlow": 1.3,    # Flow confirmation essential
        "L2_Trend": 0.7,        # Trend less reliable
    },
    "RANGE": {
        "L5_Liquidity": 1.4,    # Sweeps define range extremes
        "L6_FVG_OrderBlock": 1.3,  # OBs/FVGs are key in ranges
        "L2_Trend": 0.6,        # Trend is misleading in ranges
        "L3_VolumeProfile": 1.2,  # VP defines range boundaries
    },
    "TRANSITIONAL": {
        "L1_Intermarket": 1.3,  # Macro context crucial during transitions
        "L11_Regime": 1.5,      # Regime detection more valuable
    },
}

