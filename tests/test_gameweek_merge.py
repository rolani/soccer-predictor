"""Two-of-three gameweek slate merge."""

from __future__ import annotations

from predictor.gameweek.merge import merge_raw_fixtures
from predictor.gameweek.types import RawFixture


def rf(
    source,
    home,
    away,
    kickoff="2026-08-29T14:00:00Z",
    finished=False,
    league="EPL",
    round_label="EPL GW3",
):
    return RawFixture(
        source=source,
        league=league,
        home=home,
        away=away,
        kickoff_utc=kickoff,
        round_label=round_label,
        finished=finished,
    )


class TestTwoOfThree:
    def test_fotmob_and_fd_without_espn_is_included(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea"),
                rf("fotmob", "Arsenal", "Chelsea"),
            ],
            sources_up=3,
        )
        assert any(f.match == "Arsenal vs Chelsea" for f in board.fixtures)
        assert board.fixtures[0].unconfirmed_slate is False

    def test_espn_only_is_excluded_when_three_sources_up(self):
        board = merge_raw_fixtures(
            [rf("espn", "Arsenal", "Chelsea")],
            sources_up=3,
        )
        assert board.fixtures == []

    def test_finished_is_excluded(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", finished=True),
                rf("fotmob", "Arsenal", "Chelsea", finished=True),
            ],
            sources_up=2,
        )
        assert board.fixtures == []

    def test_kickoff_mismatch_is_skipped(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", "2026-08-29T14:00:00Z"),
                rf("fotmob", "Arsenal", "Chelsea", "2026-08-29T17:00:00Z"),
            ],
            sources_up=2,
        )
        assert board.fixtures == []
        assert any("mismatch" in s["why"].lower() for s in board.skipped)

    def test_two_sources_one_parseable_one_tbd_is_unconfirmed_not_locked(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", "2026-08-29T14:00:00Z"),
                rf("fotmob", "Arsenal", "Chelsea", "TBD"),
            ],
            sources_up=2,
        )
        assert board.fixtures == []
        assert any("unconfirmed" in s["why"].lower() for s in board.skipped)
        assert not any("mismatch" in s["why"].lower() for s in board.skipped)

    def test_two_sources_both_empty_kickoff_is_unconfirmed(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", ""),
                rf("fotmob", "Arsenal", "Chelsea", ""),
            ],
            sources_up=2,
        )
        assert board.fixtures == []
        assert any("unconfirmed" in s["why"].lower() for s in board.skipped)
        assert not any("mismatch" in s["why"].lower() for s in board.skipped)

    def test_single_source_up_marks_unconfirmed(self):
        board = merge_raw_fixtures(
            [rf("espn", "Arsenal", "Chelsea")],
            sources_up=1,
        )
        assert len(board.fixtures) == 1
        assert board.fixtures[0].unconfirmed_slate is True

    def test_single_source_empty_kickoff_is_skipped_unconfirmed(self):
        board = merge_raw_fixtures(
            [rf("espn", "Arsenal", "Chelsea", "")],
            sources_up=1,
        )
        assert board.fixtures == []
        assert any("unconfirmed" in s["why"].lower() for s in board.skipped)

    def test_zero_sources_empty(self):
        board = merge_raw_fixtures([], sources_up=0)
        assert board.fixtures == []
        assert board.source_errors == []
        assert board.sources_up == 0
        assert board.to_dict()["sources_up"] == 0

    def test_merge_records_sources_up(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea"),
                rf("fotmob", "Arsenal", "Chelsea"),
            ],
            sources_up=2,
        )
        assert board.sources_up == 2
        assert board.to_dict()["sources_up"] == 2
