"""Main analysis orchestrator. Run this daily (locally or in GitHub Actions).

Steps:
    1. Load config + persisted pattern weights.
    2. Resolve any open predictions whose horizon has elapsed.
    3. For each watchlist ticker, generate the ensemble signal. If confident,
       log new predictions and compute sizing + options recommendations.
    4. Run the random-cutoff backtest batch.
    5. Update pattern weights from backtest accuracy.
    6. Write all JSON outputs to docs/data/ for the dashboard, and persist
       updated weights and predictions to state/.
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
    aggregate_pattern_accuracy,
    run_batch,
    update_weights,
)
from .data import fetch_history_cached
from .options import recommend_options
from .scoreboard import (
    aggregate_scoreboard,
    load_predictions,
    log_predictions_from_signal,
    resolve_due_predictions,
    save_predictions,
)
from .signals import analyze
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


def load_weights(config: dict) -> dict[str, float]:
    if WEIGHTS_FILE.exists():
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.get("weights", {}).items()}
    return dict(config.get("pattern_weights", {}))


def save_weights(weights: dict[str, float], meta: dict) -> None:
    WEIGHTS_FILE.write_text(
        json.dumps({"updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "weights": weights, "meta": meta}, indent=2),
        encoding="utf-8",
    )


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


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

    # ---- 2. Generate live signals for the watchlist -----------------------
    live_signals = []
    for ticker in config["watchlist"]:
        try:
            df = fetch_history_cached(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("skipping %s: %s", ticker, e)
            continue
        if len(df) < 252:
            log.warning("skipping %s: insufficient history", ticker)
            continue
        sig = analyze(ticker, df, weights, as_of_idx=-1)
        sig_dict = sig.to_dict()

        # Sizing + options for actionable signals
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
                horizon_days=horizons[0],
                options_allowed=portfolio.get("options_allowed", True),
            )

            # Log predictions for tracking on the scoreboard
            if len(sig.fired_patterns) >= sig_cfg["min_patterns_for_signal"]:
                predictions = log_predictions_from_signal(
                    sig, horizons, sig_cfg["min_confidence"], predictions
                )

        sig_dict["sizing"] = sizing_plan.to_dict() if sizing_plan else None
        sig_dict["options"] = options_plan.to_dict() if options_plan else None
        live_signals.append(sig_dict)

    # ---- 3. Run backtest batch -------------------------------------------
    log.info("running backtest: %d samples...", bt_cfg["samples_per_run"])
    samples = run_batch(
        universe=config["backtest_universe"],
        horizons=horizons,
        weights=weights,
        n_samples=bt_cfg["samples_per_run"],
        history_years=bt_cfg["history_years"],
        min_data_days=bt_cfg["min_data_days"],
        up_threshold=bt_cfg["threshold_up_pct"],
        down_threshold=bt_cfg["threshold_down_pct"],
        seed=None,
    )
    pattern_acc = aggregate_pattern_accuracy(samples)
    ensemble_acc = aggregate_ensemble_accuracy(samples)

    # ---- 4. Update pattern weights from backtest accuracy ----------------
    if pattern_acc:
        old_weights = dict(weights)
        weights = update_weights(weights, pattern_acc)
        save_weights(weights, meta={"n_samples": len(samples), "previous_weights": old_weights})
        log.info("updated pattern weights")

    # ---- 5. Save predictions and dashboard JSON -------------------------
    save_predictions(predictions)
    scoreboard = aggregate_scoreboard(predictions)

    write_json(DATA_DIR / "signals.json", {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": live_signals,
    })
    write_json(DATA_DIR / "predictions.json", {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predictions": [p.to_dict() for p in predictions],
    })
    write_json(DATA_DIR / "scoreboard.json", scoreboard)
    write_json(DATA_DIR / "backtest.json", {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_samples": len(samples),
        "ensemble": ensemble_acc,
        "patterns": pattern_acc,
    })
    write_json(DATA_DIR / "weights.json", {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weights": weights,
    })

    log.info("done. live signals: %d, backtest samples: %d, open preds: %d, resolved preds: %d",
             len(live_signals), len(samples), scoreboard["open_predictions"], scoreboard["total_resolved"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
