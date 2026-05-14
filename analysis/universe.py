"""Ticker universe.

Broad coverage: large-cap, mid-cap, popular trading names, ETFs. Curated to
~400 tickers — most of the S&P 500 you'd actually look at, plus liquid
NASDAQ 100 names, popular small/mid caps, and a sector ETF set.

Keep edits here (not in config.yaml) so we can have a long list without
bloating the config.
"""

from __future__ import annotations

# Mega-cap tech
MEGA_TECH = ["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA"]

# Large-cap tech / software / semis
LARGE_TECH = [
    "ORCL", "CRM", "ADBE", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU",
    "AMAT", "LRCX", "KLAC", "ASML", "INTU", "NOW", "PANW", "CRWD", "SNOW",
    "PLTR", "NET", "ZS", "DDOG", "FTNT", "CHKP", "CYBR", "S",
    "IBM", "HPQ", "HPE", "DELL", "WDC", "STX", "GLW",
    "CDNS", "SNPS", "ANSS", "ADSK", "WDAY", "TEAM", "ZM", "OKTA",
    "TWLO", "MDB", "ESTC", "DT", "TENB", "QLYS", "RPD",
    "MRVL", "ON", "NXPI", "MCHP", "ADI", "MPWR", "SWKS", "TER",
    "AKAM", "FFIV", "JNPR", "ANET", "CSCO", "FSLR", "ENPH", "SEDG",
]

# Financials / banks
FINANCIALS = [
    "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", "BLK", "SCHW", "USB",
    "PNC", "TFC", "COF", "AIG", "MET", "PRU", "TRV", "AFL", "ALL", "CB",
    "MMC", "AON", "MCO", "SPGI", "ICE", "CME", "NDAQ", "MKTX",
    "DFS", "SYF", "FITB", "MTB", "HBAN", "RF", "KEY", "CFG", "ZION",
    "SBNY", "FRC", "NTRS", "STT", "BK",
    "PYPL", "SQ", "MA", "V", "FIS", "FISV", "GPN", "JKHY",
    "BRK.B",
]

# Consumer / retail / staples
CONSUMER = [
    "WMT", "COST", "HD", "LOW", "TGT", "PG", "KO", "PEP", "MCD", "SBUX",
    "NKE", "DIS", "NFLX", "CMG", "YUM", "EL", "CL", "KMB", "GIS", "K",
    "MDLZ", "STZ", "MO", "PM", "BUD", "DEO", "MNST", "KDP", "HSY",
    "BBY", "DLTR", "DG", "TJX", "ROST", "M", "JWN", "KSS", "GPS",
    "LULU", "RH", "DECK", "CROX", "SKX",
    "DPZ", "QSR", "WEN", "JACK", "WING", "BROS", "LUV", "DAL",
    "CCL", "RCL", "NCLH", "MGM", "WYNN", "LVS", "PENN", "CZR", "DKNG",
    "ABNB", "BKNG", "EXPE", "MAR", "HLT", "H",
    "F", "GM", "TM", "STLA", "RIVN", "LCID", "FSR", "NIO", "XPEV", "LI",
]

# Healthcare / biotech / pharma
HEALTHCARE = [
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "CVS", "CI", "HUM", "GILD", "MDT", "ISRG", "SYK", "BSX", "ZBH",
    "BDX", "BAX", "EW", "HOLX", "DXCM", "PODD", "ALGN", "IDXX",
    "REGN", "VRTX", "MRNA", "BIIB", "ILMN", "INCY", "BMRN", "ALNY",
    "MCK", "ABC", "CAH", "HCA", "UHS", "DVA", "CNC", "MOH",
    "NVO", "AZN", "GSK", "SNY", "RHHBY", "NVS",
]

# Industrial / defense / transport
INDUSTRIAL = [
    "BA", "CAT", "DE", "HON", "LMT", "RTX", "GE", "MMM", "EMR", "ETN",
    "ITW", "PH", "DOV", "ROK", "PCAR", "WAB", "WM", "RSG", "WCN",
    "FDX", "UPS", "UNP", "CSX", "NSC", "ODFL", "JBHT", "CHRW", "EXPD",
    "GD", "NOC", "TDG", "HEI", "TXT", "HII", "LDOS", "BAH",
    "ATR", "IR", "XYL", "FTV", "AME", "DOV", "PWR", "URI",
]

# Energy / oil / utilities
ENERGY_UTILS = [
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "MPC", "VLO", "PXD",
    "FANG", "DVN", "HES", "HAL", "BKR", "WMB", "OKE", "KMI", "EPD", "ET",
    "NEE", "DUK", "SO", "AEP", "EXC", "XEL", "ED", "SRE", "WEC", "ES",
    "EIX", "PEG", "DTE", "AEE", "CMS", "ETR", "FE", "PCG", "PPL", "AWK",
]

# Materials / commodities / chemicals
MATERIALS = [
    "LIN", "APD", "SHW", "FCX", "NEM", "ECL", "DD", "DOW", "NUE", "CTVA",
    "MOS", "CF", "FMC", "ALB", "EMN", "PPG", "MLM", "VMC", "STLD", "X",
    "BHP", "RIO", "VALE", "WPM", "FNV", "AEM",
]

# Communication / telecom / media
COMMUNICATION = [
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "PARA", "WBD", "FOX", "FOXA",
    "EA", "TTWO", "ATVI", "RBLX",
    "ROKU", "PINS", "SNAP", "LYFT", "UBER", "DASH",
    "MTCH", "BMBL", "Z", "ZG", "RDFN",
]

# Real estate
REIT = [
    "AMT", "PLD", "EQIX", "PSA", "CCI", "DLR", "O", "SPG", "WELL", "VICI",
    "AVB", "EQR", "ESS", "MAA", "UDR", "BXP", "ARE", "VTR", "PEAK",
    "EXR", "CUBE", "LSI", "STAG", "INVH", "AMH",
]

# Popular trading / meme / retail names
POPULAR_TRADING = [
    "GME", "AMC", "BB", "NOK", "BBBY",
    "PLTR", "SOFI", "HOOD", "COIN", "MSTR",
    "MARA", "RIOT", "CLSK", "WULF", "CIFR", "HUT", "BITF",
    "TSLA", "RIVN", "LCID", "NKLA", "FSR", "QS", "CHPT", "BLNK", "EVGO",
    "SPCE", "JOBY", "ACHR", "EVTL",
    "AI", "BBAI", "SOUN", "AUR", "GOEV", "RUM", "DJT",
    "PTON", "ETSY", "W", "CHWY", "SHOP", "CART", "DOCN",
    "FROG", "MDB", "ESTC", "U", "PATH", "GTLB", "ASAN",
    "AFRM", "UPST", "OPEN", "TSP", "LMND", "CVNA", "WBA",
    "FUBO", "BMBL", "RNG", "FVRR", "UPWK",
]

# ETFs — broad market, sectors, thematic, fixed income, commodities, volatility
ETFS = [
    # Broad market
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO", "VXUS", "EFA", "IEFA",
    # Sectors (SPDR)
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # Semis / tech subsectors
    "SOXX", "SMH", "IGV", "HACK", "FINX",
    # Healthcare / bio
    "IBB", "XBI", "IHI",
    # ARK family
    "ARKK", "ARKG", "ARKW", "ARKQ", "ARKF", "ARKX",
    # Metals / commodities
    "GLD", "SLV", "GDX", "GDXJ", "USO", "UNG", "DBA", "DBC",
    # Bonds
    "TLT", "IEF", "SHY", "HYG", "LQD", "EMB", "TIP",
    # Volatility / inverse
    "UVXY", "VXX", "SQQQ", "TQQQ", "SPXU", "UPRO",
    # International
    "EWZ", "EWJ", "FXI", "MCHI", "INDA", "EWY", "EWG", "EWU", "EWC",
]


def _dedup(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


_ALL = (
    MEGA_TECH + LARGE_TECH + FINANCIALS + CONSUMER + HEALTHCARE
    + INDUSTRIAL + ENERGY_UTILS + MATERIALS + COMMUNICATION + REIT
    + POPULAR_TRADING + ETFS
)

WATCHLIST = _dedup(_ALL)
BACKTEST_UNIVERSE = WATCHLIST


def watchlist() -> list[str]:
    return list(WATCHLIST)


def backtest_universe() -> list[str]:
    return list(BACKTEST_UNIVERSE)
