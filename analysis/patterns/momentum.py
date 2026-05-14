"""Stochastic Oscillator + Ichimoku Cloud patterns.

Stochastic: %K (close vs 14-bar range) and %D (3-bar SMA of %K).
    Oversold reversal:  %K < 20 then crosses above %D
    Overbought reversal: %K > 80 then crosses below %D

Ichimoku: simplified — use Tenkan-sen (9-bar Donchian midpoint) and Kijun-sen
(26-bar Donchian midpoint). Bullish cross: Tenkan crosses above Kijun.
"""

from __future__ import annotations

import pandas as pd


def _stochastic_kd(df: pd.DataFrame, idx: int, k_window: int = 14, d_window: int = 3):
    """Returns (%K, %D, prev %K, prev %D) at idx, or None if not enough data."""
    if idx < k_window + d_window:
        return None
    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    # %K series for the last (d_window + 1) bars
    k_series = []
    for j in range(idx - d_window, idx + 1):
        if j < k_window - 1:
            return None
        window_high = highs.iloc[j - k_window + 1 : j + 1].max()
        window_low = lows.iloc[j - k_window + 1 : j + 1].min()
        rng = window_high - window_low
        if rng <= 0:
            return None
        k = (closes.iloc[j] - window_low) / rng * 100.0
        k_series.append(float(k))
    if len(k_series) < d_window + 1:
        return None
    # %D = SMA of last d_window %K values
    d_now = sum(k_series[-d_window:]) / d_window
    d_prev = sum(k_series[-d_window - 1 : -1]) / d_window
    k_now = k_series[-1]
    k_prev = k_series[-2]
    return k_now, d_now, k_prev, d_prev


def detect_stochastic_oversold(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    out = _stochastic_kd(df, idx)
    if out is None:
        return None
    k, d, k_prev, d_prev = out
    # Cross-up while in oversold region
    if min(k_prev, k) < 25 and k_prev <= d_prev and k > d:
        depth = max(0.0, 25 - min(k_prev, k)) / 25.0
        conf = min(0.75, 0.55 + depth * 0.4)
        return PatternSignal(
            "stochastic_oversold", "up", conf,
            f"Stoch %K crossed above %D from oversold (low {min(k_prev, k):.1f})",
        )
    return None


def detect_stochastic_overbought(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    out = _stochastic_kd(df, idx)
    if out is None:
        return None
    k, d, k_prev, d_prev = out
    if max(k_prev, k) > 75 and k_prev >= d_prev and k < d:
        depth = max(0.0, max(k_prev, k) - 75) / 25.0
        conf = min(0.75, 0.55 + depth * 0.4)
        return PatternSignal(
            "stochastic_overbought", "down", conf,
            f"Stoch %K crossed below %D from overbought (high {max(k_prev, k):.1f})",
        )
    return None


def _ichimoku_lines(df: pd.DataFrame, idx: int):
    """Returns (tenkan, kijun, tenkan_prev, kijun_prev) at idx."""
    if idx < 26:
        return None
    h = df["High"]
    l = df["Low"]
    def midpoint(window):
        return (h.iloc[window].max() + l.iloc[window].min()) / 2.0

    tenkan = midpoint(slice(idx - 8, idx + 1))   # 9-period
    kijun = midpoint(slice(idx - 25, idx + 1))   # 26-period
    tenkan_prev = midpoint(slice(idx - 9, idx))
    kijun_prev = midpoint(slice(idx - 26, idx))
    return float(tenkan), float(kijun), float(tenkan_prev), float(kijun_prev)


def detect_ichimoku_bull_cross(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    out = _ichimoku_lines(df, idx)
    if out is None:
        return None
    tenkan, kijun, t_prev, k_prev = out
    if t_prev <= k_prev and tenkan > kijun:
        return PatternSignal(
            "ichimoku_bull_cross", "up", 0.65,
            "Ichimoku Tenkan crossed above Kijun (TK bullish cross)",
        )
    return None


def detect_ichimoku_bear_cross(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    out = _ichimoku_lines(df, idx)
    if out is None:
        return None
    tenkan, kijun, t_prev, k_prev = out
    if t_prev >= k_prev and tenkan < kijun:
        return PatternSignal(
            "ichimoku_bear_cross", "down", 0.65,
            "Ichimoku Tenkan crossed below Kijun (TK bearish cross)",
        )
    return None
