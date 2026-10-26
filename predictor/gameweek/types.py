"""Gameweek slate types. Isolated from predictor.web."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawFixture:
    source: str
    league: str
    home: str
    away: str
    kickoff_utc: str
    round_label: str
    finished: bool


@dataclass
class GameweekFixture:
    league: str
    round_label: str
    match: str
    home: str
    away: str
    kickoff_et: str
    kickoff_utc: str
    sources: list[str]
    unconfirmed_slate: bool

    @property
    def match_label(self) -> str:
        return self.match

    def to_dict(self) -> dict[str, Any]:
        return {
            "league": self.league,
            "round_label": self.round_label,
            "match": self.match,
            "home": self.home,
            "away": self.away,
            "kickoff_et": self.kickoff_et,
            "kickoff_utc": self.kickoff_utc,
            "sources": list(self.sources),
            "unconfirmed_slate": self.unconfirmed_slate,
        }


@dataclass
class GameweekBoard:
    fetched_at: str
    leagues: list[str]
    fixtures: list[GameweekFixture] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    source_errors: list[str] = field(default_factory=list)
    sources_up: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "leagues": list(self.leagues),
            "fixtures": [f.to_dict() for f in self.fixtures],
            "skipped": list(self.skipped),
            "source_errors": list(self.source_errors),
            "remaining": len(self.fixtures),
            "unconfirmed_slate": any(f.unconfirmed_slate for f in self.fixtures),
            "sources_up": self.sources_up,
        }
