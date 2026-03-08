"""
IFC Trading System — Economic Calendar Scraper
Fetches high-impact news events to enforce the 15-min blackout rule.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

from config import settings
from utils.helpers import setup_logging, retry, rate_limit, now_utc

logger = setup_logging("ifc.calendar")

EST = ZoneInfo("US/Eastern")
UTC = ZoneInfo("UTC")

# Module-level cache: avoids repeated failed HTTP calls
_cal_cache: Dict[str, Any] = {"date": None, "events": [], "ts": 0.0, "failed": False}


def fetch_economic_calendar(date: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Scrape Myfxbook economic calendar for a given date.

    Returns list of dicts with keys:
        currency, event, impact ('low'|'medium'|'high'),
        time_utc (datetime), actual, forecast, previous
    """
    import time as _time
    if date is None:
        date = now_utc()

    date_str = date.strftime("%Y-%m-%d")

    # Return cached result if same date and <5 min old (or if last attempt failed <2 min ago)
    now_ts = _time.time()
    if _cal_cache["date"] == date_str:
        if _cal_cache["failed"] and (now_ts - _cal_cache["ts"]) < 120:
            return []  # Don't retry failed fetch for 2 min
        if not _cal_cache["failed"] and (now_ts - _cal_cache["ts"]) < 300:
            return _cal_cache["events"]

    url = f"https://www.myfxbook.com/forex-economic-calendar?day={date_str}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    events: List[Dict[str, Any]] = []

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Myfxbook calendar is rendered as a table
        table = soup.find("table", {"class": "table"})
        if table is None:
            # Fallback: try any table with calendar data
            tables = soup.find_all("table")
            table = tables[0] if tables else None

        if table is None:
            logger.warning("No calendar table found for %s", date_str)
            return events

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            try:
                # Extract impact from icon class or text
                impact_cell = cells[0] if len(cells) > 0 else None
                impact = "low"
                if impact_cell:
                    impact_text = impact_cell.get_text(strip=True).lower()
                    # Check for impact icons/classes
                    impact_icons = impact_cell.find_all("span")
                    for icon in impact_icons:
                        classes = icon.get("class", [])
                        class_str = " ".join(classes).lower()
                        if "high" in class_str or "red" in class_str:
                            impact = "high"
                        elif "medium" in class_str or "orange" in class_str:
                            impact = "medium"

                # Try to extract: time, currency, event name, actual, forecast, previous
                time_text = cells[0].get_text(strip=True) if len(cells) > 0 else ""
                currency = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                event_name = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                actual = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                forecast = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                previous = cells[5].get_text(strip=True) if len(cells) > 5 else ""

                # Parse time (format varies: "HH:MM" or "H:MMam/pm")
                event_time = None
                for fmt in ("%H:%M", "%I:%M%p", "%I:%M %p"):
                    try:
                        parsed = datetime.strptime(time_text, fmt)
                        event_time = date.replace(
                            hour=parsed.hour, minute=parsed.minute,
                            second=0, microsecond=0,
                        )
                        break
                    except ValueError:
                        continue

                events.append({
                    "currency": currency.upper(),
                    "event": event_name,
                    "impact": impact,
                    "time_utc": event_time,
                    "actual": actual,
                    "forecast": forecast,
                    "previous": previous,
                })
            except Exception as e:
                logger.debug("Skipping calendar row: %s", e)
                continue

        logger.info("Fetched %d calendar events for %s", len(events), date_str)
        _cal_cache.update(date=date_str, events=events, ts=now_ts, failed=False)

    except requests.RequestException as e:
        logger.error("Calendar fetch failed (myfxbook): %s — trying fallback", e)
        events = _fetch_fallback_calendar(date, date_str)
        if events:
            _cal_cache.update(date=date_str, events=events, ts=now_ts, failed=False)
        else:
            _cal_cache.update(date=date_str, events=[], ts=now_ts, failed=True)
    except Exception as e:
        logger.error("Calendar parse error: %s — trying fallback", e)
        events = _fetch_fallback_calendar(date, date_str)
        if events:
            _cal_cache.update(date=date_str, events=events, ts=now_ts, failed=False)
        else:
            _cal_cache.update(date=date_str, events=[], ts=now_ts, failed=True)

    return _cal_cache["events"]


def _fetch_fallback_calendar(date: datetime, date_str: str) -> List[Dict[str, Any]]:
    """
    Enhancement #18 — Fallback economic calendar via ForexFactory RSS-like scrape.
    Returns high-impact events only (simpler/faster than primary).
    """
    events: List[Dict[str, Any]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        # Try ForexFactory
        url = f"https://www.forexfactory.com/calendar?day={date_str}"
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.find_all("tr", {"class": "calendar__row"})
        for row in rows:
            try:
                impact_td = row.find("td", {"class": "calendar__impact"})
                if not impact_td:
                    continue
                impact_span = impact_td.find("span")
                if not impact_span:
                    continue

                impact_classes = " ".join(impact_span.get("class", [])).lower()
                if "high" not in impact_classes and "red" not in impact_classes:
                    continue  # Only high-impact as fallback

                currency_td = row.find("td", {"class": "calendar__currency"})
                event_td = row.find("td", {"class": "calendar__event"})
                time_td = row.find("td", {"class": "calendar__time"})

                currency = currency_td.get_text(strip=True) if currency_td else ""
                event_name = event_td.get_text(strip=True) if event_td else ""
                time_text = time_td.get_text(strip=True) if time_td else ""

                event_time = None
                for fmt in ("%I:%M%p", "%I:%M %p", "%H:%M"):
                    try:
                        parsed = datetime.strptime(time_text.replace(" ", ""), fmt)
                        event_time = date.replace(
                            hour=parsed.hour, minute=parsed.minute,
                            second=0, microsecond=0,
                        )
                        break
                    except ValueError:
                        continue

                events.append({
                    "currency": currency.upper(),
                    "event": event_name,
                    "impact": "high",
                    "time_utc": event_time,
                    "actual": "",
                    "forecast": "",
                    "previous": "",
                })
            except Exception:
                continue

        if events:
            logger.info("Fallback calendar: %d high-impact events for %s", len(events), date_str)

    except Exception as e:
        logger.error("Fallback calendar also failed: %s", e)

    return events


def get_high_impact_events(
    currency: str,
    date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return only HIGH impact events for a specific currency."""
    all_events = fetch_economic_calendar(date)
    return [
        evt for evt in all_events
        if evt["impact"] == "high"
        and currency.upper() in evt["currency"]
    ]


def is_news_blackout(symbol: str, current_time: Optional[datetime] = None) -> bool:
    """
    Check if we're within the blackout window of a high-impact event.
    Returns True if no new trades should be opened.

    symbol: MT5 symbol like 'EURUSD' - checks both currencies
    """
    if current_time is None:
        current_time = now_utc()

    # Extract currencies from symbol (EURUSD → EUR, USD)
    currencies = []
    if len(symbol) >= 6:
        currencies = [symbol[:3].upper(), symbol[3:6].upper()]
    else:
        currencies = [symbol.upper()]

    blackout_mins = settings.NEWS_BLACKOUT_MINUTES
    blackout_delta = timedelta(minutes=blackout_mins)

    try:
        events = fetch_economic_calendar(current_time)
        for evt in events:
            if evt["impact"] != "high":
                continue
            if not any(c in evt["currency"] for c in currencies):
                continue
            if evt["time_utc"] is None:
                continue
            # Check if we're within the window
            if (evt["time_utc"] - blackout_delta) <= current_time <= (evt["time_utc"] + blackout_delta):
                logger.info(
                    "NEWS BLACKOUT: %s event '%s' at %s",
                    evt["currency"], evt["event"], evt["time_utc"],
                )
                return True
    except Exception as e:
        logger.error("News blackout check failed: %s — defaulting to no blackout", e)

    return False
