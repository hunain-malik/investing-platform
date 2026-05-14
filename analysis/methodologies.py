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
        description="SMA/MACD crossovers + multi-timeframe alignment + relative strength",
        pattern_filter=frozenset({
            "sma_crossover_bull", "sma_crossover_bear",
            "golden_cross", "death_cross",
            "macd_cross_bull", "macd_cross_bear",
            "multi_timeframe_bull", "multi_timeframe_bear",
            "relative_strength_bull", "relative_strength_bear",
        }),
    ),
    Methodology(
        name="mean_reversion",
        description="RSI extremes, Bollinger squeezes, doji at S/R, volume dry-up/dry-top",
        pattern_filter=frozenset({
            "rsi_oversold", "rsi_overbought",
            "bb_squeeze_breakout_up", "bb_squeeze_breakout_down",
            "doji_at_support", "doji_at_resistance",
            "volume_dry_up", "volume_dry_top",
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
        name="volume_driven",
        description="Volume-based conviction patterns (breakouts and dry-ups)",
        pattern_filter=frozenset({
            "volume_breakout_bull", "volume_breakout_bear",
            "volume_dry_up", "volume_dry_top",
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
            "relative_strength_bull", "relative_strength_bear",
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


def evaluate_meta_ensemble(
    sample,
    weights_per_horizon,
    methodology_acc_per_horizon: dict[str, dict[int, float]],
    min_methodologies_bull: int = 2,
    min_methodologies_bear: int = 3,
) -> dict | None:
    """Stacked / holistic ensemble. Per-horizon filtering.

    Each sub-methodology votes if (a) it fires for this sample AND
    (b) its accuracy AT THIS HORIZON is above 50%. A methodology can be
    great at 252d but useless at 5d, so the filter has to be horizon-specific.

    Surviving votes are weighted by (per-horizon accuracy - 0.5) * 2.
    Requires >= min_methodologies and vote margin >= 15%.
    """
    h = sample.horizon_days
    votes: list[tuple[str, float, float, str]] = []
    for m in METHODOLOGIES:
        if m.name == "meta_ensemble":
            continue
        h_acc = methodology_acc_per_horizon.get(m.name, {}).get(h)
        if h_acc is None or h_acc < 0.5:
            continue
        r = evaluate_methodology(m, sample, weights_per_horizon)
        if r is None:
            continue
        w_meth = (h_acc - 0.5) * 2
        votes.append((r["direction"], float(r["confidence"]), w_meth, m.name))

    up_votes = [v for v in votes if v[0] == "up"]
    down_votes = [v for v in votes if v[0] == "down"]
    up_score = sum(c * w for _, c, w, _ in up_votes)
    down_score = sum(c * w for _, c, w, _ in down_votes)
    total = up_score + down_score
    if total == 0:
        return None
    margin = (up_score - down_score) / total
    if abs(margin) < 0.15:
        return None

    # Asymmetric quorum: bearish calls need more methodologies agreeing because
    # markets drift up, so a "down" prediction has higher hurdle to clear.
    if margin > 0 and len(up_votes) < min_methodologies_bull:
        return None
    if margin < 0 and len(down_votes) < min_methodologies_bear:
        return None

    direction = "up" if margin > 0 else "down"
    agreement = abs(margin)
    intensity = min(1.0, total / 1.5)
    confidence = 0.5 + 0.5 * agreement * intensity

    correct = (direction == sample.actual_label)
    return {
        "direction": direction,
        "confidence": confidence,
        "correct": correct,
        "contributing_methodologies": [n for _, _, _, n in votes],
        "vote_margin": round(margin, 4),
    }


def evaluate_meta_live(
    fired_patterns: list,        # list[PatternSignal]
    regime: str,
    horizon: int,
    weights_per_horizon,
    methodology_acc_per_horizon: dict[str, dict[int, float]],
    min_methodologies_bull: int = 2,
    min_methodologies_bear: int = 3,
) -> dict | None:
    """Same logic as `evaluate_meta_ensemble` but operates on live data
    (fired PatternSignal objects, not a stored BacktestSample).
    Per-horizon accuracy filtering — a method only votes if its accuracy
    AT THIS HORIZON is above 50%.
    """
    weights_h = {p: hw.get(horizon, 1.0) for p, hw in weights_per_horizon.items()}
    votes = []
    contributing_details = []
    for m in METHODOLOGIES:
        if m.name == "meta_ensemble":
            continue
        if m.regime_filter is not None and regime not in m.regime_filter:
            continue
        h_acc = methodology_acc_per_horizon.get(m.name, {}).get(horizon)
        if h_acc is None or h_acc < 0.5:
            continue
        if m.pattern_filter is not None:
            filtered = [p for p in fired_patterns if p.name in m.pattern_filter]
        else:
            filtered = list(fired_patterns)
        if not filtered:
            continue
        direction, confidence = combine(filtered, weights_h)
        if direction == "neutral" or confidence < m.min_confidence:
            continue
        w_meth = (h_acc - 0.5) * 2
        votes.append((direction, confidence, w_meth, m.name))
        contributing_details.append({
            "methodology": m.name,
            "direction": direction,
            "confidence": round(confidence, 4),
            "weight": round(w_meth, 4),
            "accuracy": round(h_acc, 4),
        })

    up_votes = [v for v in votes if v[0] == "up"]
    down_votes = [v for v in votes if v[0] == "down"]
    up_score = sum(c * w for _, c, w, _ in up_votes)
    down_score = sum(c * w for _, c, w, _ in down_votes)
    total = up_score + down_score
    if total == 0:
        return None
    margin = (up_score - down_score) / total
    if abs(margin) < 0.15:
        return None

    if margin > 0 and len(up_votes) < min_methodologies_bull:
        return None
    if margin < 0 and len(down_votes) < min_methodologies_bear:
        return None

    direction = "up" if margin > 0 else "down"
    agreement = abs(margin)
    intensity = min(1.0, total / 1.5)
    confidence = 0.5 + 0.5 * agreement * intensity
    return {
        "direction": direction,
        "confidence": confidence,
        "vote_margin": round(margin, 4),
        "contributing_methodologies": contributing_details,
        "n_contributing": len(votes),
    }


def aggregate_meta_ensemble(
    samples,
    weights_per_horizon,
    methodology_acc_per_horizon: dict[str, dict[int, float]],
) -> dict:
    """Evaluate meta-ensemble against all samples using per-horizon methodology
    accuracies as voting weights. Returns stats matching the schema of
    `aggregate_methodology_accuracy` per methodology."""
    n_signal = 0
    n_correct = 0
    by_horizon: dict[int, dict[str, int]] = {}
    by_regime: dict[str, dict[str, int]] = {}
    method_contribution: dict[str, int] = {}

    for s in samples:
        r = evaluate_meta_ensemble(s, weights_per_horizon, methodology_acc_per_horizon)
        if r is None:
            continue
        n_signal += 1
        if r["correct"]:
            n_correct += 1
        hb = by_horizon.setdefault(s.horizon_days, {"signals": 0, "correct": 0})
        hb["signals"] += 1
        if r["correct"]:
            hb["correct"] += 1
        rb = by_regime.setdefault(s.regime, {"signals": 0, "correct": 0})
        rb["signals"] += 1
        if r["correct"]:
            rb["correct"] += 1
        for mname in r["contributing_methodologies"]:
            method_contribution[mname] = method_contribution.get(mname, 0) + 1

    return {
        "description": "Holistic meta-ensemble: stacked vote across sub-methodologies, weighted by each sub-method's backtest accuracy",
        "samples_applicable": len(samples),
        "signals_emitted": n_signal,
        "correct": n_correct,
        "accuracy": round(n_correct / n_signal, 4) if n_signal else None,
        "signal_rate": round(n_signal / len(samples), 4) if samples else None,
        "by_horizon": {
            h: {
                "signals": v["signals"],
                "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None,
            }
            for h, v in sorted(by_horizon.items())
        },
        "by_regime": {
            r: {
                "signals": v["signals"],
                "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None,
            }
            for r, v in by_regime.items()
        },
        "methodology_contribution_count": method_contribution,
        "sub_methodology_accuracies_used": {
            k: {str(h): round(v, 4) for h, v in hd.items()}
            for k, hd in methodology_acc_per_horizon.items()
        },
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
