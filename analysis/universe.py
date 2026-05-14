"""Ticker universe definitions.

Kept here (not in config.yaml) so we can have a large list without bloating
the config. The watchlist drives the daily live-signal generation; the
backtest universe drives the random-cutoff backtesting.

Lists are curated for breadth — large caps, growth, value, sectors, ETFs,
plus some popular small-caps. Penny stocks under ~$5 are excluded because
their bar data on Yahoo is often noisy/inconsistent.
"""

from __future__ import annotations

# Large caps — most popular S&P 500 names by market cap and trading volume
LARGE_CAPS = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    # Other tech
    "ORCL", "CRM", "ADBE", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX",
    "INTU", "NOW", "PANW", "CRWD", "SNOW", "PLTR", "NET", "ZS", "DDOG", "FTNT",
    # Financial
    "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", "BLK", "SCHW", "USB", "PNC", "TFC",
    "COF", "AIG", "MET", "PRU", "TRV", "AFL", "ALL", "CB",
    # Consumer
    "WMT", "COST", "HD", "LOW", "TGT", "PG", "KO", "PEP", "MCD", "SBUX", "NKE", "DIS",
    "NFLX", "CMG", "YUM", "EL", "CL", "KMB", "GIS", "K", "MDLZ", "STZ", "MO", "PM",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY", "AMGN",
    "CVS", "CI", "HUM", "GILD", "MDT", "ISRG", "SYK", "BSX", "ZBH", "BDX", "BAX",
    # Industrial
    "BA", "CAT", "DE", "HON", "LMT", "RTX", "GE", "MMM", "EMR", "ETN", "ITW", "PH",
    "FDX", "UPS", "UNP", "CSX", "NSC", "WM", "RSG", "GD", "NOC", "TDG",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "MPC", "VLO", "PXD", "FANG", "DVN",
    # Real estate / Utilities
    "AMT", "PLD", "EQIX", "PSA", "CCI", "DLR", "O", "SPG", "WELL", "VICI",
    "NEE", "DUK", "SO", "AEP", "EXC", "XEL", "ED", "SRE", "WEC", "ES",
    # Materials & Commodities
    "LIN", "APD", "SHW", "FCX", "NEM", "ECL", "DD", "DOW", "NUE", "CTVA",
    # Communication
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "PARA", "DIS",
    # Auto/EV
    "F", "GM", "RIVN", "LCID", "TSLA",
    # Retail
    "BBY", "DLTR", "DG", "TJX", "ROST", "M",
    # Cyclical / Industrials
    "MMM", "EMR", "GE", "PCAR", "WAB", "ROK",
]

# Mid / smaller caps and popular trading names (deduplicated below)
POPULAR_MID_SMALL = [
    "GME", "AMC", "BBBY", "PLTR", "SOFI", "HOOD", "COIN", "RBLX", "DKNG", "PENN",
    "MARA", "RIOT", "MSTR", "CLSK", "WULF", "CIFR",
    "ROKU", "PINS", "SNAP", "LYFT", "UBER", "DASH",
    "SPCE", "JOBY", "NKLA", "FSR", "WKHS", "QS", "CHPT", "BLNK", "EVGO",
    "AI", "BBAI", "SOUN", "AUR", "GOEV", "RUM",
    "PTON", "ETSY", "W", "CHWY", "SHOP", "CART", "ABNB",
    "DOCN", "FROG", "ESTC", "MDB", "OKTA", "TWLO", "ZM", "TEAM", "ASAN",
    "U", "PATH", "S", "GTLB", "FUBO",
    "AFRM", "UPST", "OPEN", "TSP", "BROS", "LMND", "CVNA", "WBA",
]

# ETFs — broad market, sectors, and popular thematic
ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO", "VXUS",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "ARKK", "ARKG", "ARKW", "ARKQ", "ARKF",
    "SOXX", "SMH", "IBB", "XBI", "GDX", "GDXJ",
    "TLT", "IEF", "HYG", "LQD",
    "GLD", "SLV", "USO", "UNG",
    "VIX", "UVXY",
]

# Deduplicate while preserving order
def _dedup(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


WATCHLIST = _dedup(LARGE_CAPS + POPULAR_MID_SMALL + ETFS)

# Backtest universe — same as watchlist but can diverge in the future
BACKTEST_UNIVERSE = WATCHLIST


def watchlist() -> list[str]:
    return list(WATCHLIST)


def backtest_universe() -> list[str]:
    return list(BACKTEST_UNIVERSE)
