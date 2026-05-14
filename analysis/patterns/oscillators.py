"""Oscillator-based patterns: RSI reversals, MACD crossovers."""

from __future__ import annotations

import pandas as pd


def detect_rsi_oversold(df: pd.DataFrame, idx: int):
    """RSI dipped below 30 in the last 5 bars and has now turned up."""
    from . import PatternSignal
    if idx < 5:
        return None
    window = df.iloc[idx - 5 : idx + 1]
    if pd.isna(window["rsi_14"]).any():
        return None
    min_rsi = window["rsi_14"].min()
    curr = df.iloc[idx]["rsi_14"]
    prev = df.iloc[idx - 1]["rsi_14"]
    if min_rsi < 30 and curr > prev and curr > 30:
        depth = max(0.0, 30 - min_rsi) / 30.0
        conf = min(0.75, 0.55 + depth * 0.5)
        return PatternSignal(
            "rsi_oversold", "up", conf,
            f"RSI bottomed at {min_rsi:.1f} and turned up",
        )
    return None


def detect_rsi_overbought(df: pd.DataFrame, idx: int):
    """RSI rose above 70 in the last 5 bars and has now turned down."""
    from . import PatternSignal
    if idx < 5:
        return None
    window = df.iloc[idx - 5 : idx + 1]
    if pd.isna(window["rsi_14"]).any():
        return None
    max_rsi = window["rsi_14"].max()
    curr = df.iloc[idx]["rsi_14"]
    prev = df.iloc[idx - 1]["rsi_14"]
    if max_rsi > 70 and curr < prev and curr < 70:
        depth = max(0.0, max_rsi - 70) / 30.0
        conf = min(0.75, 0.55 + depth * 0.5)
        return PatternSignal(
            "rsi_overbought", "down", conf,
            f"RSI peaked at {max_rsi:.1f} and turned down",
        )
    return None


def detect_macd_cross_bull(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["macd"]) or pd.isna(row["macd_signal"]):
        return None
    if prev["macd"] <= prev["macd_signal"] and row["macd"] > row["macd_signal"]:
        # crossing below zero is stronger than above zero
        below_zero_bonus = 0.05 if row["macd"] < 0 else 0.0
        return PatternSignal(
            "macd_cross_bull", "up", 0.6 + below_zero_bonus,
            "MACD crossed above its signal line",
        )
    return None


def detect_macd_cross_bear(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if pd.isna(row["macd"]) or pd.isna(row["macd_signal"]):
        return None
    if prev["macd"] >= prev["macd_signal"] and row["macd"] < row["macd_signal"]:
        above_zero_bonus = 0.05 if row["macd"] > 0 else 0.0
        return PatternSignal(
            "macd_cross_bear", "down", 0.6 + above_zero_bonus,
            "MACD crossed below its signal line",
        )
    return None
