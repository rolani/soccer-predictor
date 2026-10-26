"""Assemble the priced market board handed to the research agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from predictor.odds.matching import match_fixture
from predictor.odds.pinnacle import (
    OddsUnavailable,
    PinnacleMatchup,
    list_matchups,
    related,
    straight_markets,
)
from predictor.odds.quotes import MarketQuote, build_quotes

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")


@dataclass
class BoardFixture:
    league: str
    home: str
    away: str
    kickoff_utc: str
    kickoff_et: str
    matchup_id: int
    quotes: list[MarketQuote] = field(default_factory=list)

    @property
    def match_label(self) -> str:
        return f"{self.home} vs {self.away}"


@dataclass
class PricedBoard:
    fixtures: list[BoardFixture] = field(default_factory=list)
    fetched_at: str = ""
    errors: list[str] = field(default_factory=list)

    def find(self, match: str) -> BoardFixture | None:
        candidates = [
            PinnacleMatchup(
                id=f.matchup_id,
                parent_id=None,
                league=f.league,
                home=f.home,
                away=f.away,
                start_time_utc=f.kickoff_utc,
                kind="main",
            )
            for f in self.fixtures
        ]
        hit = match_fixture(match, candidates)
        if not hit:
            return None
        return next((f for f in self.fixtures if f.matchup_id == hit.id), None)

    def to_dict(self) -> dict:
        return {
            "fetched_at": self.fetched_at,
            "errors": self.errors,
            "fixtures": [
                {
                    "league": f.league,
                    "match": f.match_label,
                    "kickoff_et": f.kickoff_et,
                    "matchup_id": f.matchup_id,
                    "quotes": [
                        {
                            "family": q.family,
                            "tip": q.tip,
                            "odds": q.odds,
                            "raw_odds": q.raw_odds,
                            "fair": q.fair_probability,
                        }
                        for q in f.quotes
                    ],
                }
                for f in self.fixtures
            ],
        }


def _parse_utc(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _format_et(kickoff: datetime | None) -> str:
    """Eastern kickoff label. `%-I` is POSIX-only, so strip the pad manually."""
    if kickoff is None:
        return ""
    return kickoff.astimezone(EASTERN).strftime("%I:%M %p ET").lstrip("0")


def window_for_scope(
    scope: str,
    hours_window: int | None = None,
    target_date: str | None = None,
) -> tuple[datetime, datetime]:
    """UTC window of kickoffs a scope should consider."""
    now = datetime.now(timezone.utc)
    if scope == "window":
        return now, now + timedelta(hours=hours_window or 6)
    if scope == "date" and target_date:
        try:
            day = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=EASTERN)
        except ValueError:
            return now, now + timedelta(hours=24)
        return day.astimezone(timezone.utc), (day + timedelta(days=1)).astimezone(timezone.utc)
    if scope == "tomorrow":
        et_now = now.astimezone(EASTERN)
        start = (et_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
    if scope == "live":
        return now - timedelta(hours=3), now + timedelta(minutes=30)
    et_now = now.astimezone(EASTERN)
    end = et_now.replace(hour=23, minute=59, second=59, microsecond=0)
    return now, end.astimezone(timezone.utc)


def build_board(
    *,
    start_utc: datetime,
    end_utc: datetime,
    min_odds: float,
    max_odds: float,
    families: list[str] | None = None,
    max_fixtures: int = 40,
) -> PricedBoard:
    """Fetch and price every fixture in the window. Never raises."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors: list[str] = []

    try:
        matchups = list_matchups()
    except OddsUnavailable as e:
        logger.warning("Pinnacle unavailable: %s", e)
        return PricedBoard(fixtures=[], fetched_at=fetched_at, errors=[str(e)])
    except Exception as e:
        logger.warning("Pinnacle fetch/parse failed: %s", e)
        return PricedBoard(fixtures=[], fetched_at=fetched_at, errors=[str(e)])

    in_window: list[PinnacleMatchup] = []
    for m in matchups:
        if m.kind != "main" or m.parent_id is not None:
            continue
        kickoff = _parse_utc(m.start_time_utc)
        if kickoff and start_utc <= kickoff <= end_utc:
            in_window.append(m)
    in_window.sort(key=lambda m: m.start_time_utc)
    in_window = in_window[:max_fixtures]

    fixtures: list[BoardFixture] = []
    for m in in_window:
        try:
            rel = related(m.id)
            markets = straight_markets(m.id)
            quotes = build_quotes(m, rel + [m], markets)
        except OddsUnavailable as e:
            errors.append(f"{m.home} vs {m.away}: {e}")
            continue
        except Exception as e:
            errors.append(f"{m.home} vs {m.away}: {e}")
            continue
        quotes = [
            q
            for q in quotes
            if min_odds <= q.odds <= max_odds and (not families or q.family in families)
        ]
        if not quotes:
            continue
        fixtures.append(
            BoardFixture(
                league=m.league,
                home=m.home,
                away=m.away,
                kickoff_utc=m.start_time_utc,
                kickoff_et=_format_et(_parse_utc(m.start_time_utc)),
                matchup_id=m.id,
                quotes=quotes,
            )
        )

    return PricedBoard(fixtures=fixtures, fetched_at=fetched_at, errors=errors)


_FAMILY_LABELS = {
    "goals_totals": "Goals O/U",
    "team_totals": "Team totals",
    "halves": "First half",
    "btts": "BTTS",
    "result": "1X2",
    "dc_dnb": "DC / DNB",
    "handicap": "Asian handicap",
    "corners": "Corners",
    "specials": "Specials",
}


def format_board_for_prompt(board: PricedBoard) -> str:
    """Compact markdown board. Prices here are the only prices the agent may use."""
    if not board.fixtures:
        reason = f" ({'; '.join(board.errors[:2])})" if board.errors else ""
        return (
            "## Priced market board\n\n"
            f"**No priced markets available{reason}.** "
            "Publish picks with `price_available: false` and no odds.\n"
        )

    lines = [
        "## Priced market board",
        "",
        f"Real book prices, fetched {board.fetched_at}. "
        f"{len(board.fixtures)} fixtures, filtered to your odds range.",
        "",
        "**These are the only prices you may use.** Copy the number exactly. "
        "If the market you want is absent, pick a market that is present, or "
        "publish with `price_available: false` and no odds.",
        "",
    ]
    for f in board.fixtures:
        lines.append(f"### {f.match_label} — {f.league} — {f.kickoff_et}")
        by_family: dict[str, list[MarketQuote]] = {}
        for q in f.quotes:
            by_family.setdefault(q.family, []).append(q)
        for family in _FAMILY_LABELS:
            group = by_family.get(family)
            if not group:
                continue
            priced = " · ".join(f"{q.tip} @{q.odds:.2f}" for q in group)
            lines.append(f"- **{_FAMILY_LABELS[family]}:** {priced}")
        lines.append("")
    return "\n".join(lines)
