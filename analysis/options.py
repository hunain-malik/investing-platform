"""Options vs equity recommendation.

Pure heuristic — we do not pull option chains from a market data provider in
this build. The recommender suggests when options are worth considering and
which strategy fits the signal, but the user must price the trade in their
broker (real strike grid, real IV, real premiums).

Strategy rules:

    direction up, confidence >= 0.75, horizon <= 20d  -> long call (debit)
    direction up, confidence in [0.60, 0.75)          -> bull call spread
    direction down, confidence >= 0.75, horizon <= 20d -> long put (debit)
    direction down, confidence in [0.60, 0.75)        -> bear put spread
    confidence < 0.60                                 -> equity only / pass

Strike guidance:
    long call: slightly OTM (1-2% above spot)
    long put: slightly OTM (1-2% below spot)
    spread short leg: ~one ATR beyond the long leg in the direction of the move

Expiration (days to expiration, DTE):
    Standard retail options practice — 30 to 90 DTE for directional plays.
    Too short = gamma risk near expiry. Too long = pay too much time
    premium that bleeds away (theta decay). Sweet spot is `horizon + 30d`
    buffer.

    For horizons beyond ~1 year (252 trading days), listed options
    typically only go out to LEAPS (365 days) and most retail traders
    avoid them entirely — we don't recommend options at those horizons,
    just equity.

    target_dte = clip(horizon_days + 30, 45, 365)
                 -- and skip options entirely if horizon > 252.

Risk capital estimation is a placeholder; the user replaces with actual quotes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OptionsPlan:
    use_options: bool
    strategy: str       # "long_call", "long_put", "bull_call_spread", "bear_put_spread", "none"
    rationale: str
    long_strike: float | None = None
    short_strike: float | None = None
    target_dte_days: int = 30
    estimated_max_loss_usd: float | None = None  # caller fills in with real quote

    def to_dict(self) -> dict:
        return {
            "use_options": self.use_options,
            "strategy": self.strategy,
            "rationale": self.rationale,
            "long_strike": round(self.long_strike, 2) if self.long_strike is not None else None,
            "short_strike": round(self.short_strike, 2) if self.short_strike is not None else None,
            "target_dte_days": self.target_dte_days,
            "estimated_max_loss_usd": (
                round(self.estimated_max_loss_usd, 2) if self.estimated_max_loss_usd is not None else None
            ),
        }


def _round_strike(price: float) -> float:
    """Round to nearest strike grid (roughly: $1 strikes under $50, $2.5 to $200, $5 above)."""
    if price < 50:
        return round(price)
    if price < 200:
        return round(price * 2) / 2  # nearest 0.5 — closer to typical $2.5 grid
    return round(price / 5) * 5


def recommend_options(
    direction: str,
    confidence: float,
    spot: float,
    atr: float,
    horizon_days: int,
    options_allowed: bool,
) -> OptionsPlan:
    if not options_allowed or direction not in ("up", "down"):
        return OptionsPlan(use_options=False, strategy="none", rationale="options not allowed or no direction")

    if confidence < 0.60:
        return OptionsPlan(
            use_options=False, strategy="none",
            rationale=f"confidence {confidence:.2f} too low — use equity if anything",
        )

    # Skip options entirely for very long horizons — listed options don't
    # extend much past 1 year, and LEAPS are illiquid + expensive theta.
    if horizon_days > 252:
        return OptionsPlan(
            use_options=False, strategy="none",
            rationale=f"horizon {horizon_days}d exceeds 1y — options unsuitable (theta decay, no LEAPS that long), use equity",
        )

    # Standard retail DTE: horizon + 30d buffer, clamped to [45, 365]
    target_dte = max(45, min(365, horizon_days + 30))

    if direction == "up":
        if confidence >= 0.75 and horizon_days <= 20:
            strike = _round_strike(spot * 1.015)
            return OptionsPlan(
                use_options=True, strategy="long_call",
                rationale=f"high bullish confidence ({confidence:.2f}) and short horizon — long call for leverage",
                long_strike=strike, target_dte_days=target_dte,
            )
        long_k = _round_strike(spot * 1.005)
        short_k = _round_strike(spot + atr * 2)
        return OptionsPlan(
            use_options=True, strategy="bull_call_spread",
            rationale=f"moderate bullish confidence ({confidence:.2f}) — debit spread caps cost and risk",
            long_strike=long_k, short_strike=short_k, target_dte_days=target_dte,
        )

    # direction == "down"
    if confidence >= 0.75 and horizon_days <= 20:
        strike = _round_strike(spot * 0.985)
        return OptionsPlan(
            use_options=True, strategy="long_put",
            rationale=f"high bearish confidence ({confidence:.2f}) and short horizon — long put for leverage",
            long_strike=strike, target_dte_days=target_dte,
        )
    long_k = _round_strike(spot * 0.995)
    short_k = _round_strike(spot - atr * 2)
    return OptionsPlan(
        use_options=True, strategy="bear_put_spread",
        rationale=f"moderate bearish confidence ({confidence:.2f}) — debit spread caps cost and risk",
        long_strike=long_k, short_strike=short_k, target_dte_days=target_dte,
    )
