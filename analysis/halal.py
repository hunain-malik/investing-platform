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
    "CINF", "PGR", "HIG", "L", "LMND",
})

# Interest-based lending platforms (riba — pure interest spread businesses,
# margin lending as core revenue, buy-now-pay-later financing).
LENDING = frozenset({
    "SOFI",   # consumer lending platform
    "AFRM",   # buy-now-pay-later (interest-based financing)
    "UPST",   # AI-driven loan origination
    "HOOD",   # Robinhood — margin trading is core revenue, crypto exposure
})

# Mixed-operations conglomerates with material insurance / lending subsidiaries.
# Most Halal screeners exclude these because the insurance / interest income
# exceeds the 5% non-compliant revenue threshold. Neither SPUS nor HLAL holds them.
MIXED_OPERATIONS = frozenset({
    "BRK.B", "BRK-B", "BRK.A", "BRK-A",  # Berkshire Hathaway — GEICO + reinsurance
})

# Restaurants where pork is a regular / flagship menu item. Under standard
# AAOIFI screening (SPUS/HLAL methodology), pork revenue below 5% of total
# revenue is treated as incidental and the stock stays compliant. We take
# the more conservative line that any business prominently featuring pork
# in its menu shouldn't be in a Halal-only universe — that lines up with
# the spirit of Halal investing for retail Muslims even if it diverges
# from AAOIFI's revenue-threshold approach.
#
# NOT excluded: CMG (carnitas is one option among many proteins; SPUS
# holds it) and SBUX (bacon-egg sandwiches are a small line item; SPUS
# holds it). Wingstop (WING), Dutch Bros (BROS) — chicken-only / coffee,
# no pork — kept.
#
# NOTE: Non-zabihah meat preparation (non-halal-slaughtered beef/chicken)
# is NOT a separate exclusion criterion. AAOIFI / SPUS / HLAL don't screen
# on it — that's a personal-consumption rule, not an investment-compliance
# rule. Screening on it would put us out of line with every certified
# Halal ETF.
PORK_RESTAURANTS = frozenset({
    "MCD",    # McDonald's — bacon, sausage, McRib
    "JACK",   # Jack in the Box — bacon cheeseburgers, breakfast sausage
    "WEN",    # Wendy's — Baconator and similar bacon-forward menu
    "QSR",    # Restaurant Brands — BK bacon, Tim Hortons sausage
    "YUM",    # Yum Brands — Pizza Hut pepperoni, KFC bacon
    "DPZ",    # Domino's — pepperoni / sausage as flagship toppings
})

# Cruise lines — onboard casinos (gambling) + bar service (alcohol) account
# for a material slice of revenue. Excluded by mainstream Halal screens.
CRUISE_LINES = frozenset({
    "CCL",    # Carnival
    "RCL",    # Royal Caribbean
    "NCLH",   # Norwegian Cruise Line
})

# Hotel chains with material bar / casino revenue. Marriott, Hilton, Hyatt
# all operate hotel bars worldwide; Marriott also has casino properties.
# Conservative exclusion. (Note: MGM is already excluded under GAMBLING.)
HOTEL_OPERATORS = frozenset({
    "MAR",    # Marriott
    "HLT",    # Hilton
    "H",      # Hyatt
})

# Crypto exchanges and Bitcoin miners. Shariah scholars are split on crypto
# itself; the conservative consensus (echoed by SPUS/HLAL, which hold neither)
# is to exclude crypto-exchange operators and pure-play miners until the
# fiqh debate settles. Mining infrastructure firms with broader compute/HPC
# businesses (e.g., CORZ) may pass; pure miners listed here are excluded.
CRYPTO = frozenset({
    "COIN",                                       # Coinbase exchange
    "MARA", "RIOT", "CLSK", "WULF", "HUT", "BITF",  # Bitcoin miners
})

# Alcohol
ALCOHOL = frozenset({
    "BUD", "STZ", "DEO", "TAP", "SAM",
})

# Tobacco
TOBACCO = frozenset({
    "MO", "PM", "BTI",
})

# Gambling / casinos / sports betting / gaming REITs
GAMBLING = frozenset({
    "WYNN", "LVS", "MGM", "DKNG", "PENN", "CZR", "BYD", "FLUT",
    "FUBO",  # sports betting tilt
    "VICI",  # Vici Properties — gaming/casino REIT (owns Caesars, MGM Grand)
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

# Conventional ETFs and funds. These bundle non-Shariah-screened constituents
# (XLF holds banks; SPY holds banks + insurers; bond ETFs are pure riba;
# leveraged ETFs use swaps = gharar; volatility ETFs are pure maysir). Only
# physically-backed precious metal ETFs (GLD, SLV) and gold-miner equity
# ETFs (GDX, GDXJ) survive — gold and silver are Shariah-compliant
# stores of value (see AAOIFI Sharia Standard 57 on gold).
CONVENTIONAL_ETFS = frozenset({
    # Broad-market index funds (bundle haram constituents)
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO", "VXUS",
    "EFA", "IEFA",
    # Sector ETFs (not Shariah-screened; XLF includes banks)
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
    "XLRE", "XLC",
    # Thematic / industry ETFs
    "SOXX", "SMH", "IGV", "HACK", "FINX", "IBB", "XBI", "IHI",
    "ARKK", "ARKG", "ARKW", "ARKQ", "ARKF", "ARKX",
    # Bond ETFs (interest-bearing = riba)
    "TLT", "IEF", "SHY", "HYG", "LQD", "EMB", "TIP",
    # Commodity-futures (gharar — futures structure, not physical backing)
    "USO", "UNG", "DBA", "DBC",
    # Volatility ETFs (maysir — pure speculation on VIX)
    "UVXY", "VXX",
    # Leveraged / inverse ETFs (swaps + financing = haram structure)
    "SQQQ", "TQQQ", "SPXU", "UPRO",
    # Single-country ETFs (not Shariah-screened)
    "EWZ", "EWJ", "FXI", "MCHI", "INDA", "EWY", "EWG", "EWU", "EWC",
})

# Combine all exclusions
ALL_EXCLUDED = (
    BANKS | INSURANCE | LENDING | MIXED_OPERATIONS | ALCOHOL |
    TOBACCO | GAMBLING | WEAPONS | CRYPTO | CONVENTIONAL_ETFS |
    PORK_RESTAURANTS | CRUISE_LINES | HOTEL_OPERATORS
)


def is_halal_compliant(ticker: str) -> bool:
    """Return True if the ticker is NOT in our excluded list."""
    return ticker.upper() not in ALL_EXCLUDED


def exclusion_reason(ticker: str) -> str | None:
    """Return the category that excludes a ticker, or None if it's compliant."""
    t = ticker.upper()
    if t in BANKS:
        return "Conventional banking (interest-based deposits/lending = riba)"
    if t in INSURANCE:
        return "Conventional insurance (interest-bearing reserves)"
    if t in LENDING:
        return "Interest-based lending platform (riba)"
    if t in MIXED_OPERATIONS:
        return "Mixed-operations conglomerate (material insurance/interest income; not in SPUS/HLAL)"
    if t in ALCOHOL:
        return "Alcohol production/distribution"
    if t in TOBACCO:
        return "Tobacco industry"
    if t in GAMBLING:
        return "Gambling / casinos / sports betting / gaming REIT"
    if t in WEAPONS:
        return "Weapons manufacturer (controversial — some scholars permit defensive)"
    if t in CRYPTO:
        return "Crypto exchange / Bitcoin miner (Shariah compliance debated; not held by SPUS/HLAL)"
    if t in CONVENTIONAL_ETFS:
        return "Conventional ETF (bundles non-Shariah-screened constituents)"
    if t in PORK_RESTAURANTS:
        return "Restaurant with pork as flagship menu item (bacon/pepperoni/sausage)"
    if t in CRUISE_LINES:
        return "Cruise line (material onboard casino + bar revenue)"
    if t in HOTEL_OPERATORS:
        return "Hotel operator with material bar / casino revenue"
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
