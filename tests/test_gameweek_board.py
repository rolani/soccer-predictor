"""Gameweek calendar HTTP and board. Tests never network."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from predictor.gameweek import (
    GameweekBoard,
    GameweekFixture,
    build_gameweek_board,
    format_gameweek_for_prompt,
)
from predictor.gameweek.calendars import fetch_espn, fetch_football_data, fetch_fotmob
from predictor.gameweek.types import RawFixture

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gameweek"


def _unfinished(source: str) -> list[RawFixture]:
    return [
        RawFixture(
            source=source,
            league="EPL",
            home="Arsenal",
            away="Chelsea",
            kickoff_utc="2026-08-29T14:00:00Z",
            round_label="EPL GW3",
            finished=False,
        )
    ]


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ok_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


class TestBuildGameweekBoard:
    def test_two_sources_same_unfinished_match_is_confirmed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "predictor.gameweek.calendars.fetch_football_data",
            lambda code: _unfinished("football-data") if code == "PL" else [],
        )
        monkeypatch.setattr(
            "predictor.gameweek.calendars.fetch_fotmob",
            lambda league_id, display: _unfinished("fotmob") if league_id == 47 else [],
        )
        monkeypatch.setattr(
            "predictor.gameweek.calendars.fetch_espn",
            lambda slug, display: [],
        )

        board = build_gameweek_board()
        assert any(f.match == "Arsenal vs Chelsea" for f in board.fixtures)
        assert all(f.unconfirmed_slate is False for f in board.fixtures)
        assert board.to_dict()["unconfirmed_slate"] is False

    def test_all_fetchers_fail_empty_board_never_raises(self, monkeypatch: pytest.MonkeyPatch):
        def boom(*_a, **_k):
            raise TimeoutError("timeout")

        monkeypatch.setattr("predictor.gameweek.calendars.fetch_football_data", boom)
        monkeypatch.setattr("predictor.gameweek.calendars.fetch_fotmob", boom)
        monkeypatch.setattr("predictor.gameweek.calendars.fetch_espn", boom)

        board = build_gameweek_board()
        assert board.fixtures == []
        assert board.source_errors
        assert any("timeout" in err.lower() for err in board.source_errors)

    def test_build_gameweek_board_never_raises_if_load_all_explodes(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "predictor.gameweek.board.load_all",
            lambda: (_ for _ in ()).throw(RuntimeError("load exploded")),
        )
        board = build_gameweek_board()
        assert isinstance(board, GameweekBoard)
        assert board.fixtures == []
        assert board.source_errors


class TestFormatGameweekForPrompt:
    def test_names_remaining_matches(self):
        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[
                GameweekFixture(
                    league="EPL",
                    round_label="EPL GW3",
                    match="Arsenal vs Chelsea",
                    home="Arsenal",
                    away="Chelsea",
                    kickoff_et="10:00 AM ET",
                    kickoff_utc="2026-08-29T14:00:00Z",
                    sources=["football-data", "fotmob"],
                    unconfirmed_slate=False,
                )
            ],
        )
        text = format_gameweek_for_prompt(board)
        assert "Arsenal vs Chelsea" in text
        assert "EPL GW3" in text
        assert "10:00 AM ET" in text
        assert "football-data" in text
        assert "UNCONFIRMED SLATE" not in text

    def test_unconfirmed_slate_banner(self):
        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[
                GameweekFixture(
                    league="EPL",
                    round_label="EPL GW3",
                    match="Arsenal vs Chelsea",
                    home="Arsenal",
                    away="Chelsea",
                    kickoff_et="10:00 AM ET",
                    kickoff_utc="2026-08-29T14:00:00Z",
                    sources=["fotmob"],
                    unconfirmed_slate=True,
                )
            ],
        )
        text = format_gameweek_for_prompt(board)
        assert text.startswith("UNCONFIRMED SLATE — only one calendar responded.")
        assert "Arsenal vs Chelsea" in text


class TestFootballDataKey:
    def test_missing_api_key_is_down_without_network(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)

        def fake_get(*_a, **_k):
            raise AssertionError("requests.get must not be called")

        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", fake_get)

        with pytest.raises(Exception, match="FOOTBALL_DATA_API_KEY"):
            fetch_football_data("PL")

        monkeypatch.setattr(
            "predictor.gameweek.calendars.fetch_fotmob",
            lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("timeout")),
        )
        monkeypatch.setattr(
            "predictor.gameweek.calendars.fetch_espn",
            lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("timeout")),
        )
        board = build_gameweek_board()
        assert board.fixtures == []
        assert any("football-data" in err.lower() for err in board.source_errors)


class TestCalendarParsers:
    def test_fetch_football_data_parses_synthetic(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
        competition = _load_json("football_data_competition.json")
        matches = _load_json("football_data_matches.json")
        mock_get = MagicMock(side_effect=[_ok_response(competition), _ok_response(matches)])
        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", mock_get)
        rows = fetch_football_data("PL")
        assert len(rows) == 2
        live = [r for r in rows if not r.finished]
        done = [r for r in rows if r.finished]
        assert live[0].home == "Arsenal"
        assert live[0].away == "Chelsea"
        assert live[0].source == "football-data"
        assert live[0].round_label == "EPL GW3"
        assert live[0].kickoff_utc == "2026-08-29T14:00:00Z"
        assert done[0].finished is True
        token_header = mock_get.call_args_list[0].kwargs["headers"]["X-Auth-Token"]
        assert token_header == "test-token"
        assert mock_get.call_args_list[0].kwargs["timeout"] == 25
        assert (
            mock_get.call_args_list[0]
            .kwargs["headers"]["User-Agent"]
            .startswith("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        )

    def test_fetch_football_data_401_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "bad")
        resp = MagicMock()
        resp.status_code = 401
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error")
        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", lambda *a, **k: resp)
        with pytest.raises(Exception):
            fetch_football_data("PL")

    def test_fetch_fotmob_parses_synthetic(self, monkeypatch: pytest.MonkeyPatch):
        payload = _load_json("fotmob.json")
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(payload),
        )
        rows = fetch_fotmob(47, "EPL")
        assert any(r.home == "Arsenal" and r.away == "Chelsea" and not r.finished for r in rows)
        assert any(r.finished for r in rows)
        assert all(r.source == "fotmob" for r in rows)
        assert all(r.round_label == "EPL GW3" for r in rows)

    def test_fetch_fotmob_uses_data_leagues_url(self, monkeypatch: pytest.MonkeyPatch):
        seen: list[str] = []

        def fake_get(url, **_kw):
            seen.append(url)
            return _ok_response(_load_json("fotmob.json"))

        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", fake_get)
        fetch_fotmob(47, "EPL")
        assert seen
        assert "/api/data/leagues?id=47" in seen[0]

    def test_fetch_fotmob_flat_all_matches_keeps_active_round(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(_load_json("fotmob_flat.json")),
        )
        rows = fetch_fotmob(47, "EPL")
        pairs = {(r.home, r.away) for r in rows}
        assert ("Arsenal", "Chelsea") in pairs
        assert ("Liverpool", "Everton") in pairs
        assert ("Brighton", "Bournemouth") not in pairs
        assert ("Tottenham Hotspur", "West Ham United") not in pairs
        assert all(r.round_label == "EPL GW2" for r in rows)

    def test_fetch_fotmob_unexpected_shape_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response({"oops": True}),
        )
        with pytest.raises(Exception):
            fetch_fotmob(47, "EPL")

    def test_fetch_espn_keeps_modal_week(self, monkeypatch: pytest.MonkeyPatch):
        payload = _load_json("espn_scoreboard.json")
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(payload),
        )
        rows = fetch_espn("eng.1", "EPL")
        matches = {(r.home, r.away) for r in rows}
        assert ("Arsenal", "Chelsea") in matches
        assert ("Liverpool", "Everton") in matches
        assert ("Tottenham Hotspur", "West Ham United") not in matches
        post = [r for r in rows if r.home == "Liverpool"]
        assert post and post[0].finished is True
        live = [r for r in rows if r.home == "Arsenal"]
        assert live[0].kickoff_utc == "2026-08-29T14:00:00Z"
        assert live[0].round_label == "EPL GW3"
        assert live[0].source == "espn"

    def test_fetch_football_data_postponed_cancelled_suspended_empty_kickoff(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
        competition = {
            "currentSeason": {"currentMatchday": 3},
            "currentMatchday": 3,
        }
        matches = {
            "matches": [
                {
                    "utcDate": "2026-08-29T14:00:00Z",
                    "status": "POSTPONED",
                    "homeTeam": {"name": "Arsenal"},
                    "awayTeam": {"name": "Chelsea"},
                },
                {
                    "utcDate": "2026-08-29T16:00:00Z",
                    "status": "CANCELLED",
                    "homeTeam": {"name": "Liverpool"},
                    "awayTeam": {"name": "Everton"},
                },
                {
                    "utcDate": "2026-08-30T14:00:00Z",
                    "status": "SUSPENDED",
                    "homeTeam": {"name": "Tottenham Hotspur"},
                    "awayTeam": {"name": "West Ham United"},
                },
                {
                    "utcDate": "2026-08-30T16:00:00Z",
                    "status": "TIMED",
                    "homeTeam": {"name": "Aston Villa"},
                    "awayTeam": {"name": "Newcastle United"},
                },
            ]
        }
        mock_get = MagicMock(side_effect=[_ok_response(competition), _ok_response(matches)])
        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", mock_get)
        rows = fetch_football_data("PL")
        by_home = {r.home: r for r in rows}
        assert by_home["Arsenal"].kickoff_utc == ""
        assert by_home["Arsenal"].finished is False
        assert by_home["Liverpool"].kickoff_utc == ""
        assert by_home["Tottenham Hotspur"].kickoff_utc == ""
        assert by_home["Aston Villa"].kickoff_utc == "2026-08-30T16:00:00Z"

    def test_fetch_espn_postponed_empties_kickoff_not_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        payload = {
            "events": [
                {
                    "id": "9001",
                    "date": "2026-08-29T14:00:00Z",
                    "week": {"number": 3},
                    "status": {
                        "type": {
                            "name": "STATUS_POSTPONED",
                            "state": "post",
                            "description": "Postponed",
                        }
                    },
                    "competitions": [
                        {
                            "competitors": [
                                {"homeAway": "home", "team": {"displayName": "Arsenal"}},
                                {"homeAway": "away", "team": {"displayName": "Chelsea"}},
                            ]
                        }
                    ],
                }
            ]
        }
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(payload),
        )
        rows = fetch_espn("eng.1", "EPL")
        assert len(rows) == 1
        assert rows[0].kickoff_utc == ""
        assert rows[0].finished is False

    def test_fetch_espn_canceled_empties_kickoff(self, monkeypatch: pytest.MonkeyPatch):
        payload = {
            "events": [
                {
                    "id": "9002",
                    "date": "2026-08-29T14:00:00Z",
                    "week": {"number": 3},
                    "status": {
                        "type": {
                            "name": "STATUS_CANCELED",
                            "state": "post",
                            "description": "Canceled",
                        }
                    },
                    "competitions": [
                        {
                            "competitors": [
                                {"homeAway": "home", "team": {"displayName": "Arsenal"}},
                                {"homeAway": "away", "team": {"displayName": "Chelsea"}},
                            ]
                        }
                    ],
                }
            ]
        }
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(payload),
        )
        rows = fetch_espn("eng.1", "EPL")
        assert rows[0].kickoff_utc == ""
        assert rows[0].finished is False

    def test_fetch_fotmob_cancelled_postponed_empty_kickoff(self, monkeypatch: pytest.MonkeyPatch):
        payload = {
            "fixtures": {
                "allMatches": [
                    {
                        "round": 3,
                        "matches": [
                            {
                                "home": {"name": "Arsenal"},
                                "away": {"name": "Chelsea"},
                                "status": {
                                    "utcTime": "2026-08-29T14:00:00Z",
                                    "finished": False,
                                    "cancelled": True,
                                },
                            },
                            {
                                "home": {"name": "Liverpool"},
                                "away": {"name": "Everton"},
                                "status": {
                                    "utcTime": "2026-08-29T16:00:00Z",
                                    "finished": False,
                                    "postponed": True,
                                },
                            },
                        ],
                    }
                ]
            }
        }
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(payload),
        )
        rows = fetch_fotmob(47, "EPL")
        by_home = {r.home: r for r in rows}
        assert by_home["Arsenal"].kickoff_utc == ""
        assert by_home["Arsenal"].finished is False
        assert by_home["Liverpool"].kickoff_utc == ""
        assert by_home["Liverpool"].finished is False

    def test_two_sources_postponed_dated_utc_skipped_unconfirmed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.gameweek.merge import merge_raw_fixtures

        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
        competition = {"currentSeason": {"currentMatchday": 3}, "currentMatchday": 3}
        fd_matches = {
            "matches": [
                {
                    "utcDate": "2026-08-29T14:00:00Z",
                    "status": "POSTPONED",
                    "homeTeam": {"name": "Arsenal"},
                    "awayTeam": {"name": "Chelsea"},
                }
            ]
        }
        fotmob = {
            "fixtures": {
                "allMatches": [
                    {
                        "round": 3,
                        "matches": [
                            {
                                "home": {"name": "Arsenal"},
                                "away": {"name": "Chelsea"},
                                "status": {
                                    "utcTime": "2026-08-29T14:00:00Z",
                                    "finished": False,
                                    "postponed": True,
                                },
                            }
                        ],
                    }
                ]
            }
        }
        mock_get = MagicMock(side_effect=[_ok_response(competition), _ok_response(fd_matches)])
        monkeypatch.setattr("predictor.gameweek.calendars.requests.get", mock_get)
        fd_rows = fetch_football_data("PL")
        monkeypatch.setattr(
            "predictor.gameweek.calendars.requests.get",
            lambda *a, **k: _ok_response(fotmob),
        )
        fm_rows = fetch_fotmob(47, "EPL")
        board = merge_raw_fixtures(fd_rows + fm_rows, sources_up=2)
        assert board.fixtures == []
        assert any("unconfirmed" in s["why"].lower() for s in board.skipped)
