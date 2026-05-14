"""Market regime detection.

Three regimes based on SPY's position relative to its 200-day SMA and the
slope of that SMA:

    bull     -> SPY > 200-SMA and 200-SMA rising over last 60 bars
    bear     -> SPY < 200-SMA and 200-SMA falling over last 60 bars
    choppy   -> everything else (transitions, sideways)

Pattern accuracy is regime-dependent: trend-following patterns work in
trending regimes, mean-reversion works in choppy, and shorts work better
in bear. Tagging each backtest sample with the prevailing regime at the
cutoff date lets us see this explicitly on the dashboard.
"""

from __future__ import annotations

import logging

import pandas as pd

from .data import fetch_history_cached
from .indicators import sma

log = logging.getLogger(__name__)


def regime_at(spy_df: pd.DataFrame, cutoff: pd.Timestamp) -> str:
    """Return the regime that prevailed at `cutoff` based on SPY's frame.

    spy_df is the full SPY history (passed in so we don't refetch).
    """
    cutoff = pd.Timestamp(cutoff)
    # yfinance index is tz-naive; strip any tz from cutoff before comparison
    if cutoff.tz is not None:
        cutoff = cutoff.tz_convert(None) if hasattr(cutoff, "tz_convert") else cutoff.tz_localize(None)
    cutoff = cutoff.normalize()
    sliced = spy_df.loc[spy_df.index <= cutoff]
    if len(sliced) < 260:
        return "unknown"

    closes = sliced["Close"]
    sma_200 = sma(closes, 200)
    if pd.isna(sma_200.iloc[-1]) or pd.isna(sma_200.iloc[-61]):
        return "unknown"

    price = float(closes.iloc[-1])
    sma_now = float(sma_200.iloc[-1])
    sma_60ago = float(sma_200.iloc[-61])
    rising = sma_now > sma_60ago
    falling = sma_now < sma_60ago

    above = price > sma_now
    below = price < sma_now

    if above and rising:
        return "bull"
    if below and falling:
        return "bear"
    return "choppy"


def load_spy() -> pd.DataFrame:
    """Single-shot SPY fetch used by the backtester."""
    return fetch_history_cached("SPY", years=12)
