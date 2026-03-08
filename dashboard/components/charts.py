"""
IFC Dashboard — Chart Components
Reusable chart builders for the dashboard.
"""

import pandas as pd
from typing import Dict, Any, List, Optional


def build_ohlcv_chart_data(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Prepare OHLCV data for Streamlit charting.
    Returns dict with separate series for close, high, low.
    """
    if df.empty:
        return {}

    chart_data = pd.DataFrame({
        "Close": df["close"],
        "High": df["high"],
        "Low": df["low"],
    })
    return chart_data


def build_volume_profile_chart(
    profile_bins: pd.Series,
    poc: float,
    vah: float,
    val: float,
) -> Dict[str, Any]:
    """
    Prepare volume profile data for horizontal bar display.
    """
    return {
        "bins": profile_bins.to_dict(),
        "poc": poc,
        "vah": vah,
        "val": val,
    }


def build_equity_curve_data(curve: List[Dict]) -> pd.DataFrame:
    """Convert equity curve list to a DataFrame for charting."""
    if not curve:
        return pd.DataFrame()
    df = pd.DataFrame(curve)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def build_r_distribution_data(trades: List[Dict]) -> pd.Series:
    """Build R-multiple distribution series."""
    closed = [t for t in trades if t.get("outcome") != "OPEN"]
    if not closed:
        return pd.Series(dtype=float)
    r_values = [t["r_multiple"] for t in closed]
    return pd.Series(r_values, name="R-Multiple")


def format_pnl(value: float) -> str:
    """Format P&L with color indicator."""
    if value >= 0:
        return f"+${value:,.2f}"
    return f"-${abs(value):,.2f}"


def format_r(value: float) -> str:
    """Format R-multiple."""
    return f"{value:+.2f}R"
