"""Halal / Shariah-compliant investment screening.

This is a GENERAL-CONSENSUS filter based on common Islamic-finance
exclusions, NOT a substitute for certified Shariah-board review. For
investors who require strict Shariah compliance, refer to a recognized
Islamic finance authority or use a certified index (Dow Jones Islamic
Market Index, S&P Shariah, MSCI Islamic, IdealRatings, Refinitiv).

What we screen for (the exclusions):

1. Interest-bearing finance (riba):
   - Conventional banks (deposits + lending on interest)
   - Conventional insurance (interest-bearing reserves)
   - Pure-interest credit card issuers

2. Haram industries:
   - Alcohol producers / distributors
   - Tobacco companies
   - Gambling / casinos / sports betting
   - Conventional weapons (controversial — some scholars permit)
   - Adult entertainment (none in our large-cap universe)
   - Pork-related products

3. NOT screened (would need fundamental data we don't have):
   - Financial-ratio screens (debt/market cap < 33%, etc.)
   - Interest income < 5% of revenue threshold
   - Sukuk vs conventional bond holdings

Use the `is_halal_compliant(ticker)` function or `filter_halal_tickers(...)`.
"""

from __future__ import annotations

from .shariah_etfs import shariah_etf_tier, SPUS_HOLDINGS, HLAL_HOLDINGS

# Conventional banks (interest-based deposits + lending)
BANKS = frozenset({
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
    "FITB", "MTB", "HBAN", "RF", "KEY", "CFG", "ZION", "SBNY", "FRC",
    "NTRS", "STT", "BK", "AXP",  # AXP = credit card / lending
    "DFS", "SYF",  # credit cards
    "SCHW",  # broker / margin lending
})

# Conventional insurance
INSURANCE = frozenset({
    "AIG", "MET", "PRU", "TRV", "AFL", "ALL", "CB", "MMC", "AON",
    "CINF", "PGR", "HIG", "L",
})

# Alcohol
ALCOHOL = frozenset({
    "BUD", "STZ", "DEO", "TAP", "SAM",
})

# Tobacco
TOBACCO = frozenset({
    "MO", "PM", "BTI",
})

# Gambling / casinos / sports betting
GAMBLING = frozenset({
    "WYNN", "LVS", "MGM", "DKNG", "PENN", "CZR", "BYD", "FLUT",
    "FUBO",  # sports betting tilt
})

# Weapons / defense (CONTROVERSIAL — many scholars permit defensive use;
# some Shariah indices exclude. We exclude by default; user can override.)
WEAPONS = frozenset({
    "LMT", "RTX", "NOC", "GD", "HII", "LDOS", "TXT", "TDG",
})

# Mainstream financial services that are usually OK in general-consensus
# screening (payments processors that don't lend on interest, etc.):
#   V, MA, PYPL, SQ — payment networks; revenues are merchant fees, not interest
#   FIS, FISV, GPN, JKHY — financial-tech services (acceptable per most screens)
# These are NOT in our excluded list.

# Combine all exclusions
ALL_EXCLUDED = BANKS | INSURANCE | ALCOHOL | TOBACCO | GAMBLING | WEAPONS


def is_halal_compliant(ticker: str) -> bool:
    """Return True if the ticker is NOT in our excluded list."""
    return ticker.upper() not in ALL_EXCLUDED


def exclusion_reason(ticker: str) -> str | None:
    """Return the category that excludes a ticker, or None if it's compliant."""
    t = ticker.upper()
    if t in BANKS:
        return "Conventional banking (interest-based deposits/lending)"
    if t in INSURANCE:
        return "Conventional insurance"
    if t in ALCOHOL:
        return "Alcohol production/distribution"
    if t in TOBACCO:
        return "Tobacco industry"
    if t in GAMBLING:
        return "Gambling / casinos / sports betting"
    if t in WEAPONS:
        return "Weapons manufacturer (controversial — some scholars permit defensive)"
    return None


def filter_halal_tickers(tickers: list[str]) -> tuple[list[str], dict[str, str]]:
    """Return (allowed, excluded_with_reason)."""
    allowed = []
    excluded = {}
    for t in tickers:
        reason = exclusion_reason(t)
        if reason is None:
            allowed.append(t)
        else:
            excluded[t.upper()] = reason
    return allowed, excluded


# Export a serializable map for the frontend so the dashboard knows which
# tickers are excluded and why, without having to call back into Python.
#
# Each entry combines two compliance signals:
#  1. Industry exclusion (this module): general-consensus filter — coarse but
#     covers tickers not held by any major Shariah ETF.
#  2. Shariah ETF membership (shariah_etfs): SPUS / HLAL holdings — full
#     AAOIFI screen by a certified Shariah board (gold standard for retail).
#
# tier semantics:
#   - "etf_certified": held by SPUS and/or HLAL → highest confidence
#   - "industry_pass": passes our industry filter but not in either ETF →
#       verify on Zoya before treating as compliant
#   - "excluded":      in our exclusion list (industry-haram)
def halal_status_map(tickers: list[str]) -> dict[str, dict]:
    out = {}
    for t in tickers:
        t_up = t.upper()
        reason = exclusion_reason(t_up)
        etf = shariah_etf_tier(t_up)
        if reason is not None:
            tier = "excluded"
        elif etf["tier"] == "etf_certified":
            tier = "etf_certified"
        else:
            tier = "industry_pass"
        out[t_up] = {
            "compliant": reason is None,
            "exclusion_reason": reason,
            "tier": tier,
            "in_spus": etf["in_spus"],
            "in_hlal": etf["in_hlal"],
            "etf_count": etf["etf_count"],
        }
    return out
