"""Tests for the Pinnacle feed client. No network access."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from predictor.odds.pinnacle import PinnacleMatchup, parse_matchups

FIXTURES = Path(__file__).parent / "fixtures" / "pinnacle"


@pytest.fixture
def matchups_payload() -> list[dict]:
    return json.loads((FIXTURES / "matchups.json").read_text(encoding="utf-8"))


class TestParseMatchups:
    def test_returns_matchups(self, matchups_payload):
        out = parse_matchups(matchups_payload)
        assert out
        assert all(isinstance(m, PinnacleMatchup) for m in out)

    def test_extracts_both_participants(self, matchups_payload):
        out = [m for m in parse_matchups(matchups_payload) if m.kind == "main"]
        assert out
        assert all(m.home and m.away for m in out)

    def test_classifies_corner_matchups(self, matchups_payload):
        kinds = {m.kind for m in parse_matchups(matchups_payload)}
        assert "main" in kinds
        assert "corners" in kinds

    def test_corner_league_suffix_detected(self):
        payload = [
            {
                "id": 1,
                "parentId": 2,
                "type": "matchup",
                "league": {"name": "UEFA - Champions League Qualifiers Corners"},
                "startTime": "2026-08-26T19:00:00Z",
                "participants": [
                    {"alignment": "home", "name": "Viking (Corners)"},
                    {"alignment": "away", "name": "Dinamo Zagreb (Corners)"},
                ],
            }
        ]
        assert parse_matchups(payload)[0].kind == "corners"

    def test_bookings_league_suffix_detected(self):
        payload = [
            {
                "id": 1,
                "parentId": 2,
                "type": "matchup",
                "league": {"name": "England - EFL Cup Bookings"},
                "startTime": "2026-08-26T18:45:00Z",
                "participants": [
                    {"alignment": "home", "name": "Newcastle United (Bookings)"},
                    {"alignment": "away", "name": "West Bromwich Albion (Bookings)"},
                ],
            }
        ]
        assert parse_matchups(payload)[0].kind == "bookings"

    def test_special_carries_its_description(self):
        payload = [
            {
                "id": 3,
                "parentId": 2,
                "type": "special",
                "league": {"name": "UEFA - Champions League Qualifiers"},
                "startTime": "2026-08-26T19:00:00Z",
                "special": {"description": "Both Teams To Score?"},
                "participants": [
                    {"id": 31, "name": "Yes"},
                    {"id": 32, "name": "No"},
                ],
            }
        ]
        out = parse_matchups(payload)[0]
        assert out.kind == "special"
        assert out.special_description == "Both Teams To Score?"
        assert out.participant_names == {31: "Yes", 32: "No"}

    def test_skips_malformed_entries_without_raising(self):
        payload = [{"id": 9}, {"nonsense": True}]
        assert parse_matchups(payload) == []

    def test_skips_non_dict_entries_without_raising(self):
        assert parse_matchups([123, None, "x", {"id": 9}]) == []
