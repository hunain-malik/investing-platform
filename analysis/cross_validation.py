"""K-fold cross-validation for the meta-ensemble.

The naive meta-ensemble accuracy computed by `aggregate_meta_ensemble` is
in-sample: methodology accuracies are computed from the same samples the
meta is then evaluated on. The number tends to be optimistic.

This module runs K-fold CV: for each fold, methodology accuracies are
computed on the OTHER K-1 folds and the meta is evaluated on the held-out
fold. The aggregated meta accuracy is then a fair estimate of how the
meta would perform on unseen data.
"""

from __future__ import annotations

import random
from collections import defaultdict

from .methodologies import METHODOLOGIES, evaluate_methodology, evaluate_meta_ensemble
from .families import evaluate_consensus_families


def _methodology_acc_per_horizon_from_subset(samples, weights_per_horizon):
    """Replicates aggregate_methodology_accuracy's per-horizon accuracy
    computation but only on a subset of samples (used for the train fold)."""
    acc: dict[str, dict[int, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"signals": 0, "correct": 0}))
    for m in METHODOLOGIES:
        for s in samples:
            if m.regime_filter is not None and s.regime not in m.regime_filter:
                continue
            r = evaluate_methodology(m, s, weights_per_horizon)
            if r is None:
                continue
            cell = acc[m.name][s.horizon_days]
            cell["signals"] += 1
            if r["correct"]:
                cell["correct"] += 1
    out: dict[str, dict[int, float]] = {}
    for name, hd in acc.items():
        out[name] = {}
        for h, cell in hd.items():
            if cell["signals"]:
                out[name][h] = cell["correct"] / cell["signals"]
    return out


def _sector_methodology_acc_from_subset(samples, ticker_to_sector, weights_per_horizon):
    """Per-(sector, methodology) accuracy from a subset of samples.
    Used by sector-aware K-fold to compute sector-specific weights from
    the training fold only.
    """
    acc: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "correct": 0}))
    for m in METHODOLOGIES:
        for s in samples:
            sector = ticker_to_sector.get(s.ticker, "Unknown")
            if m.regime_filter is not None and s.regime not in m.regime_filter:
                continue
            r = evaluate_methodology(m, s, weights_per_horizon)
            if r is None:
                continue
            cell = acc[sector][m.name]
            cell["n"] += 1
            if r["correct"]:
                cell["correct"] += 1
    # Add consensus_families per sector
    for s in samples:
        sector = ticker_to_sector.get(s.ticker, "Unknown")
        r = evaluate_consensus_families(s.pattern_directions)
        if r is None or r["direction"] not in ("up", "down"):
            continue
        cell = acc[sector]["consensus_families"]
        cell["n"] += 1
        if r["direction"] == s.actual_label:
            cell["correct"] += 1
    out: dict[str, dict[str, dict]] = {}
    for sector, methods in acc.items():
        out[sector] = {}
        for name, cell in methods.items():
            out[sector][name] = {
                "n": cell["n"],
                "correct": cell["correct"],
                "accuracy": (cell["correct"] / cell["n"]) if cell["n"] else None,
            }
    return out


def kfold_meta_accuracy_sector_aware(
    samples,
    ticker_to_sector: dict[str, str],
    weights_per_horizon,
    k: int = 5,
    seed: int = 1729,
) -> dict:
    """K-fold cross-validation of the meta-ensemble WITH sector-aware
    methodology weighting. For each fold:
      1. Compute per-horizon AND per-(sector, methodology) accuracy from
         the training folds.
      2. Evaluate meta on the held-out fold using BOTH weight sources;
         sector overrides per-horizon where samples permit.

    Apples-to-apples comparable with kfold_meta_accuracy (same protocol,
    just adds sector-aware weighting). Run BOTH to measure the lift.
    """
    n = len(samples)
    if n < k * 50:
        return {"k": k, "n_samples": n, "accuracy": None, "note": "Not enough samples"}

    rng = random.Random(seed)
    indices = list(range(n))
    rng.shuffle(indices)
    folds = [indices[i::k] for i in range(k)]

    total_correct = 0
    total_signals = 0
    by_horizon: dict[int, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_regime: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_direction: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_sector: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})

    for fold_idx in range(k):
        test_idx = set(folds[fold_idx])
        train = [samples[i] for i in indices if i not in test_idx]
        test = [samples[i] for i in folds[fold_idx]]

        method_acc = _methodology_acc_per_horizon_from_subset(train, weights_per_horizon)
        sector_method_acc = _sector_methodology_acc_from_subset(train, ticker_to_sector, weights_per_horizon)

        for s in test:
            ticker_sector = ticker_to_sector.get(s.ticker)
            r = evaluate_meta_ensemble(
                s, weights_per_horizon, method_acc,
                sector=ticker_sector,
                sector_methodology_acc=sector_method_acc,
            )
            if r is None:
                continue
            total_signals += 1
            if r["correct"]:
                total_correct += 1
            for bucket, key in [
                (by_horizon, s.horizon_days),
                (by_regime, s.regime),
                (by_direction, r["direction"]),
                (by_sector, ticker_sector or "Unknown"),
            ]:
                cell = bucket[key]
                cell["signals"] += 1
                if r["correct"]:
                    cell["correct"] += 1

    def _stat(d):
        return {
            k_: {
                "signals": v["signals"],
                "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None,
            }
            for k_, v in d.items()
        }

    return {
        "k": k,
        "n_samples": n,
        "signals_emitted": total_signals,
        "correct": total_correct,
        "accuracy": round(total_correct / total_signals, 4) if total_signals else None,
        "signal_rate": round(total_signals / n, 4) if n else None,
        "by_horizon": _stat(by_horizon),
        "by_regime": _stat(by_regime),
        "by_direction": _stat(by_direction),
        "by_sector": _stat(by_sector),
        "method": "sector_aware",
    }


def kfold_meta_accuracy(samples, weights_per_horizon, k: int = 5, seed: int = 1729) -> dict:
    """Run K-fold cross-validation on the meta-ensemble.

    Returns aggregate out-of-sample stats plus per-horizon and per-regime
    breakouts.
    """
    n = len(samples)
    if n < k * 50:  # need enough samples to make folds meaningful
        return {
            "k": k, "n_samples": n,
            "accuracy": None,
            "note": "Not enough samples for meaningful k-fold (need >= k * 50)",
        }

    rng = random.Random(seed)
    indices = list(range(n))
    rng.shuffle(indices)
    folds = [indices[i::k] for i in range(k)]

    total_correct = 0
    total_signals = 0
    by_horizon: dict[int, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_regime: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_direction: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "correct": 0})

    for fold_idx in range(k):
        test_idx = set(folds[fold_idx])
        train = [samples[i] for i in indices if i not in test_idx]
        test = [samples[i] for i in folds[fold_idx]]

        method_acc = _methodology_acc_per_horizon_from_subset(train, weights_per_horizon)

        for s in test:
            r = evaluate_meta_ensemble(s, weights_per_horizon, method_acc)
            if r is None:
                continue
            total_signals += 1
            if r["correct"]:
                total_correct += 1
            bh = by_horizon[s.horizon_days]
            bh["signals"] += 1
            if r["correct"]:
                bh["correct"] += 1
            br = by_regime[s.regime]
            br["signals"] += 1
            if r["correct"]:
                br["correct"] += 1
            bd = by_direction[r["direction"]]
            bd["signals"] += 1
            if r["correct"]:
                bd["correct"] += 1

    return {
        "k": k,
        "n_samples": n,
        "signals_emitted": total_signals,
        "correct": total_correct,
        "accuracy": round(total_correct / total_signals, 4) if total_signals else None,
        "signal_rate": round(total_signals / n, 4) if n else None,
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
        "by_direction": {
            d: {
                "signals": v["signals"],
                "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None,
            }
            for d, v in by_direction.items()
        },
    }
