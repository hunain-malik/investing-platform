"""Chart patterns: moving-average crossovers, Bollinger squeezes."""

from __future__ import annotations

import pandas as pd


def _crossed_above(prev_a, prev_b, curr_a, curr_b) -> bool:
    return prev_a <= prev_b and curr_a > curr_b


def _crossed_below(prev_a, prev_b, curr_a, curr_b) -> bool:
    return prev_a >= prev_b and curr_a < curr_b


def detect_sma_crossover_bull(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["sma_20"]) or pd.isna(row["sma_50"]):
        return None
    if _crossed_above(prev["sma_20"], prev["sma_50"], row["sma_20"], row["sma_50"]):
        # confidence scales with how separated the MAs are after the cross
        sep = abs(row["sma_20"] - row["sma_50"]) / row["Close"]
        conf = min(0.8, 0.55 + sep * 5)
        return PatternSignal("sma_crossover_bull", "up", conf, "20-SMA crossed above 50-SMA")
    return None


def detect_sma_crossover_bear(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["sma_20"]) or pd.isna(row["sma_50"]):
        return None
    if _crossed_below(prev["sma_20"], prev["sma_50"], row["sma_20"], row["sma_50"]):
        sep = abs(row["sma_20"] - row["sma_50"]) / row["Close"]
        conf = min(0.8, 0.55 + sep * 5)
        return PatternSignal("sma_crossover_bear", "down", conf, "20-SMA crossed below 50-SMA")
    return None


def detect_golden_cross(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["sma_50"]) or pd.isna(row["sma_200"]):
        return None
    if _crossed_above(prev["sma_50"], prev["sma_200"], row["sma_50"], row["sma_200"]):
        return PatternSignal("golden_cross", "up", 0.7, "50-SMA crossed above 200-SMA (golden cross)")
    return None


def detect_death_cross(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["sma_50"]) or pd.isna(row["sma_200"]):
        return None
    if _crossed_below(prev["sma_50"], prev["sma_200"], row["sma_50"], row["sma_200"]):
        return PatternSignal("death_cross", "down", 0.7, "50-SMA crossed below 200-SMA (death cross)")
    return None


def detect_bb_squeeze_breakout_up(df: pd.DataFrame, idx: int):
    """Bollinger Band squeeze followed by upside breakout.

    Squeeze = bandwidth in the bottom 25% of its last 60 bars. Breakout = Close
    pushes above the upper band on a day with elevated volume.
    """
    from . import PatternSignal
    if idx < 60:
        return None
    window = df.iloc[idx - 60 : idx]
    bw_now = df.iloc[idx]["bb_bandwidth"]
    if pd.isna(bw_now):
        return None
    bw_q25 = window["bb_bandwidth"].quantile(0.25)
    if bw_now > bw_q25:
        return None
    row = df.iloc[idx]
    if row["Close"] > row["bb_upper"] and row.get("vol_z_20", 0) > 1.0:
        return PatternSignal(
            "bb_squeeze_breakout_up", "up", 0.7,
            "Bollinger squeeze with upside breakout on high volume",
        )
    return None


def detect_bb_squeeze_breakout_down(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 60:
        return None
    window = df.iloc[idx - 60 : idx]
    bw_now = df.iloc[idx]["bb_bandwidth"]
    if pd.isna(bw_now):
        return None
    bw_q25 = window["bb_bandwidth"].quantile(0.25)
    if bw_now > bw_q25:
        return None
    row = df.iloc[idx]
    if row["Close"] < row["bb_lower"] and row.get("vol_z_20", 0) > 1.0:
        return PatternSignal(
            "bb_squeeze_breakout_down", "down", 0.7,
            "Bollinger squeeze with downside breakout on high volume",
        )
    return None
