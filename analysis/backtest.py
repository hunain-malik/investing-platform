"""Backtesting engine.

Picks random (ticker, cutoff_date) samples. For each sample, runs the full
indicator + pattern + ensemble pipeline using ONLY data up to the cutoff
(no look-ahead), then compares the prediction to the actual forward N-day
return. Aggregates per-pattern and per-ensemble accuracy.

The output feeds two things:
  1. The dashboard's scoreboard (so you can see hit rates).
  2. Pattern weight updates (so the ensemble can rewire toward what works).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .data import fetch_history_cached, forward_return, slice_until
from .indicators import compute_all
from .patterns import detect_all
from .signals import combine

log = logging.getLogger(__name__)


@dataclass
class BacktestSample:
    ticker: str
    cutoff: pd.Timestamp
    horizon_days: int
    fired_patterns: list[str]
    pattern_directions: dict[str, str]
    ensemble_direction: str
    ensemble_confidence: float
    forward_return_pct: float
    actual_label: str  # "up", "down", or "flat"
    ensemble_correct: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "cutoff": self.cutoff.strftime("%Y-%m-%d"),
            "horizon_days": self.horizon_days,
            "fired_patterns": self.fired_patterns,
            "pattern_directions": self.pattern_directions,
            "ensemble_direction": self.ensemble_direction,
            "ensemble_confidence": round(self.ensemble_confidence, 4),
            "forward_return_pct": round(self.forward_return_pct, 4),
            "actual_label": self.actual_label,
            "ensemble_correct": self.ensemble_correct,
        }


def _label_return(ret_pct: float, up_threshold: float, down_threshold: float) -> str:
    if ret_pct >= up_threshold:
        return "up"
    if ret_pct <= down_threshold:
        return "down"
    return "flat"


def run_sample(
    ticker: str,
    cutoff: pd.Timestamp,
    horizon_days: int,
    weights: dict[str, float],
    up_threshold: float,
    down_threshold: float,
) -> BacktestSample | None:
    """Run a single backtest sample. Returns None if data is insufficient."""
    try:
        df_full = fetch_history_cached(ticker)
    except Exception as e:  # noqa: BLE001
        log.warning("could not fetch %s: %s", ticker, e)
        return None

    df_until = slice_until(df_full, cutoff)
    if len(df_until) < 252:  # need at least 1 year of indicator runway
        return None

    df_ind = compute_all(df_until)
    fired = detect_all(df_ind, idx=-1)
    direction, confidence = combine(fired, weights)

    ret = forward_return(df_full, cutoff, horizon_days)
    if ret is None:
        return None

    actual = _label_return(ret, up_threshold, down_threshold)
    correct = (direction == actual) and direction in ("up", "down")

    return BacktestSample(
        ticker=ticker,
        cutoff=cutoff,
        horizon_days=horizon_days,
        fired_patterns=[p.name for p in fired],
        pattern_directions={p.name: p.direction for p in fired},
        ensemble_direction=direction,
        ensemble_confidence=confidence,
        forward_return_pct=ret,
        actual_label=actual,
        ensemble_correct=correct,
    )


def run_batch(
    universe: list[str],
    horizons: list[int],
    weights: dict[str, float],
    n_samples: int,
    history_years: int,
    min_data_days: int,
    up_threshold: float,
    down_threshold: float,
    seed: int | None = None,
) -> list[BacktestSample]:
    """Run n_samples random backtest samples across `universe` and `horizons`."""
    rng = random.Random(seed)
    samples: list[BacktestSample] = []
    max_horizon = max(horizons)

    # Pre-fetch all tickers once so the loop is fast.
    histories: dict[str, pd.DataFrame] = {}
    for ticker in universe:
        try:
            histories[ticker] = fetch_history_cached(ticker, years=history_years + 2)
        except Exception as e:  # noqa: BLE001
            log.warning("skipping %s: %s", ticker, e)

    eligible = [t for t, df in histories.items() if len(df) > min_data_days + max_horizon + 30]
    if not eligible:
        log.error("no tickers with enough history")
        return samples

    attempts = 0
    max_attempts = n_samples * 4
    while len(samples) < n_samples and attempts < max_attempts:
        attempts += 1
        ticker = rng.choice(eligible)
        df = histories[ticker]
        # valid cutoff range: needs min_data_days behind it AND max_horizon ahead of it
        first_valid = min_data_days
        last_valid = len(df) - max_horizon - 1
        if last_valid <= first_valid:
            continue
        cutoff_idx = rng.randint(first_valid, last_valid)
        cutoff = df.index[cutoff_idx]
        horizon = rng.choice(horizons)
        sample = run_sample(
            ticker=ticker,
            cutoff=cutoff,
            horizon_days=horizon,
            weights=weights,
            up_threshold=up_threshold,
            down_threshold=down_threshold,
        )
        if sample is not None:
            samples.append(sample)

    log.info("backtest completed: %d valid samples (%d attempts)", len(samples), attempts)
    return samples


# ---------------------- Aggregation ----------------------


def aggregate_pattern_accuracy(samples: list[BacktestSample]) -> dict[str, dict]:
    """For each pattern, count how often its directional vote matched the actual move.

    A pattern's "correct" rate is computed standalone — when this pattern fired
    with direction X, how often was the actual label X?
    """
    stats: dict[str, dict[str, int]] = {}
    for s in samples:
        for pat_name, pat_dir in s.pattern_directions.items():
            d = stats.setdefault(pat_name, {"fires": 0, "correct": 0, "by_up": 0, "by_down": 0})
            d["fires"] += 1
            if pat_dir == "up":
                d["by_up"] += 1
            elif pat_dir == "down":
                d["by_down"] += 1
            if pat_dir == s.actual_label and pat_dir in ("up", "down"):
                d["correct"] += 1

    out: dict[str, dict] = {}
    for name, d in stats.items():
        n = d["fires"]
        accuracy = d["correct"] / n if n > 0 else 0.0
        # Bayesian shrinkage toward 0.5 (prior alpha=beta=5)
        shrunk = (d["correct"] + 5) / (n + 10)
        out[name] = {
            "fires": n,
            "correct": d["correct"],
            "raw_accuracy": round(accuracy, 4),
            "shrunk_accuracy": round(shrunk, 4),
            "by_up": d["by_up"],
            "by_down": d["by_down"],
        }
    return out


def aggregate_ensemble_accuracy(samples: list[BacktestSample]) -> dict[str, Any]:
    """Overall ensemble accuracy plus a calibration table by confidence bucket."""
    total = len(samples)
    if total == 0:
        return {"total": 0, "correct": 0, "accuracy": 0.0, "calibration": [], "by_direction": {}}

    correct = sum(1 for s in samples if s.ensemble_correct)
    by_dir: dict[str, dict[str, int]] = {}
    for s in samples:
        if s.ensemble_direction == "neutral":
            continue
        d = by_dir.setdefault(s.ensemble_direction, {"total": 0, "correct": 0})
        d["total"] += 1
        if s.ensemble_correct:
            d["correct"] += 1

    # Calibration buckets by ensemble confidence
    buckets = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
    calibration = []
    for lo, hi in buckets:
        bucket = [s for s in samples if lo <= s.ensemble_confidence < hi and s.ensemble_direction != "neutral"]
        n = len(bucket)
        c = sum(1 for s in bucket if s.ensemble_correct)
        calibration.append({
            "confidence_lo": lo,
            "confidence_hi": hi,
            "n": n,
            "correct": c,
            "accuracy": round(c / n, 4) if n > 0 else None,
        })

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "by_direction": {
            d: {"total": v["total"], "correct": v["correct"], "accuracy": round(v["correct"] / v["total"], 4)}
            for d, v in by_dir.items()
        },
        "calibration": calibration,
    }


def update_weights(
    current_weights: dict[str, float],
    pattern_stats: dict[str, dict],
    learning_rate: float = 0.5,
    floor: float = 0.3,
    ceiling: float = 2.0,
) -> dict[str, float]:
    """Re-weight patterns based on shrunk accuracy.

    A pattern with shrunk_accuracy = 0.6 gets weight 1.2 (assuming base 1.0).
    A pattern with 0.4 gets weight 0.8. Below `floor` gets floor; above `ceiling`
    gets ceiling. `learning_rate` blends new and old weights for smoothing.
    """
    new_weights = dict(current_weights)
    for name, stats in pattern_stats.items():
        # signal = (accuracy - 0.5) * 2 maps 0.5 -> 0, 1.0 -> 1, 0.0 -> -1
        # weight = base * 2^signal so accuracy 0.6 -> 1.15x, 0.7 -> 1.32x
        target = 2 ** ((stats["shrunk_accuracy"] - 0.5) * 2)
        target = max(floor, min(ceiling, target))
        current = current_weights.get(name, 1.0)
        new_weights[name] = (1 - learning_rate) * current + learning_rate * target
    return new_weights
