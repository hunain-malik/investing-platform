"""Multi-timeframe trend alignment.

Checks whether price action agrees across multiple lookback windows:
    short    = 5-day SMA
    medium-1 = 20-day SMA
    medium-2 = 50-day SMA
    long     = 200-day SMA

Bullish alignment: price > SMA5 > SMA20 > SMA50 > SMA200 (or near-monotonic).
Bearish alignment: the inverse.

This is the explicit answer to "you're only looking at one day" — the pattern
requires the trend to be consistent across one week, one month, two months,
and one year simultaneously before it fires. It's a strong contextual filter.
"""

from __future__ import annotations

import pandas as pd


def _stack_score(values: list[float], ascending: bool) -> float:
    """Return 1.0 if values are perfectly stacked in the requested order,
    declining as the stacking becomes less clean. Used to grade alignment.
    """
    n = len(values)
    if n < 2:
        return 0.0
    pairs = list(zip(values, values[1:]))
    if ascending:
        agreeing = sum(1 for a, b in pairs if a > b)
    else:
        agreeing = sum(1 for a, b in pairs if a < b)
    return agreeing / len(pairs)


def detect_multi_timeframe_alignment_bull(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 200:
        return None
    row = df.iloc[idx]
    needed = ["Close", "sma_20", "sma_50", "sma_200"]
    if any(pd.isna(row[c]) for c in needed):
        return None

    # Short-term SMA (5d) — compute on the fly so we don't need to plumb it into compute_all
    short_window = df.iloc[idx - 4 : idx + 1]["Close"]
    if len(short_window) < 5:
        return None
    sma_5 = float(short_window.mean())

    stack = [float(row["Close"]), sma_5, float(row["sma_20"]), float(row["sma_50"]), float(row["sma_200"])]
    score = _stack_score(stack, ascending=True)
    if score < 0.75:  # at least 3 of 4 pairwise comparisons agree
        return None

    # Confirm the long-term trend is actually rising (not flat)
    long_ago = df.iloc[idx - 60]["sma_50"]
    if pd.isna(long_ago) or row["sma_50"] <= long_ago:
        return None

    conf = 0.55 + 0.25 * score  # 0.55-0.80 range
    return PatternSignal(
        "multi_timeframe_bull", "up", conf,
        f"Price > 5/20/50/200 SMA stack (alignment {score:.0%}); rising 50-SMA over 60 bars",
    )


def detect_multi_timeframe_alignment_bear(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 200:
        return None
    row = df.iloc[idx]
    needed = ["Close", "sma_20", "sma_50", "sma_200"]
    if any(pd.isna(row[c]) for c in needed):
        return None

    short_window = df.iloc[idx - 4 : idx + 1]["Close"]
    if len(short_window) < 5:
        return None
    sma_5 = float(short_window.mean())

    stack = [float(row["Close"]), sma_5, float(row["sma_20"]), float(row["sma_50"]), float(row["sma_200"])]
    score = _stack_score(stack, ascending=False)
    if score < 0.75:
        return None

    long_ago = df.iloc[idx - 60]["sma_50"]
    if pd.isna(long_ago) or row["sma_50"] >= long_ago:
        return None

    conf = 0.55 + 0.25 * score
    return PatternSignal(
        "multi_timeframe_bear", "down", conf,
        f"Price < 5/20/50/200 SMA stack (alignment {score:.0%}); falling 50-SMA over 60 bars",
    )
