"""Ensemble signal generation.

Combines the individual pattern detections from `patterns.detect_all` into a
single recommendation with a calibrated confidence score.

Combiner:
    For each fired pattern p with direction d_p (+1 up / -1 down):
        contribution_p = weight[p] * intrinsic_confidence_p * d_p
    weighted_vote = sum(contribution_p)
    total_firepower = sum(weight[p] * intrinsic_confidence_p)
    agreement = |weighted_vote| / total_firepower            in [0, 1]
    intensity = min(1, total_firepower / FIREPOWER_TARGET)   in [0, 1]
    confidence = 0.5 + 0.5 * agreement * intensity           in [0.5, 1]
    direction  = sign(weighted_vote)

Agreement penalises mixed signals (one up, one down → near 0). Intensity
penalises thin evidence (only one weak pattern → low). Both must be high for
confidence to approach 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .indicators import compute_all
from .patterns import PatternSignal, detect_all

# When the total weighted firepower hits this, we treat it as a "loud" signal
# and the intensity term saturates at 1.0. Empirically calibrated — 3-4
# medium-confidence patterns firing in agreement.
FIREPOWER_TARGET = 3.0


@dataclass
class EnsembleSignal:
    ticker: str
    as_of: pd.Timestamp
    direction: str  # "up", "down", "neutral"
    confidence: float  # 0.5-1.0 (0.5 = no information)
    fired_patterns: list[PatternSignal] = field(default_factory=list)
    price: float = 0.0
    atr: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "as_of": self.as_of.strftime("%Y-%m-%d"),
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "fired_patterns": [p.to_dict() for p in self.fired_patterns],
            "price": round(self.price, 4),
            "atr": round(self.atr, 4),
        }


def combine(
    fired: list[PatternSignal],
    weights: dict[str, float],
) -> tuple[str, float]:
    """Return (direction, confidence)."""
    if not fired:
        return "neutral", 0.5

    weighted_vote = 0.0
    firepower = 0.0
    for p in fired:
        w = weights.get(p.name, 1.0)
        contribution = w * p.confidence
        firepower += contribution
        weighted_vote += contribution * (1 if p.direction == "up" else -1)

    if firepower == 0:
        return "neutral", 0.5

    agreement = abs(weighted_vote) / firepower
    intensity = min(1.0, firepower / FIREPOWER_TARGET)
    confidence = 0.5 + 0.5 * agreement * intensity

    if weighted_vote > 0:
        direction = "up"
    elif weighted_vote < 0:
        direction = "down"
    else:
        direction = "neutral"

    return direction, confidence


def analyze(
    ticker: str,
    df_raw: pd.DataFrame,
    weights: dict[str, float],
    as_of_idx: int = -1,
) -> EnsembleSignal:
    """Run the full indicator + pattern + ensemble pipeline on `df_raw`.

    `as_of_idx` lets the backtester evaluate the signal as it would have looked
    on a past day; defaults to the last row (today).
    """
    df = compute_all(df_raw)
    if as_of_idx < 0:
        as_of_idx = len(df) + as_of_idx
    fired = detect_all(df, as_of_idx)
    direction, confidence = combine(fired, weights)
    row = df.iloc[as_of_idx]
    return EnsembleSignal(
        ticker=ticker,
        as_of=df.index[as_of_idx],
        direction=direction,
        confidence=confidence,
        fired_patterns=fired,
        price=float(row["Close"]),
        atr=float(row["atr_14"]) if not pd.isna(row.get("atr_14")) else 0.0,
    )
