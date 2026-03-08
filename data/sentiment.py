"""
IFC Trading System — Sentiment Data (COT, Fear & Greed, Retail Sentiment)
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Any, Optional

from utils.helpers import setup_logging, retry, rate_limit

logger = setup_logging("ifc.sentiment")


class SentimentData:
    """Fetches COT reports, CNN Fear & Greed, and Myfxbook retail sentiment."""

    # ── COT Report ───────────────────────────────────────────────────
    @staticmethod
    @retry(max_retries=1, delay=0.5)
    def fetch_cot_data(instrument_name: str = "EURO FX") -> Dict[str, Any]:
        """
        Fetch latest Commitments of Traders data via cot_reports library.

        Parameters
        ----------
        instrument_name : CFTC instrument name, e.g.
            'EURO FX', 'JAPANESE YEN', 'BRITISH POUND', 'GOLD', 'E-MINI S&P 500'

        Returns
        -------
        dict with commercial/non-commercial positions, changes, extreme flag
        """
        try:
            import cot_reports as cot
            # Get current year data
            df = cot.cot_year(datetime.now().year, cot_report_type="legacy_fut")
            if df.empty:
                return {"status": "no_data"}

            # Filter for the instrument
            mask = df["Market and Exchange Names"].str.contains(
                instrument_name, case=False, na=False
            )
            instrument_df = df[mask].sort_index()

            if instrument_df.empty:
                logger.warning("COT: No data found for '%s'", instrument_name)
                return {"status": "not_found", "instrument": instrument_name}

            latest = instrument_df.iloc[-1]

            # Column names vary by cot_reports version
            def _get_col(row, candidates, default=0):
                for c in candidates:
                    if c in row.index:
                        return int(row[c])
                return default

            _COM_LONG = ["Commercial Long", "Commercial Positions-Long (All)"]
            _COM_SHORT = ["Commercial Short", "Commercial Positions-Short (All)"]
            _NC_LONG = ["Noncommercial Long", "Noncommercial Positions-Long (All)"]
            _NC_SHORT = ["Noncommercial Short", "Noncommercial Positions-Short (All)"]

            commercial_long = _get_col(latest, _COM_LONG)
            commercial_short = _get_col(latest, _COM_SHORT)
            commercial_net = commercial_long - commercial_short

            noncommercial_long = _get_col(latest, _NC_LONG)
            noncommercial_short = _get_col(latest, _NC_SHORT)
            noncommercial_net = noncommercial_long - noncommercial_short

            # Check for extreme positioning (naïve: compare to recent range)
            if len(instrument_df) >= 10:
                # Find the correct column name for the dataframe
                nc_long_col = next((c for c in _NC_LONG if c in instrument_df.columns), None)
                nc_short_col = next((c for c in _NC_SHORT if c in instrument_df.columns), None)
                if nc_long_col and nc_short_col:
                    recent_nets = (
                        instrument_df[nc_long_col].astype(float)
                        - instrument_df[nc_short_col].astype(float)
                    )
                    pct_rank = (
                        (noncommercial_net - recent_nets.min())
                        / (recent_nets.max() - recent_nets.min() + 1e-9)
                    )
                    extreme = pct_rank > 0.9 or pct_rank < 0.1
                else:
                    extreme = False
            else:
                extreme = False

            return {
                "status": "ok",
                "commercial_net": commercial_net,
                "commercial_bias": "LONG" if commercial_net > 0 else "SHORT",
                "noncommercial_net": noncommercial_net,
                "noncommercial_bias": "LONG" if noncommercial_net > 0 else "SHORT",
                "extreme_positioning": extreme,
            }
        except ImportError:
            logger.warning("cot_reports not installed — COT data unavailable")
            return {"status": "unavailable"}
        except Exception as e:
            logger.error("COT fetch failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Fear & Greed Index ───────────────────────────────────────────
    @staticmethod
    @retry(max_retries=1, delay=0.5)
    def fetch_fear_greed() -> Dict[str, Any]:
        """
        Fetch CNN Fear & Greed Index via the fear-and-greed library.
        Returns value (0-100), description, and zone classification.
        """
        try:
            import fear_and_greed
            data = fear_and_greed.get()
            value = data.value
            description = data.description

            # Classify into zones
            if value <= 20:
                zone = "EXTREME_FEAR"
            elif value <= 40:
                zone = "FEAR"
            elif value <= 60:
                zone = "NEUTRAL"
            elif value <= 80:
                zone = "GREED"
            else:
                zone = "EXTREME_GREED"

            return {
                "status": "ok",
                "value": round(value, 1),
                "description": description,
                "zone": zone,
            }
        except ImportError:
            logger.warning("fear-and-greed not installed")
            return {"status": "unavailable"}
        except Exception as e:
            logger.error("Fear & Greed fetch failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Retail Sentiment (Myfxbook) ──────────────────────────────────
    @staticmethod
    @retry(max_retries=0, delay=0.0)
    @rate_limit(min_interval=1.0)
    def fetch_retail_sentiment(symbol: str = "EURUSD") -> Dict[str, Any]:
        """
        Scrape Myfxbook Community Outlook for retail long/short percentages.
        Returns long %, short %, and whether it's a contrarian signal.
        """
        url = "https://www.myfxbook.com/community/outlook"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Myfxbook structures sentiment in table rows
            # Look for the symbol in the page
            rows = soup.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if not cells:
                    continue
                # First cell usually contains the symbol name
                row_text = cells[0].get_text(strip=True).upper().replace("/", "")
                if symbol.upper() in row_text:
                    # Try to extract long/short percentages
                    long_pct = None
                    short_pct = None
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        if "%" in text:
                            try:
                                pct = float(text.replace("%", ""))
                                if long_pct is None:
                                    long_pct = pct
                                elif short_pct is None:
                                    short_pct = pct
                            except ValueError:
                                continue

                    if long_pct is not None and short_pct is not None:
                        # Contrarian: if >70% of retail is one direction, fade them
                        contrarian = long_pct > 70 or short_pct > 70
                        contrarian_dir = (
                            "SHORT" if long_pct > 70
                            else "LONG" if short_pct > 70
                            else "NONE"
                        )
                        return {
                            "status": "ok",
                            "symbol": symbol,
                            "long_pct": long_pct,
                            "short_pct": short_pct,
                            "contrarian_signal": contrarian,
                            "contrarian_direction": contrarian_dir,
                        }

            logger.warning("Retail sentiment: Symbol %s not found on page", symbol)
            return {"status": "not_found", "symbol": symbol}

        except requests.RequestException as e:
            logger.error("Myfxbook scrape failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Aggregate Sentiment Snapshot ─────────────────────────────────
    def get_sentiment_snapshot(
        self, cot_instrument: str = "EURO FX", fx_symbol: str = "EURUSD"
    ) -> Dict[str, Any]:
        """Combine all sentiment sources into one dict."""
        return {
            "cot": self.fetch_cot_data(cot_instrument),
            "fear_greed": self.fetch_fear_greed(),
            "retail": self.fetch_retail_sentiment(fx_symbol),
        }
