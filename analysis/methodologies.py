"""Methodology framework.

Each methodology is a named approach: a subset of patterns to use, an
optional regime filter, and a min-confidence cutoff. Methodologies are
evaluated in post-processing of the same backtest samples so adding one
doesn't require re-running data fetches.

Defined here so adding/removing methodologies is one edit, not a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .signals import combine


@dataclass(frozen=True)
class Methodology:
    name: str
    description: str
    pattern_filter: frozenset[str] | None = None  # None = all patterns
    regime_filter: frozenset[str] | None = None   # None = all regimes
    min_confidence: float = 0.50                  # gate before counting in accuracy


METHODOLOGIES: list[Methodology] = [
    Methodology(
        name="all",
        description="All patterns combined — baseline ensemble",
        pattern_filter=None,
    ),
    Methodology(
        name="trend_following",
        description="SMA/MACD crossovers and multi-timeframe alignment only",
        pattern_filter=frozenset({
            "sma_crossover_bull", "sma_crossover_bear",
            "golden_cross", "death_cross",
            "macd_cross_bull", "macd_cross_bear",
            "multi_timeframe_bull", "multi_timeframe_bear",
        }),
    ),
    Methodology(
        name="mean_reversion",
        description="RSI extremes, Bollinger squeezes, doji at S/R",
        pattern_filter=frozenset({
            "rsi_oversold", "rsi_overbought",
            "bb_squeeze_breakout_up", "bb_squeeze_breakout_down",
            "doji_at_support", "doji_at_resistance",
        }),
    ),
    Methodology(
        name="candlestick_only",
        description="Only candlestick patterns — wick/body shape signals",
        pattern_filter=frozenset({
            "bullish_engulfing", "bearish_engulfing",
            "hammer", "shooting_star",
            "doji_at_support", "doji_at_resistance",
        }),
    ),
    Methodology(
        name="high_confidence",
        description="All patterns but only count signals with confidence >= 0.75",
        pattern_filter=None,
        min_confidence=0.75,
    ),
    Methodology(
        name="trend_in_trending_regime",
        description="Trend-following patterns, but only when the market is in a clear bull or bear regime",
        pattern_filter=frozenset({
            "sma_crossover_bull", "sma_crossover_bear",
            "golden_cross", "death_cross",
            "macd_cross_bull", "macd_cross_bear",
            "multi_timeframe_bull", "multi_timeframe_bear",
        }),
        regime_filter=frozenset({"bull", "bear"}),
    ),
]


def evaluate_methodology(
    methodology: Methodology,
    sample,  # BacktestSample
    weights_per_horizon,  # PerHorizonWeights
) -> dict | None:
    """Re-run the combiner for `sample` using only this methodology's patterns.

    Returns {direction, confidence, correct} or None if the methodology is
    inapplicable to this sample (e.g. regime filter excludes it).
    """
    if methodology.regime_filter is not None and sample.regime not in methodology.regime_filter:
        return None

    # rebuild PatternSignals from stored sample data
    from .patterns import PatternSignal
    fired = []
    for pat_name, pat_dir in sample.pattern_directions.items():
        if methodology.pattern_filter is not None and pat_name not in methodology.pattern_filter:
            continue
        # intrinsic confidence is lost on serialization; assume 0.65 as a generic value.
        # backtest stores fired_patterns + pattern_directions, not full PatternSignal objects.
        fired.append(PatternSignal(name=pat_name, direction=pat_dir, confidence=0.65))

    if not fired:
        return None

    # weights for this horizon
    h = sample.horizon_days
    weights_h = {p: hw.get(h, 1.0) for p, hw in weights_per_horizon.items()}

    direction, confidence = combine(fired, weights_h)
    if direction == "neutral":
        return None
    if confidence < methodology.min_confidence:
        return None

    correct = (direction == sample.actual_label)
    return {
        "direction": direction,
        "confidence": confidence,
        "correct": correct,
    }


def aggregate_methodology_accuracy(
    samples,  # list[BacktestSample]
    weights_per_horizon,
) -> dict[str, dict]:
    """For each methodology, evaluate it against every applicable sample and
    return per-methodology accuracy stats."""
    out: dict[str, dict] = {}
    for m in METHODOLOGIES:
        n_applicable = 0
        n_signal = 0
        n_correct = 0
        by_horizon: dict[int, dict[str, int]] = {}
        for s in samples:
            applicable = True
            if m.regime_filter is not None and s.regime not in m.regime_filter:
                applicable = False
            if applicable:
                n_applicable += 1
            r = evaluate_methodology(m, s, weights_per_horizon)
            if r is None:
                continue
            n_signal += 1
            if r["correct"]:
                n_correct += 1
            hb = by_horizon.setdefault(s.horizon_days, {"signals": 0, "correct": 0})
            hb["signals"] += 1
            if r["correct"]:
                hb["correct"] += 1

        out[m.name] = {
            "description": m.description,
            "samples_applicable": n_applicable,
            "signals_emitted": n_signal,
            "correct": n_correct,
            "accuracy": round(n_correct / n_signal, 4) if n_signal else None,
            "signal_rate": round(n_signal / n_applicable, 4) if n_applicable else None,
            "by_horizon": {
                h: {
                    "signals": v["signals"],
                    "correct": v["correct"],
                    "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None,
                }
                for h, v in sorted(by_horizon.items())
            },
        }
    return out
