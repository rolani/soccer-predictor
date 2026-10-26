"""Tests for fixture and market resolution."""

from __future__ import annotations

import pytest
from predictor.odds.matching import (
    match_fixture,
    normalize_team,
    resolve_quote,
    split_match,
)
from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote


def mu(id_: int, league: str, home: str, away: str, start="2026-08-26T19:00:00Z"):
    return PinnacleMatchup(
        id=id_,
        parent_id=None,
        league=league,
        home=home,
        away=away,
        start_time_utc=start,
        kind="main",
    )


CANDIDATES = [
    mu(1, "UEFA - Champions League Qualifiers", "Viking", "Dinamo Zagreb"),
    mu(2, "Croatia - HNL", "Istra 1961", "Dinamo Zagreb", "2026-08-29T16:30:00Z"),
    mu(3, "England - EFL Cup", "Newcastle United", "West Bromwich Albion"),
    mu(4, "UEFA - Champions League Qualifiers", "Lyon", "Fenerbahce"),
    mu(5, "England - EFL Cup", "Preston North End", "Everton", "2026-08-26T18:45:00Z"),
]


class TestNormalize:
    def test_strips_accents(self):
        assert normalize_team("Fenerbahçe") == normalize_team("Fenerbahce")

    def test_drops_club_noise(self):
        assert normalize_team("Viking FK") == normalize_team("Viking")

    def test_keeps_distinguishing_words(self):
        assert normalize_team("Newcastle United") != normalize_team("Newcastle Jets")


class TestSplit:
    @pytest.mark.parametrize("raw", ["A vs B", "A v B", "A - B", "A  vs.  B"])
    def test_separators(self, raw):
        assert split_match(raw) == ("A", "B")

    def test_returns_none_without_a_separator(self):
        assert split_match("Just one name") is None


class TestMatchFixture:
    def test_exact_match(self):
        assert match_fixture("Lyon vs Fenerbahce", CANDIDATES).id == 4

    def test_tolerates_club_suffixes_and_accents(self):
        assert match_fixture("Viking FK vs GNK Dinamo Zagreb", CANDIDATES).id == 1

    def test_does_not_confuse_two_fixtures_sharing_a_team(self):
        """Both fixture 1 and 2 contain Dinamo Zagreb; only one has Viking."""
        assert match_fixture("Viking FK vs Dinamo Zagreb", CANDIDATES).id == 1

    def test_abbreviated_names(self):
        assert match_fixture("Newcastle vs West Bromwich Albion", CANDIDATES).id == 3

    def test_unknown_fixture_returns_none(self):
        assert match_fixture("Barcelona vs Real Madrid", CANDIDATES) is None

    def test_prefers_none_over_a_weak_guess(self):
        assert match_fixture("Everton vs Liverpool", CANDIDATES) is None

    def test_unparseable_string_returns_none(self):
        assert match_fixture("nonsense", CANDIDATES) is None


def q(tip: str, family="goals_totals", odds=1.25, line=1.5):
    return MarketQuote(
        family=family,
        market="Over/Under 1.5 goals",
        tip=tip,
        line=line,
        side=None,
        period=0,
        odds=odds,
        raw_odds=odds + 0.02,
        fair_probability=0.78,
        source_key="k",
    )


QUOTES = [
    q("Over 1.5 goals"),
    q("Under 1.5 goals", odds=4.0),
    q("Everton over 0.5 goals", family="team_totals", odds=1.30, line=0.5),
    q("BTTS Yes", family="btts", odds=1.70, line=None),
]


class TestResolveQuote:
    def test_exact_tip(self):
        assert resolve_quote("Over 1.5 goals", "", QUOTES).odds == 1.25

    def test_case_and_whitespace_insensitive(self):
        assert resolve_quote("  over 1.5 GOALS ", "", QUOTES) is not None

    def test_team_total_phrasing_variant(self):
        assert resolve_quote("Everton Over 0.5", "Team over 0.5", QUOTES) is not None

    def test_btts_variant(self):
        assert resolve_quote("Both teams to score - Yes", "BTTS", QUOTES) is not None

    def test_unknown_tip_returns_none(self):
        assert resolve_quote("Correct score 3-2", "", QUOTES) is None

    def test_does_not_return_the_opposite_side(self):
        """Over must never resolve to the Under price."""
        assert resolve_quote("Over 1.5 goals", "", QUOTES).tip == "Over 1.5 goals"
