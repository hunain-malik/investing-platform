"""News sentiment analysis.

Pulls recent news headlines from Yahoo Finance via `yfinance.Ticker.news`
(no API key required), scores them with VADER, and aggregates into a
per-ticker sentiment score in [-1, 1].

LIMITATION: yfinance only exposes ~recent news (last 1-2 weeks). We cannot
fetch historical headlines for a past cutoff date, so sentiment patterns
fire on LIVE signals only — they're excluded from the backtest because we
cannot validate them against history. Their accuracy will become visible
in the live scoreboard as predictions resolve.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    score: float        # weighted mean compound score in [-1, 1]
    headline_count: int
    label: str          # "bullish" / "bearish" / "neutral"
    headlines: list[str]

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "headline_count": self.headline_count,
            "label": self.label,
            "headlines": self.headlines[:5],
        }


def _vader():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except Exception as e:  # noqa: BLE001
        log.warning("VADER not available: %s", e)
        return None


_ANALYZER = _vader()


def fetch_sentiment(ticker: str) -> SentimentResult | None:
    """Return aggregated sentiment for the ticker, or None if no headlines."""
    if _ANALYZER is None:
        return None
    try:
        news = yf.Ticker(ticker).news or []
    except Exception as e:  # noqa: BLE001
        log.warning("could not fetch news for %s: %s", ticker, e)
        return None

    titles: list[str] = []
    for item in news:
        # yfinance shape changed in 0.2.55+; titles can live at item["content"]["title"]
        # or item["title"] on older shapes
        title = None
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, dict):
            title = content.get("title")
        if not title and isinstance(item, dict):
            title = item.get("title")
        if title:
            titles.append(str(title))

    titles = titles[:15]  # cap to keep VADER calls cheap
    if not titles:
        return None

    scores = [_ANALYZER.polarity_scores(t)["compound"] for t in titles]
    mean_score = sum(scores) / len(scores)
    if mean_score >= 0.15:
        label = "bullish"
    elif mean_score <= -0.15:
        label = "bearish"
    else:
        label = "neutral"

    return SentimentResult(
        score=mean_score,
        headline_count=len(titles),
        label=label,
        headlines=titles,
    )
