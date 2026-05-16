"""Fetch SPUS + HLAL holdings from SEC EDGAR and write to docs/data/.

ETFs file form NPORT-P quarterly with the SEC. The primary_doc.xml inside
each filing contains a complete <invstOrSec> list with every holding,
including the ticker. This script:

  1. Looks up the CIK for each ETF series via EDGAR's company search.
  2. Reads the latest NPORT-P submission index for that CIK.
  3. Downloads the primary_doc.xml.
  4. Parses out tickers (filtering out cash / Treasury repo lines).
  5. Writes {"spus": [...], "hlal": [...], "fetched_at": "..."} to
     docs/data/shariah_etf_holdings.json.

If the fetch fails (network error, SEC throttle, schema change), the
script falls back to keeping the existing file in place — it never
writes an empty list, because shariah_etfs.py would silently fall back
to its top-25 seed if the file existed but was blank.

SEC requires a descriptive User-Agent on all programmatic requests
(see https://www.sec.gov/os/accessing-edgar-data). We send a real
contact email so SEC can throttle us politely if needed.

Run standalone or wire into the daily-analysis workflow:
  python -m analysis.fetch_shariah_etf_holdings
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


USER_AGENT = "investing-platform/1.0 (hunain.malik@uni.minerva.edu)"
SEC_RATE_LIMIT_SECONDS = 0.15  # SEC's stated cap is 10 req/sec; we leave headroom

# ETF series_id (or CIK) → display name. SEC indexes ETFs by CIK of the
# trust, but NPORT-P filings are per-series. We resolve by company search
# below, but having a hardcoded fallback avoids name-search ambiguity.
ETF_DESCRIPTORS = [
    {
        "key": "spus",
        "ticker": "SPUS",
        "name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
        "trust_search": "SP Funds Trust",
    },
    {
        "key": "hlal",
        "ticker": "HLAL",
        "name": "Wahed FTSE USA Shariah ETF",
        "trust_search": "Wahed",
    },
]


def _http_get(url: str) -> bytes:
    """GET a URL with SEC's required User-Agent and a small rate-limit pause."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
    time.sleep(SEC_RATE_LIMIT_SECONDS)
    return body


def _find_cik_for_ticker(ticker: str) -> str | None:
    """Look up a CIK from the SEC's ticker→CIK mapping.

    Returns a 10-digit CIK string (zero-padded) or None.
    """
    body = _http_get("https://www.sec.gov/files/company_tickers.json")
    data = json.loads(body.decode("utf-8"))
    target = ticker.upper()
    for _, row in data.items():
        if row.get("ticker", "").upper() == target:
            return str(row["cik_str"]).zfill(10)
    return None


def _latest_nport_p_accession(cik: str) -> tuple[str, str] | None:
    """Return (accession_no_no_dashes, primary_doc_filename) for the most
    recent NPORT-P filing of this CIK, or None.
    """
    body = _http_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    data = json.loads(body.decode("utf-8"))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary = recent.get("primaryDocument", [])
    for f, acc, doc in zip(forms, accessions, primary):
        if f == "NPORT-P":
            return acc.replace("-", ""), doc
    return None


def _extract_tickers_from_nport(xml_bytes: bytes) -> list[str]:
    """Parse primary_doc.xml of an NPORT-P filing and return the list of
    equity tickers held. Cash, Treasury, and non-equity holdings are
    filtered out.
    """
    # NPORT-P uses namespaces; we strip them for robustness.
    text = xml_bytes.decode("utf-8", errors="ignore")
    text = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", text, count=0)
    root = ET.fromstring(text)
    tickers: list[str] = []
    for inv in root.iter("invstOrSec"):
        # asset type — only equities (EC = Equity-common)
        asset_cat = inv.findtext("assetCat", default="").upper()
        # title is descriptive; ticker tag is what we want, with fallback to identifiers
        ticker_el = inv.find("ticker")
        ticker = (ticker_el.text or "").strip().upper() if ticker_el is not None else ""
        # Identifiers block has CUSIP/ISIN; we only want a clean ticker.
        # Skip cash, treasury, derivatives, repos
        if asset_cat in {"DBT", "STIV", "RA", "REPO"}:
            continue
        if not ticker:
            continue
        # Skip obvious non-equity sentinels SEC sometimes uses
        if ticker in {"N/A", "NA", "NONE", "CASH", "USD"}:
            continue
        # Skip composite tickers with whitespace/punctuation (e.g., "T-RW")
        if not re.match(r"^[A-Z][A-Z\.\-]{0,9}$", ticker):
            continue
        tickers.append(ticker)
    # de-dupe preserving order
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _fetch_etf_holdings(ticker: str) -> list[str]:
    """End-to-end: ticker → latest NPORT-P → list of equity ticker holdings."""
    cik = _find_cik_for_ticker(ticker)
    if cik is None:
        print(f"  [{ticker}] CIK lookup failed", file=sys.stderr)
        return []
    accession = _latest_nport_p_accession(cik)
    if accession is None:
        print(f"  [{ticker}] no NPORT-P found (CIK {cik})", file=sys.stderr)
        return []
    acc, doc = accession
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
    print(f"  [{ticker}] fetching {url}", file=sys.stderr)
    xml = _http_get(url)
    return _extract_tickers_from_nport(xml)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / "docs" / "data" / "shariah_etf_holdings.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, list[str] | str] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "SEC EDGAR NPORT-P",
    }
    any_success = False
    for descriptor in ETF_DESCRIPTORS:
        key = descriptor["key"]
        ticker = descriptor["ticker"]
        print(f"Fetching {ticker} holdings...", file=sys.stderr)
        try:
            holdings = _fetch_etf_holdings(ticker)
        except Exception as e:  # noqa: BLE001
            print(f"  [{ticker}] error: {e}", file=sys.stderr)
            holdings = []
        if holdings:
            any_success = True
            result[key] = holdings
            print(f"  [{ticker}] {len(holdings)} holdings", file=sys.stderr)
        else:
            print(f"  [{ticker}] no holdings parsed; keeping seed list as-is", file=sys.stderr)

    if not any_success:
        print("All fetches failed — not writing output (seed list remains in effect)", file=sys.stderr)
        return 1

    # Always preserve whichever side succeeded; if HLAL fetch failed but SPUS
    # succeeded, we leave HLAL out of the output and shariah_etfs.py falls
    # back to seed for HLAL.
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
