"""Football-data.org, FotMob, and ESPN matchday calendars.

The only module that may HTTP-fetch gameweek schedules.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from predictor.gameweek.types import RawFixture

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TIMEOUT = 25
ET = ZoneInfo("America/New_York")

LEAGUES = (
    ("EPL", "PL", "eng.1", 47),
    ("Bundesliga", "BL1", "ger.1", 54),
    ("La Liga", "PD", "esp.1", 87),
    ("Serie A", "SA", "ita.1", 55),
    ("Ligue 1", "FL1", "fra.1", 53),
)

_FD_FINISHED = frozenset({"FINISHED", "AWARDED"})
_FD_UNCONFIRMED = frozenset({"POSTPONED", "CANCELLED", "CANCELED", "SUSPENDED", "ABANDONED"})
_ESPN_UNCONFIRMED_MARKERS = ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED", "ABANDONED")
_CODE_TO_DISPLAY = {code: display for display, code, _slug, _fid in LEAGUES}


def _fd_kickoff_utc(status: str, utc: str) -> str:
    if status.upper() in _FD_UNCONFIRMED:
        return ""
    return utc


def _espn_unconfirmed(stype: dict[str, Any]) -> bool:
    blob = " ".join(str(stype.get(key) or "") for key in ("name", "state", "description")).upper()
    return any(marker in blob for marker in _ESPN_UNCONFIRMED_MARKERS)


def _fotmob_unconfirmed(status: dict[str, Any]) -> bool:
    if status.get("cancelled") or status.get("canceled") or status.get("postponed"):
        return True
    return False


class CalendarDown(Exception):
    """One calendar source is unavailable. load_all catches this."""


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if extra:
        h.update(extra)
    return h


def _get(url: str, extra_headers: dict[str, str] | None = None) -> Any:
    r = requests.get(url, headers=_headers(extra_headers), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _fd_matchday(data: dict[str, Any]) -> int:
    season = data.get("currentSeason") if isinstance(data.get("currentSeason"), dict) else {}
    n = season.get("currentMatchday") or data.get("currentMatchday")
    try:
        return int(n)
    except (TypeError, ValueError):
        raise CalendarDown("unexpected shape") from None


def fetch_football_data(league_code: str) -> list[RawFixture]:
    token = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if not token:
        raise CalendarDown("no FOOTBALL_DATA_API_KEY (optional third calendar)")

    display = _CODE_TO_DISPLAY.get(league_code, league_code)
    auth = {"X-Auth-Token": token}
    competition = _get(
        f"https://api.football-data.org/v4/competitions/{league_code}",
        extra_headers=auth,
    )
    if not isinstance(competition, dict):
        raise CalendarDown("unexpected shape")
    matchday = _fd_matchday(competition)
    payload = _get(
        f"https://api.football-data.org/v4/competitions/{league_code}/matches?matchday={matchday}",
        extra_headers=auth,
    )
    if not isinstance(payload, dict) or "matches" not in payload:
        raise CalendarDown("unexpected shape")
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise CalendarDown("unexpected shape")

    rows: list[RawFixture] = []
    label = f"{display} GW{matchday}"
    for item in matches:
        if not isinstance(item, dict):
            continue
        home = item.get("homeTeam") if isinstance(item.get("homeTeam"), dict) else {}
        away = item.get("awayTeam") if isinstance(item.get("awayTeam"), dict) else {}
        home_name = home.get("name") or ""
        away_name = away.get("name") or ""
        if not home_name or not away_name:
            continue
        status = str(item.get("status") or "")
        utc = item.get("utcDate") or ""
        if not isinstance(utc, str):
            utc = str(utc) if utc else ""
        rows.append(
            RawFixture(
                source="football-data",
                league=display,
                home=home_name,
                away=away_name,
                kickoff_utc=_fd_kickoff_utc(status, utc),
                round_label=label,
                finished=status in _FD_FINISHED,
            )
        )
    return rows


def _group_round(group: dict[str, Any]) -> int | None:
    raw = group.get("round")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _as_round(raw: Any) -> int | None:
    try:
        return int(raw) if raw is not None and raw != "" else None
    except (TypeError, ValueError):
        return None


def _fotmob_active_round(data: dict[str, Any], all_matches: list[Any]) -> int | None:
    """Official current matchday: fixtureInfo.activeRound, else earliest unfinished."""
    fixtures = data.get("fixtures") if isinstance(data.get("fixtures"), dict) else {}
    info = fixtures.get("fixtureInfo") if isinstance(fixtures.get("fixtureInfo"), dict) else {}
    active = info.get("activeRound") if isinstance(info.get("activeRound"), dict) else {}
    n = _as_round(active.get("roundId") or active.get("round"))
    if n is not None:
        return n
    unfinished: list[int] = []
    for item in all_matches:
        if not isinstance(item, dict):
            continue
        nested = item.get("matches")
        if isinstance(nested, list):
            rnd = _group_round(item)
            if rnd is not None and any(
                isinstance(m, dict) and not _fotmob_finished(m) for m in nested
            ):
                unfinished.append(rnd)
            continue
        if not _fotmob_finished(item):
            rnd = _group_round(item)
            if rnd is not None:
                unfinished.append(rnd)
    return min(unfinished) if unfinished else None


def _fotmob_finished(item: dict[str, Any]) -> bool:
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    return bool(status.get("finished"))


def _fotmob_row(item: dict[str, Any], display: str, round_n: int | None) -> RawFixture | None:
    home = item.get("home") if isinstance(item.get("home"), dict) else {}
    away = item.get("away") if isinstance(item.get("away"), dict) else {}
    home_name = home.get("name") or ""
    away_name = away.get("name") or ""
    if not home_name or not away_name:
        return None
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    utc = status.get("utcTime") or ""
    if not isinstance(utc, str):
        utc = str(utc) if utc else ""
    if _fotmob_unconfirmed(status):
        utc = ""
    n = round_n
    if n is None:
        n = _group_round(item)
    label = f"{display} GW{n}" if n is not None else display
    return RawFixture(
        source="fotmob",
        league=display,
        home=home_name,
        away=away_name,
        kickoff_utc=utc,
        round_label=label,
        finished=_fotmob_finished(item),
    )


def _fotmob_all_matches(data: Any) -> list[Any]:
    if not isinstance(data, dict):
        raise CalendarDown("unexpected shape")
    fixtures = data.get("fixtures")
    if isinstance(fixtures, dict) and "allMatches" in fixtures:
        all_matches = fixtures["allMatches"]
    elif "allMatches" in data:
        all_matches = data["allMatches"]
    else:
        raise CalendarDown("unexpected shape")
    if not isinstance(all_matches, list):
        raise CalendarDown("unexpected shape")
    return all_matches


def fetch_fotmob(league_id: int, display: str) -> list[RawFixture]:
    data = _get(f"https://www.fotmob.com/api/data/leagues?id={league_id}")
    all_matches = _fotmob_all_matches(data)
    if not all_matches:
        return []

    current = _fotmob_active_round(data, all_matches)
    first = all_matches[0]
    if isinstance(first, dict) and isinstance(first.get("matches"), list):
        groups: list[tuple[int | None, list[dict[str, Any]]]] = []
        for group in all_matches:
            if not isinstance(group, dict):
                continue
            matches = [m for m in (group.get("matches") or []) if isinstance(m, dict)]
            groups.append((_group_round(group), matches))
        if current is None:
            nums = [n for n, _ in groups if n is not None]
            current = max(nums) if nums else None
        rows: list[RawFixture] = []
        for n, matches in groups:
            if current is not None and n != current:
                continue
            for item in matches:
                row = _fotmob_row(item, display, n)
                if row:
                    rows.append(row)
        return rows

    rows = []
    for item in all_matches:
        if not isinstance(item, dict):
            continue
        n = _group_round(item)
        if current is not None and n != current:
            continue
        row = _fotmob_row(item, display, n)
        if row:
            rows.append(row)
    return rows


def _espn_week(event: dict[str, Any]) -> int | None:
    week = event.get("week") if isinstance(event.get("week"), dict) else {}
    raw = week.get("number")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _espn_event_row(event: dict[str, Any], display: str, week_n: int | None) -> RawFixture | None:
    comps = event.get("competitions") or []
    comp = comps[0] if comps else {}
    if not isinstance(comp, dict):
        return None
    home = away = ""
    for c in comp.get("competitors") or []:
        if not isinstance(c, dict):
            continue
        team = c.get("team") if isinstance(c.get("team"), dict) else {}
        name = team.get("displayName") or team.get("name") or ""
        if c.get("homeAway") == "home":
            home = name
        elif c.get("homeAway") == "away":
            away = name
    if not home or not away:
        return None
    status = event.get("status") if isinstance(event.get("status"), dict) else {}
    stype = status.get("type") if isinstance(status.get("type"), dict) else {}
    unconfirmed = _espn_unconfirmed(stype)
    finished = stype.get("state") == "post" and not unconfirmed
    utc = event.get("date") or ""
    if not isinstance(utc, str):
        utc = str(utc) if utc else ""
    if unconfirmed:
        utc = ""
    n = week_n if week_n is not None else _espn_week(event)
    label = f"{display} GW{n}" if n is not None else display
    return RawFixture(
        source="espn",
        league=display,
        home=home,
        away=away,
        kickoff_utc=utc,
        round_label=label,
        finished=finished,
    )


def _modal_week(events: list[dict[str, Any]]) -> int | None:
    weeks = [w for w in (_espn_week(ev) for ev in events) if w is not None]
    if not weeks:
        return None
    counts = Counter(weeks)
    top = max(counts.values())
    return min(w for w, c in counts.items() if c == top)


def fetch_espn(slug: str, display: str) -> list[RawFixture]:
    payloads: list[Any] = [
        _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard")
    ]
    now = datetime.now(tz=ET)
    for i in range(8):
        day = (now + timedelta(days=i)).strftime("%Y%m%d")
        payloads.append(
            _get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day}"
            )
        )

    by_id: dict[str, dict[str, Any]] = {}
    known_shape = False
    for payload in payloads:
        if not isinstance(payload, dict) or "events" not in payload:
            continue
        known_shape = True
        events = payload.get("events") or []
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            eid = str(event.get("id") or "")
            key = eid if eid else f"{event.get('date')}-{event.get('name')}"
            by_id[key] = event

    if not known_shape:
        raise CalendarDown("unexpected shape")

    events = list(by_id.values())
    modal = _modal_week(events)
    rows: list[RawFixture] = []
    for event in events:
        week_n = _espn_week(event)
        if modal is not None and week_n != modal:
            continue
        row = _espn_event_row(event, display, week_n)
        if row:
            rows.append(row)
    return rows


def _collect(name: str, loader, raw: list[RawFixture], errors: list[str]) -> int:
    try:
        raw.extend(loader())
        return 1
    except (requests.Timeout, TimeoutError):
        errors.append(f"{name}: timeout")
        return 0
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        return 0


def load_all() -> tuple[list[RawFixture], list[str], int]:
    raw: list[RawFixture] = []
    errors: list[str] = []
    sources_up = 0

    def load_fd() -> list[RawFixture]:
        rows: list[RawFixture] = []
        for _display, code, _slug, _fid in LEAGUES:
            rows.extend(fetch_football_data(code))
        return rows

    def load_fotmob() -> list[RawFixture]:
        rows: list[RawFixture] = []
        for display, _code, _slug, league_id in LEAGUES:
            rows.extend(fetch_fotmob(league_id, display))
        return rows

    def load_espn() -> list[RawFixture]:
        rows: list[RawFixture] = []
        for display, _code, slug, _fid in LEAGUES:
            rows.extend(fetch_espn(slug, display))
        return rows

    sources_up += _collect("football-data", load_fd, raw, errors)
    sources_up += _collect("fotmob", load_fotmob, raw, errors)
    sources_up += _collect("espn", load_espn, raw, errors)
    return raw, errors, sources_up
