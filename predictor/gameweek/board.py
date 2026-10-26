"""Build and format the gameweek slate. Never raises."""

from __future__ import annotations

from datetime import datetime, timezone

from predictor.gameweek.calendars import load_all
from predictor.gameweek.merge import merge_raw_fixtures
from predictor.gameweek.types import GameweekBoard, GameweekFixture


def build_gameweek_board() -> GameweekBoard:
    try:
        raw, errors, sources_up = load_all()
        board = merge_raw_fixtures(raw, sources_up=sources_up)
        board.source_errors = errors
        return board
    except Exception as exc:
        return GameweekBoard(
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            leagues=[],
            source_errors=[str(exc)],
        )


def format_gameweek_for_prompt(board: GameweekBoard) -> str:
    lines: list[str] = []
    unconfirmed = bool(board.to_dict().get("unconfirmed_slate")) or any(
        f.unconfirmed_slate for f in board.fixtures
    )
    if unconfirmed:
        lines.append("UNCONFIRMED SLATE — only one calendar responded.")
        lines.append("")

    grouped: dict[str, list[GameweekFixture]] = {}
    order: list[str] = []
    for fixture in board.fixtures:
        label = fixture.round_label or fixture.league
        if label not in grouped:
            grouped[label] = []
            order.append(label)
        grouped[label].append(fixture)

    for label in order:
        lines.append(f"### {label}")
        for fixture in grouped[label]:
            sources = ", ".join(fixture.sources)
            lines.append(f"- {fixture.match} · {fixture.kickoff_et} · {sources}")
        lines.append("")

    return "\n".join(lines).rstrip()
