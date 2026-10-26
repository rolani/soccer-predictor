"""OddsFilter screener fallback — one JSON of 1X2, Over/Under 2.5, and BTTS.

https://oddsfilter.com/api/screener?d=YYYY-MM-DD is the table behind
oddsfilter.com. Consensus decimals are already soft-book prices.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from predictor.odds.quotes import MarketQuote

logger = logging.getLogger(__name__)

SCREENER = "https://oddsfilter.com/api/screener"
CACHE_TTL_SECONDS = 90
REQUEST_TIMEOUT = 25

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://oddsfilter.com/",
}

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class OddsFilterEvent:
    event_id: int
    league: str
    home: str
    away: str
    kickoff_utc: str
    row: dict


def _decimal(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


def _quote(family: str, market: str, tip: str, line: float | None, odds: float) -> MarketQuote:
    return MarketQuote(
        family=family,
        market=market,
        tip=tip,
        line=line,
        side=None,
        period=0,
        odds=round(odds, 3),
        raw_odds=round(odds, 3),
        fair_probability=round(1.0 / odds, 5),
        source_key="oddsfilter",
        source="oddsfilter",
    )


def quotes_from_row(row: dict) -> list[MarketQuote]:
    home = (row.get("h") or "").strip()
    away = (row.get("a") or "").strip()
    out: list[MarketQuote] = []
    one_x_two = row.get("o") or []
    if home and away and len(one_x_two) >= 3:
        labels = [
            (f"{home} win", one_x_two[0]),
            ("Draw", one_x_two[1]),
            (f"{away} win", one_x_two[2]),
        ]
        for tip, raw in labels:
            price = _decimal(raw)
            if price:
                out.append(_quote("result", "Match result", tip, None, price))
    ou = row.get("ou") or []
    if len(ou) >= 2:
        over, under = _decimal(ou[0]), _decimal(ou[1])
        if over:
            out.append(_quote("goals_totals", "Over/Under 2.5 goals", "Over 2.5 goals", 2.5, over))
        if under:
            out.append(
                _quote("goals_totals", "Over/Under 2.5 goals", "Under 2.5 goals", 2.5, under)
            )
    btts = row.get("bt") or []
    if len(btts) >= 2:
        yes, no = _decimal(btts[0]), _decimal(btts[1])
        if yes:
            out.append(_quote("btts", "BTTS", "BTTS Yes", None, yes))
        if no:
            out.append(_quote("btts", "BTTS", "BTTS No", None, no))
    return out


def _league_name(leagues: dict, league_id: Any) -> str:
    info = leagues.get(str(league_id)) or leagues.get(league_id) or {}
    if isinstance(info, dict):
        return info.get("n") or ""
    return str(info or "")


def _unix_to_utc(raw: Any) -> str:
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows_to_events(payload: dict) -> list[OddsFilterEvent]:
    leagues = payload.get("leagues") or {}
    events: list[OddsFilterEvent] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        home = (row.get("h") or "").strip()
        away = (row.get("a") or "").strip()
        if not home or not away:
            continue
        event_id = row.get("i")
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            continue
        events.append(
            OddsFilterEvent(
                event_id=event_id,
                league=_league_name(leagues, row.get("l")),
                home=home,
                away=away,
                kickoff_utc=_unix_to_utc(row.get("t")),
                row=row,
            )
        )
    return events


def _cache_get(key: str) -> Any | None:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def fetch_screener(day: str) -> dict:
    key = f"screener:{day}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        response = requests.get(
            SCREENER, params={"d": day}, headers=_HEADERS, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("OddsFilter request failed: %s", exc)
        return {}
    if response.status_code != 200:
        logger.warning("OddsFilter returned %s", response.status_code)
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    _cache_set(key, payload)
    return payload


def _parse_kickoff(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build_oddsfilter_board(
    *,
    start_utc: datetime,
    end_utc: datetime,
    min_odds: float,
    max_odds: float,
    families: list[str] | None = None,
    max_fixtures: int = 40,
):
    """Build a priced board from OddsFilter. Never raises."""
    from predictor.odds.board import BoardFixture, PricedBoard, _format_et

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors: list[str] = []
    days = {
        start_utc.date(),
        end_utc.date(),
        (start_utc - timedelta(hours=6)).date(),
    }
    seen: set[int] = set()
    events: list[OddsFilterEvent] = []
    for day in sorted(days):
        try:
            payload = fetch_screener(day.isoformat())
            for ev in rows_to_events(payload):
                if ev.event_id in seen:
                    continue
                kickoff = _parse_kickoff(ev.kickoff_utc)
                if kickoff and start_utc <= kickoff <= end_utc:
                    seen.add(ev.event_id)
                    events.append(ev)
        except Exception as exc:
            errors.append(f"oddsfilter {day}: {exc}")
    events.sort(key=lambda ev: ev.kickoff_utc)
    events = events[:max_fixtures]
    fixtures: list[BoardFixture] = []
    for ev in events:
        quotes = [
            q
            for q in quotes_from_row(ev.row)
            if min_odds <= q.odds <= max_odds and (not families or q.family in families)
        ]
        if not quotes:
            continue
        kickoff = _parse_kickoff(ev.kickoff_utc)
        fixtures.append(
            BoardFixture(
                league=ev.league,
                home=ev.home,
                away=ev.away,
                kickoff_utc=ev.kickoff_utc,
                kickoff_et=_format_et(kickoff),
                matchup_id=ev.event_id,
                quotes=quotes,
            )
        )
    if not fixtures:
        errors.append("OddsFilter returned no priced fixtures in window")
    return PricedBoard(fixtures=fixtures, fetched_at=fetched_at, errors=errors)
