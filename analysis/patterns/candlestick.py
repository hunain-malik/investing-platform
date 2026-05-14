"""Candlestick patterns.

Standard definitions per Nison's "Japanese Candlestick Charting Techniques".
We require a confirming context (prior trend) for hammer/shooting-star and
for doji-at-support/resistance to reduce noise.
"""

from __future__ import annotations

import pandas as pd


def _body(row) -> float:
    return abs(row["Close"] - row["Open"])


def _upper_wick(row) -> float:
    return row["High"] - max(row["Open"], row["Close"])


def _lower_wick(row) -> float:
    return min(row["Open"], row["Close"]) - row["Low"]


def _range(row) -> float:
    return row["High"] - row["Low"]


def _is_green(row) -> bool:
    return row["Close"] > row["Open"]


def _is_red(row) -> bool:
    return row["Close"] < row["Open"]


def _trend_down_5(df: pd.DataFrame, idx: int) -> bool:
    if idx < 5:
        return False
    return df.iloc[idx]["Close"] < df.iloc[idx - 5]["Close"]


def _trend_up_5(df: pd.DataFrame, idx: int) -> bool:
    if idx < 5:
        return False
    return df.iloc[idx]["Close"] > df.iloc[idx - 5]["Close"]


def detect_bullish_engulfing(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    today = df.iloc[idx]
    yesterday = df.iloc[idx - 1]
    if not (_is_red(yesterday) and _is_green(today)):
        return None
    if today["Open"] < yesterday["Close"] and today["Close"] > yesterday["Open"]:
        if _trend_down_5(df, idx):  # only meaningful after a downtrend
            ratio = _body(today) / max(_body(yesterday), 1e-9)
            conf = min(0.75, 0.55 + 0.05 * (ratio - 1))
            return PatternSignal(
                "bullish_engulfing", "up", conf,
                "Green body engulfs prior red body after downtrend",
            )
    return None


def detect_bearish_engulfing(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 1:
        return None
    today = df.iloc[idx]
    yesterday = df.iloc[idx - 1]
    if not (_is_green(yesterday) and _is_red(today)):
        return None
    if today["Open"] > yesterday["Close"] and today["Close"] < yesterday["Open"]:
        if _trend_up_5(df, idx):
            ratio = _body(today) / max(_body(yesterday), 1e-9)
            conf = min(0.75, 0.55 + 0.05 * (ratio - 1))
            return PatternSignal(
                "bearish_engulfing", "down", conf,
                "Red body engulfs prior green body after uptrend",
            )
    return None


def detect_hammer(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 5:
        return None
    row = df.iloc[idx]
    rng = _range(row)
    if rng <= 0:
        return None
    body = _body(row)
    lower = _lower_wick(row)
    upper = _upper_wick(row)
    if body < rng * 0.3 and lower > body * 2 and upper < body * 0.5:
        if _trend_down_5(df, idx):
            return PatternSignal(
                "hammer", "up", 0.6,
                "Hammer candle (long lower wick, small body) after downtrend",
            )
    return None


def detect_shooting_star(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 5:
        return None
    row = df.iloc[idx]
    rng = _range(row)
    if rng <= 0:
        return None
    body = _body(row)
    lower = _lower_wick(row)
    upper = _upper_wick(row)
    if body < rng * 0.3 and upper > body * 2 and lower < body * 0.5:
        if _trend_up_5(df, idx):
            return PatternSignal(
                "shooting_star", "down", 0.6,
                "Shooting-star candle (long upper wick, small body) after uptrend",
            )
    return None


def _local_support(df: pd.DataFrame, idx: int, lookback: int = 30) -> float:
    if idx < lookback:
        return float("nan")
    window = df.iloc[idx - lookback : idx]
    return float(window["Low"].min())


def _local_resistance(df: pd.DataFrame, idx: int, lookback: int = 30) -> float:
    if idx < lookback:
        return float("nan")
    window = df.iloc[idx - lookback : idx]
    return float(window["High"].max())


def detect_doji_at_support(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 30:
        return None
    row = df.iloc[idx]
    rng = _range(row)
    if rng <= 0:
        return None
    body = _body(row)
    if body / rng > 0.1:
        return None  # not a doji
    support = _local_support(df, idx)
    if support != support:  # NaN check
        return None
    proximity = abs(row["Low"] - support) / max(row["Close"], 1e-9)
    if proximity < 0.02:  # within 2% of support
        return PatternSignal(
            "doji_at_support", "up", 0.55,
            f"Doji at local support ~{support:.2f}",
        )
    return None


def detect_doji_at_resistance(df: pd.DataFrame, idx: int):
    from . import PatternSignal
    if idx < 30:
        return None
    row = df.iloc[idx]
    rng = _range(row)
    if rng <= 0:
        return None
    body = _body(row)
    if body / rng > 0.1:
        return None
    resistance = _local_resistance(df, idx)
    if resistance != resistance:
        return None
    proximity = abs(row["High"] - resistance) / max(row["Close"], 1e-9)
    if proximity < 0.02:
        return PatternSignal(
            "doji_at_resistance", "down", 0.55,
            f"Doji at local resistance ~{resistance:.2f}",
        )
    return None
