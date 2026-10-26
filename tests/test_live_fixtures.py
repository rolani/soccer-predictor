"""Tests for live fixture fetching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from predictor.live_fixtures import (
    _parse_espn_event,
    fetch_live_board,
    format_board_for_prompt,
)

SAMPLE_IN_PLAY = {
    "id": "123",
    "status": {
        "displayClock": "67'",
        "type": {"state": "in", "detail": "2nd Half"},
    },
    "leagues": [{"name": "MLS"}],
    "competitions": [
        {
            "competitors": [
                {"homeAway": "home", "score": "2", "team": {"displayName": "Home FC"}},
                {"homeAway": "away", "score": "1", "team": {"displayName": "Away FC"}},
            ]
        }
    ],
}


def test_parse_espn_in_play_event():
    fx = _parse_espn_event(SAMPLE_IN_PLAY)
    assert fx is not None
    assert fx.match == "Home FC vs Away FC"
    assert fx.score == "2-1"
    assert fx.minute == "67'"
    assert fx.league == "MLS"


def test_parse_espn_pre_match_skipped():
    pre = {**SAMPLE_IN_PLAY, "status": {"type": {"state": "pre"}}}
    assert _parse_espn_event(pre) is None


def test_format_board_for_prompt_lists_verify_urls():
    from predictor.live_fixtures import LiveFixture, LiveFixtureBoard

    board = LiveFixtureBoard(
        fetched_at="2026-08-23T12:00:00-04:00",
        in_play_count=1,
        fixtures=[
            LiveFixture(
                league="MLS",
                match="A vs B",
                minute="55'",
                score="1-0",
                status="2nd Half",
                home="A",
                away="B",
            )
        ],
    )
    text = format_board_for_prompt(board)
    assert "livescore.com" in text.lower()
    assert "flashscore.com" in text.lower()
    assert "sofascore.com" in text.lower()
    assert "A vs B" in text


@patch("predictor.live_fixtures.requests.get")
def test_fetch_live_board(mock_get):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"events": [SAMPLE_IN_PLAY]}
    mock_get.return_value = mock_resp

    board = fetch_live_board()
    assert board.in_play_count == 1
    assert board.fixtures[0].match == "Home FC vs Away FC"
