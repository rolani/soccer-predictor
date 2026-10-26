"""Tests for Pinnacle market normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from predictor.odds.pinnacle import parse_matchups
from predictor.odds.quotes import FAMILIES, MarketQuote, build_quotes

FIXTURES = Path(__file__).parent / "fixtures" / "pinnacle"
MAIN_ID = 1634269216


@pytest.fixture
def quotes() -> list[MarketQuote]:
    related_payload = json.loads((FIXTURES / f"related_{MAIN_ID}.json").read_text(encoding="utf-8"))
    markets = json.loads((FIXTURES / f"straight_{MAIN_ID}.json").read_text(encoding="utf-8"))
    related = parse_matchups(related_payload)
    main = next(m for m in related if m.id == MAIN_ID and m.kind == "main")
    return build_quotes(main, related, markets)


def find(quotes: list[MarketQuote], tip: str) -> MarketQuote | None:
    return next((q for q in quotes if q.tip.lower() == tip.lower()), None)


class TestCoverage:
    def test_produces_quotes(self, quotes):
        assert len(quotes) > 20

    def test_every_family_is_known(self, quotes):
        assert {q.family for q in quotes} <= set(FAMILIES)

    def test_covers_the_core_families(self, quotes):
        families = {q.family for q in quotes}
        for expected in ("goals_totals", "team_totals", "result", "handicap", "btts", "dc_dnb"):
            assert expected in families, f"missing {expected}"


class TestTipVocabulary:
    def test_over_1_5(self, quotes):
        q = find(quotes, "Over 1.5 goals")
        assert q is not None
        assert q.family == "goals_totals"
        assert q.line == 1.5
        assert q.period == 0

    def test_under_3_5(self, quotes):
        assert find(quotes, "Under 3.5 goals") is not None

    def test_team_over_uses_the_team_name(self, quotes):
        tips = [q.tip for q in quotes if q.family == "team_totals"]
        assert any(t.startswith("Lyon over") for t in tips)
        assert any(t.startswith("Fenerbahce over") for t in tips)

    def test_btts_yes_and_no(self, quotes):
        assert find(quotes, "BTTS Yes") is not None
        assert find(quotes, "BTTS No") is not None

    def test_draw_no_bet_names_the_side(self, quotes):
        assert find(quotes, "Lyon draw no bet") is not None

    def test_double_chance(self, quotes):
        tips = {q.tip for q in quotes if q.family == "dc_dnb"}
        assert any("or draw" in t.lower() for t in tips)

    def test_first_half_prefixed(self, quotes):
        assert any(q.tip.startswith("1H ") for q in quotes if q.period == 1)


class TestPricing:
    def test_btts_yes_matches_the_recorded_american_price(self, quotes):
        """BTTS Yes was -151 => 1.662 decimal raw (recorded fixture)."""
        q = find(quotes, "BTTS Yes")
        assert q.raw_odds == pytest.approx(1.662, abs=0.002)

    def test_book_price_is_shorter_than_the_sharp_price(self, quotes):
        q = find(quotes, "Over 1.5 goals")
        assert q.odds < q.raw_odds

    def test_fair_probability_is_between_zero_and_one(self, quotes):
        assert all(0.0 < q.fair_probability < 1.0 for q in quotes)

    def test_odds_are_decimal_above_one(self, quotes):
        assert all(q.odds > 1.0 for q in quotes)


class TestRobustness:
    def test_market_with_a_single_price_is_skipped(self):
        """A one-sided market cannot be de-vigged, so it must not produce a quote."""
        main = parse_matchups(
            [
                {
                    "id": 1,
                    "parentId": None,
                    "type": "matchup",
                    "league": {"name": "Test League"},
                    "startTime": "2026-08-26T19:00:00Z",
                    "participants": [
                        {"id": 10, "alignment": "home", "name": "Home"},
                        {"id": 11, "alignment": "away", "name": "Away"},
                    ],
                }
            ]
        )[0]
        markets = [
            {
                "matchupId": 1,
                "type": "total",
                "key": "s;0;ou;2.5",
                "period": 0,
                "prices": [{"designation": "over", "points": 2.5, "price": -110}],
            }
        ]
        assert build_quotes(main, [main], markets) == []

    def test_unknown_market_type_is_ignored(self):
        main = parse_matchups(
            [
                {
                    "id": 1,
                    "parentId": None,
                    "type": "matchup",
                    "league": {"name": "Test League"},
                    "startTime": "2026-08-26T19:00:00Z",
                    "participants": [
                        {"id": 10, "alignment": "home", "name": "Home"},
                        {"id": 11, "alignment": "away", "name": "Away"},
                    ],
                }
            ]
        )[0]
        markets = [{"matchupId": 1, "type": "mystery", "key": "s;0;x", "period": 0, "prices": []}]
        assert build_quotes(main, [main], markets) == []
