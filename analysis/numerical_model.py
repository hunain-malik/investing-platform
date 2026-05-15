"""Numerical / statistical alternative to pattern recognition.

Trains a logistic-regression classifier on continuous indicator features
(returns, RSI, MACD, SMA distances, volatility, volume z, ATR ratio)
to predict P(up) for each horizon. Evaluated with the same K-fold protocol
as the pattern-based meta-ensemble, so the two are directly comparable.

The user asked whether a mathematical model might beat pattern recognition.
This module is the answer: side-by-side benchmark on the same backtest
samples. If it wins, we should weight it; if it loses, we show that
explicitly and stick with patterns.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from .data import fetch_history_cached, slice_until
from .indicators import compute_all

log = logging.getLogger(__name__)


FEATURE_NAMES = [
    "ret_5d", "ret_20d", "ret_60d",
    "rsi_14",
    "macd_hist_norm",
    "dist_sma_20", "dist_sma_50", "dist_sma_200",
    "vol_20d",
    "atr_ratio",
    "vol_z_20",
    "bb_bandwidth",
    "rel_strength_20",
]


def compute_features(df_ind: pd.DataFrame, idx: int) -> list[float] | None:
    """Extract a feature vector at row `idx`. Returns None if data insufficient.

    Features are normalized (ratios, z-scores, percent returns) so a single
    set of model coefficients applies across all tickers and price levels.
    """
    if idx < 60:
        return None
    row = df_ind.iloc[idx]
    close = float(row["Close"])

    def _pct(idx_back: int):
        if idx_back > idx:
            return None
        prev = float(df_ind.iloc[idx - idx_back]["Close"])
        if prev <= 0:
            return None
        return (close / prev) - 1.0

    ret_5 = _pct(5)
    ret_20 = _pct(20)
    ret_60 = _pct(60)
    if ret_5 is None or ret_20 is None or ret_60 is None:
        return None

    rsi = row.get("rsi_14")
    if pd.isna(rsi):
        return None
    rsi_centered = (float(rsi) - 50.0) / 50.0  # [-1, 1]

    macd_hist = row.get("macd_hist")
    macd_norm = (float(macd_hist) / close) if (macd_hist is not None and not pd.isna(macd_hist) and close > 0) else 0.0

    def _dist(col):
        v = row.get(col)
        if v is None or pd.isna(v) or v <= 0:
            return 0.0
        return (close - float(v)) / float(v)

    dist_20 = _dist("sma_20")
    dist_50 = _dist("sma_50")
    dist_200 = _dist("sma_200")

    # 20d realized volatility (std of daily returns)
    window = df_ind.iloc[idx - 19 : idx + 1]["Close"]
    if len(window) < 20:
        return None
    rets = window.pct_change().dropna()
    vol_20 = float(rets.std()) if len(rets) else 0.0

    atr = row.get("atr_14")
    atr_ratio = (float(atr) / close) if (atr is not None and not pd.isna(atr) and close > 0) else 0.0

    vol_z = row.get("vol_z_20")
    vol_z_v = float(vol_z) if (vol_z is not None and not pd.isna(vol_z)) else 0.0
    # cap extremes
    vol_z_v = max(-3.0, min(3.0, vol_z_v))

    bb_bw = row.get("bb_bandwidth")
    bb_bw_v = float(bb_bw) if (bb_bw is not None and not pd.isna(bb_bw)) else 0.0

    # Relative strength vs SPY (uses spy_close column if present)
    rel = 0.0
    if "spy_close" in df_ind.columns and idx >= 20:
        s_now = df_ind.iloc[idx]["spy_close"]
        s_20 = df_ind.iloc[idx - 20]["spy_close"]
        if not pd.isna(s_now) and not pd.isna(s_20) and float(s_20) > 0:
            s_ret = (float(s_now) / float(s_20)) - 1.0
            rel = ret_20 - s_ret

    return [ret_5, ret_20, ret_60, rsi_centered, macd_norm,
            dist_20, dist_50, dist_200, vol_20, atr_ratio,
            vol_z_v, bb_bw_v, rel]


def collect_features_for_samples(samples: list) -> tuple[np.ndarray, np.ndarray, list[int], list[str]]:
    """For each backtest sample, recompute features at the cutoff bar.

    Returns (X, y, horizons, regimes) where X is (n, n_features) features,
    y is (n,) binary (1 if actual_label == 'up' else 0 if 'down' else -1
    for 'flat' — flat samples are excluded by the caller).
    """
    rows_X = []
    rows_y = []
    horizons = []
    regimes = []
    for s in samples:
        if s.actual_label not in ("up", "down"):
            continue
        try:
            df_full = fetch_history_cached(s.ticker)
        except Exception:  # noqa: BLE001
            continue
        df_until = slice_until(df_full, s.cutoff)
        if len(df_until) < 252:
            continue
        df_ind = compute_all(df_until)
        feat = compute_features(df_ind, idx=len(df_ind) - 1)
        if feat is None:
            continue
        rows_X.append(feat)
        rows_y.append(1 if s.actual_label == "up" else 0)
        horizons.append(s.horizon_days)
        regimes.append(s.regime)
    if not rows_X:
        return np.empty((0, len(FEATURE_NAMES))), np.empty((0,)), [], []
    return np.array(rows_X), np.array(rows_y), horizons, regimes


def kfold_logistic_regression(
    X: np.ndarray,
    y: np.ndarray,
    horizons: list[int],
    regimes: list[str],
    k: int = 5,
    seed: int = 1729,
) -> dict[str, Any]:
    """Train logistic regression with K-fold CV; report accuracy overall
    and by horizon/regime, plus feature coefficients from a final fit on
    all data.
    """
    n = len(y)
    if n < k * 50:
        return {
            "k": k, "n_samples": n,
            "accuracy": None,
            "note": "Not enough samples for k-fold (need >= k*50)",
        }

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import KFold
    except ImportError as e:  # noqa: BLE001
        log.warning("scikit-learn not available: %s", e)
        return {"k": k, "n_samples": n, "accuracy": None, "note": "sklearn missing"}

    kf = KFold(n_splits=k, shuffle=True, random_state=seed)

    total_correct = 0
    total_n = 0
    by_horizon: dict[int, dict] = defaultdict(lambda: {"signals": 0, "correct": 0})
    by_regime: dict[str, dict] = defaultdict(lambda: {"signals": 0, "correct": 0})
    confidences_correct: list[tuple[float, bool]] = []

    for train_idx, test_idx in kf.split(X):
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        model = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
        model.fit(X_tr_s, y_tr)
        proba = model.predict_proba(X_te_s)[:, 1]  # P(y=1, i.e. up)

        for i, idx_orig in enumerate(test_idx):
            p_up = float(proba[i])
            actual = int(y_te[i])
            # Emit a signal only when prob is meaningfully off 0.5
            if abs(p_up - 0.5) < 0.05:
                continue
            pred = 1 if p_up > 0.5 else 0
            correct = (pred == actual)
            confidence = abs(p_up - 0.5) * 2  # [0, 1]
            total_n += 1
            if correct:
                total_correct += 1
            confidences_correct.append((confidence, correct))
            h = horizons[idx_orig]
            r = regimes[idx_orig]
            bh = by_horizon[h]
            bh["signals"] += 1
            if correct:
                bh["correct"] += 1
            br = by_regime[r]
            br["signals"] += 1
            if correct:
                br["correct"] += 1

    # Final model on all data for coefficient inspection
    scaler_all = StandardScaler()
    X_all = scaler_all.fit_transform(X)
    final = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs").fit(X_all, y)
    coef = dict(zip(FEATURE_NAMES, [round(float(c), 4) for c in final.coef_[0]]))
    intercept = round(float(final.intercept_[0]), 4)

    # Calibration: split signals by predicted-confidence bucket
    buckets = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1.01)]
    calibration = []
    for lo, hi in buckets:
        in_bucket = [c for c, _ in confidences_correct if lo <= c < hi]
        n_b = len(in_bucket)
        correct_b = sum(1 for conf, correct in confidences_correct if lo <= conf < hi and correct)
        calibration.append({
            "confidence_lo": lo,
            "confidence_hi": hi,
            "n": n_b,
            "correct": correct_b,
            "accuracy": round(correct_b / n_b, 4) if n_b > 0 else None,
        })

    return {
        "k": k,
        "n_samples": n,
        "signals_emitted": total_n,
        "correct": total_correct,
        "accuracy": round(total_correct / total_n, 4) if total_n else None,
        "signal_rate": round(total_n / n, 4) if n else None,
        "by_horizon": {
            h: {"signals": v["signals"], "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None}
            for h, v in sorted(by_horizon.items())
        },
        "by_regime": {
            r: {"signals": v["signals"], "correct": v["correct"],
                "accuracy": round(v["correct"] / v["signals"], 4) if v["signals"] else None}
            for r, v in by_regime.items()
        },
        "calibration": calibration,
        "model_coefficients": coef,
        "model_intercept": intercept,
        "feature_names": FEATURE_NAMES,
        "description": "Logistic regression on continuous indicator features — pure numerical alternative to pattern recognition",
    }


def evaluate_numerical_model(samples) -> dict:
    """Top-level entry: collect features from samples, run K-fold LR, return stats."""
    log.info("collecting features for %d samples...", len(samples))
    X, y, horizons, regimes = collect_features_for_samples(samples)
    if len(X) == 0:
        return {"accuracy": None, "note": "no features collected"}
    log.info("running K-fold logistic regression on %d samples × %d features...", len(X), X.shape[1])
    return kfold_logistic_regression(X, y, horizons, regimes)
