"""Ensemble signal generation with per-horizon weights.

For each horizon (5d / 10d / 20d / ...) the system maintains its own set of
pattern weights, tuned independently from backtest accuracy at THAT horizon.
A pattern that's useful at 5d may be useless at 20d (or vice-versa), so a
single global weight blurs the signal.

Combiner (per-horizon):
    For each fired pattern p (filtered by methodology, if any):
        contribution_p = weight_h[p] * intrinsic_confidence_p * sign(direction_p)
    weighted_vote = sum(contribution_p)
    firepower     = sum(weight_h[p] * intrinsic_confidence_p)
    agreement     = |weighted_vote| / firepower
    intensity     = min(1, firepower / FIREPOWER_TARGET)
    confidence    = 0.5 + 0.5 * agreement * intensity
    direction     = sign(weighted_vote)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from .indicators import compute_all
from .patterns import PatternSignal, detect_all

FIREPOWER_TARGET = 3.0


# Weight schema: nested dict {pattern_name: {horizon_int: float}}
PerHorizonWeights = dict[str, dict[int, float]]


def weights_for_horizon(all_weights: PerHorizonWeights, horizon: int) -> dict[str, float]:
    """Flatten the nested weights into {pattern: weight} for one horizon."""
    return {p: hw.get(horizon, 1.0) for p, hw in all_weights.items()}


@dataclass
class EnsembleSignal:
    ticker: str
    as_of: pd.Timestamp
    horizon_days: int
    direction: str
    confidence: float
    fired_patterns: list[PatternSignal] = field(default_factory=list)
    price: float = 0.0
    atr: float = 0.0
    methodology: str = "all"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "as_of": self.as_of.strftime("%Y-%m-%d"),
            "horizon_days": self.horizon_days,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "fired_patterns": [p.to_dict() for p in self.fired_patterns],
            "price": round(self.price, 4),
            "atr": round(self.atr, 4),
            "methodology": self.methodology,
        }


def combine(
    fired: Iterable[PatternSignal],
    weights: dict[str, float],
) -> tuple[str, float]:
    """Return (direction, confidence) from a set of fired patterns and flat weights."""
    fired = list(fired)
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
    # Cap at 0.95 — the baseline combine() can saturate at 1.0 when all
    # patterns agree at full firepower, which is misleading: it's still
    # the same pattern set, not multi-source independent confirmation.
    # Higher tiers (meta_ensemble, consensus_families) apply their own
    # Bayesian caps; this matches that behavior at the bottom layer.
    confidence = min(0.95, 0.5 + 0.5 * agreement * intensity)

    if weighted_vote > 0:
        direction = "up"
    elif weighted_vote < 0:
        direction = "down"
    else:
        direction = "neutral"

    return direction, confidence


def analyze_one_horizon(
    ticker: str,
    df_raw: pd.DataFrame,
    weights_h: dict[str, float],
    horizon: int,
    as_of_idx: int = -1,
    methodology: str = "all",
    pattern_filter: set[str] | None = None,
) -> EnsembleSignal:
    """Run indicators + pattern detection + combine for one horizon."""
    df = compute_all(df_raw)
    if as_of_idx < 0:
        as_of_idx = len(df) + as_of_idx
    fired_all = detect_all(df, as_of_idx)
    fired = [p for p in fired_all if pattern_filter is None or p.name in pattern_filter]
    direction, confidence = combine(fired, weights_h)
    row = df.iloc[as_of_idx]
    return EnsembleSignal(
        ticker=ticker,
        as_of=df.index[as_of_idx],
        horizon_days=horizon,
        direction=direction,
        confidence=confidence,
        fired_patterns=fired,
        price=float(row["Close"]),
        atr=float(row["atr_14"]) if not pd.isna(row.get("atr_14")) else 0.0,
        methodology=methodology,
    )


def analyze_all_horizons(
    ticker: str,
    df_raw: pd.DataFrame,
    all_weights: PerHorizonWeights,
    horizons: list[int],
    as_of_idx: int = -1,
) -> list[EnsembleSignal]:
    """Produce one EnsembleSignal per horizon for the same cutoff bar."""
    out: list[EnsembleSignal] = []
    df = compute_all(df_raw)
    if as_of_idx < 0:
        as_of_idx = len(df) + as_of_idx
    fired = detect_all(df, as_of_idx)
    row = df.iloc[as_of_idx]
    price = float(row["Close"])
    atr_val = float(row["atr_14"]) if not pd.isna(row.get("atr_14")) else 0.0
    for h in horizons:
        w = weights_for_horizon(all_weights, h)
        direction, confidence = combine(fired, w)
        out.append(EnsembleSignal(
            ticker=ticker,
            as_of=df.index[as_of_idx],
            horizon_days=h,
            direction=direction,
            confidence=confidence,
            fired_patterns=fired,
            price=price,
            atr=atr_val,
        ))
    return out
