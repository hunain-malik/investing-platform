"""Main analysis orchestrator. Daily entry point.

Pipeline:
    1. Load config + per-horizon pattern weights (migrate flat weights if needed).
    2. Resolve any open predictions whose horizon has elapsed.
    3. For each watchlist ticker:
         - Fetch data, fetch sentiment.
         - For each horizon, generate ensemble signal with horizon-specific weights.
         - For actionable signals (confidence >= min_confidence), attach sizing +
           options recommendations + sentiment context, and log a prediction.
    4. Run backtest batch (random ticker × random cutoff × random horizon),
       tagging each sample with the prevailing market regime.
    5. Aggregate per-pattern, per-horizon, per-regime accuracy.
    6. Evaluate each named methodology against the same backtest samples.
    7. Update per-horizon weights from backtest accuracy.
    8. Write JSON outputs to docs/data/.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .backtest import (
    aggregate_ensemble_accuracy,
    aggregate_pattern_accuracy_flat,
    aggregate_pattern_accuracy_per_horizon,
    run_batch,
    update_weights_per_horizon,
)
from .data import fetch_history_cached
from .methodologies import METHODOLOGIES, aggregate_methodology_accuracy
from .options import recommend_options
from .scoreboard import (
    aggregate_scoreboard,
    load_predictions,
    log_predictions_from_signal,
    resolve_due_predictions,
    save_predictions,
)
from .sentiment import fetch_sentiment
from .signals import analyze_all_horizons
from .sizing import size_position

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
    """Load per-horizon weights. Migrate flat weights from older state files."""
    horizons = config["horizons_days"]
    if WEIGHTS_FILE.exists():
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        raw = data.get("weights", {})
        out: dict[str, dict[int, float]] = {}
        for p, v in raw.items():
            if isinstance(v, dict):
                # already per-horizon — keys may be strings from JSON
                out[p] = {int(h): float(w) for h, w in v.items()}
            else:
                # flat weight, broadcast across all horizons
                out[p] = {h: float(v) for h in horizons}
        if out:
            return out
    return _initial_weights_per_horizon(config)


def save_weights(weights: dict[str, dict[int, float]], meta: dict) -> None:
    payload = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    # ---- 1. Resolve any open predictions whose horizon has elapsed --------
    predictions = load_predictions()
    predictions, resolved = resolve_due_predictions(
        predictions,
        up_threshold=bt_cfg["threshold_up_pct"],
        down_threshold=bt_cfg["threshold_down_pct"],
    )
    log.info("resolved %d predictions", resolved)

    # ---- 2. Generate live signals (per horizon) ---------------------------
    live_signals = []
    sentiments_by_ticker: dict[str, dict] = {}
    for ticker in config["watchlist"]:
        try:
            df = fetch_history_cached(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("skipping %s: %s", ticker, e)
            continue
        if len(df) < 252:
            continue

        sentiment = fetch_sentiment(ticker)
        if sentiment is not None:
            sentiments_by_ticker[ticker] = sentiment.to_dict()

        horizon_signals = analyze_all_horizons(ticker, df, weights, horizons)
        for sig in horizon_signals:
            sig_dict = sig.to_dict()
            sig_dict["sentiment"] = sentiments_by_ticker.get(ticker)

            sizing_plan = None
            options_plan = None
            if sig.direction in ("up", "down") and sig.confidence >= sig_cfg["min_confidence"]:
                sizing_plan = size_position(
                    direction=sig.direction,
                    entry=sig.price,
                    atr=sig.atr,
                    confidence=sig.confidence,
                    capital_usd=portfolio["capital_usd"],
                    risk_per_trade_pct=portfolio["risk_per_trade_pct"],
                    max_position_pct=portfolio["max_position_pct"],
                )
                options_plan = recommend_options(
                    direction=sig.direction,
                    confidence=sig.confidence,
                    spot=sig.price,
                    atr=sig.atr,
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

    # ---- 3. Run backtest batch -------------------------------------------
    log.info("running backtest: %d samples...", bt_cfg["samples_per_run"])
    samples = run_batch(
        universe=config["backtest_universe"],
        horizons=horizons,
        weights_per_horizon=weights,
        n_samples=bt_cfg["samples_per_run"],
        history_years=bt_cfg["history_years"],
        min_data_days=bt_cfg["min_data_days"],
        up_threshold=bt_cfg["threshold_up_pct"],
        down_threshold=bt_cfg["threshold_down_pct"],
        seed=None,
    )

    # ---- 4. Aggregate accuracies (overall + per-horizon + per-regime) -----
    ensemble_acc = aggregate_ensemble_accuracy(samples)
    pattern_acc_flat = aggregate_pattern_accuracy_flat(samples)
    pattern_acc_per_h = aggregate_pattern_accuracy_per_horizon(samples)

    # ---- 5. Evaluate methodologies ---------------------------------------
    methodology_stats = aggregate_methodology_accuracy(samples, weights)

    # ---- 6. Update pattern weights per-horizon ---------------------------
    if pattern_acc_per_h:
        old_weights = {p: dict(hw) for p, hw in weights.items()}
        weights = update_weights_per_horizon(weights, pattern_acc_per_h)
        save_weights(weights, meta={"n_samples": len(samples), "previous_weights": old_weights})

    # ---- 7. Save predictions and dashboard JSON -------------------------
    save_predictions(predictions)
    scoreboard = aggregate_scoreboard(predictions)

    write_json(DATA_DIR / "signals.json", {
        "updated_at": _ts(),
        "signals": live_signals,
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
    })
    write_json(DATA_DIR / "methodologies.json", {
        "updated_at": _ts(),
        "n_samples": len(samples),
        "methodologies": methodology_stats,
        "definitions": [
            {"name": m.name, "description": m.description,
             "pattern_filter": sorted(m.pattern_filter) if m.pattern_filter else None,
             "regime_filter": sorted(m.regime_filter) if m.regime_filter else None,
             "min_confidence": m.min_confidence}
            for m in METHODOLOGIES
        ],
    })
    write_json(DATA_DIR / "weights.json", {
        "updated_at": _ts(),
        "weights": {p: {str(h): w for h, w in hw.items()} for p, hw in weights.items()},
    })

    log.info(
        "done. live signals: %d (%d sentiments), backtest samples: %d, "
        "open preds: %d, resolved preds: %d",
        len(live_signals), len(sentiments_by_ticker), len(samples),
        scoreboard["open_predictions"], scoreboard["total_resolved"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
