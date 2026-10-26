"""Target-odds solver — researched subset and optional board fill."""

from __future__ import annotations

import pytest
from predictor.odds.board import BoardFixture, PricedBoard
from predictor.odds.quotes import MarketQuote
from predictor.web.match_utils import normalize_match_key
from predictor.web.odds_solver import solve_target_ticket
from predictor.web.schema import Pick


def _sample_pick(**kwargs) -> Pick:
    defaults = dict(
        match="Alpha vs Beta",
        tip="Over 1.5 goals",
        odds=1.55,
        confidence=82,
        estimated_probability=0.72,
        reasoning="Both sides score regularly.",
        evidence=["Alpha scored in 8/10 home games", "Beta conceded in 7/10 away"],
    )
    defaults.update(kwargs)
    return Pick(**defaults)


def _quote(
    tip: str = "Over 2.5 goals",
    *,
    family: str = "goals_totals",
    market: str = "Over/Under 2.5 goals",
    odds: float = 2.20,
    fair_probability: float = 0.42,
) -> MarketQuote:
    return MarketQuote(
        family=family,
        market=market,
        tip=tip,
        line=2.5,
        side=None,
        period=0,
        odds=odds,
        raw_odds=odds + 0.02,
        fair_probability=fair_probability,
        source_key="k",
    )


def _fixture(
    home: str,
    away: str,
    quotes: list[MarketQuote],
    *,
    matchup_id: int = 1,
) -> BoardFixture:
    return BoardFixture(
        league="EPL",
        home=home,
        away=away,
        kickoff_utc="2026-08-29T14:00:00Z",
        kickoff_et="10:00 AM ET",
        matchup_id=matchup_id,
        quotes=quotes,
    )


class TestResearchedPass:
    def test_product_3_41_is_not_in_band_for_target_8(self):
        picks = [
            _sample_pick(match="A vs B", odds=1.25, estimated_probability=0.80),
            _sample_pick(match="C vs D", odds=1.30, estimated_probability=0.76),
            _sample_pick(match="E vs F", odds=2.10, estimated_probability=0.45),
        ]
        ticket = solve_target_ticket(picks, 8.0)
        assert ticket.in_band is False
        assert ticket.combined_odds == pytest.approx(1.25 * 1.30 * 2.10)
        assert ticket.used_fill is False
        assert ticket.extra_picks == []
        assert len(ticket.leg_indices) == 3

    def test_subset_7_392_hits_in_band_for_target_8(self):
        picks = [
            _sample_pick(match="A vs B", odds=1.40, estimated_probability=0.70),
            _sample_pick(match="C vs D", odds=1.50, estimated_probability=0.66),
            _sample_pick(match="E vs F", odds=1.60, estimated_probability=0.62),
            _sample_pick(match="G vs H", odds=2.20, estimated_probability=0.44),
        ]
        ticket = solve_target_ticket(picks, 8.0)
        assert 8.0 * 0.85 <= 1.5 * 1.6 * 2.2 * 1.4 <= 8.0 * 1.15
        assert ticket.in_band is True
        assert ticket.combined_odds == pytest.approx(1.40 * 1.50 * 1.60 * 2.20)
        assert set(ticket.leg_indices) == {0, 1, 2, 3}
        assert ticket.used_fill is False
        assert ticket.extra_picks == []

    def test_prefers_fewer_legs_when_both_in_band(self):
        picks = [
            _sample_pick(match="A vs B", odds=2.00, estimated_probability=0.50),
            _sample_pick(match="C vs D", odds=2.00, estimated_probability=0.50),
            _sample_pick(match="E vs F", odds=2.00, estimated_probability=0.50),
            _sample_pick(match="G vs H", odds=1.10, estimated_probability=0.90),
        ]
        ticket = solve_target_ticket(picks, 8.0)
        assert ticket.in_band is True
        assert len(ticket.leg_indices) == 3
        assert 3 not in ticket.leg_indices
        assert ticket.combined_odds == pytest.approx(8.0)

    def test_empty_candidates_returns_empty_ticket(self):
        picks = [
            _sample_pick(
                match="A vs B",
                tip="2-1",
                market="Correct score",
                odds=None,
                price_available=False,
                estimated_probability=0.18,
            ),
        ]
        ticket = solve_target_ticket(picks, 8.0)
        assert ticket.leg_indices == []
        assert ticket.in_band is False
        assert ticket.combined_odds is None
        assert ticket.extra_picks == []
        assert ticket.used_fill is False


class TestFillPass:
    def test_fill_adds_new_match_never_duplicates(self):
        picks = [
            _sample_pick(match="Alpha vs Beta", odds=1.25, estimated_probability=0.80),
            _sample_pick(match="Gamma vs Delta", odds=1.30, estimated_probability=0.76),
            _sample_pick(match="Epsilon vs Zeta", odds=2.10, estimated_probability=0.45),
        ]
        board = PricedBoard(
            fixtures=[
                _fixture(
                    "Alpha",
                    "Beta",
                    [_quote(odds=2.35, fair_probability=0.40)],
                    matchup_id=1,
                ),
                _fixture(
                    "New",
                    "Side",
                    [_quote(odds=2.20, fair_probability=0.42)],
                    matchup_id=2,
                ),
            ],
            fetched_at="now",
            errors=[],
        )
        ticket = solve_target_ticket(picks, 8.0, board=board, fill=True)
        assert ticket.used_fill is True
        assert ticket.in_band is True
        assert len(ticket.extra_picks) == 1
        extra = ticket.extra_picks[0]
        assert extra.match == "New vs Side"
        used = {normalize_match_key(picks[i].match) for i in ticket.leg_indices if i < len(picks)}
        used |= {normalize_match_key(p.match) for p in ticket.extra_picks}
        assert len(used) == len(ticket.leg_indices)
        researched_keys = {normalize_match_key(p.match) for p in picks}
        assert normalize_match_key(extra.match) not in researched_keys
        assert extra.reasoning.startswith("unresearched board fill")
        assert extra.confidence == 50
        assert extra.evidence == ["Board price only — not researched."]
        assert extra.price_source == "pinnacle"
        assert extra.odds == 2.20
        assert extra.price_available is True
        assert extra.estimated_probability == 0.42
        assert ticket.leg_indices[-1] == len(picks)

    def test_fill_ignores_correct_score_quotes(self):
        picks = [
            _sample_pick(match="A vs B", odds=1.25, estimated_probability=0.80),
            _sample_pick(match="C vs D", odds=1.30, estimated_probability=0.76),
            _sample_pick(match="E vs F", odds=2.10, estimated_probability=0.45),
        ]
        board = PricedBoard(
            fixtures=[
                _fixture(
                    "Score",
                    "Line",
                    [
                        _quote(
                            "2-1",
                            family="specials",
                            market="Correct score",
                            odds=2.20,
                            fair_probability=0.40,
                        )
                    ],
                    matchup_id=10,
                ),
                _fixture(
                    "Goals",
                    "Club",
                    [_quote(odds=2.50, fair_probability=0.38)],
                    matchup_id=11,
                ),
            ],
            fetched_at="now",
            errors=[],
        )
        ticket = solve_target_ticket(picks, 8.0, board=board, fill=True)
        assert ticket.used_fill is True
        assert ticket.extra_picks
        assert all("correct score" not in p.market.lower() for p in ticket.extra_picks)
        assert all(p.market.lower() != "correct score" for p in ticket.extra_picks)
        assert all(p.match != "Score vs Line" for p in ticket.extra_picks)
        assert ticket.extra_picks[0].match == "Goals vs Club"

    def test_fill_true_unused_when_researched_already_in_band(self):
        picks = [
            _sample_pick(match="A vs B", odds=1.40, estimated_probability=0.70),
            _sample_pick(match="C vs D", odds=1.50, estimated_probability=0.66),
            _sample_pick(match="E vs F", odds=1.60, estimated_probability=0.62),
            _sample_pick(match="G vs H", odds=2.20, estimated_probability=0.44),
        ]
        board = PricedBoard(
            fixtures=[
                _fixture(
                    "New",
                    "Side",
                    [_quote(odds=1.50, fair_probability=0.65)],
                    matchup_id=99,
                ),
            ],
            fetched_at="now",
            errors=[],
        )
        ticket = solve_target_ticket(picks, 8.0, board=board, fill=True)
        assert ticket.in_band is True
        assert ticket.used_fill is False
        assert ticket.extra_picks == []
