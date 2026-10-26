"""Fetch in-play soccer fixtures for live prediction runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
ET = ZoneInfo("America/New_York")

# Agent verification URLs (webSearch / read) — see live-fixtures.md
LIVE_SOURCE_URLS = {
    "espn_scoreboard": "https://www.espn.com/soccer/scoreboard",
    "livescore": "https://www.livescore.com/en/football/live/",
    "flashscore": "https://www.flashscore.com/",
    "sofascore": "https://www.sofascore.com/",
    "fotmob": "https://www.fotmob.com/live",
}


@dataclass
class LiveFixture:
    league: str
    match: str
    minute: str
    score: str
    status: str  # e.g. "1st Half", "2nd Half", "Halftime"
    home: str
    away: str
    source: str = "espn"
    espn_event_id: str = ""
    detail_url: str = ""
    home_score: int | None = None
    away_score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LiveFixtureBoard:
    fetched_at: str
    timezone: str = "America/New_York"
    in_play_count: int = 0
    fixtures: list[LiveFixture] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)
    agent_verify_urls: dict[str, str] = field(default_factory=lambda: dict(LIVE_SOURCE_URLS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "timezone": self.timezone,
            "in_play_count": self.in_play_count,
            "fixtures": [f.to_dict() for f in self.fixtures],
            "sources_checked": self.sources_checked,
            "agent_verify_urls": self.agent_verify_urls,
        }


def _espn_scoreboard_url(date_et: datetime | None = None) -> str:
    dt = date_et or datetime.now(tz=ET)
    d = dt.strftime("%Y%m%d")
    return f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={d}"


def _parse_espn_event(event: dict[str, Any]) -> LiveFixture | None:
    status = event.get("status", {})
    state = status.get("type", {}).get("state", "")
    if state != "in":
        return None

    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home = away = None
    home_score = away_score = None
    for c in competitors:
        team = c.get("team", {})
        name = team.get("displayName") or team.get("name") or "?"
        score = c.get("score")
        try:
            score_i = int(score) if score is not None else None
        except (TypeError, ValueError):
            score_i = None
        if c.get("homeAway") == "home":
            home = name
            home_score = score_i
        else:
            away = name
            away_score = score_i

    if not home or not away:
        return None

    league = (event.get("leagues") or [{}])[0].get("name") or event.get("name") or "Soccer"
    minute = status.get("displayClock") or status.get("clock") or "?"
    detail = (
        status.get("type", {}).get("detail")
        or status.get("type", {}).get("shortDetail")
        or "In play"
    )
    score_str = f"{home_score or 0}-{away_score or 0}"

    event_id = str(event.get("id", ""))
    detail_url = f"https://www.espn.com/soccer/match/_/gameId/{event_id}" if event_id else ""

    return LiveFixture(
        league=league,
        match=f"{home} vs {away}",
        minute=str(minute),
        score=score_str,
        status=detail,
        home=home,
        away=away,
        source="espn",
        espn_event_id=event_id,
        detail_url=detail_url,
        home_score=home_score,
        away_score=away_score,
    )


def fetch_live_fixtures_espn(date_et: datetime | None = None) -> list[LiveFixture]:
    """Programmatic live board from ESPN (used by web app pre-check)."""
    url = _espn_scoreboard_url(date_et)
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    fixtures: list[LiveFixture] = []
    for event in data.get("events") or []:
        fx = _parse_espn_event(event)
        if fx:
            fixtures.append(fx)

    fixtures.sort(key=lambda f: (f.league, f.match))
    return fixtures


def fetch_live_board() -> LiveFixtureBoard:
    """Return current in-play fixtures plus verification URLs for the agent."""
    now = datetime.now(tz=ET)
    fixtures = fetch_live_fixtures_espn(now)
    return LiveFixtureBoard(
        fetched_at=now.isoformat(timespec="seconds"),
        in_play_count=len(fixtures),
        fixtures=fixtures,
        sources_checked=["espn_api"],
    )


def format_board_for_prompt(board: LiveFixtureBoard) -> str:
    """Compact block injected into live-run agent prompts."""
    lines = [
        "## Live fixture board (ESPN API snapshot — verify on Sofascore/FlashScore/LiveScore)",
        f"Fetched: {board.fetched_at} Eastern · **{board.in_play_count}** matches in play",
        "",
        "Cross-check each candidate on:",
        f"- LiveScore: {LIVE_SOURCE_URLS['livescore']}",
        f"- FlashScore: {LIVE_SOURCE_URLS['flashscore']}",
        f"- Sofascore: {LIVE_SOURCE_URLS['sofascore']}",
        f"- FotMob: {LIVE_SOURCE_URLS['fotmob']}",
        "",
    ]
    if not board.fixtures:
        lines.append(
            "**No in-play games on ESPN right now.** Still check LiveScore, FlashScore, "
            "and Sofascore — Asia/Europe overlap or ESPN gaps happen. "
            "If truly nothing is live, submit empty picks and list sources checked in `skipped`."
        )
        return "\n".join(lines)

    lines.append("| League | Match | Minute | Score | Status |")
    lines.append("|--------|-------|--------|-------|--------|")
    for f in board.fixtures[:40]:
        lines.append(f"| {f.league} | {f.match} | {f.minute} | {f.score} | {f.status} |")
    if len(board.fixtures) > 40:
        lines.append(f"| … | +{len(board.fixtures) - 40} more | | | |")

    lines.extend(
        [
            "",
            "For each in-play match above (and any extra found on Sofascore/FlashScore/LiveScore):",
            "1. Confirm minute + score on at least two sources.",
            "2. Pull shots/xG/corners if available (Sofascore or FotMob match page).",
            "3. Try SportyBet ng live price; if unavailable, publish with `price_available: false` (no odds).",
            "4. One pick per match max.",
        ]
    )
    return "\n".join(lines)
