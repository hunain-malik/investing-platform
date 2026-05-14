"""Pattern detection.

Each pattern detector inspects an indicator-enriched DataFrame at a given row
index and returns an Optional[PatternSignal]. The ensemble in signals.py
collects all triggered patterns and combines them into a final recommendation.

`detect_all` runs every registered pattern and returns the list that fired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from . import candlestick, chart, oscillators


@dataclass(frozen=True)
class PatternSignal:
    name: str
    direction: str  # "up" or "down"
    confidence: float  # 0-1, intrinsic strength of this pattern instance
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "confidence": self.confidence,
            "note": self.note,
        }


PatternFn = Callable[[pd.DataFrame, int], "PatternSignal | None"]


# Registry of every detector. signals.py and backtest.py iterate this.
DETECTORS: list[PatternFn] = [
    chart.detect_sma_crossover_bull,
    chart.detect_sma_crossover_bear,
    chart.detect_golden_cross,
    chart.detect_death_cross,
    chart.detect_bb_squeeze_breakout_up,
    chart.detect_bb_squeeze_breakout_down,
    oscillators.detect_rsi_oversold,
    oscillators.detect_rsi_overbought,
    oscillators.detect_macd_cross_bull,
    oscillators.detect_macd_cross_bear,
    candlestick.detect_bullish_engulfing,
    candlestick.detect_bearish_engulfing,
    candlestick.detect_hammer,
    candlestick.detect_shooting_star,
    candlestick.detect_doji_at_support,
    candlestick.detect_doji_at_resistance,
]


def detect_all(df: pd.DataFrame, idx: int = -1) -> list[PatternSignal]:
    """Run every detector on row `idx` of df. Returns the patterns that fired."""
    if idx < 0:
        idx = len(df) + idx
    out: list[PatternSignal] = []
    for fn in DETECTORS:
        try:
            sig = fn(df, idx)
        except Exception:  # noqa: BLE001 — detectors must never crash a run
            sig = None
        if sig is not None:
            out.append(sig)
    return out
