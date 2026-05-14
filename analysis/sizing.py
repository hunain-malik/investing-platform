"""Position sizing.

Given an entry signal with price and ATR, plus user capital and risk profile,
recommend how many shares to buy and where to place the stop-loss.

Method:
    1. Risk dollars per trade  = capital * risk_per_trade_pct
    2. Stop distance           = ATR_MULT * ATR  (default 2.0x ATR)
    3. Stop price              = entry - stop_distance (long) or entry + stop_distance (short)
    4. Ideal shares            = risk_dollars / stop_distance
    5. Position dollars        = ideal_shares * entry
    6. Cap at max_position_pct of capital
    7. Scale by a confidence factor that ramps from 0 at conf=0.5 to 1 at conf=0.85+

This is a classic fixed-fractional sizer with an ATR-based stop and a
confidence ramp on top. Not Kelly (Kelly assumes you know the true win rate;
we don't, especially early when the scoreboard is thin).
"""

from __future__ import annotations

from dataclasses import dataclass

ATR_MULT = 2.0


@dataclass
class SizingPlan:
    direction: str           # "up" (long) or "down" (short)
    entry: float
    stop: float
    shares: int
    position_usd: float
    risk_usd: float
    confidence_factor: float

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry": round(self.entry, 4),
            "stop": round(self.stop, 4),
            "shares": self.shares,
            "position_usd": round(self.position_usd, 2),
            "risk_usd": round(self.risk_usd, 2),
            "confidence_factor": round(self.confidence_factor, 4),
        }


def _confidence_factor(confidence: float) -> float:
    """0 at 0.5, 1 at 0.85+. Linear ramp in between."""
    if confidence <= 0.5:
        return 0.0
    if confidence >= 0.85:
        return 1.0
    return (confidence - 0.5) / 0.35


def size_position(
    direction: str,
    entry: float,
    atr: float,
    confidence: float,
    capital_usd: float,
    risk_per_trade_pct: float,
    max_position_pct: float,
) -> SizingPlan | None:
    """Return a sizing plan, or None if the signal is too weak / data is bad."""
    if direction not in ("up", "down"):
        return None
    if entry <= 0 or atr <= 0:
        return None

    cf = _confidence_factor(confidence)
    if cf == 0.0:
        return None  # not confident enough to trade

    risk_dollars = capital_usd * (risk_per_trade_pct / 100.0) * cf
    stop_distance = ATR_MULT * atr
    if stop_distance <= 0:
        return None

    if direction == "up":
        stop = entry - stop_distance
    else:
        stop = entry + stop_distance

    ideal_shares = risk_dollars / stop_distance
    ideal_position_usd = ideal_shares * entry

    max_position_usd = capital_usd * (max_position_pct / 100.0)
    if ideal_position_usd > max_position_usd:
        capped_shares = max_position_usd / entry
    else:
        capped_shares = ideal_shares

    shares = int(capped_shares)  # whole shares only
    if shares <= 0:
        return None

    actual_position_usd = shares * entry
    actual_risk_usd = shares * stop_distance

    return SizingPlan(
        direction=direction,
        entry=entry,
        stop=stop,
        shares=shares,
        position_usd=actual_position_usd,
        risk_usd=actual_risk_usd,
        confidence_factor=cf,
    )
