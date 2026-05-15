"""Main analysis orchestrator. Daily entry point.

Pipeline:
    1. Load config + per-horizon pattern weights (migrate flat weights if needed).
    2. Resolve any open predictions whose horizon has elapsed.
    3. Run backtest batch FIRST so we know each methodology's current accuracy.
    4. Aggregate per-pattern, per-horizon, per-regime accuracy.
    5. Evaluate each named methodology + the holistic meta-ensemble.
    6. Update per-horizon pattern weights from backtest accuracy.
    7. Generate live signals per (ticker, horizon) using updated weights AND
       the holistic meta-ensemble using fresh methodology accuracies.
    8. Write JSON outputs to docs/data/.

The backtest-before-live ordering means the meta-ensemble's vote on live data
uses the most recent backtest's methodology accuracies — methodologies below
chance get dropped before they influence today's actionable recommendation.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from .backtest import (
    aggregate_ensemble_accuracy,
    aggregate_pattern_accuracy_flat,
    aggregate_pattern_accuracy_per_horizon,
    aggregate_per_ticker,
    run_batch,
    update_weights_per_horizon,
)
from .cross_validation import kfold_meta_accuracy
from .data import fetch_history_cached
from .earnings import days_until_earnings
from .numerical_model import evaluate_numerical_model
from .indicators import compute_all
from .families import evaluate_consensus_families_live
from .methodologies import (
    METHODOLOGIES,
    aggregate_consensus_families,
    aggregate_meta_ensemble,
    aggregate_methodology_accuracy,
    evaluate_meta_live,
)
from .options import recommend_options
from .patterns import detect_all
from .regime import load_spy, regime_at
from .scoreboard import (
    aggregate_scoreboard,
    load_predictions,
    log_predictions_from_signal,
    resolve_due_predictions,
    save_predictions,
)
from .sentiment import fetch_sentiment
from .signals import EnsembleSignal, analyze_all_horizons
from .sizing import size_position
from .universe import backtest_universe, watchlist

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.yaml"
STATE_DIR = ROOT / "state"
DATA_DIR = ROOT / "docs" / "data"
WEIGHTS_FILE = STATE_DIR / "weights.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))


def _initial_weights_per_horizon(config: dict) -> dict[str, dict[int, float]]:
    flat = config.get("pattern_weights", {}) or {}
    horizons = config["horizons_days"]
    return {p: {h: float(w) for h in horizons} for p, w in flat.items()}


def load_weights(config: dict) -> dict[str, dict[int, float]]:
    horizons = config["horizons_days"]
    if WEIGHTS_FILE.exists():
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        raw = data.get("weights", {})
        out: dict[str, dict[int, float]] = {}
        for p, v in raw.items():
            if isinstance(v, dict):
                out[p] = {int(h): float(w) for h, w in v.items()}
            else:
                out[p] = {h: float(v) for h in horizons}
        # Ensure all horizons present (new horizons added via config get default 1.0)
        for p in out:
            for h in horizons:
                out[p].setdefault(h, 1.0)
        if out:
            return out
    return _initial_weights_per_horizon(config)


def save_weights(weights: dict[str, dict[int, float]], meta: dict) -> None:
    payload = {
        "updated_at": _ts(),
        "weights": {p: {str(h): w for h, w in hw.items()} for p, hw in weights.items()},
        "meta": meta,
    }
    WEIGHTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    STATE_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    weights = load_weights(config)
    horizons = config["horizons_days"]
    portfolio = config["portfolio"]
    bt_cfg = config["backtest"]
    sig_cfg = config["signals"]

    # Watchlist and backtest universe — fall back to universe.py defaults
    watchlist_tickers = config.get("watchlist") or watchlist()
    bt_universe = config.get("backtest_universe") or backtest_universe()

    # ---- 1. Resolve any open predictions whose horizon has elapsed --------
    predictions = load_predictions()
    predictions, resolved = resolve_due_predictions(
        predictions,
        up_threshold=bt_cfg["threshold_up_pct"],
        down_threshold=bt_cfg["threshold_down_pct"],
    )
    log.info("resolved %d predictions", resolved)

    # ---- 2. Run backtest FIRST so methodology accuracies are known --------
    log.info("running backtest: %d samples across horizons %s",
             bt_cfg["samples_per_run"], horizons)
    samples = run_batch(
        universe=bt_universe,
        horizons=horizons,
        weights_per_horizon=weights,
        n_samples=bt_cfg["samples_per_run"],
        history_years=bt_cfg["history_years"],
        min_data_days=bt_cfg["min_data_days"],
        up_threshold=bt_cfg["threshold_up_pct"],
        down_threshold=bt_cfg["threshold_down_pct"],
        seed=None,
    )

    # ---- 3. Aggregate accuracies + evaluate methodologies -----------------
    ensemble_acc = aggregate_ensemble_accuracy(samples)
    pattern_acc_flat = aggregate_pattern_accuracy_flat(samples)
    pattern_acc_per_h = aggregate_pattern_accuracy_per_horizon(samples)
    methodology_stats = aggregate_methodology_accuracy(samples, weights)

    # Meta ensemble uses each methodology's per-horizon accuracy as its
    # voting weight. A methodology that's bad at 5d but great at 252d should
    # vote on 252d samples only.
    method_acc_per_h: dict[str, dict[int, float]] = {}
    for name, s in methodology_stats.items():
        by_h = s.get("by_horizon", {}) or {}
        method_acc_per_h[name] = {
            int(h): float(v["accuracy"]) for h, v in by_h.items()
            if v.get("accuracy") is not None
        }
    methodology_stats["meta_ensemble"] = aggregate_meta_ensemble(
        samples, weights, method_acc_per_h,
    )
    # Decorrelated family-based meta — patterns grouped into 6 independent
    # families, each casts one vote. Addresses the correlated-methodology
    # vote-inflation issue.
    consensus_families_stats = aggregate_consensus_families(samples)
    methodology_stats["consensus_families"] = consensus_families_stats

    # Extract per-horizon family accuracies for use in LIVE signal generation
    family_acc_per_h_for_live: dict[int, dict[str, float]] = {}
    for fam_name, hd in (consensus_families_stats.get("family_accuracies_per_horizon", {})).items():
        for h_str, acc in hd.items():
            h = int(h_str)
            family_acc_per_h_for_live.setdefault(h, {})[fam_name] = float(acc)

    # Auto-prune methodologies whose accuracy is below 0.5 at EVERY horizon
    # they had data for. These are net-harmful and shouldn't be acted on.
    pruned: list[str] = []
    for name, stats in methodology_stats.items():
        if name == "meta_ensemble":
            continue
        by_h = stats.get("by_horizon", {}) or {}
        if not by_h:
            continue
        accs = [v.get("accuracy") for v in by_h.values() if v.get("accuracy") is not None]
        if accs and all(a < 0.5 for a in accs):
            pruned.append(name)
            stats["pruned"] = True
        else:
            stats["pruned"] = False

    # K-fold cross-validated meta accuracy — the honest, out-of-sample number
    kfold_result = kfold_meta_accuracy(samples, weights, k=5)

    # Numerical-model methodology: pure logistic regression on continuous features,
    # K-fold evaluated. Tests if a mathematical model beats pattern recognition.
    log.info("running numerical-model benchmark...")
    numerical_result = evaluate_numerical_model(samples)

    # Per-ticker accuracy
    per_ticker_stats = aggregate_per_ticker(samples)

    # ---- 4. Update per-horizon pattern weights from backtest --------------
    if pattern_acc_per_h:
        old_weights = {p: dict(hw) for p, hw in weights.items()}
        weights = update_weights_per_horizon(weights, pattern_acc_per_h)
        save_weights(weights, meta={"n_samples": len(samples), "previous_weights": old_weights})

    # ---- 5. Generate live signals (per horizon) using updated weights ----
    live_signals = []
    live_meta_signals = []
    live_consensus_signals = []
    sentiments_by_ticker: dict[str, dict] = {}

    # Load SPY once for live regime detection AND relative-strength patterns
    try:
        spy_df = load_spy()
        from .indicators import set_benchmark
        set_benchmark(spy_df)
        # Use the most recent bar from SPY's own index as the "current" cutoff
        # to avoid timezone mismatches with the naive yfinance index.
        latest_spy_date = spy_df.index[-1]
        live_regime = regime_at(spy_df, latest_spy_date)
    except Exception as e:  # noqa: BLE001
        log.warning("could not compute live regime: %s", e)
        live_regime = "unknown"

    for ticker in watchlist_tickers:
        try:
            df = fetch_history_cached(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("skipping %s: %s", ticker, e)
            continue
        if len(df) < 252:
            continue

        horizon_signals = analyze_all_horizons(ticker, df, weights, horizons)

        # Compute fired patterns once for meta evaluation (same for all horizons)
        df_ind = compute_all(df)
        fired_today = detect_all(df_ind, idx=-1)

        # Only fetch sentiment + earnings for tickers that actually fired a
        # pattern (avoid hundreds of unnecessary yfinance calls per run)
        ticker_earnings_days: int | None = None
        if fired_today:
            sentiment = fetch_sentiment(ticker)
            if sentiment is not None:
                sentiments_by_ticker[ticker] = sentiment.to_dict()
            try:
                ticker_earnings_days = days_until_earnings(ticker)
            except Exception:  # noqa: BLE001
                ticker_earnings_days = None

        for sig in horizon_signals:
            sig_dict = sig.to_dict()
            sig_dict["sentiment"] = sentiments_by_ticker.get(ticker)
            sig_dict["regime"] = live_regime

            sizing_plan = None
            options_plan = None
            if sig.direction in ("up", "down") and sig.confidence >= sig_cfg["min_confidence"]:
                sizing_plan = size_position(
                    direction=sig.direction,
                    entry=sig.price, atr=sig.atr, confidence=sig.confidence,
                    capital_usd=portfolio["capital_usd"],
                    risk_per_trade_pct=portfolio["risk_per_trade_pct"],
                    max_position_pct=portfolio["max_position_pct"],
                )
                options_plan = recommend_options(
                    direction=sig.direction, confidence=sig.confidence,
                    spot=sig.price, atr=sig.atr,
                    horizon_days=sig.horizon_days,
                    options_allowed=portfolio.get("options_allowed", True),
                )
                if len(sig.fired_patterns) >= sig_cfg["min_patterns_for_signal"]:
                    predictions = log_predictions_from_signal(
                        sig, [sig.horizon_days], sig_cfg["min_confidence"], predictions
                    )
            sig_dict["sizing"] = sizing_plan.to_dict() if sizing_plan else None
            sig_dict["options"] = options_plan.to_dict() if options_plan else None
            live_signals.append(sig_dict)

            # Meta-ensemble live evaluation using per-horizon methodology accs
            meta = evaluate_meta_live(
                fired_patterns=fired_today,
                regime=live_regime,
                horizon=sig.horizon_days,
                weights_per_horizon=weights,
                methodology_acc_per_horizon=method_acc_per_h,
            )
            # Consensus families live evaluation (decorrelated)
            fam_acc_at_h = family_acc_per_h_for_live.get(sig.horizon_days, {})
            consensus = evaluate_consensus_families_live(
                fired_today,
                family_accuracies_at_horizon=fam_acc_at_h if fam_acc_at_h else None,
            )
            if consensus is not None:
                cons_sizing = size_position(
                    direction=consensus["direction"], entry=sig.price, atr=sig.atr,
                    confidence=consensus["confidence"],
                    capital_usd=portfolio["capital_usd"],
                    risk_per_trade_pct=portfolio["risk_per_trade_pct"],
                    max_position_pct=portfolio["max_position_pct"],
                )
                cons_options = recommend_options(
                    direction=consensus["direction"], confidence=consensus["confidence"],
                    spot=sig.price, atr=sig.atr, horizon_days=sig.horizon_days,
                    options_allowed=portfolio.get("options_allowed", True),
                )
                live_consensus_signals.append({
                    "ticker": ticker,
                    "as_of": sig.as_of.strftime("%Y-%m-%d"),
                    "horizon_days": sig.horizon_days,
                    "regime": live_regime,
                    "direction": consensus["direction"],
                    "confidence": round(consensus["confidence"], 4),
                    "vote_margin": consensus["vote_margin"],
                    "n_families": consensus["n_families"],
                    "contributing_families": consensus["contributing_families"],
                    "price": round(sig.price, 4),
                    "atr": round(sig.atr, 4),
                    "sentiment": sentiments_by_ticker.get(ticker),
                    "earnings_in_days": ticker_earnings_days,
                    "earnings_in_horizon": (ticker_earnings_days is not None and ticker_earnings_days <= sig.horizon_days),
                    "sizing": cons_sizing.to_dict() if cons_sizing else None,
                    "options": cons_options.to_dict() if cons_options else None,
                })

            if meta is not None:
                meta_sizing = size_position(
                    direction=meta["direction"], entry=sig.price, atr=sig.atr,
                    confidence=meta["confidence"],
                    capital_usd=portfolio["capital_usd"],
                    risk_per_trade_pct=portfolio["risk_per_trade_pct"],
                    max_position_pct=portfolio["max_position_pct"],
                )
                meta_options = recommend_options(
                    direction=meta["direction"], confidence=meta["confidence"],
                    spot=sig.price, atr=sig.atr, horizon_days=sig.horizon_days,
                    options_allowed=portfolio.get("options_allowed", True),
                )
                # Flag if earnings hit before the horizon closes (event risk)
                earnings_in_horizon = (
                    ticker_earnings_days is not None
                    and ticker_earnings_days <= sig.horizon_days
                )

                live_meta_signals.append({
                    "ticker": ticker,
                    "as_of": sig.as_of.strftime("%Y-%m-%d"),
                    "horizon_days": sig.horizon_days,
                    "regime": live_regime,
                    "direction": meta["direction"],
                    "confidence": round(meta["confidence"], 4),
                    "vote_margin": meta["vote_margin"],
                    "n_contributing": meta["n_contributing"],
                    "contributing_methodologies": meta["contributing_methodologies"],
                    "price": round(sig.price, 4),
                    "atr": round(sig.atr, 4),
                    "sentiment": sentiments_by_ticker.get(ticker),
                    "earnings_in_days": ticker_earnings_days,
                    "earnings_in_horizon": earnings_in_horizon,
                    "sizing": meta_sizing.to_dict() if meta_sizing else None,
                    "options": meta_options.to_dict() if meta_options else None,
                })

                # Log a meta prediction for the live scoreboard
                if meta["confidence"] >= sig_cfg["min_confidence"]:
                    meta_pseudo_signal = EnsembleSignal(
                        ticker=ticker,
                        as_of=sig.as_of,
                        horizon_days=sig.horizon_days,
                        direction=meta["direction"],
                        confidence=meta["confidence"],
                        fired_patterns=sig.fired_patterns,
                        price=sig.price,
                        atr=sig.atr,
                        methodology="meta_ensemble",
                    )
                    predictions = log_predictions_from_signal(
                        meta_pseudo_signal, [sig.horizon_days],
                        sig_cfg["min_confidence"], predictions,
                    )

    # ---- 6. Save predictions and dashboard JSON --------------------------
    save_predictions(predictions)
    scoreboard = aggregate_scoreboard(predictions)

    write_json(DATA_DIR / "signals.json", {
        "updated_at": _ts(),
        "live_regime": live_regime,
        "signals": live_signals,
        "meta_signals": live_meta_signals,
        "consensus_signals": live_consensus_signals,
        "sentiments": sentiments_by_ticker,
    })
    write_json(DATA_DIR / "predictions.json", {
        "updated_at": _ts(),
        "predictions": [p.to_dict() for p in predictions],
    })
    write_json(DATA_DIR / "scoreboard.json", scoreboard)
    write_json(DATA_DIR / "backtest.json", {
        "updated_at": _ts(),
        "n_samples": len(samples),
        "ensemble": ensemble_acc,
        "patterns_flat": pattern_acc_flat,
        "patterns_per_horizon": pattern_acc_per_h,
        "per_ticker": per_ticker_stats,
    })
    write_json(DATA_DIR / "methodologies.json", {
        "updated_at": _ts(),
        "n_samples": len(samples),
        "meta_kfold": kfold_result,
        "numerical_model_kfold": numerical_result,
        "pruned": pruned,
        "methodologies": methodology_stats,
        "definitions": [
            {"name": m.name, "description": m.description,
             "pattern_filter": sorted(m.pattern_filter) if m.pattern_filter else None,
             "regime_filter": sorted(m.regime_filter) if m.regime_filter else None,
             "min_confidence": m.min_confidence}
            for m in METHODOLOGIES
        ] + [{
            "name": "meta_ensemble",
            "description": "Holistic meta-ensemble: stacked vote across the others, weighted by each sub-method's backtest accuracy",
            "pattern_filter": None,
            "regime_filter": None,
            "min_confidence": 0.50,
        }],
    })
    write_json(DATA_DIR / "weights.json", {
        "updated_at": _ts(),
        "weights": {p: {str(h): w for h, w in hw.items()} for p, hw in weights.items()},
    })

    log.info(
        "done. live regime: %s. signals: %d ensemble + %d meta. "
        "backtest samples: %d. open preds: %d. resolved preds: %d.",
        live_regime, len(live_signals), len(live_meta_signals), len(samples),
        scoreboard["open_predictions"], scoreboard["total_resolved"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
