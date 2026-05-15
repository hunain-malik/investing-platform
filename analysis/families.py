"""Pattern families for decorrelated voting.

Confidence calibration: uses Bayesian log-odds updating. Each family that
votes contributes log-odds based on its per-horizon backtest accuracy:

    log_odds += log(acc / (1 - acc)) if vote is UP
    log_odds -= log(acc / (1 - acc)) if vote is DOWN

A family at 60% accuracy contributes ±log(1.5) ≈ ±0.405 per vote. Three
60%-accurate families all voting UP push log-odds to +1.22, which sigmoids
to P(up) = 0.77 — not 1.0. This correctly reflects that even unanimous
agreement among imperfect voters doesn't yield certainty.

Confidence is hard-capped at 0.95 to acknowledge irreducible uncertainty
(black swans, regime shifts, model misspecification).

The old formula `0.5 + 0.5 * |margin|` produced confidence 1.0 whenever
all participating voters agreed, regardless of voter count or voter
accuracy. That was overconfident and is fixed here.

The methodology-based meta-ensemble counted correlated votes multiple times:
e.g. `all`, `trend_following`, and `trend_in_trending_regime` all included
SMA + MACD + multi-timeframe patterns, so when "3 methodologies agreed
DOWN" it was largely ONE underlying trend signal counted three times.

This module groups patterns into independent FAMILIES — categories of
signals that look at fundamentally different phenomena:

    trend           : SMA/MACD/multi-timeframe/Ichimoku/golden-death cross
    momentum        : RSI, Stochastic
    volatility      : Bollinger Bands (squeeze/breakout)
    volume          : volume breakouts, dry-up/dry-top
    candlestick     : engulfing, hammer, shooting star, doji
    relative_strength: RS vs SPY

Each family produces ONE vote based on the patterns within it. The
consensus_families meta aggregates these family votes — those agreements
are statistically meaningful because each family looks at different data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    patterns: frozenset[str]
    description: str


FAMILIES: list[Family] = [
    Family(
        name="trend",
        description="SMA/MACD crossovers, multi-timeframe alignment, golden/death cross, Ichimoku",
        patterns=frozenset({
            "sma_crossover_bull", "sma_crossover_bear",
            "golden_cross", "death_cross",
            "macd_cross_bull", "macd_cross_bear",
            "multi_timeframe_bull", "multi_timeframe_bear",
            "ichimoku_bull_cross", "ichimoku_bear_cross",
        }),
    ),
    Family(
        name="momentum",
        description="RSI and Stochastic oscillators (oversold/overbought reversals)",
        patterns=frozenset({
            "rsi_oversold", "rsi_overbought",
            "stochastic_oversold", "stochastic_overbought",
        }),
    ),
    Family(
        name="volatility",
        description="Bollinger Band squeeze + breakout patterns",
        patterns=frozenset({
            "bb_squeeze_breakout_up", "bb_squeeze_breakout_down",
        }),
    ),
    Family(
        name="volume",
        description="High-volume breakouts and divergences (dry-up at lows, dry-top at highs)",
        patterns=frozenset({
            "volume_breakout_bull", "volume_breakout_bear",
            "volume_dry_up", "volume_dry_top",
        }),
    ),
    Family(
        name="candlestick",
        description="Single- and two-candle reversal patterns (engulfing, hammer, shooting star, doji at S/R)",
        patterns=frozenset({
            "bullish_engulfing", "bearish_engulfing",
            "hammer", "shooting_star",
            "doji_at_support", "doji_at_resistance",
        }),
    ),
    Family(
        name="relative_strength",
        description="Out/under-performance vs SPY over 20 days",
        patterns=frozenset({
            "relative_strength_bull", "relative_strength_bear",
        }),
    ),
]


def family_for_pattern(pattern_name: str) -> str | None:
    """Return the family name a pattern belongs to, or None if uncategorized."""
    for fam in FAMILIES:
        if pattern_name in fam.patterns:
            return fam.name
    return None


def evaluate_family_vote(
    family: Family,
    fired_patterns_with_directions: dict[str, str],
) -> tuple[str, float] | None:
    """Aggregate patterns within ONE family to a single (direction, confidence)
    vote. Returns None if no pattern from this family fired.

    Confidence in [0, 1]: 0 if family votes are split 50/50, 1 if unanimous.
    """
    fam_patterns_fired = [
        (name, direction) for name, direction in fired_patterns_with_directions.items()
        if name in family.patterns
    ]
    if not fam_patterns_fired:
        return None
    up = sum(1 for _, d in fam_patterns_fired if d == "up")
    down = sum(1 for _, d in fam_patterns_fired if d == "down")
    total = up + down
    if total == 0:
        return None
    if up > down:
        return ("up", up / total)
    if down > up:
        return ("down", down / total)
    return None  # tied — no vote


def evaluate_consensus_families_live(
    fired_pattern_signals: list,
    family_accuracies_at_horizon: dict[str, float] | None = None,
    min_families: int = 3,
    min_margin: float = 0.30,
) -> dict | None:
    """Live-data version: takes a list of fired PatternSignal objects
    (with .name and .direction) instead of a stored dict. Useful for
    operating on today's signals as opposed to historical samples.
    """
    fired_dict = {p.name: p.direction for p in fired_pattern_signals}
    return evaluate_consensus_families(
        fired_dict, family_accuracies_at_horizon, min_families, min_margin,
    )


import math

# Confidence cap — even a unanimous high-accuracy panel shouldn't claim
# certainty. Markets can surprise; this prevents the model from telling
# users it's 100% sure when it's never seen the future.
MAX_CONFIDENCE = 0.95

# Default accuracy assumption when no historical data is available for a
# family at this horizon. 0.55 = slight edge over chance — conservative.
DEFAULT_ACC = 0.55


def evaluate_consensus_families(
    fired_patterns_with_directions: dict[str, str],
    family_accuracies_at_horizon: dict[str, float] | None = None,
    min_families: int = 3,
    min_margin: float = 0.30,
) -> dict | None:
    """Aggregate family-level votes via Bayesian log-odds update.

    Returns None if fewer than min_families voted, or net vote margin too small.
    Confidence is hard-capped at 0.95 — even unanimous agreement among
    imperfect voters does NOT yield certainty.
    """
    votes = []
    contributing = []
    log_odds = 0.0  # prior log-odds for P(up) = 0.5
    weighted_up = 0.0
    weighted_down = 0.0

    for fam in FAMILIES:
        v = evaluate_family_vote(fam, fired_patterns_with_directions)
        if v is None:
            continue
        direction, internal_conf = v

        # Get this family's historical accuracy at the current horizon
        raw_acc = (family_accuracies_at_horizon or {}).get(fam.name)
        if raw_acc is None:
            acc = DEFAULT_ACC
        else:
            acc = float(raw_acc)
        # Drop below-chance families
        if acc < 0.5:
            continue
        # Clip extreme accuracies to avoid log(0) and prevent any single
        # family from dominating the log-odds update
        acc_clipped = max(0.51, min(0.85, acc))

        # Bayesian log-odds contribution. Internal_conf scales the strength —
        # a family where 3-of-3 patterns agree is more decisive than 2-of-3.
        log_lr = math.log(acc_clipped / (1.0 - acc_clipped))
        signed_contribution = log_lr * internal_conf
        if direction == "up":
            log_odds += signed_contribution
            weighted_up += signed_contribution
        else:
            log_odds -= signed_contribution
            weighted_down += signed_contribution

        votes.append((direction, internal_conf, acc, fam.name))
        contributing.append({
            "family": fam.name,
            "direction": direction,
            "internal_confidence": round(internal_conf, 4),
            "log_odds_contribution": round(signed_contribution * (1 if direction == "up" else -1), 4),
            "accuracy": round(acc, 4),
        })

    if len(votes) < min_families:
        return None

    total_log_odds_magnitude = weighted_up + weighted_down  # both positive
    if total_log_odds_magnitude == 0:
        return None
    # Normalized margin in [-1, 1] for diagnostic display
    margin = (weighted_up - weighted_down) / total_log_odds_magnitude
    if abs(margin) < min_margin:
        return None

    p_up = 1.0 / (1.0 + math.exp(-log_odds))
    direction = "up" if p_up > 0.5 else "down"
    confidence = max(p_up, 1.0 - p_up)
    # Hard cap so even strong consensus can't claim certainty
    confidence = min(MAX_CONFIDENCE, confidence)

    return {
        "direction": direction,
        "confidence": round(confidence, 4),
        "vote_margin": round(margin, 4),
        "log_odds": round(log_odds, 4),
        "n_families": len(votes),
        "contributing_families": contributing,
    }
