"""Flashscore odds fallback when the Pinnacle guest feed is blocked.

Flashscore (same data family as Sofascore) publishes a delimited match list
and a per-match GraphQL odds comparison — the numbers shown when you open a
match. Those are already soft-book prices, used as-is as an approximation.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from predictor.odds.quotes import MarketQuote

logger = logging.getLogger(__name__)

FEED_BASE = "https://www.flashscore.com/x/feed"
ODDS_URL = "https://global.ds.lsapp.eu/odds/pq_graphql"
FSIGN = "SW9D1eZo"
DIV = "\u00f7"
NOT = "\u00ac"
CACHE_TTL_SECONDS = 90
REQUEST_TIMEOUT = 20
MAX_WORKERS = 6

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "x-fsign": FSIGN,
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "Accept": "*/*",
}

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class FlashscoreEvent:
    event_id: str
    league: str
    home: str
    away: str
    kickoff_utc: str
    home_pid: str
    away_pid: str


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of empty list")
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def parse_feed(text: str) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    for block in (text or "").split("~"):
        if not block.strip():
            continue
        fields: dict[str, str] = {}
        for item in block.split(NOT):
            if DIV not in item:
                continue
            key, value = item.split(DIV, 1)
            if key:
                fields[key] = value
        if fields:
            recs.append(fields)
    return recs


def _unix_to_utc(raw: str) -> str:
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_events(text: str) -> list[FlashscoreEvent]:
    events: list[FlashscoreEvent] = []
    league = ""
    for rec in parse_feed(text):
        if rec.get("ZA"):
            league = rec["ZA"]
        event_id = rec.get("AA") or ""
        home = rec.get("AE") or rec.get("CX") or rec.get("FH") or ""
        away = rec.get("AF") or rec.get("FK") or ""
        if not event_id or not home or not away:
            continue
        events.append(
            FlashscoreEvent(
                event_id=event_id,
                league=league,
                home=home,
                away=away,
                kickoff_utc=_unix_to_utc(rec.get("ADE") or rec.get("AD") or ""),
                home_pid=rec.get("JA") or "",
                away_pid=rec.get("JB") or "",
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


def _get_text(url: str) -> str:
    cached = _cache_get(url)
    if cached is not None:
        return cached
    try:
        response = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Flashscore request failed %s: %s", url, exc)
        return ""
    if response.status_code != 200:
        logger.warning("Flashscore returned %s for %s", response.status_code, url)
        return ""
    text = response.text
    _cache_set(url, text)
    return text


def _geo() -> str:
    return os.environ.get("FLASHSCORE_GEO", "NG").strip() or "NG"


def fetch_event_odds(event_id: str) -> list[dict]:
    key = f"odds:{event_id}:{_geo()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    params = {
        "_hash": "oce",
        "eventId": event_id,
        "projectId": "2",
        "geoIpCode": _geo(),
        "geoIpSubdivisionCode": "",
    }
    try:
        response = requests.get(ODDS_URL, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Flashscore odds failed for %s: %s", event_id, exc)
        return []
    if response.status_code != 200:
        logger.warning("Flashscore odds %s for %s", response.status_code, event_id)
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    odds = (((payload.get("data") or {}).get("findOddsByEventId") or {}).get("odds")) or []
    if not isinstance(odds, list):
        return []
    _cache_set(key, odds)
    return odds


def _decimal(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


def _handicap_line(item: dict) -> float | None:
    hand = item.get("handicap")
    raw = hand.get("value") if isinstance(hand, dict) else hand
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _quote(
    *,
    family: str,
    market: str,
    tip: str,
    line: float | None,
    odds: float,
    period: int,
    source_key: str,
) -> MarketQuote:
    fair = round(1.0 / odds, 5) if odds > 1.0 else 0.0
    return MarketQuote(
        family=family,
        market=market,
        tip=tip,
        line=line,
        side=None,
        period=period,
        odds=round(odds, 3),
        raw_odds=round(odds, 3),
        fair_probability=fair,
        source_key=source_key,
        source="flashscore",
    )


def quotes_from_odds(
    *,
    home: str,
    away: str,
    home_pid: str,
    away_pid: str,
    odds: list[dict],
) -> list[MarketQuote]:
    buckets: dict[tuple, list[float]] = {}

    def add(key: tuple, value: float | None) -> None:
        if value is None:
            return
        buckets.setdefault(key, []).append(value)

    for group in odds or []:
        if not isinstance(group, dict):
            continue
        btype = group.get("bettingType") or ""
        scope = group.get("bettingScope") or ""
        period = 1 if scope == "FIRST_HALF" else 0
        if scope not in ("FULL_TIME", "FIRST_HALF"):
            continue
        prefix = "1H " if period == 1 else ""
        for item in group.get("odds") or []:
            if not isinstance(item, dict) or item.get("active") is False:
                continue
            price = _decimal(item.get("value"))
            pid = item.get("eventParticipantId")
            if btype == "HOME_DRAW_AWAY":
                if pid == home_pid:
                    add(("1x2", period, "home"), price)
                elif pid == away_pid:
                    add(("1x2", period, "away"), price)
                elif pid in (None, "", "null"):
                    add(("1x2", period, "draw"), price)
            elif btype == "OVER_UNDER":
                line = _handicap_line(item)
                side = (item.get("selection") or "").upper()
                if line is None or side not in ("OVER", "UNDER"):
                    continue
                add(("ou", period, line, side.lower()), price)
            elif btype == "BOTH_TEAMS_TO_SCORE" and period == 0:
                flag = item.get("bothTeamsToScore")
                if flag is True:
                    add(("btts", "yes"), price)
                elif flag is False:
                    add(("btts", "no"), price)
            elif btype == "DRAW_NO_BET" and period == 0:
                if pid == home_pid:
                    add(("dnb", "home"), price)
                elif pid == away_pid:
                    add(("dnb", "away"), price)
            elif btype == "ASIAN_HANDICAP" and period == 0:
                line = _handicap_line(item)
                if line is None:
                    continue
                if pid == home_pid:
                    add(("ah", line, "home"), price)
                elif pid == away_pid:
                    add(("ah", line, "away"), price)

    out: list[MarketQuote] = []
    if ("1x2", 0, "home") in buckets:
        out.append(
            _quote(
                family="result",
                market="Match result",
                tip=f"{home} win",
                line=None,
                odds=median(buckets[("1x2", 0, "home")]),
                period=0,
                source_key="1x2",
            )
        )
    if ("1x2", 0, "draw") in buckets:
        out.append(
            _quote(
                family="result",
                market="Match result",
                tip="Draw",
                line=None,
                odds=median(buckets[("1x2", 0, "draw")]),
                period=0,
                source_key="1x2",
            )
        )
    if ("1x2", 0, "away") in buckets:
        out.append(
            _quote(
                family="result",
                market="Match result",
                tip=f"{away} win",
                line=None,
                odds=median(buckets[("1x2", 0, "away")]),
                period=0,
                source_key="1x2",
            )
        )
    for key, values in buckets.items():
        if key[0] != "ou":
            continue
        _, period, line, side = key
        prefix = "1H " if period == 1 else ""
        label = "Over" if side == "over" else "Under"
        family = "halves" if period == 1 else "goals_totals"
        out.append(
            _quote(
                family=family,
                market=f"{prefix}Over/Under {line:g} goals",
                tip=f"{prefix}{label} {line:g} goals",
                line=float(line),
                odds=median(values),
                period=period,
                source_key=f"ou-{line}",
            )
        )
    if ("btts", "yes") in buckets:
        out.append(
            _quote(
                family="btts",
                market="BTTS",
                tip="BTTS Yes",
                line=None,
                odds=median(buckets[("btts", "yes")]),
                period=0,
                source_key="btts",
            )
        )
    if ("btts", "no") in buckets:
        out.append(
            _quote(
                family="btts",
                market="BTTS",
                tip="BTTS No",
                line=None,
                odds=median(buckets[("btts", "no")]),
                period=0,
                source_key="btts",
            )
        )
    if ("dnb", "home") in buckets:
        out.append(
            _quote(
                family="dc_dnb",
                market="Draw no bet",
                tip=f"{home} draw no bet",
                line=None,
                odds=median(buckets[("dnb", "home")]),
                period=0,
                source_key="dnb",
            )
        )
    if ("dnb", "away") in buckets:
        out.append(
            _quote(
                family="dc_dnb",
                market="Draw no bet",
                tip=f"{away} draw no bet",
                line=None,
                odds=median(buckets[("dnb", "away")]),
                period=0,
                source_key="dnb",
            )
        )
    for key, values in buckets.items():
        if key[0] != "ah":
            continue
        _, line, side = key
        team = home if side == "home" else away
        out.append(
            _quote(
                family="handicap",
                market=f"Asian handicap {line:+g}",
                tip=f"{team} {line:+g} AH",
                line=float(line),
                odds=median(values),
                period=0,
                source_key=f"ah-{line}",
            )
        )
    return out


def _parse_kickoff(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _stable_id(event_id: str) -> int:
    return zlib.adler32(event_id.encode("utf-8")) & 0x7FFFFFFF


def _list_day(offset: int) -> list[FlashscoreEvent]:
    url = f"{FEED_BASE}/f_1_{offset}_2_en_1"
    return parse_events(_get_text(url))


def build_flashscore_board(
    *,
    start_utc: datetime,
    end_utc: datetime,
    min_odds: float,
    max_odds: float,
    families: list[str] | None = None,
    max_fixtures: int = 40,
):
    """Build a priced board from Flashscore. Never raises."""
    from predictor.odds.board import BoardFixture, PricedBoard, _format_et

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors: list[str] = []
    seen: set[str] = set()
    events: list[FlashscoreEvent] = []
    for offset in (-1, 0, 1):
        try:
            for ev in _list_day(offset):
                if ev.event_id in seen:
                    continue
                seen.add(ev.event_id)
                kickoff = _parse_kickoff(ev.kickoff_utc)
                if kickoff and start_utc <= kickoff <= end_utc:
                    events.append(ev)
        except Exception as exc:
            errors.append(f"flashscore list offset {offset}: {exc}")
    events.sort(key=lambda ev: ev.kickoff_utc)
    events = events[:max_fixtures]
    if not events:
        return PricedBoard(
            fixtures=[],
            fetched_at=fetched_at,
            errors=errors or ["Flashscore returned no fixtures in window"],
        )

    fixtures: list[BoardFixture] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(fetch_event_odds, ev.event_id): ev for ev in events}
        for future in as_completed(future_map):
            ev = future_map[future]
            try:
                raw_odds = future.result()
            except Exception as exc:
                errors.append(f"{ev.home} vs {ev.away}: {exc}")
                continue
            quotes = [
                q
                for q in quotes_from_odds(
                    home=ev.home,
                    away=ev.away,
                    home_pid=ev.home_pid,
                    away_pid=ev.away_pid,
                    odds=raw_odds,
                )
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
                    matchup_id=_stable_id(ev.event_id),
                    quotes=quotes,
                )
            )
    fixtures.sort(key=lambda f: f.kickoff_utc)
    return PricedBoard(fixtures=fixtures, fetched_at=fetched_at, errors=errors)
