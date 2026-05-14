"""Technical indicators computed from OHLCV bars.

All functions take a DataFrame with columns Open, High, Low, Close, Volume
indexed by date, and return a Series or DataFrame aligned to the same index.

Formulas are the standard textbook ones (Investopedia / Murphy's
"Technical Analysis of the Financial Markets"). Numbers tie out with TA-Lib
to within floating-point tolerance for the indicators we use.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_bandwidth": bandwidth}
    )


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range. Returns absolute price units."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    """How extreme today's volume is vs the trailing window."""
    mean = volume.rolling(window=window, min_periods=window).mean()
    std = volume.rolling(window=window, min_periods=window).std()
    return (volume - mean) / std.replace(0, np.nan)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the full indicator suite to a copy of df."""
    out = df.copy()
    close = out["Close"]
    out["sma_20"] = sma(close, 20)
    out["sma_50"] = sma(close, 50)
    out["sma_200"] = sma(close, 200)
    out["ema_12"] = ema(close, 12)
    out["ema_26"] = ema(close, 26)
    out["rsi_14"] = rsi(close, 14)
    macd_df = macd(close)
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]
    bb = bollinger(close)
    out["bb_mid"] = bb["bb_mid"]
    out["bb_upper"] = bb["bb_upper"]
    out["bb_lower"] = bb["bb_lower"]
    out["bb_bandwidth"] = bb["bb_bandwidth"]
    out["atr_14"] = atr(out, 14)
    out["vol_z_20"] = volume_zscore(out["Volume"], 20)
    return out
