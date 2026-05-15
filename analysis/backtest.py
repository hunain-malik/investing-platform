"""Backtesting engine — per-horizon, per-regime.

Picks random (ticker, cutoff_date) samples. For each sample, fires all
patterns and tests every requested horizon, comparing the ensemble's
direction to the actual N-day forward return.

Each sample is tagged with the market regime that prevailed at the cutoff
(bull / bear / choppy / unknown) so accuracy can be sliced by regime. Each
sample also stores the fired patterns and their directions so methodologies
can be evaluated in post-processing without re-running the data fetch.
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
from .regime import load_spy, regime_at
from .signals import combine, weights_for_horizon

log = logging.getLogger(__name__)


@dataclass
class BacktestSample:
    ticker: str
    cutoff: pd.Timestamp
    horizon_days: int
    regime: str
    fired_patterns: list[str]
    pattern_directions: dict[str, str]
    ensemble_direction: str
    ensemble_confidence: float
    forward_return_pct: float
    actual_label: str
    ensemble_correct: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "cutoff": self.cutoff.strftime("%Y-%m-%d"),
            "horizon_days": self.horizon_days,
            "regime": self.regime,
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


def _run_one(
    ticker: str,
    df_full: pd.DataFrame,
    cutoff: pd.Timestamp,
    horizon: int,
    regime: str,
    weights_h: dict[str, float],
    up_threshold: float,
    down_threshold: float,
) -> BacktestSample | None:
    df_until = slice_until(df_full, cutoff)
    if len(df_until) < 252:
        return None

    df_ind = compute_all(df_until)
    fired = detect_all(df_ind, idx=-1)
    direction, confidence = combine(fired, weights_h)

    ret = forward_return(df_full, cutoff, horizon)
    if ret is None:
        return None

    actual = _label_return(ret, up_threshold, down_threshold)
    correct = (direction == actual) and direction in ("up", "down")

    return BacktestSample(
        ticker=ticker,
        cutoff=cutoff,
        horizon_days=horizon,
        regime=regime,
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
    weights_per_horizon: dict[str, dict[int, float]],
    n_samples: int,
    history_years: int,
    min_data_days: int,
    up_threshold: float,
    down_threshold: float,
    seed: int | None = None,
) -> list[BacktestSample]:
    rng = random.Random(seed)
    samples: list[BacktestSample] = []
    max_horizon = max(horizons)

    # Pre-fetch all tickers once
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

    # Load SPY once for regime tagging AND for relative-strength patterns
    try:
        spy = load_spy()
        from .indicators import set_benchmark
        set_benchmark(spy)
    except Exception as e:  # noqa: BLE001
        log.warning("could not load SPY for regime detection: %s", e)
        spy = None

    attempts = 0
    max_attempts = n_samples * 4
    while len(samples) < n_samples and attempts < max_attempts:
        attempts += 1
        ticker = rng.choice(eligible)
        df = histories[ticker]
        first_valid = min_data_days
        last_valid = len(df) - max_horizon - 1
        if last_valid <= first_valid:
            continue
        cutoff_idx = rng.randint(first_valid, last_valid)
        cutoff = df.index[cutoff_idx]
        horizon = rng.choice(horizons)

        regime = regime_at(spy, cutoff) if spy is not None else "unknown"
        weights_h = weights_for_horizon(weights_per_horizon, horizon)

        sample = _run_one(
            ticker, df, cutoff, horizon, regime,
            weights_h, up_threshold, down_threshold,
        )
        if sample is not None:
            samples.append(sample)

    log.info("backtest completed: %d valid samples (%d attempts)", len(samples), attempts)
    return samples


# ---------------------- Aggregation ----------------------


def aggregate_pattern_accuracy_per_horizon(
    samples: list[BacktestSample],
) -> dict[str, dict[int, dict]]:
    """For each (pattern, horizon), how often did this pattern's vote match actual?

    Returns {pattern: {horizon: {fires, correct, raw_accuracy, shrunk_accuracy, ...}}}
    """
    stats: dict[str, dict[int, dict]] = {}
    for s in samples:
        for pat_name, pat_dir in s.pattern_directions.items():
            d = stats.setdefault(pat_name, {}).setdefault(s.horizon_days, {
                "fires": 0, "correct": 0, "by_up": 0, "by_down": 0,
            })
            d["fires"] += 1
            if pat_dir == "up":
                d["by_up"] += 1
            elif pat_dir == "down":
                d["by_down"] += 1
            if pat_dir == s.actual_label and pat_dir in ("up", "down"):
                d["correct"] += 1

    out: dict[str, dict[int, dict]] = {}
    for pat, hd in stats.items():
        out[pat] = {}
        for h, d in hd.items():
            n = d["fires"]
            shrunk = (d["correct"] + 5) / (n + 10)
            out[pat][h] = {
                "fires": n,
                "correct": d["correct"],
                "raw_accuracy": round(d["correct"] / n, 4) if n else 0.0,
                "shrunk_accuracy": round(shrunk, 4),
                "by_up": d["by_up"],
                "by_down": d["by_down"],
            }
    return out


def aggregate_by_sector(
    samples: list[BacktestSample],
    ticker_to_sector: dict[str, str],
) -> dict[str, dict]:
    """Per-sector directional accuracy. Asks: do tech stocks follow
    different patterns than pharma?

    For each sector, reports:
        n samples, n directional, accuracy, bullish acc, bearish acc,
        best/worst horizon, best methodology (if patterns_by_methodology
        info is available — not used here, methodologies module handles it).
    """
    stats: dict[str, dict] = {}
    for s in samples:
        sector = ticker_to_sector.get(s.ticker, "Unknown")
        if s.ensemble_direction not in ("up", "down"):
            continue
        d = stats.setdefault(sector, {
            "n": 0, "correct": 0,
            "up": 0, "up_correct": 0,
            "down": 0, "down_correct": 0,
            "by_horizon": {},
        })
        d["n"] += 1
        if s.ensemble_direction == "up":
            d["up"] += 1
            if s.ensemble_correct:
                d["up_correct"] += 1
        else:
            d["down"] += 1
            if s.ensemble_correct:
                d["down_correct"] += 1
        if s.ensemble_correct:
            d["correct"] += 1
        hb = d["by_horizon"].setdefault(s.horizon_days, {"n": 0, "correct": 0})
        hb["n"] += 1
        if s.ensemble_correct:
            hb["correct"] += 1

    out = {}
    for sector, d in stats.items():
        by_h = {}
        best_h, best_acc = None, -1
        for h, hd in sorted(d["by_horizon"].items()):
            acc = hd["correct"] / hd["n"] if hd["n"] else None
            by_h[h] = {"n": hd["n"], "correct": hd["correct"], "accuracy": round(acc, 4) if acc is not None else None}
            if acc is not None and acc > best_acc:
                best_acc = acc
                best_h = h
        out[sector] = {
            "n": d["n"],
            "correct": d["correct"],
            "accuracy": round(d["correct"] / d["n"], 4) if d["n"] else None,
            "up_n": d["up"],
            "up_accuracy": round(d["up_correct"] / d["up"], 4) if d["up"] else None,
            "down_n": d["down"],
            "down_accuracy": round(d["down_correct"] / d["down"], 4) if d["down"] else None,
            "by_horizon": by_h,
            "best_horizon": best_h,
            "best_horizon_accuracy": round(best_acc, 4) if best_h else None,
        }
    return out


def aggregate_methodology_by_sector(
    samples: list[BacktestSample],
    ticker_to_sector: dict[str, str],
    weights_per_horizon: dict[str, dict[int, float]],
) -> dict[str, dict[str, dict]]:
    """For each (sector, methodology), compute accuracy.

    Reveals which methodology works best for which sector.
    Returns: {sector: {methodology_name: {n_signals, n_correct, accuracy}}}
    """
    from .methodologies import METHODOLOGIES, evaluate_methodology
    from .families import evaluate_consensus_families

    out: dict[str, dict[str, dict]] = {}

    # Pass 1: each methodology
    for m in METHODOLOGIES:
        for s in samples:
            sector = ticker_to_sector.get(s.ticker, "Unknown")
            if m.regime_filter is not None and s.regime not in m.regime_filter:
                continue
            r = evaluate_methodology(m, s, weights_per_horizon)
            if r is None:
                continue
            cell = out.setdefault(sector, {}).setdefault(m.name, {"n": 0, "correct": 0})
            cell["n"] += 1
            if r["correct"]:
                cell["correct"] += 1

    # Pass 2: consensus_families (different signature)
    for s in samples:
        sector = ticker_to_sector.get(s.ticker, "Unknown")
        r = evaluate_consensus_families(s.pattern_directions)
        if r is None or r["direction"] not in ("up", "down"):
            continue
        cell = out.setdefault(sector, {}).setdefault("consensus_families", {"n": 0, "correct": 0})
        cell["n"] += 1
        correct = (r["direction"] == s.actual_label)
        if correct:
            cell["correct"] += 1

    # Compute accuracies
    for sector, methods in out.items():
        for name, cell in methods.items():
            cell["accuracy"] = round(cell["correct"] / cell["n"], 4) if cell["n"] else None
    return out


def aggregate_per_ticker(samples: list[BacktestSample], min_samples: int = 10) -> dict[str, dict]:
    """Per-ticker directional accuracy. Tickers with fewer than `min_samples`
    backtest hits are still returned but flagged via the `n` count so the
    dashboard can show them differently."""
    stats: dict[str, dict[str, int]] = {}
    for s in samples:
        if s.ensemble_direction not in ("up", "down"):
            continue
        d = stats.setdefault(s.ticker, {"n": 0, "correct": 0, "up": 0, "down": 0, "up_correct": 0, "down_correct": 0})
        d["n"] += 1
        if s.ensemble_direction == "up":
            d["up"] += 1
            if s.ensemble_correct:
                d["up_correct"] += 1
        else:
            d["down"] += 1
            if s.ensemble_correct:
                d["down_correct"] += 1
        if s.ensemble_correct:
            d["correct"] += 1
    out: dict[str, dict] = {}
    for t, d in stats.items():
        out[t] = {
            "n": d["n"],
            "correct": d["correct"],
            "accuracy": round(d["correct"] / d["n"], 4) if d["n"] else None,
            "up_n": d["up"],
            "up_accuracy": round(d["up_correct"] / d["up"], 4) if d["up"] else None,
            "down_n": d["down"],
            "down_accuracy": round(d["down_correct"] / d["down"], 4) if d["down"] else None,
            "min_samples_met": d["n"] >= min_samples,
        }
    return out


def aggregate_pattern_accuracy_flat(samples: list[BacktestSample]) -> dict[str, dict]:
    """Horizon-agnostic per-pattern stats for the dashboard's at-a-glance view."""
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
        shrunk = (d["correct"] + 5) / (n + 10)
        out[name] = {
            "fires": n,
            "correct": d["correct"],
            "raw_accuracy": round(d["correct"] / n, 4) if n else 0.0,
            "shrunk_accuracy": round(shrunk, 4),
            "by_up": d["by_up"],
            "by_down": d["by_down"],
        }
    return out


def aggregate_ensemble_accuracy(samples: list[BacktestSample]) -> dict[str, Any]:
    total_samples = len(samples)
    if total_samples == 0:
        return {
            "total_samples": 0, "directional_total": 0, "directional_correct": 0,
            "accuracy": None, "neutral_rate": None,
            "calibration": [], "by_direction": {}, "by_horizon": {}, "by_regime": {},
        }

    directional = [s for s in samples if s.ensemble_direction in ("up", "down")]
    neutral_count = total_samples - len(directional)
    correct = sum(1 for s in directional if s.ensemble_correct)

    by_dir: dict[str, dict[str, int]] = {}
    for s in directional:
        d = by_dir.setdefault(s.ensemble_direction, {"total": 0, "correct": 0})
        d["total"] += 1
        if s.ensemble_correct:
            d["correct"] += 1

    by_horizon: dict[int, dict[str, int]] = {}
    for s in directional:
        d = by_horizon.setdefault(s.horizon_days, {"total": 0, "correct": 0})
        d["total"] += 1
        if s.ensemble_correct:
            d["correct"] += 1

    by_regime: dict[str, dict[str, int]] = {}
    for s in directional:
        d = by_regime.setdefault(s.regime, {"total": 0, "correct": 0})
        d["total"] += 1
        if s.ensemble_correct:
            d["correct"] += 1

    buckets = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
    calibration = []
    for lo, hi in buckets:
        bucket = [s for s in directional if lo <= s.ensemble_confidence < hi]
        n = len(bucket)
        c = sum(1 for s in bucket if s.ensemble_correct)
        calibration.append({
            "confidence_lo": lo, "confidence_hi": hi,
            "n": n, "correct": c,
            "accuracy": round(c / n, 4) if n > 0 else None,
        })

    return {
        "total_samples": total_samples,
        "directional_total": len(directional),
        "directional_correct": correct,
        "accuracy": round(correct / len(directional), 4) if directional else None,
        "neutral_rate": round(neutral_count / total_samples, 4),
        "by_direction": {
            d: {"total": v["total"], "correct": v["correct"],
                "accuracy": round(v["correct"] / v["total"], 4)}
            for d, v in by_dir.items()
        },
        "by_horizon": {
            h: {"total": v["total"], "correct": v["correct"],
                "accuracy": round(v["correct"] / v["total"], 4)}
            for h, v in sorted(by_horizon.items())
        },
        "by_regime": {
            r: {"total": v["total"], "correct": v["correct"],
                "accuracy": round(v["correct"] / v["total"], 4)}
            for r, v in by_regime.items()
        },
        "calibration": calibration,
    }


# ---------------------- Weight updates ----------------------


def update_weights_per_horizon(
    current: dict[str, dict[int, float]],
    pattern_stats: dict[str, dict[int, dict]],
    learning_rate: float = 0.5,
    floor: float = 0.3,
    ceiling: float = 2.0,
) -> dict[str, dict[int, float]]:
    """Re-weight each (pattern, horizon) toward 2^((shrunk_acc - 0.5) * 2)."""
    new: dict[str, dict[int, float]] = {p: dict(hw) for p, hw in current.items()}
    for pattern, hd in pattern_stats.items():
        new.setdefault(pattern, {})
        for horizon, stats in hd.items():
            target = 2 ** ((stats["shrunk_accuracy"] - 0.5) * 2)
            target = max(floor, min(ceiling, target))
            cur = current.get(pattern, {}).get(horizon, 1.0)
            new[pattern][horizon] = (1 - learning_rate) * cur + learning_rate * target
    return new
