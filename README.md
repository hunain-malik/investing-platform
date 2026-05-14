# investing-platform

A personal pattern-recognition investing platform. Pulls public market data, runs an ensemble of technical-analysis patterns, generates buy/sell/hold signals with confidence scores, recommends position size + whether to use options or equity, and tracks every prediction it makes on a public scoreboard so you can see its real hit rate over time.

The platform runs on GitHub Actions (daily) and publishes results to a static dashboard via GitHub Pages.

## Important

This is not investment advice. The system predicts probabilistically based on historical patterns in public market data. You are responsible for every trade you place. Read the scoreboard before acting on any signal — if accuracy is below 55% on a given pattern set, ignore it.

## What it does

1. **Fetches daily OHLCV data** for a configurable watchlist (default: large-cap US equities) via Yahoo Finance.
2. **Computes technical indicators**: SMA/EMA, RSI, MACD, Bollinger Bands, ATR, volume metrics.
3. **Detects chart patterns**: moving-average crossovers (golden/death cross), RSI overbought/oversold, MACD crossovers, Bollinger squeezes/breakouts, candlestick patterns (engulfing, hammer, doji, shooting star), support/resistance breaks.
4. **Combines signals into an ensemble** with per-pattern weights derived from backtest accuracy. Each pattern votes; the ensemble's confidence is the calibrated weighted vote.
5. **Recommends position size** based on your configured capital and risk tolerance (capped Kelly + ATR stop-loss).
6. **Recommends options vs equity** when directional confidence is high and time horizon is right.
7. **Backtests on random historical cutoffs**: picks a random ticker and a random past date, predicts forward N days using only data up to that date, then scores against actuals. This produces thousands of validated predictions on day 1.
8. **Tracks live predictions** with timestamps. Each prediction has a horizon (e.g., 5, 10, 20 days). When the horizon closes, the prediction is resolved (correct/wrong) and added to the scoreboard.
9. **Re-weights patterns** based on accumulated accuracy so the ensemble improves over time.

## Scoreboard

The dashboard shows:
- Total predictions made, correct (green), wrong (red).
- Bullish accuracy and bearish accuracy broken out separately.
- Per-pattern accuracy (so you can see which individual signals are working).
- Ensemble accuracy by confidence bucket (calibration plot).
- Recent prediction log with status.
- Current open signals you might want to act on.

## How to run locally (optional)

You only need Python locally if you want to run analyses manually. The GitHub Actions workflow runs everything daily on its own.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m analysis.run
```

Outputs go to `docs/data/` as JSON.

## Configuration

Edit `config.yaml`:
- `watchlist`: tickers to analyze.
- `capital`: how much you have to invest.
- `risk_per_trade_pct`: max % of capital risked per trade (default 2%).
- `backtest`: number of random historical samples per pattern.
- `horizons_days`: forward-looking prediction windows.

## License

MIT. See LICENSE.
