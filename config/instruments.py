"""
IFC Trading System — Instrument Watchlist
Define every symbol the system should monitor together with
broker-specific naming, pip size, and intermarket relationships.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Instrument:
    """Single tradeable instrument definition."""
    mt5_symbol: str              # Exact symbol name in your MT5 broker
    display_name: str            # Human-friendly name
    category: str                # "forex" | "index" | "crypto" | "commodity" | "stock"
    pip_size: float              # Size of one pip in price units
    pip_value_per_lot: float     # $ value of 1 pip per 1.0 lot
    typical_spread: float        # Normal spread in pips
    atr_reference: float         # Typical 14-period daily ATR in pips (approximate)
    yfinance_ticker: Optional[str] = None  # For supplementary data (futures volume etc.)
    intermarket_correlations: dict = field(default_factory=dict)
    active: bool = True          # Set False to skip without deleting
    # Enhancement Plan #4: Category-specific killzone preference
    killzone_preference: str = "forex"  # "forex" | "equity" | "crypto" | "commodity"
    # Enhancement Plan #11: COT instrument name (for L10 sentiment)
    cot_name: Optional[str] = None      # CFTC COT report name, e.g. "EURO FX"


# ──────────────────────────────────────────────────────────────────────
# FOREX MAJORS
# ──────────────────────────────────────────────────────────────────────
EURUSD = Instrument(
    mt5_symbol="EURUSDm",
    display_name="EUR/USD",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=10.0,
    typical_spread=1.0,
    atr_reference=60,
    yfinance_ticker="6E=F",
    intermarket_correlations={"DXY": -0.95, "US10Y": -0.4},
    killzone_preference="forex",
    cot_name="EURO FX",
)

GBPUSD = Instrument(
    mt5_symbol="GBPUSDm",
    display_name="GBP/USD",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=10.0,
    typical_spread=1.2,
    atr_reference=80,
    yfinance_ticker="6B=F",
    intermarket_correlations={"DXY": -0.85},
    killzone_preference="forex",
    cot_name="BRITISH POUND",
)

USDJPY = Instrument(
    mt5_symbol="USDJPYm",
    display_name="USD/JPY",
    category="forex",
    pip_size=0.01,
    pip_value_per_lot=6.7,   # Approximate – varies with JPY rate
    typical_spread=1.0,
    atr_reference=80,
    yfinance_ticker="6J=F",
    intermarket_correlations={"DXY": 0.80, "US10Y": 0.65},
    killzone_preference="forex",
    cot_name="JAPANESE YEN",
)

AUDUSD = Instrument(
    mt5_symbol="AUDUSDm",
    display_name="AUD/USD",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=10.0,
    typical_spread=1.2,
    atr_reference=55,
    yfinance_ticker="6A=F",
    intermarket_correlations={"DXY": -0.75, "SPX": 0.50},
    killzone_preference="forex",
    cot_name="AUSTRALIAN DOLLAR",
)

USDCAD = Instrument(
    mt5_symbol="USDCADm",
    display_name="USD/CAD",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=7.5,
    typical_spread=1.5,
    atr_reference=65,
    yfinance_ticker="6C=F",
    intermarket_correlations={"DXY": 0.80, "OIL": -0.55},
    killzone_preference="forex",
    cot_name="CANADIAN DOLLAR",
)

NZDUSD = Instrument(
    mt5_symbol="NZDUSDm",
    display_name="NZD/USD",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=10.0,
    typical_spread=1.5,
    atr_reference=50,
    intermarket_correlations={"DXY": -0.70},
    killzone_preference="forex",
    cot_name="NEW ZEALAND DOLLAR",
)

USDCHF = Instrument(
    mt5_symbol="USDCHFm",
    display_name="USD/CHF",
    category="forex",
    pip_size=0.0001,
    pip_value_per_lot=10.5,
    typical_spread=1.3,
    atr_reference=55,
    intermarket_correlations={"DXY": 0.90},
    killzone_preference="forex",
    cot_name="SWISS FRANC",
)

# ──────────────────────────────────────────────────────────────────────
# INDICES (CFDs — symbol names vary by broker, adjust mt5_symbol)
# ──────────────────────────────────────────────────────────────────────
US30 = Instrument(
    mt5_symbol="US30m",        # EXNESS naming
    display_name="Dow Jones 30",
    category="index",
    pip_size=1.0,
    pip_value_per_lot=1.0,
    typical_spread=2.0,
    atr_reference=350,
    yfinance_ticker="YM=F",
    intermarket_correlations={"VIX": -0.80, "SPX": 0.95},
    killzone_preference="equity",
    cot_name="DOW JONES",
)

NAS100 = Instrument(
    mt5_symbol="USTECm",       # EXNESS naming
    display_name="Nasdaq 100",
    category="index",
    pip_size=0.1,
    pip_value_per_lot=1.0,
    typical_spread=1.5,
    atr_reference=250,
    yfinance_ticker="NQ=F",
    intermarket_correlations={"VIX": -0.80, "US10Y": -0.50},
    killzone_preference="equity",
    cot_name="NASDAQ",
)

SPX500 = Instrument(
    mt5_symbol="US500m",       # EXNESS naming
    display_name="S&P 500",
    category="index",
    pip_size=0.1,
    pip_value_per_lot=1.0,
    typical_spread=0.5,
    atr_reference=60,
    yfinance_ticker="ES=F",
    intermarket_correlations={"VIX": -0.85},
    killzone_preference="equity",
    cot_name="E-MINI S&P 500",
)

# ──────────────────────────────────────────────────────────────────────
# CRYPTO (CFDs — symbol names vary by broker)
# ──────────────────────────────────────────────────────────────────────
BTCUSD = Instrument(
    mt5_symbol="BTCUSDm",
    display_name="Bitcoin / USD",
    category="crypto",
    pip_size=1.0,
    pip_value_per_lot=1.0,
    typical_spread=30,
    atr_reference=2500,
    yfinance_ticker="BTC-USD",
    intermarket_correlations={"SPX": 0.55, "DXY": -0.40},
    killzone_preference="crypto",
    cot_name="BITCOIN",
)

ETHUSD = Instrument(
    mt5_symbol="ETHUSDm",
    display_name="Ethereum / USD",
    category="crypto",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=2.0,
    atr_reference=120,
    yfinance_ticker="ETH-USD",
    intermarket_correlations={"BTC": 0.85, "SPX": 0.45},
    killzone_preference="crypto",
)


# ──────────────────────────────────────────────────────────────────────
# COMMODITIES
# ──────────────────────────────────────────────────────────────────────
XAUUSD = Instrument(
    mt5_symbol="XAUUSDm",
    display_name="Gold / USD",
    category="commodity",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=20,
    atr_reference=30,
    yfinance_ticker="GC=F",
    intermarket_correlations={"DXY": -0.60, "US10Y": -0.35, "VIX": 0.30},
    killzone_preference="commodity",
    cot_name="GOLD",
)

XAGUSD = Instrument(
    mt5_symbol="XAGUSDm",
    display_name="Silver / USD",
    category="commodity",
    pip_size=0.001,
    pip_value_per_lot=5.0,
    typical_spread=2.0,
    atr_reference=50,
    yfinance_ticker="SI=F",
    intermarket_correlations={"GOLD": 0.85, "DXY": -0.50},
    killzone_preference="commodity",
    cot_name="SILVER",
)

USOIL = Instrument(
    mt5_symbol="USOILm",
    display_name="US Oil (WTI)",
    category="commodity",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=3.0,
    atr_reference=200,
    yfinance_ticker="CL=F",
    intermarket_correlations={"DXY": -0.30, "SPX": 0.35},
    killzone_preference="commodity",
    cot_name="CRUDE OIL",
)


# ──────────────────────────────────────────────────────────────────────
# US STOCKS (CFDs — EXNESS naming with m suffix)
# ──────────────────────────────────────────────────────────────────────
AAPL = Instrument(
    mt5_symbol="AAPLm",
    display_name="Apple",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.15,
    atr_reference=4.0,
    yfinance_ticker="AAPL",
    intermarket_correlations={"SPX": 0.85, "VIX": -0.70},
    killzone_preference="equity",
)

TSLA = Instrument(
    mt5_symbol="TSLAm",
    display_name="Tesla",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.30,
    atr_reference=12.0,
    yfinance_ticker="TSLA",
    intermarket_correlations={"SPX": 0.65, "VIX": -0.55},
    killzone_preference="equity",
)

NVDA = Instrument(
    mt5_symbol="NVDAm",
    display_name="Nvidia",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.20,
    atr_reference=8.0,
    yfinance_ticker="NVDA",
    intermarket_correlations={"SPX": 0.75, "VIX": -0.65},
    killzone_preference="equity",
)

AMZN = Instrument(
    mt5_symbol="AMZNm",
    display_name="Amazon",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.20,
    atr_reference=5.0,
    yfinance_ticker="AMZN",
    intermarket_correlations={"SPX": 0.80, "VIX": -0.65},
    killzone_preference="equity",
)

MSFT = Instrument(
    mt5_symbol="MSFTm",
    display_name="Microsoft",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.15,
    atr_reference=5.0,
    yfinance_ticker="MSFT",
    intermarket_correlations={"SPX": 0.85, "VIX": -0.70},
    killzone_preference="equity",
)

META = Instrument(
    mt5_symbol="METAm",
    display_name="Meta",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.30,
    atr_reference=8.0,
    yfinance_ticker="META",
    intermarket_correlations={"SPX": 0.75, "VIX": -0.60},
    killzone_preference="equity",
)

GOOGL = Instrument(
    mt5_symbol="GOOGLm",
    display_name="Google",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.15,
    atr_reference=4.0,
    yfinance_ticker="GOOGL",
    intermarket_correlations={"SPX": 0.80, "VIX": -0.65},
    killzone_preference="equity",
)

NFLX = Instrument(
    mt5_symbol="NFLXm",
    display_name="Netflix",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.50,
    atr_reference=10.0,
    yfinance_ticker="NFLX",
    intermarket_correlations={"SPX": 0.65, "VIX": -0.50},
    killzone_preference="equity",
)

AMD = Instrument(
    mt5_symbol="AMDm",
    display_name="AMD",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.15,
    atr_reference=5.0,
    yfinance_ticker="AMD",
    intermarket_correlations={"SPX": 0.70, "VIX": -0.55},
    killzone_preference="equity",
)

JPM = Instrument(
    mt5_symbol="JPMm",
    display_name="JPMorgan",
    category="stock",
    pip_size=0.01,
    pip_value_per_lot=1.0,
    typical_spread=0.15,
    atr_reference=3.5,
    yfinance_ticker="JPM",
    intermarket_correlations={"SPX": 0.80, "US10Y": 0.40},
    killzone_preference="equity",
)


# ──────────────────────────────────────────────────────────────────────
# MASTER WATCHLIST — toggle .active to include/exclude
# ──────────────────────────────────────────────────────────────────────
WATCHLIST: list[Instrument] = [
    # Forex
    EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD, USDCHF,
    # Indices
    US30, NAS100, SPX500,
    # Commodities
    XAUUSD, XAGUSD, USOIL,
    # Crypto
    BTCUSD, ETHUSD,
    # Stocks
    AAPL, TSLA, NVDA, AMZN, MSFT, META, GOOGL, NFLX, AMD, JPM,
]


# ── Dict keyed by display-friendly name (used throughout the system) ──
INSTRUMENTS = {inst.mt5_symbol: inst for inst in WATCHLIST if inst.active}


def get_active_instruments() -> list[Instrument]:
    """Return only instruments flagged as active."""
    return [i for i in WATCHLIST if i.active]


def get_instrument_by_symbol(mt5_symbol: str) -> Optional[Instrument]:
    """Look up an instrument by its MT5 symbol name."""
    for inst in WATCHLIST:
        if inst.mt5_symbol == mt5_symbol:
            return inst
    return None


# ──────────────────────────────────────────────────────────────────────
# INTERMARKET REFERENCE TICKERS  (fetched via yfinance)
# ──────────────────────────────────────────────────────────────────────
INTERMARKET_TICKERS = {
    "DXY":   "DX-Y.NYB",
    "US10Y": "^TNX",
    "VIX":   "^VIX",
    "SPX":   "^GSPC",
    "GOLD":  "GC=F",
    "OIL":   "CL=F",
    "BTC":   "BTC-USD",
}
