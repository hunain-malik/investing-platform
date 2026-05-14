"""Earnings calendar lookup.

Fetches the next scheduled earnings date for a ticker via yfinance's
calendar accessor. We use this to flag short-horizon signals where earnings
will hit before the horizon closes — those should be treated with caution
because earnings cause large outsized moves unrelated to technical setup.

yfinance's calendar shape has shifted across versions; this handles the
common shapes defensively.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


def next_earnings_date(ticker: str) -> Optional[datetime]:
    """Return the next scheduled earnings date, or None if not available."""
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception as e:  # noqa: BLE001
        log.debug("could not fetch earnings calendar for %s: %s", ticker, e)
        return None

    if cal is None:
        return None

    candidate = None

    if isinstance(cal, dict):
        # newer yfinance (~0.2.55+)
        raw = cal.get("Earnings Date") or cal.get("earningsDate")
        if isinstance(raw, list) and raw:
            candidate = raw[0]
        elif raw is not None:
            candidate = raw

    elif isinstance(cal, pd.DataFrame) and not cal.empty:
        # older yfinance
        try:
            row = cal.loc["Earnings Date"]
            candidate = row.iloc[0]
        except Exception:  # noqa: BLE001
            return None

    if candidate is None:
        return None
    try:
        dt = pd.Timestamp(candidate).to_pydatetime()
    except Exception:  # noqa: BLE001
        return None

    # only return if it's actually in the future and within ~6 months
    now = datetime.utcnow()
    if dt < now or (dt - now).days > 200:
        return None
    return dt


def days_until_earnings(ticker: str) -> Optional[int]:
    """Days from today until next earnings, or None if unknown."""
    dt = next_earnings_date(ticker)
    if dt is None:
        return None
    delta = (dt - datetime.utcnow()).days
    return max(0, delta)
