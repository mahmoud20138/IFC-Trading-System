"""
IFC Trading System — Intermarket Data Fetcher
Pulls DXY, US10Y, VIX, SPX, Gold, Oil, BTC via yfinance with caching.
"""

import time
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any

from config.instruments import INTERMARKET_TICKERS
from utils.helpers import setup_logging, retry, rate_limit

logger = setup_logging("ifc.intermarket")

# Module-level shared cache so Streamlit reruns don't re-download
_SHARED_CACHE: Dict[str, Dict[str, Any]] = {}
_SNAPSHOT_CACHE: Dict[str, Any] = {}  # {"ts": float, "data": dict}
_SNAPSHOT_TTL = 300  # 5 min


class IntermarketData:
    """
    Fetch and cache intermarket reference data.
    All data is sourced from Yahoo Finance.
    Uses a module-level shared cache so data persists across Streamlit reruns.
    """

    def __init__(self, cache_ttl: int = 300):
        self._cache = _SHARED_CACHE         # shared across instances
        self._cache_ttl = cache_ttl

    def _is_cached(self, key: str) -> bool:
        if key not in self._cache:
            return False
        return (time.time() - self._cache[key]["ts"]) < self._cache_ttl

    def _set_cache(self, key: str, data: Any):
        self._cache[key] = {"ts": time.time(), "data": data}

    def _get_cache(self, key: str) -> Any:
        return self._cache[key]["data"]

    # ── Generic fetcher ──────────────────────────────────────────────
    @retry(max_retries=2, delay=1.0)
    @rate_limit(min_interval=1.0)
    def _fetch_yf(
        self,
        ticker: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Download OHLCV from yfinance with retry + rate limit."""
        cache_key = f"{ticker}_{period}_{interval}"
        if self._is_cached(cache_key):
            return self._get_cache(cache_key)

        logger.debug("Fetching yfinance: %s period=%s interval=%s", ticker, period, interval)
        try:
            data = yf.download(
                ticker, period=period, interval=interval,
                progress=False, auto_adjust=True,
            )
        except Exception as e:
            logger.warning("yfinance download error for %s: %s", ticker, e)
            return pd.DataFrame()

        if data is None or data.empty:
            logger.warning("Empty yfinance response for %s", ticker)
            return pd.DataFrame()

        # Flatten multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        self._set_cache(cache_key, data)
        return data

    # ── Specific fetchers ────────────────────────────────────────────
    def fetch_dxy(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["DXY"], period, interval)

    def fetch_us10y(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["US10Y"], period, interval)

    def fetch_vix(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        # Try primary ticker, fall back to alternatives if it fails
        for ticker in [INTERMARKET_TICKERS["VIX"], "VIXY", "VXX"]:
            df = self._fetch_yf(ticker, period, interval)
            if not df.empty:
                return df
        logger.warning("All VIX tickers failed")
        return pd.DataFrame()

    def fetch_spx(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["SPX"], period, interval)

    def fetch_gold(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["GOLD"], period, interval)

    def fetch_oil(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["OIL"], period, interval)

    def fetch_btc(self, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        return self._fetch_yf(INTERMARKET_TICKERS["BTC"], period, interval)

    # ── Trend analysis helpers ───────────────────────────────────────
    @staticmethod
    def compute_trend(df: pd.DataFrame, lookback: int = 20) -> Dict[str, Any]:
        """
        Quick trend determination from OHLCV DataFrame.
        Returns direction, strength (0-1), current level, change %.
        """
        if df.empty or len(df) < lookback:
            return {"direction": "UNKNOWN", "strength": 0, "level": 0, "change_pct": 0}

        # Handle both "Close" and "close" column names
        close_col = "Close" if "Close" in df.columns else "close"
        if close_col not in df.columns:
            return {"direction": "UNKNOWN", "strength": 0, "level": 0, "change_pct": 0}

        close = df[close_col].values
        current = float(close[-1])
        prev = float(close[-lookback])
        change_pct = ((current - prev) / prev) * 100 if prev != 0 else 0

        # Simple linear regression slope for strength
        x = range(len(close[-lookback:]))
        slope = pd.Series(close[-lookback:]).corr(pd.Series(x))
        slope = 0 if pd.isna(slope) else slope

        if change_pct > 1:
            direction = "RISING"
        elif change_pct < -1:
            direction = "FALLING"
        else:
            direction = "FLAT"

        return {
            "direction": direction,
            "strength": abs(slope),
            "level": current,
            "change_pct": round(change_pct, 2),
        }

    # ── Aggregate snapshot ───────────────────────────────────────────
    def get_full_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch all intermarket instruments and return trend analysis.
        Uses module-level snapshot cache to avoid redundant yfinance calls.
        """
        global _SNAPSHOT_CACHE
        if _SNAPSHOT_CACHE and (time.time() - _SNAPSHOT_CACHE.get("ts", 0)) < _SNAPSHOT_TTL:
            return _SNAPSHOT_CACHE["data"]

        snapshot = {}
        fetchers = {
            "DXY": self.fetch_dxy,
            "US10Y": self.fetch_us10y,
            "VIX": self.fetch_vix,
            "SPX": self.fetch_spx,
            "GOLD": self.fetch_gold,
            "OIL": self.fetch_oil,
            "BTC": self.fetch_btc,
        }
        for name, fetcher in fetchers.items():
            try:
                df = fetcher()
                trend = self.compute_trend(df)
                # Add VIX-specific fields
                if name == "VIX" and not df.empty:
                    close_col = "Close" if "Close" in df.columns else "close"
                    vix_level = float(df[close_col].iloc[-1]) if close_col in df.columns else 20.0
                    trend["regime"] = (
                        "calm" if vix_level < 15
                        else "normal" if vix_level < 25
                        else "fear" if vix_level < 35
                        else "extreme_fear"
                    )
                snapshot[name] = trend
            except Exception as e:
                logger.error("Failed to fetch %s: %s", name, e)
                snapshot[name] = {"direction": "ERROR", "strength": 0, "level": 0, "change_pct": 0}

        _SNAPSHOT_CACHE.update({"ts": time.time(), "data": snapshot})
        return snapshot

    def determine_risk_regime(self, snapshot: Optional[Dict] = None) -> str:
        """
        Classify current macro environment as RISK_ON / RISK_OFF / MIXED.
        """
        if snapshot is None:
            snapshot = self.get_full_snapshot()

        risk_on_signals = 0
        risk_off_signals = 0

        # VIX: low = risk on, high = risk off
        vix = snapshot.get("VIX", {})
        if vix.get("regime") in ("calm", "normal"):
            risk_on_signals += 1
        elif vix.get("regime") in ("fear", "extreme_fear"):
            risk_off_signals += 1

        # SPX: rising = risk on
        spx = snapshot.get("SPX", {})
        if spx.get("direction") == "RISING":
            risk_on_signals += 1
        elif spx.get("direction") == "FALLING":
            risk_off_signals += 1

        # DXY: falling = risk on (weaker dollar → EM/risk flows)
        dxy = snapshot.get("DXY", {})
        if dxy.get("direction") == "FALLING":
            risk_on_signals += 1
        elif dxy.get("direction") == "RISING":
            risk_off_signals += 1

        # Gold: rising = risk off (flight to safety)
        gold = snapshot.get("GOLD", {})
        if gold.get("direction") == "RISING":
            risk_off_signals += 1
        elif gold.get("direction") == "FALLING":
            risk_on_signals += 1

        if risk_on_signals >= 3:
            return "RISK_ON"
        elif risk_off_signals >= 3:
            return "RISK_OFF"
        else:
            return "MIXED"
