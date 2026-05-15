"""Live prediction logging and scoreboard aggregation.

State lives in `state/predictions.json` and is committed to the repo so it
persists across GitHub Actions runs.

A prediction's lifecycle:
    1. Logged when the ensemble emits a signal with confidence >= min_confidence.
    2. While `horizon_end` is in the future, status = "open".
    3. After `horizon_end`, the resolver fetches actual price at that date,
       computes return, labels it up/down/flat, and marks correct/wrong.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .data import fetch_history_cached
from .signals import EnsembleSignal

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_DIR.mkdir(exist_ok=True)
PREDICTIONS_FILE = STATE_DIR / "predictions.json"


@dataclass
class Prediction:
    id: str
    ticker: str
    made_at: str
    as_of_price: float
    horizon_days: int
    horizon_end: str
    predicted_direction: str
    ensemble_confidence: float
    fired_patterns: list[str]
    status: str = "open"
    resolved_at: str | None = None
    actual_return_pct: float | None = None
    actual_label: str | None = None
    correct: bool | None = None
    notes: str = ""
    # Methodology that generated this prediction. Empty for legacy entries
    # filed before this field existed. Populated for new predictions filed
    # via meta_pseudo_signal / consensus_pseudo_signal in run.py.
    methodology: str = ""
    sector: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _make_id(ticker: str, made_at: str, horizon_days: int, direction: str) -> str:
    raw = f"{ticker}|{made_at}|{horizon_days}|{direction}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def load_predictions() -> list[Prediction]:
    if not PREDICTIONS_FILE.exists():
        return []
    data = json.loads(PREDICTIONS_FILE.read_text(encoding="utf-8"))
    return [Prediction(**p) for p in data.get("predictions", [])]


def save_predictions(preds: list[Prediction]) -> None:
    payload = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predictions": [p.to_dict() for p in preds],
    }
    PREDICTIONS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _trading_horizon_end(start: pd.Timestamp, horizon_days: int) -> str:
    """Approximate calendar end date for an N-trading-day horizon.

    Roughly 7 calendar days per 5 trading days. We allow the resolver some
    slack and check whether the actual N-th-trading-day bar exists.
    """
    approx_calendar = int(horizon_days * 1.45) + 1
    return (start + timedelta(days=approx_calendar)).strftime("%Y-%m-%d")


def log_predictions_from_signal(
    signal: EnsembleSignal,
    horizons: list[int],
    min_confidence: float,
    existing: list[Prediction],
    sector: str = "",
) -> list[Prediction]:
    """Append new predictions for `signal` (one per horizon) if not already logged.

    Returns the updated predictions list.
    """
    if signal.direction == "neutral" or signal.confidence < min_confidence:
        return existing

    existing_ids = {p.id for p in existing}
    made_at = signal.as_of.strftime("%Y-%m-%d")
    new = list(existing)
    for h in horizons:
        pid = _make_id(signal.ticker, made_at, h, signal.direction)
        if pid in existing_ids:
            continue
        new.append(Prediction(
            id=pid,
            ticker=signal.ticker,
            made_at=made_at,
            as_of_price=signal.price,
            horizon_days=h,
            horizon_end=_trading_horizon_end(signal.as_of, h),
            predicted_direction=signal.direction,
            ensemble_confidence=signal.confidence,
            fired_patterns=[p.name for p in signal.fired_patterns],
            methodology=signal.methodology or "",
            sector=sector or "",
        ))
    return new


def resolve_due_predictions(
    preds: list[Prediction],
    up_threshold: float,
    down_threshold: float,
    today: datetime | None = None,
) -> tuple[list[Prediction], int]:
    """Resolve any open predictions whose horizon has elapsed.

    Returns (updated predictions, number resolved).
    """
    today = today or datetime.utcnow()
    today_str = today.strftime("%Y-%m-%d")
    resolved_count = 0

    for p in preds:
        if p.status != "open":
            continue
        if p.horizon_end > today_str:
            continue
        try:
            df = fetch_history_cached(p.ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("could not resolve %s: %s", p.ticker, e)
            continue
        made_ts = pd.Timestamp(p.made_at)
        bars_after = df.loc[df.index > made_ts]
        if len(bars_after) < p.horizon_days:
            continue  # not enough trading bars yet
        end_price = float(bars_after["Close"].iloc[p.horizon_days - 1])
        ret_pct = (end_price - p.as_of_price) / p.as_of_price * 100.0
        if ret_pct >= up_threshold:
            actual = "up"
        elif ret_pct <= down_threshold:
            actual = "down"
        else:
            actual = "flat"
        p.actual_return_pct = round(ret_pct, 4)
        p.actual_label = actual
        p.correct = (p.predicted_direction == actual) and actual in ("up", "down")
        p.status = "resolved"
        p.resolved_at = today_str
        resolved_count += 1

    return preds, resolved_count


def aggregate_scoreboard(preds: list[Prediction]) -> dict[str, Any]:
    """Build the rolled-up stats the dashboard reads."""
    resolved = [p for p in preds if p.status == "resolved"]
    open_preds = [p for p in preds if p.status == "open"]

    total = len(resolved)
    correct = sum(1 for p in resolved if p.correct)

    bullish = [p for p in resolved if p.predicted_direction == "up"]
    bearish = [p for p in resolved if p.predicted_direction == "down"]

    bullish_correct = sum(1 for p in bullish if p.correct)
    bearish_correct = sum(1 for p in bearish if p.correct)

    # Per-pattern accuracy among resolved predictions (a prediction counts toward
    # a pattern if that pattern fired in the prediction)
    by_pattern: dict[str, dict[str, int]] = {}
    for p in resolved:
        for pat in p.fired_patterns:
            d = by_pattern.setdefault(pat, {"n": 0, "correct": 0})
            d["n"] += 1
            if p.correct:
                d["correct"] += 1
    pattern_stats = {
        name: {
            "n": v["n"],
            "correct": v["correct"],
            "accuracy": round(v["correct"] / v["n"], 4) if v["n"] > 0 else None,
        }
        for name, v in by_pattern.items()
    }

    return {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_resolved": total,
        "total_correct": correct,
        "overall_accuracy": round(correct / total, 4) if total else None,
        "bullish": {
            "n": len(bullish),
            "correct": bullish_correct,
            "accuracy": round(bullish_correct / len(bullish), 4) if bullish else None,
        },
        "bearish": {
            "n": len(bearish),
            "correct": bearish_correct,
            "accuracy": round(bearish_correct / len(bearish), 4) if bearish else None,
        },
        "open_predictions": len(open_preds),
        "by_pattern": pattern_stats,
    }
