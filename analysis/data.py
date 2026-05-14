"""Market data fetching.

Pulls daily OHLCV bars from Yahoo Finance via yfinance. Caches the raw frame
in-memory per process so multiple modules can share the same fetch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.parquet"


def fetch_history(
    ticker: str,
    years: int = 10,
    use_disk_cache: bool = True,
) -> pd.DataFrame:
    """Return a DataFrame indexed by date with columns Open, High, Low, Close, Volume.

    Splits and dividends are adjusted by yfinance when auto_adjust=True.
    """
    ticker = ticker.upper()
    cache_file = _cache_path(ticker)

    if use_disk_cache and cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime < timedelta(hours=12):
            df = pd.read_parquet(cache_file)
            log.info("loaded %s from cache (%d rows)", ticker, len(df))
            return df

    end = datetime.now()
    start = end - timedelta(days=years * 366)
    log.info("fetching %s from %s to %s", ticker, start.date(), end.date())

    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df is None or df.empty:
        raise RuntimeError(f"no data returned for {ticker}")

    # yfinance returns MultiIndex columns when a single ticker is passed — flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index)
    df = df.dropna()

    if use_disk_cache:
        try:
            df.to_parquet(cache_file)
        except Exception as e:  # noqa: BLE001
            log.warning("could not cache %s: %s", ticker, e)

    return df


@lru_cache(maxsize=64)
def fetch_history_cached(ticker: str, years: int = 10) -> pd.DataFrame:
    """In-process cached wrapper. Returns the same frame every call within a process."""
    return fetch_history(ticker, years=years, use_disk_cache=True)


def slice_until(df: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Return only rows on or before the cutoff date. Used by the backtester
    to avoid look-ahead bias.
    """
    cutoff = pd.Timestamp(cutoff).normalize()
    return df.loc[df.index <= cutoff]


def forward_return(df: pd.DataFrame, cutoff: pd.Timestamp, horizon_days: int) -> float | None:
    """Return the percent change in Close from `cutoff` to `cutoff + horizon_days`
    (trading days). Returns None if there isn't enough data after the cutoff.
    """
    cutoff = pd.Timestamp(cutoff).normalize()
    after = df.loc[df.index > cutoff]
    if len(after) < horizon_days:
        return None
    start_row = df.loc[df.index <= cutoff]
    if start_row.empty:
        return None
    start_price = float(start_row["Close"].iloc[-1])
    end_price = float(after["Close"].iloc[horizon_days - 1])
    if start_price <= 0:
        return None
    return (end_price - start_price) / start_price * 100.0
