"""Target-odds ticket solver. Pure functions. No HTTP."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from predictor.odds.board import BoardFixture, PricedBoard
from predictor.odds.quotes import MarketQuote
from predictor.web.match_utils import normalize_match_key
from predictor.web.schema import Pick

_CS_SCORE = re.compile(r"^\d+-\d+$")
_FILL_FAMILIES = frozenset({"goals_totals", "team_totals", "btts"})
_MAX_CANDIDATES = 16


@dataclass
class TargetTicket:
    leg_indices: list[int]
    combined_odds: float | None
    joint_probability: float
    in_band: bool
    used_fill: bool
    label: str
    extra_picks: list[Pick]  # fill legs to append; empty on researched pass


def _is_correct_score(*, market: str, tip: str, family: str = "") -> bool:
    m = (market or "").lower()
    t = (tip or "").strip()
    tl = t.lower()
    if m == "correct score" or "correct score" in m or "correct score" in tl:
        return True
    if _CS_SCORE.match(t):
        return True
    if family == "specials" and (m == "correct score" or _CS_SCORE.match(t)):
        return True
    return False


def _is_priced_candidate(p: Pick) -> bool:
    if not p.price_available or p.odds is None:
        return False
    return not _is_correct_score(market=p.market, tip=p.tip, family=p.market_family)


def _in_band(product: float, target: float, band: float) -> bool:
    return target * (1.0 - band) <= product <= target * (1.0 + band)


def _log_distance(product: float, target: float) -> float:
    if product <= 0 or target <= 0:
        return float("inf")
    return abs(math.log(product) - math.log(target))


def _label(target: float, *, filled: bool) -> str:
    kind = "board fill" if filled else "researched"
    return f"Target {target:g}× ({kind})"


def _empty(target: float) -> TargetTicket:
    return TargetTicket(
        leg_indices=[],
        combined_odds=None,
        joint_probability=0.0,
        in_band=False,
        used_fill=False,
        label=_label(target, filled=False),
        extra_picks=[],
    )


def _ticket_from_indices(
    picks: list[Pick],
    indices: list[int],
    target: float,
    band: float,
    extra: list[Pick] | None = None,
    used_fill: bool = False,
) -> TargetTicket:
    extra = extra or []
    legs: list[Pick] = []
    for i in indices:
        if i < len(picks):
            legs.append(picks[i])
        else:
            legs.append(extra[i - len(picks)])
    product = 1.0
    joint = 1.0
    for p in legs:
        product *= float(p.odds) if p.odds is not None else 1.0
        joint *= p.estimated_probability
    return TargetTicket(
        leg_indices=list(indices),
        combined_odds=product if indices else None,
        joint_probability=joint if indices else 0.0,
        in_band=_in_band(product, target, band) if indices else False,
        used_fill=used_fill,
        label=_label(target, filled=used_fill),
        extra_picks=list(extra),
    )


def _best_researched(picks: list[Pick], target: float, band: float) -> TargetTicket:
    ranked = [(i, p) for i, p in enumerate(picks) if _is_priced_candidate(p)]
    ranked.sort(key=lambda ip: ip[1].confidence, reverse=True)
    ranked = ranked[:_MAX_CANDIDATES]
    n = len(ranked)
    if n == 0:
        return _empty(target)

    best_in_mask: int | None = None
    best_in_key: tuple[int, float] | None = None
    best_close_mask: int | None = None
    best_close_dist = float("inf")

    for mask in range(1, 1 << n):
        product = 1.0
        joint = 1.0
        n_legs = 0
        for b in range(n):
            if mask & (1 << b):
                p = ranked[b][1]
                product *= float(p.odds)
                joint *= p.estimated_probability
                n_legs += 1
        if _in_band(product, target, band):
            key = (n_legs, -joint)
            if best_in_key is None or key < best_in_key:
                best_in_key = key
                best_in_mask = mask
        dist = _log_distance(product, target)
        if dist < best_close_dist:
            best_close_dist = dist
            best_close_mask = mask

    use_mask = best_in_mask if best_in_mask is not None else best_close_mask
    assert use_mask is not None
    indices = [ranked[b][0] for b in range(n) if use_mask & (1 << b)]
    return _ticket_from_indices(picks, indices, target, band)


def _quote_allowed(q: MarketQuote, min_odds: float, max_odds: float) -> bool:
    if q.family not in _FILL_FAMILIES:
        return False
    if not (min_odds <= q.odds <= max_odds):
        return False
    return not _is_correct_score(market=q.market, tip=q.tip, family=q.family)


def _pick_from_quote(fixture: BoardFixture, quote: MarketQuote) -> Pick:
    fair = quote.fair_probability if quote.fair_probability else (1.0 / quote.odds)
    return Pick(
        league=fixture.league,
        match=f"{fixture.home} vs {fixture.away}",
        kickoff_et=fixture.kickoff_et,
        market=quote.market,
        tip=quote.tip,
        odds=quote.odds,
        price_source="pinnacle",
        market_family=quote.family,
        price_available=True,
        confidence=50,
        estimated_probability=fair,
        reasoning="unresearched board fill — priced quote copied from the board.",
        evidence=["Board price only — not researched."],
    )


def _greedy_fill(
    picks: list[Pick],
    researched: TargetTicket,
    target: float,
    band: float,
    board: PricedBoard,
    min_odds: float,
    max_odds: float,
) -> TargetTicket:
    extra: list[Pick] = []
    indices = list(researched.leg_indices)
    used = {normalize_match_key(p.match) for p in picks}
    product = researched.combined_odds if researched.combined_odds is not None else 1.0
    upper = target * (1.0 + band)

    while not _in_band(product, target, band):
        under: list[tuple[float, BoardFixture, MarketQuote, str]] = []
        for fixture in board.fixtures:
            key = normalize_match_key(f"{fixture.home} vs {fixture.away}")
            if key in used:
                continue
            for q in fixture.quotes:
                if not _quote_allowed(q, min_odds, max_odds):
                    continue
                new_prod = product * q.odds
                if new_prod > upper:
                    continue
                under.append((_log_distance(new_prod, target), fixture, q, key))
        if not under:
            break
        under.sort(key=lambda row: row[0])
        _, fixture, q, key = under[0]
        extra.append(_pick_from_quote(fixture, q))
        indices.append(len(picks) + len(extra) - 1)
        used.add(key)
        product *= q.odds

    if not extra:
        return researched
    return _ticket_from_indices(picks, indices, target, band, extra=extra, used_fill=True)


def solve_target_ticket(
    picks: list[Pick],
    target: float,
    *,
    band: float = 0.15,
    board: PricedBoard | None = None,
    fill: bool = False,
    min_odds: float = 1.10,
    max_odds: float = 5.0,
) -> TargetTicket:
    researched = _best_researched(picks, target, band)
    if not fill or researched.in_band:
        return researched
    if board is None:
        return researched
    return _greedy_fill(picks, researched, target, band, board, min_odds, max_odds)
