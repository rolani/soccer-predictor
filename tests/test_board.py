"""Tests for priced board assembly and prompt formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from predictor.odds.board import (
    BoardFixture,
    PricedBoard,
    build_board,
    format_board_for_prompt,
    window_for_scope,
)
from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote


def quote(tip, family="goals_totals", odds=1.25):
    return MarketQuote(
        family=family,
        market="m",
        tip=tip,
        line=1.5,
        side=None,
        period=0,
        odds=odds,
        raw_odds=odds + 0.02,
        fair_probability=0.78,
        source_key="k",
    )


def fixture(**kw) -> BoardFixture:
    defaults = dict(
        league="UEFA - Champions League Qualifiers",
        home="Lyon",
        away="Fenerbahce",
        kickoff_utc="2026-08-26T19:00:00Z",
        kickoff_et="3:00 PM ET",
        matchup_id=4,
        quotes=[quote("Over 1.5 goals"), quote("BTTS Yes", "btts", 1.70)],
    )
    defaults.update(kw)
    return BoardFixture(**defaults)


class TestWindowForScope:
    def test_today_starts_now(self):
        start, end = window_for_scope("today")
        assert start <= datetime.now(timezone.utc) + timedelta(minutes=1)
        assert end > start

    def test_window_respects_hours(self):
        start, end = window_for_scope("window", hours_window=6)
        assert timedelta(hours=5, minutes=30) < end - start < timedelta(hours=6, minutes=30)

    def test_date_scope_covers_the_named_day(self):
        start, end = window_for_scope("date", target_date="2026-09-01")
        assert (end - start) > timedelta(hours=20)

    def test_tomorrow_starts_in_the_future(self):
        start, _ = window_for_scope("tomorrow")
        assert start > datetime.now(timezone.utc)


class TestBuildBoard:
    def test_filters_by_odds_range(self, monkeypatch):
        monkeypatch.setattr(
            "predictor.odds.board.list_matchups",
            lambda: [
                PinnacleMatchup(
                    id=4,
                    parent_id=None,
                    league="L",
                    home="Lyon",
                    away="Fenerbahce",
                    start_time_utc=_soon(),
                    kind="main",
                )
            ],
        )
        monkeypatch.setattr("predictor.odds.board.related", lambda mid: [])
        monkeypatch.setattr("predictor.odds.board.straight_markets", lambda mid: [])
        monkeypatch.setattr(
            "predictor.odds.board.build_quotes",
            lambda main, rel, mk: [
                quote("Over 1.5 goals", odds=1.25),
                quote("Under 1.5 goals", odds=4.00),
            ],
        )
        board = build_board(
            start_utc=datetime.now(timezone.utc) - timedelta(hours=1),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=12),
            min_odds=1.10,
            max_odds=2.00,
        )
        tips = [q.tip for f in board.fixtures for q in f.quotes]
        assert "Over 1.5 goals" in tips
        assert "Under 1.5 goals" not in tips

    def test_pinnacle_failure_yields_an_empty_board_not_an_exception(self, monkeypatch):
        from predictor.odds.pinnacle import OddsUnavailable

        def boom():
            raise OddsUnavailable("down")

        monkeypatch.setattr("predictor.odds.board.list_matchups", boom)
        monkeypatch.setattr(
            "predictor.odds.oddsfilter.build_oddsfilter_board",
            lambda **kw: PricedBoard(fixtures=[], fetched_at="now", errors=["oddsfilter down"]),
        )
        monkeypatch.setattr(
            "predictor.odds.flashscore.build_flashscore_board",
            lambda **kw: PricedBoard(fixtures=[], fetched_at="now", errors=["flashscore down"]),
        )
        board = build_board(
            start_utc=datetime.now(timezone.utc),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=6),
            min_odds=1.1,
            max_odds=3.0,
        )
        assert board.fixtures == []
        assert board.errors

    def test_pinnacle_403_falls_back_to_oddsfilter(self, monkeypatch):
        from predictor.odds.pinnacle import OddsUnavailable

        def boom():
            raise OddsUnavailable("Pinnacle returned 403")

        monkeypatch.setattr("predictor.odds.board.list_matchups", boom)
        monkeypatch.setattr(
            "predictor.odds.oddsfilter.build_oddsfilter_board",
            lambda **kw: PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[]),
        )
        board = build_board(
            start_utc=datetime.now(timezone.utc),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=6),
            min_odds=1.1,
            max_odds=3.0,
        )
        assert board.fixtures
        assert board.fixtures[0].home == "Lyon"

    def test_empty_oddsfilter_falls_back_to_flashscore(self, monkeypatch):
        from predictor.odds.pinnacle import OddsUnavailable

        def boom():
            raise OddsUnavailable("Pinnacle returned 403")

        monkeypatch.setattr("predictor.odds.board.list_matchups", boom)
        monkeypatch.setattr(
            "predictor.odds.oddsfilter.build_oddsfilter_board",
            lambda **kw: PricedBoard(fixtures=[], fetched_at="now", errors=["empty"]),
        )
        monkeypatch.setattr(
            "predictor.odds.flashscore.build_flashscore_board",
            lambda **kw: PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[]),
        )
        board = build_board(
            start_utc=datetime.now(timezone.utc),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=6),
            min_odds=1.1,
            max_odds=3.0,
        )
        assert board.fixtures
        assert board.fixtures[0].home == "Lyon"


class TestFind:
    def test_find_resolves_a_fixture(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        assert board.find("Lyon vs Fenerbahce") is not None

    def test_find_returns_none_for_an_unknown_fixture(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        assert board.find("Barcelona vs Real Madrid") is None


class TestPromptFormat:
    def test_includes_fixture_and_price(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        text = format_board_for_prompt(board)
        assert "Lyon vs Fenerbahce" in text
        assert "1.25" in text
        assert "Over 1.5 goals" in text

    def test_groups_by_family(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        text = format_board_for_prompt(board)
        assert "goals_totals" in text or "Goals" in text

    def test_empty_board_says_so(self):
        text = format_board_for_prompt(PricedBoard(fixtures=[], fetched_at="now", errors=["down"]))
        assert "no priced" in text.lower()


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
