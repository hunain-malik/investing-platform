"""Shariah-compliant ETF holdings — SPUS and HLAL.

Stocks held by these two ETFs are AAOIFI/FTSE-Shariah certified by their
respective Shariah supervisory boards (IdealRatings for SPUS, FTSE Shariah
Index methodology for HLAL). Holding membership is a much stronger
compliance signal than my industry-exclusion list in halal.py — these
boards apply full AAOIFI screens (industry + leverage ratio + interest
income ratio + non-compliant revenue ratio + purification calculations).

This module exposes:
  - SPUS_HOLDINGS, HLAL_HOLDINGS frozensets of tickers
  - SHARIAH_ETF_CERTIFIED = union of both
  - shariah_etf_tier(ticker) → {"tier", "in_spus", "in_hlal", "etf_count"}

The seed data below is the top-25 by weight from each ETF (verified
2026-05-15 via stockanalysis.com). The full rosters (~221 in SPUS, ~210
in HLAL — ~310 unique tickers across both) are loaded at runtime from
data/shariah_etf_holdings.json if it exists; that file is produced by
scripts/fetch_shariah_etf_holdings.py which pulls N-PORT-P filings from
SEC EDGAR.
"""

from __future__ import annotations

import json
from pathlib import Path


# Verified top-25 by weight, fetched 2026-05-15 via stockanalysis.com
_SPUS_SEED = frozenset({
    "NVDA", "AAPL", "MSFT", "GOOGL", "AVGO", "TSLA", "LLY", "MU", "XOM",
    "AMD", "JNJ", "CSCO", "ABBV", "LRCX", "PG", "AMAT", "ORCL", "HD",
    "GEV", "MRK", "TXN", "LIN", "KLAC", "PEP", "IBM",
})

_HLAL_SEED = frozenset({
    "AAPL", "MSFT", "GOOGL", "AVGO", "GOOG", "META", "TSLA", "MU", "LLY",
    "AMD", "XOM", "JNJ", "INTC", "CSCO", "LRCX", "CVX", "AMAT", "PG",
    "KO", "GEV", "TXN", "MRK", "KLAC", "LIN", "QCOM",
})


def _load_full_holdings() -> tuple[frozenset[str], frozenset[str]]:
    """Load the full SPUS + HLAL holdings from disk if available, else seed."""
    repo_root = Path(__file__).resolve().parent.parent
    holdings_path = repo_root / "docs" / "data" / "shariah_etf_holdings.json"
    if not holdings_path.exists():
        return _SPUS_SEED, _HLAL_SEED
    try:
        with holdings_path.open(encoding="utf-8") as f:
            data = json.load(f)
        spus = frozenset(t.upper() for t in data.get("spus", []))
        hlal = frozenset(t.upper() for t in data.get("hlal", []))
        # Fall back to seed if file is corrupted / empty
        if not spus:
            spus = _SPUS_SEED
        if not hlal:
            hlal = _HLAL_SEED
        return spus, hlal
    except (json.JSONDecodeError, OSError):
        return _SPUS_SEED, _HLAL_SEED


SPUS_HOLDINGS, HLAL_HOLDINGS = _load_full_holdings()
SHARIAH_ETF_CERTIFIED = SPUS_HOLDINGS | HLAL_HOLDINGS


def shariah_etf_tier(ticker: str) -> dict:
    """Return ETF membership info for a ticker.

    tier:
      - "etf_certified": held by SPUS and/or HLAL (highest confidence,
        AAOIFI-screened by certified Shariah board)
      - "not_in_etf":   not held by either, requires manual verification
    """
    t = ticker.upper()
    in_spus = t in SPUS_HOLDINGS
    in_hlal = t in HLAL_HOLDINGS
    return {
        "tier": "etf_certified" if (in_spus or in_hlal) else "not_in_etf",
        "in_spus": in_spus,
        "in_hlal": in_hlal,
        "etf_count": int(in_spus) + int(in_hlal),
    }
