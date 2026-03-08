"""
IFC Trading System — Utility Helpers: Time, Logging, Decorators
"""

import time
import functools
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings


# ═════════════════════════════════════════════════════════════════════
# TIME UTILITIES
# ═════════════════════════════════════════════════════════════════════

EST = ZoneInfo("US/Eastern")
UTC = ZoneInfo("UTC")


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def now_est() -> datetime:
    return datetime.now(tz=EST)


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


def to_est(dt: datetime) -> datetime:
    return dt.astimezone(EST)


def parse_time_est(time_str: str, base_date: Optional[datetime] = None) -> datetime:
    """Parse 'HH:MM' string into a datetime in EST on *base_date* (default today)."""
    if base_date is None:
        base_date = now_est()
    h, m = map(int, time_str.split(":"))
    return base_date.replace(hour=h, minute=m, second=0, microsecond=0)


def is_within_window(start_str: str, end_str: str) -> bool:
    """Check if current EST time is between two 'HH:MM' strings."""
    current = now_est()
    start = parse_time_est(start_str, current)
    end = parse_time_est(end_str, current)
    # Handle overnight windows (e.g. 20:00 – 00:00)
    if end <= start:
        return current >= start or current <= end
    return start <= current <= end


def current_killzone() -> Optional[str]:
    """Return the name of the killzone we're currently in, or None."""
    for name, kz in settings.KILLZONES.items():
        if is_within_window(kz["start"], kz["end"]):
            return name
    return None


def is_lunch_break() -> bool:
    return is_within_window(
        settings.LUNCH_NO_TRADE["start"],
        settings.LUNCH_NO_TRADE["end"],
    )


def is_friday_cutoff() -> bool:
    current = now_est()
    if current.strftime("%A") != "Friday":
        return False
    cutoff = parse_time_est(settings.FRIDAY_CUTOFF, current)
    return current >= cutoff


def day_of_week_multiplier() -> float:
    day = now_est().strftime("%A")
    return settings.DAY_MULTIPLIERS.get(day, 1.0)


def get_session_range_times() -> dict:
    """Return Asian session start/end as UTC datetimes for today."""
    est_now = now_est()
    asian_start = parse_time_est(
        settings.KILLZONES["asian"]["start"], est_now
    )
    asian_end = parse_time_est(
        settings.KILLZONES["asian"]["end"], est_now
    )
    if asian_end <= asian_start:
        asian_end += timedelta(days=1)
    return {
        "asian_start": to_utc(asian_start),
        "asian_end": to_utc(asian_end),
    }


# MT5 timeframe string → MetaTrader5 constant name mapping
TF_MAP = {
    "M1":  "TIMEFRAME_M1",
    "M5":  "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1":  "TIMEFRAME_H1",
    "H4":  "TIMEFRAME_H4",
    "D1":  "TIMEFRAME_D1",
    "W1":  "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}


# ═════════════════════════════════════════════════════════════════════
# LOGGING
# ═════════════════════════════════════════════════════════════════════

def setup_logging(name: str = "ifc") -> logging.Logger:
    """Configure and return a logger with file + console handlers."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — force UTF-8 on Windows to support emoji
    import sys, io
    if sys.platform == "win32":
        stream = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    else:
        stream = sys.stderr
    ch = logging.StreamHandler(stream)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Rotating file handler — also UTF-8
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ═════════════════════════════════════════════════════════════════════
# DECORATORS
# ═════════════════════════════════════════════════════════════════════

def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry a function on exception with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _delay = delay
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    logger = logging.getLogger("ifc.retry")
                    logger.warning(
                        "%s attempt %d/%d failed: %s",
                        func.__name__, attempt, max_retries, exc,
                    )
                    if attempt < max_retries:
                        time.sleep(_delay)
                        _delay *= backoff
            raise last_exc  # type: ignore
        return wrapper
    return decorator


def rate_limit(min_interval: float):
    """Ensure at least *min_interval* seconds between calls."""
    def decorator(func):
        last_call = [0.0]

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_call[0]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            result = func(*args, **kwargs)
            last_call[0] = time.time()
            return result
        return wrapper
    return decorator


def timed(func):
    """Log execution time of a function."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        logger = logging.getLogger("ifc.timing")
        logger.debug("%s took %.3fs", func.__name__, elapsed)
        return result
    return wrapper
