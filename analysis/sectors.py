"""Sector lookup and caching.

Each ticker is tagged with its sector (Technology, Healthcare, Financial
Services, etc.) so we can aggregate backtest accuracy by sector and ask:
"do tech stocks follow different patterns than pharmaceuticals?"

Sectors are fetched from yfinance.Ticker.info, which is slow and rate-limited.
We cache the result in state/sectors.json (committed to repo) and only
refresh entries older than 90 days or never-fetched.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parent.parent / "state" / "sectors.json"
REFRESH_AFTER_DAYS = 90


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"entries": {}}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"entries": {}}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    cache["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _is_stale(entry: dict) -> bool:
    fetched = entry.get("fetched_at")
    if not fetched:
        return True
    try:
        dt = datetime.fromisoformat(fetched.replace("Z", ""))
    except Exception:  # noqa: BLE001
        return True
    return datetime.utcnow() - dt > timedelta(days=REFRESH_AFTER_DAYS)


def fetch_sector_for_ticker(ticker: str) -> str:
    """Fetch one ticker's sector via yfinance.Ticker.info."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:  # noqa: BLE001
        log.debug("sector fetch failed for %s: %s", ticker, e)
        return "Unknown"
    sector = info.get("sector") or info.get("quoteType") or "Unknown"
    # Sometimes ETFs return weird quoteType values; clean common ones
    if sector in ("ETF", "MUTUALFUND", "INDEX"):
        sector = "ETF / Fund"
    return str(sector).strip() or "Unknown"


def get_sectors(tickers: list[str], force_refresh: bool = False) -> dict[str, str]:
    """Return a {ticker: sector} mapping, refreshing stale entries.

    Hits yfinance only for missing or stale tickers. Caches everything to
    state/sectors.json (committed to repo so future runs are instant).
    """
    cache = _load_cache()
    entries = cache.setdefault("entries", {})
    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    to_fetch = []
    for t in tickers:
        ent = entries.get(t)
        if force_refresh or ent is None or _is_stale(ent):
            to_fetch.append(t)

    if to_fetch:
        log.info("fetching sectors for %d ticker(s)...", len(to_fetch))
        for t in to_fetch:
            sector = fetch_sector_for_ticker(t)
            entries[t] = {"sector": sector, "fetched_at": now_str}
        _save_cache(cache)
    else:
        log.info("all %d ticker sectors hot-cached", len(tickers))

    return {t: entries[t]["sector"] for t in tickers if t in entries}
