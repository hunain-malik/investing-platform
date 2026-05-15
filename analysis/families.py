"""Pattern families for decorrelated voting.

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


def evaluate_consensus_families(
    fired_patterns_with_directions: dict[str, str],
    family_accuracies_at_horizon: dict[str, float] | None = None,
    min_families: int = 3,
    min_margin: float = 0.30,
) -> dict | None:
    """Aggregate family-level votes into a single consensus call.

    Returns None if fewer than min_families voted, or vote margin too small.
    Each family that fires contributes one vote, weighted by its own backtest
    accuracy at this horizon (if known; defaults to neutral weight otherwise).
    """
    votes = []
    contributing = []
    for fam in FAMILIES:
        v = evaluate_family_vote(fam, fired_patterns_with_directions)
        if v is None:
            continue
        direction, internal_conf = v
        # weight from per-horizon accuracy if provided
        acc = (family_accuracies_at_horizon or {}).get(fam.name, 0.5)
        if acc < 0.5:
            continue  # drop below-chance families
        w = (acc - 0.5) * 2 if family_accuracies_at_horizon else 1.0
        votes.append((direction, internal_conf, w, fam.name))
        contributing.append({
            "family": fam.name,
            "direction": direction,
            "internal_confidence": round(internal_conf, 4),
            "accuracy_weight": round(w, 4),
            "accuracy": round(acc, 4),
        })

    if len(votes) < min_families:
        return None

    up_votes = [v for v in votes if v[0] == "up"]
    down_votes = [v for v in votes if v[0] == "down"]
    up_score = sum(c * w for _, c, w, _ in up_votes)
    down_score = sum(c * w for _, c, w, _ in down_votes)
    total = up_score + down_score
    if total == 0:
        return None
    margin = (up_score - down_score) / total
    if abs(margin) < min_margin:
        return None

    direction = "up" if margin > 0 else "down"
    confidence = 0.5 + 0.5 * abs(margin)
    return {
        "direction": direction,
        "confidence": confidence,
        "vote_margin": round(margin, 4),
        "n_families": len(votes),
        "contributing_families": contributing,
    }
