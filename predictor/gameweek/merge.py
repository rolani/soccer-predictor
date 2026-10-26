"""Two-of-three merge of calendar rows into a Gameweek slate."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from predictor.gameweek.types import GameweekBoard, GameweekFixture, RawFixture
from predictor.odds.matching import normalize_team

EASTERN = ZoneInfo("America/New_York")
LEAGUE_ORDER = ("EPL", "Bundesliga", "La Liga", "Serie A", "Ligue 1")
SOURCE_PREF = ("football-data", "fotmob", "espn")
KICKOFF_TOLERANCE = timedelta(minutes=15)


def _parse_utc(kickoff_utc: str) -> datetime:
    return datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))


def _format_et(kickoff: datetime) -> str:
    """Eastern kickoff label matching odds.board (strip leading zero)."""
    return kickoff.astimezone(EASTERN).strftime("%I:%M %p ET").lstrip("0")


def _source_rank(source: str) -> int:
    try:
        return SOURCE_PREF.index(source)
    except ValueError:
        return len(SOURCE_PREF)


def _preferred_row(rows: list[RawFixture]) -> RawFixture:
    return min(rows, key=lambda r: _source_rank(r.source))


def _match_label(rows: list[RawFixture]) -> str:
    row = _preferred_row(rows)
    return f"{row.home} vs {row.away}"


def _round_label(rows: list[RawFixture]) -> str:
    for row in rows:
        if row.round_label:
            return row.round_label
    return ""


def _source_names(rows: list[RawFixture]) -> list[str]:
    present = {row.source for row in rows}
    ordered = [s for s in SOURCE_PREF if s in present]
    extras = [s for s in present if s not in SOURCE_PREF]
    return ordered + extras


def _parsed_kickoffs(rows: list[RawFixture]) -> list[tuple[RawFixture, datetime]]:
    parsed: list[tuple[RawFixture, datetime]] = []
    for row in rows:
        try:
            parsed.append((row, _parse_utc(row.kickoff_utc)))
        except (TypeError, ValueError):
            continue
    return parsed


def _agreed_kickoff(rows: list[RawFixture]) -> RawFixture | None:
    """Return a preferred row only when two parseable times agree within 15 minutes."""
    parsed = _parsed_kickoffs(rows)
    if len(parsed) < 2:
        return None

    agreeing: list[tuple[RawFixture, datetime]] = []
    for row, when in parsed:
        partners = sum(1 for _, other in parsed if abs(when - other) <= KICKOFF_TOLERANCE)
        if partners >= 2:
            agreeing.append((row, when))
    if not agreeing:
        return None
    agreeing.sort(key=lambda item: (_source_rank(item[0].source), item[1]))
    return agreeing[0][0]


def _league_sort_key(league: str) -> tuple[int, str]:
    try:
        return (LEAGUE_ORDER.index(league), league)
    except ValueError:
        return (len(LEAGUE_ORDER), league)


def merge_raw_fixtures(raw: list[RawFixture], *, sources_up: int) -> GameweekBoard:
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if sources_up == 0:
        return GameweekBoard(fetched_at=fetched_at, leagues=[], source_errors=[], sources_up=0)

    groups: dict[tuple[str, str, str], list[RawFixture]] = defaultdict(list)
    for row in raw:
        key = (row.league, normalize_team(row.home), normalize_team(row.away))
        groups[key].append(row)

    fixtures: list[GameweekFixture] = []
    skipped: list[dict[str, str]] = []
    unconfirmed = sources_up == 1

    for rows in groups.values():
        sources = {row.source for row in rows}
        if sources_up >= 2 and len(sources) < 2:
            continue
        if all(row.finished for row in rows):
            continue
        if unconfirmed:
            agreed = _preferred_row(rows)
            try:
                when = _parse_utc(agreed.kickoff_utc)
                kickoff_et = _format_et(when)
                kickoff_utc = agreed.kickoff_utc
            except (TypeError, ValueError):
                skipped.append({"match": _match_label(rows), "why": "kickoff unconfirmed"})
                continue
        else:
            parsed = _parsed_kickoffs(rows)
            if len(parsed) < 2:
                skipped.append({"match": _match_label(rows), "why": "kickoff unconfirmed"})
                continue
            agreed_row = _agreed_kickoff(rows)
            if agreed_row is None:
                skipped.append({"match": _match_label(rows), "why": "kickoff mismatch"})
                continue
            agreed = agreed_row
            when = _parse_utc(agreed.kickoff_utc)
            kickoff_et = _format_et(when)
            kickoff_utc = agreed.kickoff_utc

        names = _preferred_row(rows)
        fixtures.append(
            GameweekFixture(
                league=names.league,
                round_label=_round_label(rows),
                match=_match_label(rows),
                home=names.home,
                away=names.away,
                kickoff_et=kickoff_et,
                kickoff_utc=kickoff_utc,
                sources=_source_names(rows),
                unconfirmed_slate=unconfirmed,
            )
        )

    fixtures.sort(key=lambda f: (_league_sort_key(f.league), f.kickoff_utc, f.match))
    seen: set[str] = set()
    leagues: list[str] = []
    for name in LEAGUE_ORDER:
        if any(f.league == name for f in fixtures) and name not in seen:
            leagues.append(name)
            seen.add(name)
    for f in fixtures:
        if f.league not in seen:
            leagues.append(f.league)
            seen.add(f.league)

    return GameweekBoard(
        fetched_at=fetched_at,
        leagues=leagues,
        fixtures=fixtures,
        skipped=skipped,
        source_errors=[],
        sources_up=sources_up,
    )
