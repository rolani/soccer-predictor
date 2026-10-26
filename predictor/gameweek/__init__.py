"""Gameweek slate: two-of-three calendars, isolated from predictor.web."""

from __future__ import annotations

from predictor.gameweek.board import build_gameweek_board, format_gameweek_for_prompt
from predictor.gameweek.types import GameweekBoard, GameweekFixture

__all__ = [
    "GameweekBoard",
    "GameweekFixture",
    "build_gameweek_board",
    "format_gameweek_for_prompt",
]
