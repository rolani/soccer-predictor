"""Odds conversion and the soft-book pricing model.

Pinnacle is a sharp book (about 4.8% overround). SportyBet is soft and loads
margin onto longshots. We strip Pinnacle's vig to fair probabilities, then
re-apply a soft-book overround using the odds-ratio transform, which leaves
heavy favourites close to fair and shortens longer prices.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

DEFAULT_OVERROUND: dict[str, float] = {
    "goals_totals": 1.055,
    "team_totals": 1.055,
    "halves": 1.055,
    "btts": 1.055,
    "handicap": 1.055,
    "result": 1.070,
    "corners": 1.070,
    "dc_dnb": 1.060,
    "specials": 1.150,
}


def overround_for(family: str) -> float:
    """Target book overround for a market family, overridable per family."""
    env_key = f"PREDICTOR_OVERROUND_{family.upper()}"
    raw = os.environ.get(env_key, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_OVERROUND.get(family, DEFAULT_OVERROUND["specials"])


def american_to_decimal(price: float) -> float:
    """Convert American odds to decimal."""
    price = float(price)
    if price > 0:
        return 1.0 + price / 100.0
    return 1.0 + 100.0 / abs(price)


def _odds_ratio(p: float, c: float) -> float:
    """Odds-ratio transform. c > 1 inflates, c < 1 deflates, c == 1 is identity."""
    return (c * p) / (c * p - p + 1.0)


def _solve_c(probs: Sequence[float], target_sum: float) -> float:
    """Bisect for c such that sum(_odds_ratio(p, c)) == target_sum."""
    if not probs:
        return 1.0
    valid = [p for p in probs if 0.0 < p < 1.0]
    if not valid:
        return 1.0
    lo, hi = 1e-6, 1e6
    for _ in range(200):
        mid = (lo + hi) / 2.0
        total = sum(_odds_ratio(p, mid) for p in valid)
        if total < target_sum:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def devig(raw_decimals: Sequence[float]) -> list[float]:
    """Strip the book's margin, returning fair probabilities that sum to 1."""
    implied = [1.0 / d for d in raw_decimals]
    c = _solve_c(implied, 1.0)
    return [_odds_ratio(p, c) for p in implied]


def revig(fair: Sequence[float], target_overround: float) -> list[float]:
    """Re-apply a book margin to fair probabilities."""
    c = _solve_c(fair, target_overround)
    return [_odds_ratio(p, c) for p in fair]


def to_book_prices(raw_decimals: Sequence[float], family: str) -> list[float]:
    """Convert sharp decimal prices into soft-book decimal prices."""
    if not raw_decimals:
        return []
    fair = devig(raw_decimals)
    adjusted = revig(fair, overround_for(family))
    return [round(1.0 / p, 3) for p in adjusted]
