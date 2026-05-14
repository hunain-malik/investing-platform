"""Volume-based patterns.

Volume confirms or denies a price move. A green candle on volume well above
average is bullish conviction; a green candle on dry volume is suspect.
"""

from __future__ import annotations

import pandas as pd


def detect_volume_breakout_bull(df: pd.DataFrame, idx: int):
    """Up-move with conviction: green candle, closes in upper third of range,
    volume z-score >= 2 (volume well above 20-bar average)."""
    from . import PatternSignal
    if idx < 21:
        return None
    row = df.iloc[idx]
    if row["Close"] <= row["Open"]:
        return None
    rng = row["High"] - row["Low"]
    if rng <= 0:
        return None
    close_pct = (row["Close"] - row["Low"]) / rng
    if close_pct < 0.66:
        return None
    vz = row.get("vol_z_20")
    if vz is None or pd.isna(vz) or vz < 2.0:
        return None
    conf = 0.55 + min(0.20, (vz - 2.0) * 0.05)
    return PatternSignal(
        "volume_breakout_bull", "up", conf,
        f"Green candle closing in upper third on volume z={vz:.1f}",
    )


def detect_volume_breakout_bear(df: pd.DataFrame, idx: int):
    """Down-move with conviction: red candle, closes in lower third of range,
    volume z-score >= 2."""
    from . import PatternSignal
    if idx < 21:
        return None
    row = df.iloc[idx]
    if row["Close"] >= row["Open"]:
        return None
    rng = row["High"] - row["Low"]
    if rng <= 0:
        return None
    close_pct = (row["Close"] - row["Low"]) / rng
    if close_pct > 0.34:
        return None
    vz = row.get("vol_z_20")
    if vz is None or pd.isna(vz) or vz < 2.0:
        return None
    conf = 0.55 + min(0.20, (vz - 2.0) * 0.05)
    return PatternSignal(
        "volume_breakout_bear", "down", conf,
        f"Red candle closing in lower third on volume z={vz:.1f}",
    )


def detect_volume_dry_up(df: pd.DataFrame, idx: int):
    """Selling exhaustion: price made a new 20-day low, but volume on the
    new low is less than volume at the prior 20-day low (sellers losing
    conviction). Bullish reversal setup.
    """
    from . import PatternSignal
    if idx < 40:
        return None
    window = df.iloc[idx - 19 : idx + 1]
    if len(window) < 20:
        return None
    low_today = float(window["Low"].iloc[-1])
    prior_window = df.iloc[idx - 39 : idx - 19]
    prior_low = float(prior_window["Low"].min())
    # require new 20-day low vs prior 20-day window
    if low_today >= prior_low:
        return None
    vol_today = float(window["Volume"].iloc[-1])
    prior_low_idx = prior_window["Low"].idxmin()
    vol_at_prior_low = float(prior_window.loc[prior_low_idx, "Volume"])
    if vol_today >= vol_at_prior_low * 0.85:
        return None  # volume not meaningfully dried up
    return PatternSignal(
        "volume_dry_up", "up", 0.6,
        "New 20-day low on lower volume than prior low — selling exhaustion",
    )


def detect_volume_dry_top(df: pd.DataFrame, idx: int):
    """Rally without conviction: new 20-day high but volume below the prior
    high's volume. Bearish reversal setup."""
    from . import PatternSignal
    if idx < 40:
        return None
    window = df.iloc[idx - 19 : idx + 1]
    high_today = float(window["High"].iloc[-1])
    prior_window = df.iloc[idx - 39 : idx - 19]
    prior_high = float(prior_window["High"].max())
    if high_today <= prior_high:
        return None
    vol_today = float(window["Volume"].iloc[-1])
    prior_high_idx = prior_window["High"].idxmax()
    vol_at_prior_high = float(prior_window.loc[prior_high_idx, "Volume"])
    if vol_today >= vol_at_prior_high * 0.85:
        return None
    return PatternSignal(
        "volume_dry_top", "down", 0.6,
        "New 20-day high on lower volume than prior high — rally lacks conviction",
    )
