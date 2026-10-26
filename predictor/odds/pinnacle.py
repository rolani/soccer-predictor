"""Pinnacle guest odds feed. The only module that talks to Pinnacle over HTTP.

Pinnacle publishes an unauthenticated read-only feed. SportyBet is bot-protected
and cannot be read programmatically, so Pinnacle stands in as the price source;
`pricing.py` converts sharp prices into soft-book equivalents.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
SOCCER_SPORT_ID = 29
# Pinnacle guest feed key (public, unauthenticated read-only). Override with PINNACLE_API_KEY.
_DEFAULT_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
CACHE_TTL_SECONDS = 90
REQUEST_TIMEOUT = 25

_CORNER_SUFFIXES = ("corners",)
_BOOKING_SUFFIXES = ("bookings", "cards")


class OddsUnavailable(RuntimeError):
    """Raised inside this module only. Callers should catch and degrade."""


@dataclass(frozen=True)
class PinnacleMatchup:
    id: int
    parent_id: int | None
    league: str
    home: str
    away: str
    start_time_utc: str
    kind: str  # main | corners | bookings | special
    special_description: str = ""
    participant_names: dict[int, str] = field(default_factory=dict)


def _api_key() -> str:
    return os.environ.get("PINNACLE_API_KEY", "").strip() or _DEFAULT_KEY


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-API-Key": _api_key(),
        "Accept": "application/json",
    }


_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _get(path: str) -> Any:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    try:
        r = requests.get(f"{BASE}{path}", headers=_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise OddsUnavailable(f"Pinnacle request failed: {e}") from e
    if r.status_code != 200:
        raise OddsUnavailable(f"Pinnacle returned {r.status_code} for {path}")
    try:
        data = r.json()
    except ValueError as e:
        raise OddsUnavailable(f"Pinnacle returned non-JSON for {path}") from e
    with _cache_lock:
        _cache[path] = (now, data)
    return data


def _classify(entry: dict) -> str:
    if entry.get("type") == "special":
        return "special"
    league = (entry.get("league") or {}).get("name", "").lower()
    if any(league.endswith(s) for s in _CORNER_SUFFIXES):
        return "corners"
    if any(league.endswith(s) for s in _BOOKING_SUFFIXES):
        return "bookings"
    return "main"


def parse_matchups(payload: list[dict]) -> list[PinnacleMatchup]:
    """Convert raw matchup entries into PinnacleMatchup, skipping malformed ones."""
    out: list[PinnacleMatchup] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        try:
            kind = _classify(entry)
            parts = entry.get("participants") or []
            names = {int(p["id"]): p.get("name", "") for p in parts if p.get("id") is not None}
            home = away = ""
            for p in parts:
                if p.get("alignment") == "home":
                    home = p.get("name", "")
                elif p.get("alignment") == "away":
                    away = p.get("name", "")
            if kind != "special" and not (home and away):
                continue
            out.append(
                PinnacleMatchup(
                    id=int(entry["id"]),
                    parent_id=int(entry["parentId"]) if entry.get("parentId") else None,
                    league=(entry.get("league") or {}).get("name", ""),
                    home=home,
                    away=away,
                    start_time_utc=entry.get("startTime", ""),
                    kind=kind,
                    special_description=(entry.get("special") or {}).get("description", ""),
                    participant_names=names,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def list_matchups() -> list[PinnacleMatchup]:
    payload = _get(f"/sports/{SOCCER_SPORT_ID}/matchups?withSpecials=false&brandId=0")
    return parse_matchups(payload)


def related(matchup_id: int) -> list[PinnacleMatchup]:
    """Corners, bookings, and special matchups hanging off a main fixture."""
    return parse_matchups(_get(f"/matchups/{matchup_id}/related"))


def straight_markets(matchup_id: int) -> list[dict]:
    """Markets for this matchup and every related matchup, keyed by matchupId."""
    payload = _get(f"/matchups/{matchup_id}/markets/related/straight?primaryOnly=false")
    return payload if isinstance(payload, list) else []


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
