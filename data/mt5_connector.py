"""
IFC Trading System — MetaTrader 5 Data Connector
Wraps the MetaTrader5 package for OHLCV, ticks, account, and symbol data.
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from config import credentials, settings
from utils.helpers import setup_logging, retry

logger = setup_logging("ifc.mt5")

# MT5 timeframe constant mapping
_TF = {
    "M1":  mt5.TIMEFRAME_M1,
    "M2":  mt5.TIMEFRAME_M2,
    "M3":  mt5.TIMEFRAME_M3,
    "M5":  mt5.TIMEFRAME_M5,
    "M10": mt5.TIMEFRAME_M10,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H2":  mt5.TIMEFRAME_H2,
    "H4":  mt5.TIMEFRAME_H4,
    "H6":  mt5.TIMEFRAME_H6,
    "H8":  mt5.TIMEFRAME_H8,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


class MT5Connector:
    """Manages the MT5 terminal connection and all data retrieval."""

    _symbol_cache: Dict[str, str] = {}   # base → resolved name

    def __init__(self):
        self._connected = False

    # ── Symbol Resolution ────────────────────────────────────────────
    def resolve_symbol(self, symbol: str) -> str:
        """
        Return the broker's actual symbol name.
        Tries exact match first, then common suffixes (m, c, .m, .c).
        Falls back to a partial-match scan of all available symbols.
        Results are cached for the session.
        """
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        self.ensure_connected()

        # 1) Exact match
        info = mt5.symbol_info(symbol)
        if info is not None:
            self._symbol_cache[symbol] = symbol
            return symbol

        # 2) Try common suffixes
        for suffix in ("m", "c", ".m", ".c"):
            candidate = symbol + suffix
            info = mt5.symbol_info(candidate)
            if info is not None:
                logger.info("Resolved symbol %s → %s", symbol, candidate)
                self._symbol_cache[symbol] = candidate
                return candidate

        # 3) Fuzzy: strip any existing suffix from symbol and search
        base = symbol.rstrip("mMcC")
        all_syms = mt5.symbols_get()
        if all_syms:
            for s in all_syms:
                if s.name.upper().startswith(base.upper()) and len(s.name) <= len(base) + 2:
                    logger.info("Resolved symbol %s → %s (fuzzy)", symbol, s.name)
                    self._symbol_cache[symbol] = s.name
                    return s.name

        # Give up — return original (will produce a warning downstream)
        logger.warning("Could not resolve symbol %s — using as-is", symbol)
        self._symbol_cache[symbol] = symbol
        return symbol

    # ── Connection ───────────────────────────────────────────────────
    @retry(max_retries=3, delay=2.0)
    def connect(self) -> bool:
        """Initialize MT5 terminal and log in."""
        if self._connected:
            return True

        init_kwargs: Dict[str, Any] = {}
        if credentials.MT5_PATH:
            init_kwargs["path"] = credentials.MT5_PATH
        if credentials.MT5_TIMEOUT:
            init_kwargs["timeout"] = credentials.MT5_TIMEOUT

        if not mt5.initialize(**init_kwargs):
            err = mt5.last_error()
            logger.error("MT5 initialize failed: %s", err)
            raise ConnectionError(f"MT5 init failed: {err}")

        if credentials.MT5_LOGIN:
            authorized = mt5.login(
                login=credentials.MT5_LOGIN,
                password=credentials.MT5_PASSWORD,
                server=credentials.MT5_SERVER,
            )
            if not authorized:
                err = mt5.last_error()
                logger.error("MT5 login failed: %s", err)
                mt5.shutdown()
                raise ConnectionError(f"MT5 login failed: {err}")

        self._connected = True
        info = mt5.terminal_info()
        logger.info(
            "MT5 connected: %s | Build %s | Account %s",
            info.name if info else "?",
            info.build if info else "?",
            mt5.account_info().login if mt5.account_info() else "?",
        )
        return True

    def disconnect(self):
        """Shutdown the MT5 connection."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 disconnected")

    def ensure_connected(self):
        """Reconnect if the connection dropped."""
        if not self._connected:
            self.connect()
        # Quick health check
        if mt5.terminal_info() is None:
            self._connected = False
            self.connect()

    # ── Account ──────────────────────────────────────────────────────
    def get_account_info(self) -> Dict[str, Any]:
        """Return key account metrics."""
        self.ensure_connected()
        info = mt5.account_info()
        if info is None:
            logger.error("Failed to get account info: %s", mt5.last_error())
            return {}
        return {
            "login": info.login,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "currency": info.currency,
            "leverage": info.leverage,
        }

    # ── Symbol info ──────────────────────────────────────────────────
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return broker-specific symbol properties."""
        self.ensure_connected()
        mt5.symbol_select(symbol, True)  # Ensure symbol is visible
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning("Symbol info unavailable for %s", symbol)
            return None
        return {
            "name": info.name,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "trade_tick_size": info.trade_tick_size,
            "trade_tick_value": info.trade_tick_value,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "bid": info.bid,
            "ask": info.ask,
        }

    # ── OHLCV Data ───────────────────────────────────────────────────
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 500,
        start_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV bars as a pandas DataFrame.

        Parameters
        ----------
        symbol : MT5 symbol name
        timeframe : string key like 'M1', 'M15', 'H4', 'D1'
        bars : number of bars to fetch (from most recent)
        start_time : if provided, fetch *bars* starting from this UTC datetime
        """
        self.ensure_connected()
        tf = _TF.get(timeframe)
        if tf is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        mt5.symbol_select(symbol, True)

        if start_time is not None:
            rates = mt5.copy_rates_from(symbol, tf, start_time, bars)
        else:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)

        if rates is None or len(rates) == 0:
            logger.warning(
                "No bars returned for %s %s (%d bars): %s",
                symbol, timeframe, bars, mt5.last_error(),
            )
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(
            columns={
                "tick_volume": "tick_volume",
                "real_volume": "real_volume",
            },
            inplace=True,
        )
        return df

    def get_ohlcv_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Fetch bars within a specific UTC datetime range."""
        self.ensure_connected()
        tf = _TF.get(timeframe)
        if tf is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_range(symbol, tf, start, end)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        return df

    # ── Tick Data ────────────────────────────────────────────────────
    def get_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        flags: int = mt5.COPY_TICKS_ALL,
    ) -> pd.DataFrame:
        """
        Fetch tick data between UTC datetimes.
        flags: mt5.COPY_TICKS_ALL | COPY_TICKS_INFO | COPY_TICKS_TRADE
        """
        self.ensure_connected()
        mt5.symbol_select(symbol, True)
        ticks = mt5.copy_ticks_range(symbol, start, end, flags)
        if ticks is None or len(ticks) == 0:
            logger.warning("No ticks for %s: %s", symbol, mt5.last_error())
            return pd.DataFrame()
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        return df

    def get_ticks_from(
        self,
        symbol: str,
        start: datetime,
        count: int = 100_000,
        flags: int = mt5.COPY_TICKS_ALL,
    ) -> pd.DataFrame:
        """Fetch *count* ticks starting from a UTC datetime."""
        self.ensure_connected()
        mt5.symbol_select(symbol, True)
        ticks = mt5.copy_ticks_from(symbol, start, count, flags)
        if ticks is None or len(ticks) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        return df

    # ── Market Depth ─────────────────────────────────────────────────
    def subscribe_market_depth(self, symbol: str) -> bool:
        self.ensure_connected()
        return mt5.market_book_add(symbol)

    def get_market_depth(self, symbol: str) -> List[Dict]:
        self.ensure_connected()
        book = mt5.market_book_get(symbol)
        if book is None:
            return []
        return [
            {"type": entry.type, "price": entry.price, "volume": entry.volume}
            for entry in book
        ]

    def unsubscribe_market_depth(self, symbol: str) -> bool:
        return mt5.market_book_release(symbol)

    # ── Positions ────────────────────────────────────────────────────
    def get_open_positions(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return open positions, optionally filtered by symbol."""
        self.ensure_connected()
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        if positions is None:
            return []
        result = []
        for p in positions:
            result.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "magic": p.magic,
                "comment": p.comment,
                "time": datetime.fromtimestamp(p.time, tz=timezone.utc),
            })
        return result

    # ── Order History ────────────────────────────────────────────────
    def get_history_deals(
        self,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Fetch deal history between UTC datetimes."""
        self.ensure_connected()
        if end is None:
            end = datetime.now(tz=timezone.utc)
        deals = mt5.history_deals_get(start, end)
        if deals is None or len(deals) == 0:
            return pd.DataFrame()
        df = pd.DataFrame([d._asdict() for d in deals])
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    # ── Current Tick ─────────────────────────────────────────────────
    def get_current_tick(self, symbol: str) -> Optional[Dict]:
        """Get latest bid/ask for a symbol."""
        self.ensure_connected()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
        }
