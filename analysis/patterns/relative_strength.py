"""Relative strength vs the broad market (SPY).

If a ticker outperforms SPY by a meaningful margin over a lookback window,
it's showing relative strength — institutional accumulation, sector
leadership, or company-specific tailwinds. The opposite (relative weakness)
often precedes further declines.

Implementation note: relative strength requires SPY's data aligned to the
ticker's dates. We compute the 20-day ticker return and the 20-day SPY
return at the same `idx` from `df["spy_close"]`, which compute_all attaches
if a benchmark series is provided.
"""

from __future__ import annotations

import pandas as pd


def _rs_20(df: pd.DataFrame, idx: int) -> float | None:
    if idx < 20 or "spy_close" not in df.columns:
        return None
    t_now = float(df.iloc[idx]["Close"])
    t_20 = float(df.iloc[idx - 20]["Close"])
    s_now_raw = df.iloc[idx]["spy_close"]
    s_20_raw = df.iloc[idx - 20]["spy_close"]
    if pd.isna(s_now_raw) or pd.isna(s_20_raw):
        return None
    s_now = float(s_now_raw)
    s_20 = float(s_20_raw)
    if t_20 <= 0 or s_20 <= 0:
        return None
    t_ret = (t_now / t_20) - 1.0
    s_ret = (s_now / s_20) - 1.0
    return t_ret - s_ret


def detect_relative_strength_bull(df: pd.DataFrame, idx: int):
    """Ticker has outperformed SPY by >= 3% over the last 20 trading days."""
    from . import PatternSignal
    rs = _rs_20(df, idx)
    if rs is None or rs < 0.03:
        return None
    conf = 0.55 + min(0.25, (rs - 0.03) * 2.5)  # 3% diff -> 0.55, ~13% -> 0.80
    return PatternSignal(
        "relative_strength_bull", "up", conf,
        f"Outperformed SPY by {rs * 100:+.1f}% over 20 days",
    )


def detect_relative_strength_bear(df: pd.DataFrame, idx: int):
    """Ticker has underperformed SPY by >= 3% over the last 20 trading days."""
    from . import PatternSignal
    rs = _rs_20(df, idx)
    if rs is None or rs > -0.03:
        return None
    conf = 0.55 + min(0.25, (-rs - 0.03) * 2.5)
    return PatternSignal(
        "relative_strength_bear", "down", conf,
        f"Underperformed SPY by {rs * 100:+.1f}% over 20 days",
    )
