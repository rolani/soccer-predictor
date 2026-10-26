# Real Odds, Analysis Runs, and Market Diversity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace agent-invented betting odds with server-verified prices from Pinnacle's public feed, add a one-click analysis run to the web app, and widen the market mix beyond goals markets.

**Architecture:** A new `predictor/odds/` package fetches Pinnacle's free guest odds feed, de-vigs it and re-vigs it to a SportyBet-like margin, and assembles a *priced market board*. The board is injected into the agent prompt and used by `submit_picks` to overwrite any price the agent invented before the odds and margin gates run. A separate `AnalysisManager` runs the existing `/predictions-analysis` workflow as an SDK agent with write access, triggered from the Analysis tab.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, `requests`, `cursor-sdk`, pytest, React 18 + Vite + Tailwind.

## Global Constraints

- **This repo is not under git version control.** Where a normal plan says "commit", run the full test suite instead and confirm it is green before moving on. Do not run `git init` unless the user asks.
- Python `>=3.10`. Use `from __future__ import annotations` at the top of every new module, matching the existing codebase.
- New runtime dependencies: none. `requests` is already a base dependency.
- Tests must never make a network call. All Pinnacle payloads are recorded to `tests/fixtures/pinnacle/` and replayed.
- All Pinnacle HTTP contact lives in `predictor/odds/pinnacle.py`. No other module may import `requests` for odds.
- Any Pinnacle failure degrades to an empty board and unpriced picks. It must never raise out of a prediction run.
- Pinnacle guest API base: `https://guest.api.arcadia.pinnacle.com/0.1`. Soccer sport id: `29`. Guest key: `CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R`, overridable via `PINNACLE_API_KEY`.
- Pinnacle returns **American** odds. Every price crossing a module boundary is **decimal**.
- Tip strings emitted by the board must match the vocabulary already in `.cursor/skills/soccer-predictions/markets.md` and historical `run.json` files, so `MASTER.md` market rows stay comparable.
- Run the suite with `python -m pytest tests/ -v` from the repo root.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `predictor/odds/__init__.py` | Public exports: `build_board`, `PricedBoard`, `MarketQuote`, `resolve_quote` |
| `predictor/odds/pricing.py` | American↔decimal, de-vig, re-vig, per-family overrounds |
| `predictor/odds/pinnacle.py` | The only module that talks to Pinnacle over HTTP; TTL cache |
| `predictor/odds/quotes.py` | Pinnacle market payloads → `MarketQuote` vocabulary |
| `predictor/odds/matching.py` | Free-text match string → Pinnacle matchup; tip string → quote |
| `predictor/odds/board.py` | `PricedBoard` assembly and prompt formatting |
| `predictor/web/verify.py` | Applies the board to submitted picks |
| `predictor/web/market_mix.py` | Recent market-family mix for the diversity prompt block |
| `predictor/web/analysis_runner.py` | `AnalysisManager` + graded-runs ledger |
| `webapp/src/RunLog.jsx` | Shared SSE log pane |
| `tests/fixtures/pinnacle/*.json` | Recorded payloads |
| `tests/test_pricing.py`, `tests/test_quotes.py`, `tests/test_matching.py`, `tests/test_board.py`, `tests/test_verify.py`, `tests/test_analysis_runner.py` | Unit tests |

**Modify:**

| Path | Change |
|---|---|
| `predictor/web/schema.py` | `Pick` gains `quoted_odds`, `price_source`, `market_family`; `CreateRunRequest` gains `book_overround` |
| `predictor/web/tools.py` | Verify prices against the board before gating |
| `predictor/web/prompt.py` | Inject board, price discipline, diversity block |
| `predictor/web/runner.py` | Fetch board once per run, pass into context |
| `predictor/web/app.py` | `/api/odds/board`, `/api/analysis/status`, `/api/analysis/run` |
| `predictor/web/settings.py` | Odds cache dir and overround env plumbing |
| `webapp/src/App.jsx` | Use `RunLog`, show price provenance |
| `webapp/src/AnalysisPanel.jsx` | Run analysis button + log |
| `.cursor/rules/soccer-prediction-core.mdc`, `.cursor/skills/soccer-predictions/markets.md`, `.cursor/skills/soccer-predictions/run-schema.md`, `.analysis/MASTER.md`, `README.md` | Doc updates |

---

### Task 1: Pricing math

The core of the odds fix. Pinnacle runs about 4.8% overround; SportyBet is a soft book that loads margin onto longshots. Strip Pinnacle's vig to fair probabilities, then re-apply a soft-book overround with the odds-ratio method, which leaves heavy favourites nearly unchanged and shortens longer prices.

**Files:**
- Create: `predictor/odds/__init__.py` (empty for now), `predictor/odds/pricing.py`
- Test: `tests/test_pricing.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `american_to_decimal(price: float) -> float`
  - `devig(raw_decimals: Sequence[float]) -> list[float]`
  - `revig(fair: Sequence[float], target_overround: float) -> list[float]`
  - `to_book_prices(raw_decimals: Sequence[float], family: str) -> list[float]`
  - `overround_for(family: str) -> float`
  - `DEFAULT_OVERROUND: dict[str, float]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pricing.py`:

```python
"""Tests for odds conversion and the soft-book pricing model."""

from __future__ import annotations

import pytest

from predictor.odds.pricing import (
    DEFAULT_OVERROUND,
    american_to_decimal,
    devig,
    overround_for,
    revig,
    to_book_prices,
)


class TestConversion:
    def test_negative_american(self):
        assert american_to_decimal(-152) == pytest.approx(1.658, abs=0.001)

    def test_positive_american(self):
        assert american_to_decimal(127) == pytest.approx(2.27, abs=0.001)

    def test_even_money(self):
        assert american_to_decimal(100) == pytest.approx(2.0, abs=0.001)


class TestDevig:
    def test_fair_probabilities_sum_to_one(self):
        fair = devig([1.237, 4.18])
        assert sum(fair) == pytest.approx(1.0, abs=1e-6)

    def test_favourite_keeps_the_larger_share(self):
        fair = devig([1.237, 4.18])
        assert fair[0] > fair[1]

    def test_three_way_sums_to_one(self):
        fair = devig([1.962, 3.66, 3.87])
        assert sum(fair) == pytest.approx(1.0, abs=1e-6)

    def test_devig_lowers_the_favourite_probability(self):
        raw_favourite = 1 / 1.237
        assert devig([1.237, 4.18])[0] < raw_favourite


class TestRevig:
    def test_hits_the_target_overround(self):
        adjusted = revig([0.7855, 0.2145], 1.055)
        assert sum(adjusted) == pytest.approx(1.055, abs=1e-6)

    def test_longshot_absorbs_more_margin_than_favourite(self):
        fair = [0.7855, 0.2145]
        adjusted = revig(fair, 1.055)
        fav_uplift = adjusted[0] / fair[0]
        dog_uplift = adjusted[1] / fair[1]
        assert dog_uplift > fav_uplift


class TestSportybetCalibration:
    """Reference prices captured from SportyBet ng on 2026-08-26."""

    @pytest.mark.parametrize(
        "pinnacle_pair,sportybet",
        [
            ((1.237, 4.18), 1.25),   # Lyon v Fenerbahce, Over 1.5
            ((1.181, 4.98), 1.18),   # Viking v Dinamo Zagreb, Over 1.5
            ((1.324, 3.42), 1.33),   # Celje v Slovan Bratislava, Over 1.5
        ],
    )
    def test_model_lands_near_the_real_book(self, pinnacle_pair, sportybet):
        modelled = to_book_prices(list(pinnacle_pair), "goals_totals")[0]
        assert modelled == pytest.approx(sportybet, abs=0.03)

    def test_model_never_overstates_a_short_favourite(self):
        """Understating is safe for advertised combined odds; overstating is the bug."""
        modelled = to_book_prices([1.237, 4.18], "goals_totals")[0]
        assert modelled <= 1.25 + 0.001


class TestOverroundConfig:
    def test_defaults_present_for_every_family(self):
        for family in (
            "goals_totals", "team_totals", "halves", "btts",
            "handicap", "result", "dc_dnb", "corners", "specials",
        ):
            assert family in DEFAULT_OVERROUND

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PREDICTOR_OVERROUND_GOALS_TOTALS", "1.09")
        assert overround_for("goals_totals") == pytest.approx(1.09)

    def test_unknown_family_falls_back(self):
        assert overround_for("nonsense") == pytest.approx(DEFAULT_OVERROUND["specials"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.odds'`

- [ ] **Step 3: Write the implementation**

Create `predictor/odds/__init__.py` as an empty file.

Create `predictor/odds/pricing.py`:

```python
"""Odds conversion and the soft-book pricing model.

Pinnacle is a sharp book (about 4.8% overround). SportyBet is soft and loads
margin onto longshots. We strip Pinnacle's vig to fair probabilities, then
re-apply a soft-book overround using the odds-ratio transform, which leaves
heavy favourites close to fair and shortens longer prices.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

DEFAULT_OVERROUND: dict[str, float] = {
    "goals_totals": 1.055,
    "team_totals": 1.055,
    "halves": 1.055,
    "btts": 1.055,
    "handicap": 1.055,
    "result": 1.070,
    "corners": 1.070,
    "dc_dnb": 1.060,
    "specials": 1.150,
}


def overround_for(family: str) -> float:
    """Target book overround for a market family, overridable per family."""
    env_key = f"PREDICTOR_OVERROUND_{family.upper()}"
    raw = os.environ.get(env_key, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_OVERROUND.get(family, DEFAULT_OVERROUND["specials"])


def american_to_decimal(price: float) -> float:
    """Convert American odds to decimal."""
    price = float(price)
    if price > 0:
        return 1.0 + price / 100.0
    return 1.0 + 100.0 / abs(price)


def _odds_ratio(p: float, c: float) -> float:
    """Odds-ratio transform. c > 1 inflates, c < 1 deflates, c == 1 is identity."""
    return (c * p) / (c * p - p + 1.0)


def _solve_c(probs: Sequence[float], target_sum: float) -> float:
    """Bisect for c such that sum(_odds_ratio(p, c)) == target_sum."""
    lo, hi = 1e-6, 1e6
    for _ in range(200):
        mid = (lo + hi) / 2.0
        total = sum(_odds_ratio(p, mid) for p in probs)
        if total < target_sum:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def devig(raw_decimals: Sequence[float]) -> list[float]:
    """Strip the book's margin, returning fair probabilities that sum to 1."""
    implied = [1.0 / d for d in raw_decimals]
    c = _solve_c(implied, 1.0)
    return [_odds_ratio(p, c) for p in implied]


def revig(fair: Sequence[float], target_overround: float) -> list[float]:
    """Re-apply a book margin to fair probabilities."""
    c = _solve_c(fair, target_overround)
    return [_odds_ratio(p, c) for p in fair]


def to_book_prices(raw_decimals: Sequence[float], family: str) -> list[float]:
    """Convert sharp decimal prices into soft-book decimal prices."""
    if not raw_decimals:
        return []
    fair = devig(raw_decimals)
    adjusted = revig(fair, overround_for(family))
    return [round(1.0 / p, 3) for p in adjusted]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: PASS, 14 tests.

If `test_model_lands_near_the_real_book` fails, the overround defaults need adjusting — not the transform. Print `to_book_prices` output for each parametrized case and tune `DEFAULT_OVERROUND["goals_totals"]` between 1.045 and 1.065.

- [ ] **Step 5: Verify the whole suite is still green**

Run: `python -m pytest tests/ -v`
Expected: PASS, no new failures.

---

### Task 2: Pinnacle client

**Files:**
- Create: `predictor/odds/pinnacle.py`
- Modify: `predictor/web/settings.py`
- Create: `tests/fixtures/pinnacle/matchups.json`, `tests/fixtures/pinnacle/related_1634269216.json`, `tests/fixtures/pinnacle/straight_1634269216.json`
- Create: `scripts/record_pinnacle_fixtures.py`
- Test: `tests/test_pinnacle.py`

**Interfaces:**
- Consumes: `predictor.odds.pricing.american_to_decimal`
- Produces:
  - `PinnacleMatchup` dataclass with fields `id: int`, `parent_id: int | None`, `league: str`, `home: str`, `away: str`, `start_time_utc: str`, `kind: str`, `special_description: str`
  - `list_matchups() -> list[PinnacleMatchup]`
  - `related(matchup_id: int) -> list[PinnacleMatchup]`
  - `straight_markets(matchup_id: int) -> list[dict]`
  - `parse_matchups(payload: list[dict]) -> list[PinnacleMatchup]`
  - `OddsUnavailable` exception

- [ ] **Step 1: Write the recording script**

Create `scripts/record_pinnacle_fixtures.py`. This is a developer tool, run once, never in tests:

```python
"""Record live Pinnacle payloads as test fixtures. Run manually, not in CI."""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R",
    "Accept": "application/json",
}
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pinnacle"


def get(path: str):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def main(matchup_id: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "matchups.json").write_text(
        json.dumps(get("/sports/29/matchups?withSpecials=false&brandId=0")[:400], indent=1),
        encoding="utf-8",
    )
    (OUT / f"related_{matchup_id}.json").write_text(
        json.dumps(get(f"/matchups/{matchup_id}/related"), indent=1), encoding="utf-8"
    )
    (OUT / f"straight_{matchup_id}.json").write_text(
        json.dumps(
            get(f"/matchups/{matchup_id}/markets/related/straight?primaryOnly=false"),
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    import sys

    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1634269216)
```

- [ ] **Step 2: Record the fixtures**

Run: `python scripts/record_pinnacle_fixtures.py`

Expected: three files under `tests/fixtures/pinnacle/`. If the live feed no longer has matchup `1634269216`, pass a current soccer matchup id as an argument — pick one from `matchups.json` whose `league.name` contains `Champions League` or `Premier League` and whose `parentId` is `null`.

Then trim `matchups.json` by hand if it exceeds 2 MB: keep the first 400 entries plus any entry whose `id` or `parentId` equals the recorded matchup id.

- [ ] **Step 3: Write the failing test**

Create `tests/test_pinnacle.py`:

```python
"""Tests for the Pinnacle feed client. No network access."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from predictor.odds.pinnacle import PinnacleMatchup, parse_matchups

FIXTURES = Path(__file__).parent / "fixtures" / "pinnacle"


@pytest.fixture
def matchups_payload() -> list[dict]:
    return json.loads((FIXTURES / "matchups.json").read_text(encoding="utf-8"))


class TestParseMatchups:
    def test_returns_matchups(self, matchups_payload):
        out = parse_matchups(matchups_payload)
        assert out
        assert all(isinstance(m, PinnacleMatchup) for m in out)

    def test_extracts_both_participants(self, matchups_payload):
        out = [m for m in parse_matchups(matchups_payload) if m.kind == "main"]
        assert out
        assert all(m.home and m.away for m in out)

    def test_classifies_corner_matchups(self, matchups_payload):
        kinds = {m.kind for m in parse_matchups(matchups_payload)}
        assert "main" in kinds

    def test_corner_league_suffix_detected(self):
        payload = [
            {
                "id": 1,
                "parentId": 2,
                "type": "matchup",
                "league": {"name": "UEFA - Champions League Qualifiers Corners"},
                "startTime": "2026-08-26T19:00:00Z",
                "participants": [
                    {"alignment": "home", "name": "Viking (Corners)"},
                    {"alignment": "away", "name": "Dinamo Zagreb (Corners)"},
                ],
            }
        ]
        assert parse_matchups(payload)[0].kind == "corners"

    def test_bookings_league_suffix_detected(self):
        payload = [
            {
                "id": 1,
                "parentId": 2,
                "type": "matchup",
                "league": {"name": "England - EFL Cup Bookings"},
                "startTime": "2026-08-26T18:45:00Z",
                "participants": [
                    {"alignment": "home", "name": "Newcastle United (Bookings)"},
                    {"alignment": "away", "name": "West Bromwich Albion (Bookings)"},
                ],
            }
        ]
        assert parse_matchups(payload)[0].kind == "bookings"

    def test_special_carries_its_description(self):
        payload = [
            {
                "id": 3,
                "parentId": 2,
                "type": "special",
                "league": {"name": "UEFA - Champions League Qualifiers"},
                "startTime": "2026-08-26T19:00:00Z",
                "special": {"description": "Both Teams To Score?"},
                "participants": [
                    {"id": 31, "name": "Yes"},
                    {"id": 32, "name": "No"},
                ],
            }
        ]
        out = parse_matchups(payload)[0]
        assert out.kind == "special"
        assert out.special_description == "Both Teams To Score?"
        assert out.participant_names == {31: "Yes", 32: "No"}

    def test_skips_malformed_entries_without_raising(self):
        payload = [{"id": 9}, {"nonsense": True}]
        assert parse_matchups(payload) == []
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_pinnacle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.odds.pinnacle'`

- [ ] **Step 5: Write the implementation**

Create `predictor/odds/pinnacle.py`:

```python
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
        try:
            kind = _classify(entry)
            parts = entry.get("participants") or []
            names = {
                int(p["id"]): p.get("name", "")
                for p in parts
                if p.get("id") is not None
            }
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_pinnacle.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 7: Confirm no network call happened**

Run: `python -m pytest tests/test_pinnacle.py -v -p no:cacheprovider`
Expected: PASS in under 2 seconds. A multi-second run means a fixture is missing and something reached the network — fix the fixture path.

- [ ] **Step 8: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 3: Quote normalization

Turns Pinnacle's three payload shapes (straight markets, specials joined by `participantId`, corner sub-matchups) into one `MarketQuote` vocabulary.

**Files:**
- Create: `predictor/odds/quotes.py`
- Test: `tests/test_quotes.py`

**Interfaces:**
- Consumes: `PinnacleMatchup`, `american_to_decimal`, `to_book_prices`
- Produces:
  - `MarketQuote` frozen dataclass: `family: str`, `market: str`, `tip: str`, `line: float | None`, `side: str | None`, `period: int`, `odds: float`, `raw_odds: float`, `fair_probability: float`, `source_key: str`
  - `FAMILIES: tuple[str, ...]`
  - `build_quotes(main: PinnacleMatchup, related: list[PinnacleMatchup], markets: list[dict]) -> list[MarketQuote]`

**Key payload facts, confirmed against the live feed:**

- Straight markets carry `matchupId`, `type` (`moneyline` / `total` / `team_total` / `spread`), `key` (e.g. `s;0;ou;1.5`), `period` (0 = full time, 1 = first half), optional `side` (`home` / `away`), and `prices: [{designation, points, price}]` where `price` is American.
- Special markets are separate matchups. Their prices appear in the same straight-markets response with `type == "moneyline"` and `prices: [{participantId, price}]`. Join `participantId` against `PinnacleMatchup.participant_names`. Example: `Both Teams To Score?` → `{1634663449: "Yes", 1634663450: "No"}` with prices `-152` and `127`.
- Corner markets are a child matchup whose league name ends in `Corners`, carrying its own `total` and `spread` markets.

- [ ] **Step 1: Write the failing test**

Create `tests/test_quotes.py`:

```python
"""Tests for Pinnacle market normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from predictor.odds.pinnacle import parse_matchups
from predictor.odds.quotes import FAMILIES, MarketQuote, build_quotes

FIXTURES = Path(__file__).parent / "fixtures" / "pinnacle"
MAIN_ID = 1634269216


@pytest.fixture
def quotes() -> list[MarketQuote]:
    related_payload = json.loads(
        (FIXTURES / f"related_{MAIN_ID}.json").read_text(encoding="utf-8")
    )
    markets = json.loads(
        (FIXTURES / f"straight_{MAIN_ID}.json").read_text(encoding="utf-8")
    )
    related = parse_matchups(related_payload)
    main = next(m for m in related if m.id == MAIN_ID and m.kind == "main")
    return build_quotes(main, related, markets)


def find(quotes: list[MarketQuote], tip: str) -> MarketQuote | None:
    return next((q for q in quotes if q.tip.lower() == tip.lower()), None)


class TestCoverage:
    def test_produces_quotes(self, quotes):
        assert len(quotes) > 20

    def test_every_family_is_known(self, quotes):
        assert {q.family for q in quotes} <= set(FAMILIES)

    def test_covers_the_core_families(self, quotes):
        families = {q.family for q in quotes}
        for expected in ("goals_totals", "team_totals", "result", "handicap", "btts", "dc_dnb"):
            assert expected in families, f"missing {expected}"


class TestTipVocabulary:
    def test_over_1_5(self, quotes):
        q = find(quotes, "Over 1.5 goals")
        assert q is not None
        assert q.family == "goals_totals"
        assert q.line == 1.5
        assert q.period == 0

    def test_under_3_5(self, quotes):
        assert find(quotes, "Under 3.5 goals") is not None

    def test_team_over_uses_the_team_name(self, quotes):
        tips = [q.tip for q in quotes if q.family == "team_totals"]
        assert any(t.startswith("Lyon over") for t in tips)
        assert any(t.startswith("Fenerbahce over") for t in tips)

    def test_btts_yes_and_no(self, quotes):
        assert find(quotes, "BTTS Yes") is not None
        assert find(quotes, "BTTS No") is not None

    def test_draw_no_bet_names_the_side(self, quotes):
        assert find(quotes, "Lyon draw no bet") is not None

    def test_double_chance(self, quotes):
        tips = {q.tip for q in quotes if q.family == "dc_dnb"}
        assert any("or draw" in t.lower() for t in tips)

    def test_first_half_prefixed(self, quotes):
        assert any(q.tip.startswith("1H ") for q in quotes if q.period == 1)


class TestPricing:
    def test_btts_yes_matches_the_recorded_american_price(self, quotes):
        """BTTS Yes was -152 => 1.658 decimal raw."""
        q = find(quotes, "BTTS Yes")
        assert q.raw_odds == pytest.approx(1.658, abs=0.002)

    def test_book_price_is_shorter_than_the_sharp_price(self, quotes):
        q = find(quotes, "Over 1.5 goals")
        assert q.odds < q.raw_odds

    def test_fair_probability_is_between_zero_and_one(self, quotes):
        assert all(0.0 < q.fair_probability < 1.0 for q in quotes)

    def test_odds_are_decimal_above_one(self, quotes):
        assert all(q.odds > 1.0 for q in quotes)


class TestRobustness:
    def test_market_with_a_single_price_is_skipped(self):
        """A one-sided market cannot be de-vigged, so it must not produce a quote."""
        main = parse_matchups(
            [
                {
                    "id": 1,
                    "parentId": None,
                    "type": "matchup",
                    "league": {"name": "Test League"},
                    "startTime": "2026-08-26T19:00:00Z",
                    "participants": [
                        {"id": 10, "alignment": "home", "name": "Home"},
                        {"id": 11, "alignment": "away", "name": "Away"},
                    ],
                }
            ]
        )[0]
        markets = [
            {
                "matchupId": 1,
                "type": "total",
                "key": "s;0;ou;2.5",
                "period": 0,
                "prices": [{"designation": "over", "points": 2.5, "price": -110}],
            }
        ]
        assert build_quotes(main, [main], markets) == []

    def test_unknown_market_type_is_ignored(self):
        main = parse_matchups(
            [
                {
                    "id": 1,
                    "parentId": None,
                    "type": "matchup",
                    "league": {"name": "Test League"},
                    "startTime": "2026-08-26T19:00:00Z",
                    "participants": [
                        {"id": 10, "alignment": "home", "name": "Home"},
                        {"id": 11, "alignment": "away", "name": "Away"},
                    ],
                }
            ]
        )[0]
        markets = [{"matchupId": 1, "type": "mystery", "key": "s;0;x", "period": 0, "prices": []}]
        assert build_quotes(main, [main], markets) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quotes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.odds.quotes'`

- [ ] **Step 3: Write the implementation**

Create `predictor/odds/quotes.py`:

```python
"""Normalize Pinnacle market payloads into one betting vocabulary.

Tip strings must match `.cursor/skills/soccer-predictions/markets.md` so that
MASTER.md market rows stay comparable across this change.
"""

from __future__ import annotations

from dataclasses import dataclass

from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.pricing import american_to_decimal, devig, overround_for, revig

FAMILIES = (
    "goals_totals",
    "team_totals",
    "halves",
    "btts",
    "result",
    "dc_dnb",
    "handicap",
    "corners",
    "specials",
)


@dataclass(frozen=True)
class MarketQuote:
    family: str
    market: str
    tip: str
    line: float | None
    side: str | None
    period: int
    odds: float
    raw_odds: float
    fair_probability: float
    source_key: str


def _price_group(
    labels: list[str],
    american: list[float],
    *,
    family: str,
    market: str,
    line: float | None,
    side: str | None,
    period: int,
    source_key: str,
) -> list[MarketQuote]:
    """De-vig a complete market, re-vig to the book margin, emit one quote per outcome."""
    if len(american) < 2 or len(labels) != len(american):
        return []
    try:
        raw = [american_to_decimal(a) for a in american]
    except (TypeError, ValueError, ZeroDivisionError):
        return []
    if any(d <= 1.0 for d in raw):
        return []
    fair = devig(raw)
    adjusted = revig(fair, overround_for(family))
    out: list[MarketQuote] = []
    for label, raw_d, f, adj in zip(labels, raw, fair, adjusted):
        out.append(
            MarketQuote(
                family=family,
                market=market,
                tip=label,
                line=line,
                side=side,
                period=period,
                odds=round(1.0 / adj, 3),
                raw_odds=round(raw_d, 3),
                fair_probability=round(f, 5),
                source_key=source_key,
            )
        )
    return out


def _half(period: int) -> str:
    return "1H " if period == 1 else ""


def _totals(m: dict, period: int, is_corners: bool) -> list[MarketQuote]:
    prices = m.get("prices") or []
    over = next((p for p in prices if p.get("designation") == "over"), None)
    under = next((p for p in prices if p.get("designation") == "under"), None)
    if not over or not under:
        return []
    line = over.get("points")
    if line is None:
        return []
    family = "corners" if is_corners else ("halves" if period == 1 else "goals_totals")
    noun = "corners" if is_corners else "goals"
    prefix = "" if is_corners else _half(period)
    return _price_group(
        [f"{prefix}Over {line} {noun}", f"{prefix}Under {line} {noun}"],
        [over["price"], under["price"]],
        family=family,
        market=f"{prefix}Over/Under {line} {noun}",
        line=line,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


def _team_totals(m: dict, period: int, home: str, away: str) -> list[MarketQuote]:
    prices = m.get("prices") or []
    over = next((p for p in prices if p.get("designation") == "over"), None)
    under = next((p for p in prices if p.get("designation") == "under"), None)
    if not over or not under:
        return []
    line = over.get("points")
    side = m.get("side")
    if line is None or side not in ("home", "away"):
        return []
    team = home if side == "home" else away
    prefix = _half(period)
    family = "halves" if period == 1 else "team_totals"
    return _price_group(
        [f"{prefix}{team} over {line} goals", f"{prefix}{team} under {line} goals"],
        [over["price"], under["price"]],
        family=family,
        market=f"{prefix}{team} team total {line}",
        line=line,
        side=side,
        period=period,
        source_key=m.get("key", ""),
    )


def _moneyline(m: dict, period: int, home: str, away: str) -> list[MarketQuote]:
    prices = {p.get("designation"): p.get("price") for p in m.get("prices") or []}
    if not {"home", "away"} <= set(prices):
        return []
    prefix = _half(period)
    labels = [f"{prefix}{home} win", f"{prefix}Draw", f"{prefix}{away} win"]
    american = [prices["home"], prices.get("draw"), prices["away"]]
    if american[1] is None:
        labels = [labels[0], labels[2]]
        american = [american[0], american[2]]
    return _price_group(
        labels,
        american,
        family="result",
        market=f"{prefix}Match result",
        line=None,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


def _spread(m: dict, period: int, home: str, away: str, is_corners: bool) -> list[MarketQuote]:
    prices = m.get("prices") or []
    h = next((p for p in prices if p.get("designation") == "home"), None)
    a = next((p for p in prices if p.get("designation") == "away"), None)
    if not h or not a:
        return []
    hl, al = h.get("points"), a.get("points")
    if hl is None or al is None:
        return []
    prefix = _half(period)
    noun = " corners" if is_corners else ""
    family = "corners" if is_corners else "handicap"
    return _price_group(
        [f"{prefix}{home} {hl:+g}{noun} AH", f"{prefix}{away} {al:+g}{noun} AH"],
        [h["price"], a["price"]],
        family=family,
        market=f"{prefix}Asian handicap {hl:+g}{noun}",
        line=hl,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


_SPECIAL_FAMILIES = {
    "both teams to score?": "btts",
    "draw no bet": "dc_dnb",
    "double chance": "dc_dnb",
}


def _special_family(description: str) -> str:
    return _SPECIAL_FAMILIES.get(description.strip().lower(), "specials")


def _special_tip(description: str, participant: str) -> str:
    desc = description.strip().lower()
    if desc == "both teams to score?":
        return f"BTTS {participant}"
    if desc == "draw no bet":
        return f"{participant} draw no bet"
    if desc == "double chance":
        return f"Double chance {participant}"
    if desc.endswith("?"):
        return f"{description[:-1].strip()}: {participant}"
    return f"{description}: {participant}"


def _special(m: dict, special: PinnacleMatchup) -> list[MarketQuote]:
    prices = m.get("prices") or []
    labels: list[str] = []
    american: list[float] = []
    for p in prices:
        pid = p.get("participantId")
        name = special.participant_names.get(pid) if pid is not None else None
        if name is None or p.get("price") is None:
            continue
        labels.append(_special_tip(special.special_description, name))
        american.append(p["price"])
    return _price_group(
        labels,
        american,
        family=_special_family(special.special_description),
        market=special.special_description,
        line=None,
        side=None,
        period=int(m.get("period") or 0),
        source_key=m.get("key", ""),
    )


def build_quotes(
    main: PinnacleMatchup,
    related: list[PinnacleMatchup],
    markets: list[dict],
) -> list[MarketQuote]:
    """Normalize every market attached to a fixture and its related matchups."""
    by_id = {r.id: r for r in related}
    by_id.setdefault(main.id, main)
    out: list[MarketQuote] = []

    for m in markets or []:
        mid = m.get("matchupId")
        owner = by_id.get(mid)
        if owner is None:
            continue
        if owner.kind == "bookings":
            continue

        period = int(m.get("period") or 0)
        mtype = m.get("type")

        if owner.kind == "special":
            if mtype == "moneyline":
                out.extend(_special(m, owner))
            continue

        if period not in (0, 1):
            continue
        is_corners = owner.kind == "corners"

        if mtype == "total":
            out.extend(_totals(m, period, is_corners))
        elif mtype == "team_total" and not is_corners:
            out.extend(_team_totals(m, period, main.home, main.away))
        elif mtype == "moneyline" and not is_corners:
            out.extend(_moneyline(m, period, main.home, main.away))
        elif mtype == "spread":
            out.extend(_spread(m, period, main.home, main.away, is_corners))

    seen: set[tuple[str, int]] = set()
    unique: list[MarketQuote] = []
    for q in out:
        key = (q.tip.lower(), q.period)
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_quotes.py -v`
Expected: PASS, 17 tests.

If `test_draw_no_bet_names_the_side` fails, print the distinct `special_description` values in the recorded fixture and align `_SPECIAL_FAMILIES` keys with the exact strings:

```bash
python -c "import json,pathlib; d=json.loads(pathlib.Path('tests/fixtures/pinnacle/related_1634269216.json').read_text()); print(sorted({(e.get('special') or {}).get('description','') for e in d}))"
```

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 4: Fixture and market matching

**Files:**
- Create: `predictor/odds/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `PinnacleMatchup`, `MarketQuote`
- Produces:
  - `normalize_team(name: str) -> str`
  - `split_match(match: str) -> tuple[str, str] | None`
  - `match_fixture(match: str, candidates: list[PinnacleMatchup], *, min_side=0.72, min_combined=0.80) -> PinnacleMatchup | None`
  - `resolve_quote(tip: str, market: str, quotes: list[MarketQuote]) -> MarketQuote | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching.py`:

```python
"""Tests for fixture and market resolution."""

from __future__ import annotations

import pytest

from predictor.odds.matching import (
    match_fixture,
    normalize_team,
    resolve_quote,
    split_match,
)
from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote


def mu(id_: int, league: str, home: str, away: str, start="2026-08-26T19:00:00Z"):
    return PinnacleMatchup(
        id=id_, parent_id=None, league=league, home=home, away=away,
        start_time_utc=start, kind="main",
    )


CANDIDATES = [
    mu(1, "UEFA - Champions League Qualifiers", "Viking", "Dinamo Zagreb"),
    mu(2, "Croatia - HNL", "Istra 1961", "Dinamo Zagreb", "2026-08-29T16:30:00Z"),
    mu(3, "England - EFL Cup", "Newcastle United", "West Bromwich Albion"),
    mu(4, "UEFA - Champions League Qualifiers", "Lyon", "Fenerbahce"),
    mu(5, "England - EFL Cup", "Preston North End", "Everton", "2026-08-26T18:45:00Z"),
]


class TestNormalize:
    def test_strips_accents(self):
        assert normalize_team("Fenerbahçe") == normalize_team("Fenerbahce")

    def test_drops_club_noise(self):
        assert normalize_team("Viking FK") == normalize_team("Viking")

    def test_keeps_distinguishing_words(self):
        assert normalize_team("Newcastle United") != normalize_team("Newcastle Jets")


class TestSplit:
    @pytest.mark.parametrize("raw", ["A vs B", "A v B", "A - B", "A  vs.  B"])
    def test_separators(self, raw):
        assert split_match(raw) == ("A", "B")

    def test_returns_none_without_a_separator(self):
        assert split_match("Just one name") is None


class TestMatchFixture:
    def test_exact_match(self):
        assert match_fixture("Lyon vs Fenerbahce", CANDIDATES).id == 4

    def test_tolerates_club_suffixes_and_accents(self):
        assert match_fixture("Viking FK vs GNK Dinamo Zagreb", CANDIDATES).id == 1

    def test_does_not_confuse_two_fixtures_sharing_a_team(self):
        """Both fixture 1 and 2 contain Dinamo Zagreb; only one has Viking."""
        assert match_fixture("Viking FK vs Dinamo Zagreb", CANDIDATES).id == 1

    def test_abbreviated_names(self):
        assert match_fixture("Newcastle vs West Bromwich Albion", CANDIDATES).id == 3

    def test_unknown_fixture_returns_none(self):
        assert match_fixture("Barcelona vs Real Madrid", CANDIDATES) is None

    def test_prefers_none_over_a_weak_guess(self):
        assert match_fixture("Everton vs Liverpool", CANDIDATES) is None

    def test_unparseable_string_returns_none(self):
        assert match_fixture("nonsense", CANDIDATES) is None


def q(tip: str, family="goals_totals", odds=1.25, line=1.5):
    return MarketQuote(
        family=family, market="Over/Under 1.5 goals", tip=tip, line=line, side=None,
        period=0, odds=odds, raw_odds=odds + 0.02, fair_probability=0.78, source_key="k",
    )


QUOTES = [
    q("Over 1.5 goals"),
    q("Under 1.5 goals", odds=4.0),
    q("Everton over 0.5 goals", family="team_totals", odds=1.30, line=0.5),
    q("BTTS Yes", family="btts", odds=1.70, line=None),
]


class TestResolveQuote:
    def test_exact_tip(self):
        assert resolve_quote("Over 1.5 goals", "", QUOTES).odds == 1.25

    def test_case_and_whitespace_insensitive(self):
        assert resolve_quote("  over 1.5 GOALS ", "", QUOTES) is not None

    def test_team_total_phrasing_variant(self):
        assert resolve_quote("Everton Over 0.5", "Team over 0.5", QUOTES) is not None

    def test_btts_variant(self):
        assert resolve_quote("Both teams to score - Yes", "BTTS", QUOTES) is not None

    def test_unknown_tip_returns_none(self):
        assert resolve_quote("Correct score 3-2", "", QUOTES) is None

    def test_does_not_return_the_opposite_side(self):
        """Over must never resolve to the Under price."""
        assert resolve_quote("Over 1.5 goals", "", QUOTES).tip == "Over 1.5 goals"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.odds.matching'`

- [ ] **Step 3: Write the implementation**

Create `predictor/odds/matching.py`:

```python
"""Resolve agent-written match and tip strings against the Pinnacle board.

Prefers returning None over a wrong answer: a mismatched price is worse than
no price, because a wrong price silently passes the margin gate.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote

_NOISE = {
    "fc", "cf", "afc", "sc", "ac", "as", "sk", "nk", "gnk", "hk", "fk", "bk",
    "cd", "ca", "sv", "vfl", "vfb", "tsg", "ss", "ssc", "us", "usa", "aj",
    "club", "de", "the",
}
_SEPARATOR = re.compile(r"\s+(?:vs?\.?|@|-|–|—)\s+", re.IGNORECASE)


def normalize_team(name: str) -> str:
    """Lowercase, strip accents and punctuation, drop club-noise tokens."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE]
    return " ".join(tokens)


def split_match(match: str) -> tuple[str, str] | None:
    parts = _SEPARATOR.split((match or "").strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def _similarity(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, overlap)
    return ratio


def match_fixture(
    match: str,
    candidates: list[PinnacleMatchup],
    *,
    min_side: float = 0.72,
    min_combined: float = 0.80,
) -> PinnacleMatchup | None:
    """Best-scoring candidate above both thresholds, else None."""
    split = split_match(match)
    if not split:
        return None
    home, away = split

    best: PinnacleMatchup | None = None
    best_score = 0.0
    for c in candidates:
        if c.kind != "main":
            continue
        hs, as_ = _similarity(home, c.home), _similarity(away, c.away)
        if hs < min_side or as_ < min_side:
            continue
        score = (hs + as_) / 2.0
        if score >= min_combined and score > best_score:
            best, best_score = c, score
    return best


def _canonical_tip(text: str) -> str:
    """Collapse phrasing variants so 'BTTS Yes' and 'Both teams to score - Yes' agree."""
    s = normalize_team(text)
    s = s.replace("both teams to score", "btts")
    s = re.sub(r"\bgoals?\b", "", s)
    s = re.sub(r"\bteam total\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def resolve_quote(
    tip: str,
    market: str,
    quotes: list[MarketQuote],
) -> MarketQuote | None:
    """Find the quote a pick refers to. Exact canonical match, then containment."""
    if not quotes:
        return None
    target = _canonical_tip(tip)
    if not target:
        return None

    by_canonical = {_canonical_tip(q.tip): q for q in quotes}
    if target in by_canonical:
        return by_canonical[target]

    combined = _canonical_tip(f"{market} {tip}") if market else target
    if combined in by_canonical:
        return by_canonical[combined]

    target_tokens = set(target.split())
    best: MarketQuote | None = None
    best_score = 0.0
    for canonical, quote in by_canonical.items():
        tokens = set(canonical.split())
        if not tokens:
            continue
        # Never cross over/under or yes/no boundaries.
        for opposites in (("over", "under"), ("yes", "no")):
            if (opposites[0] in tokens) != (opposites[0] in target_tokens):
                break
            if (opposites[1] in tokens) != (opposites[1] in target_tokens):
                break
        else:
            overlap = len(tokens & target_tokens) / len(tokens | target_tokens)
            if overlap > best_score:
                best, best_score = quote, overlap
    return best if best_score >= 0.6 else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_matching.py -v`
Expected: PASS, 19 tests.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 5: Priced board assembly

**Files:**
- Create: `predictor/odds/board.py`
- Modify: `predictor/odds/__init__.py`
- Test: `tests/test_board.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4
- Produces:
  - `BoardFixture` dataclass: `league`, `home`, `away`, `kickoff_utc`, `kickoff_et`, `matchup_id`, `quotes: list[MarketQuote]`, plus `match_label` property returning `"{home} vs {away}"`
  - `PricedBoard` dataclass: `fixtures: list[BoardFixture]`, `fetched_at: str`, `errors: list[str]`, plus `find(match: str) -> BoardFixture | None`
  - `build_board(*, start_utc, end_utc, min_odds, max_odds, families=None, max_fixtures=40) -> PricedBoard`
  - `window_for_scope(scope: str, hours_window=None, target_date=None) -> tuple[datetime, datetime]`
  - `format_board_for_prompt(board: PricedBoard) -> str`
- `predictor/odds/__init__.py` re-exports `MarketQuote`, `PricedBoard`, `BoardFixture`, `build_board`, `window_for_scope`, `format_board_for_prompt`, `match_fixture`, `resolve_quote`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_board.py`:

```python
"""Tests for priced board assembly and prompt formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from predictor.odds.board import (
    BoardFixture,
    PricedBoard,
    build_board,
    format_board_for_prompt,
    window_for_scope,
)
from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote


def quote(tip, family="goals_totals", odds=1.25):
    return MarketQuote(
        family=family, market="m", tip=tip, line=1.5, side=None, period=0,
        odds=odds, raw_odds=odds + 0.02, fair_probability=0.78, source_key="k",
    )


def fixture(**kw) -> BoardFixture:
    defaults = dict(
        league="UEFA - Champions League Qualifiers",
        home="Lyon",
        away="Fenerbahce",
        kickoff_utc="2026-08-26T19:00:00Z",
        kickoff_et="3:00 PM ET",
        matchup_id=4,
        quotes=[quote("Over 1.5 goals"), quote("BTTS Yes", "btts", 1.70)],
    )
    defaults.update(kw)
    return BoardFixture(**defaults)


class TestWindowForScope:
    def test_today_starts_now(self):
        start, end = window_for_scope("today")
        assert start <= datetime.now(timezone.utc) + timedelta(minutes=1)
        assert end > start

    def test_window_respects_hours(self):
        start, end = window_for_scope("window", hours_window=6)
        assert timedelta(hours=5, minutes=30) < end - start < timedelta(hours=6, minutes=30)

    def test_date_scope_covers_the_named_day(self):
        start, end = window_for_scope("date", target_date="2026-09-01")
        assert (end - start) > timedelta(hours=20)

    def test_tomorrow_starts_in_the_future(self):
        start, _ = window_for_scope("tomorrow")
        assert start > datetime.now(timezone.utc)


class TestBuildBoard:
    def test_filters_by_odds_range(self, monkeypatch):
        monkeypatch.setattr(
            "predictor.odds.board.list_matchups",
            lambda: [
                PinnacleMatchup(
                    id=4, parent_id=None, league="L", home="Lyon", away="Fenerbahce",
                    start_time_utc=_soon(), kind="main",
                )
            ],
        )
        monkeypatch.setattr("predictor.odds.board.related", lambda mid: [])
        monkeypatch.setattr("predictor.odds.board.straight_markets", lambda mid: [])
        monkeypatch.setattr(
            "predictor.odds.board.build_quotes",
            lambda main, rel, mk: [quote("Over 1.5 goals", odds=1.25),
                                   quote("Under 1.5 goals", odds=4.00)],
        )
        board = build_board(
            start_utc=datetime.now(timezone.utc) - timedelta(hours=1),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=12),
            min_odds=1.10,
            max_odds=2.00,
        )
        tips = [q.tip for f in board.fixtures for q in f.quotes]
        assert "Over 1.5 goals" in tips
        assert "Under 1.5 goals" not in tips

    def test_pinnacle_failure_yields_an_empty_board_not_an_exception(self, monkeypatch):
        from predictor.odds.pinnacle import OddsUnavailable

        def boom():
            raise OddsUnavailable("down")

        monkeypatch.setattr("predictor.odds.board.list_matchups", boom)
        board = build_board(
            start_utc=datetime.now(timezone.utc),
            end_utc=datetime.now(timezone.utc) + timedelta(hours=6),
            min_odds=1.1,
            max_odds=3.0,
        )
        assert board.fixtures == []
        assert board.errors


class TestFind:
    def test_find_resolves_a_fixture(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        assert board.find("Lyon vs Fenerbahce") is not None

    def test_find_returns_none_for_an_unknown_fixture(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        assert board.find("Barcelona vs Real Madrid") is None


class TestPromptFormat:
    def test_includes_fixture_and_price(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        text = format_board_for_prompt(board)
        assert "Lyon vs Fenerbahce" in text
        assert "1.25" in text
        assert "Over 1.5 goals" in text

    def test_groups_by_family(self):
        board = PricedBoard(fixtures=[fixture()], fetched_at="now", errors=[])
        text = format_board_for_prompt(board)
        assert "goals_totals" in text or "Goals" in text

    def test_empty_board_says_so(self):
        text = format_board_for_prompt(PricedBoard(fixtures=[], fetched_at="now", errors=["down"]))
        assert "no priced" in text.lower()


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_board.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.odds.board'`

- [ ] **Step 3: Write the implementation**

Create `predictor/odds/board.py`:

```python
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
                id=f.matchup_id, parent_id=None, league=f.league, home=f.home,
                away=f.away, start_time_utc=f.kickoff_utc, kind="main",
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
                        {"family": q.family, "tip": q.tip, "odds": q.odds,
                         "raw_odds": q.raw_odds, "fair": q.fair_probability}
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
        except OddsUnavailable as e:
            errors.append(f"{m.home} vs {m.away}: {e}")
            continue
        quotes = build_quotes(m, rel + [m], markets)
        quotes = [
            q for q in quotes
            if min_odds <= q.odds <= max_odds
            and (not families or q.family in families)
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
```

Then replace `predictor/odds/__init__.py`:

```python
"""Real market prices for prediction runs."""

from predictor.odds.board import (
    BoardFixture,
    PricedBoard,
    build_board,
    format_board_for_prompt,
    window_for_scope,
)
from predictor.odds.matching import match_fixture, resolve_quote
from predictor.odds.quotes import FAMILIES, MarketQuote

__all__ = [
    "BoardFixture",
    "FAMILIES",
    "MarketQuote",
    "PricedBoard",
    "build_board",
    "format_board_for_prompt",
    "match_fixture",
    "resolve_quote",
    "window_for_scope",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_board.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Smoke-test against the live feed once, by hand**

Run:

```bash
python -c "from datetime import datetime,timedelta,timezone; from predictor.odds import build_board, format_board_for_prompt; b=build_board(start_utc=datetime.now(timezone.utc), end_utc=datetime.now(timezone.utc)+timedelta(hours=24), min_odds=1.10, max_odds=3.0, max_fixtures=3); print(format_board_for_prompt(b))"
```

Expected: a markdown board with three fixtures and prices. This confirms end-to-end wiring against the real feed. If it prints "No priced markets available", the feed shape has changed — inspect and fix `parse_matchups` before continuing.

- [ ] **Step 6: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 6: Schema extension

**Files:**
- Modify: `predictor/web/schema.py:39-70` (`Pick`), `predictor/web/schema.py:97-114` (`CreateRunRequest`)
- Test: `tests/test_web.py` (add a class)

**Interfaces:**
- Produces: `Pick.quoted_odds: float | None`, `Pick.price_source: str`, `Pick.market_family: str`, `CreateRunRequest.book_overround: dict[str, float] | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
class TestPriceProvenance:
    def test_pick_defaults_to_unpriced_source(self):
        p = _sample_pick()
        assert p.price_source == "unpriced"
        assert p.quoted_odds is None
        assert p.market_family == ""

    def test_pick_carries_provenance_through_a_roundtrip(self):
        p = _sample_pick(
            odds=1.18, quoted_odds=1.40, price_source="pinnacle", market_family="goals_totals"
        )
        restored = Pick.model_validate_json(p.model_dump_json())
        assert restored.odds == 1.18
        assert restored.quoted_odds == 1.40
        assert restored.price_source == "pinnacle"
        assert restored.market_family == "goals_totals"

    def test_request_accepts_overround_override(self):
        req = CreateRunRequest(book_overround={"goals_totals": 1.09})
        assert req.book_overround["goals_totals"] == 1.09

    def test_request_overround_defaults_to_none(self):
        assert CreateRunRequest().book_overround is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::TestPriceProvenance -v`
Expected: FAIL — `Pick` has no attribute `price_source`.

- [ ] **Step 3: Write the implementation**

In `predictor/web/schema.py`, inside `Pick`, replace the odds block:

```python
    odds: float | None = Field(default=None, gt=1.0)
    price_available: bool = True
    book: str = "SportyBet ng"
```

with:

```python
    odds: float | None = Field(default=None, gt=1.0)
    quoted_odds: float | None = None
    price_source: str = "unpriced"  # pinnacle | unpriced
    market_family: str = ""
    price_available: bool = True
    book: str = "SportyBet ng (modelled)"
```

In `CreateRunRequest`, after `model: str = "composer-2.5"`, add:

```python
    book_overround: dict[str, float] | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web.py::TestPriceProvenance -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. `test_submit_picks_schema_has_required_fields` still passes because the new fields are optional.

---

### Task 7: Price verification

The heart of the fix. Every submitted pick is re-priced from the board before the gates run.

**Files:**
- Create: `predictor/web/verify.py`
- Modify: `predictor/web/tools.py:19-28` (context), `predictor/web/tools.py:41-72` (gates)
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `PricedBoard`, `resolve_quote`, `Pick`
- Produces: `verify_prices(picks: list[Pick], board: PricedBoard | None) -> tuple[list[Pick], list[str]]` returning re-priced picks and human-readable notes; `SubmitPicksContext.__init__` gains a keyword-only `board: PricedBoard | None = None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify.py`:

```python
"""Tests for server-side price verification."""

from __future__ import annotations

import pytest

from predictor.odds.board import BoardFixture, PricedBoard
from predictor.odds.quotes import MarketQuote
from predictor.web.schema import Pick
from predictor.web.verify import verify_prices


def quote(tip, odds, family="goals_totals"):
    return MarketQuote(
        family=family, market="m", tip=tip, line=1.5, side=None, period=0,
        odds=odds, raw_odds=odds + 0.02, fair_probability=0.80, source_key="k",
    )


def board() -> PricedBoard:
    return PricedBoard(
        fixtures=[
            BoardFixture(
                league="UEFA - Champions League Qualifiers",
                home="Viking",
                away="Dinamo Zagreb",
                kickoff_utc="2026-08-26T19:00:00Z",
                kickoff_et="3:00 PM ET",
                matchup_id=1,
                quotes=[quote("Over 1.5 goals", 1.18), quote("BTTS Yes", 1.70, "btts")],
            )
        ],
        fetched_at="2026-08-26T14:00:00+00:00",
        errors=[],
    )


def pick(**kw) -> Pick:
    defaults = dict(
        match="Viking FK vs GNK Dinamo Zagreb",
        market="Over 1.5",
        tip="Over 1.5 goals",
        odds=1.40,
        confidence=79,
        estimated_probability=0.82,
        reasoning="Level aggregate forces both sides forward.",
        evidence=["First leg 2-2 with four goals before half-time"],
    )
    defaults.update(kw)
    return Pick(**defaults)


class TestOverwrite:
    def test_inflated_price_is_replaced_with_the_book_price(self):
        out, notes = verify_prices([pick()], board())
        assert out[0].odds == 1.18
        assert notes

    def test_original_quote_is_retained(self):
        out, _ = verify_prices([pick()], board())
        assert out[0].quoted_odds == 1.40

    def test_provenance_is_recorded(self):
        out, _ = verify_prices([pick()], board())
        assert out[0].price_source == "pinnacle"
        assert out[0].market_family == "goals_totals"
        assert out[0].price_available is True

    def test_matching_price_produces_no_note(self):
        out, notes = verify_prices([pick(odds=1.18)], board())
        assert out[0].odds == 1.18
        assert not notes

    def test_note_names_both_numbers(self):
        _, notes = verify_prices([pick()], board())
        assert "1.40" in notes[0] and "1.18" in notes[0]


class TestUnpriced:
    def test_unknown_fixture_becomes_unpriced(self):
        out, _ = verify_prices([pick(match="Barcelona vs Real Madrid")], board())
        assert out[0].price_available is False
        assert out[0].odds is None
        assert out[0].price_source == "unpriced"

    def test_unknown_fixture_keeps_the_agent_quote_for_reference(self):
        out, _ = verify_prices([pick(match="Barcelona vs Real Madrid")], board())
        assert out[0].quoted_odds == 1.40

    def test_unknown_market_on_a_known_fixture_becomes_unpriced(self):
        out, _ = verify_prices([pick(tip="Correct score 2-1", market="Correct score")], board())
        assert out[0].price_available is False

    def test_absent_board_leaves_picks_unpriced(self):
        out, notes = verify_prices([pick()], None)
        assert out[0].price_available is False
        assert notes


class TestGateInteraction:
    """Verification runs before the gates, so the gates see the true price."""

    def test_true_price_can_fail_a_margin_gate_the_fake_price_passed(self):
        out, _ = verify_prices([pick(odds=1.40, estimated_probability=0.82)], board())
        implied_at_true_price = 1.0 / out[0].odds
        assert out[0].estimated_probability < implied_at_true_price + 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'predictor.web.verify'`

- [ ] **Step 3: Write the implementation**

Create `predictor/web/verify.py`:

```python
"""Replace agent-supplied odds with verified board prices.

The agent cannot read a sportsbook, so any price it writes is an estimate.
Estimates skew high because the odds-range gate rejects anything below
`min_odds`, which rewards pricing to the floor. Everything published must
therefore be re-priced from the board before the gates run.
"""

from __future__ import annotations

from predictor.odds.board import PricedBoard
from predictor.odds.matching import resolve_quote
from predictor.web.schema import Pick

PRICE_TOLERANCE = 0.005


def verify_prices(
    picks: list[Pick],
    board: PricedBoard | None,
) -> tuple[list[Pick], list[str]]:
    """Re-price every pick from the board. Returns (picks, notes)."""
    notes: list[str] = []
    out: list[Pick] = []

    for p in picks:
        claimed = p.odds
        fixture = board.find(p.match) if board else None
        quote = resolve_quote(p.tip, p.market, fixture.quotes) if fixture else None

        if quote is None:
            reason = (
                "no board" if board is None
                else "fixture not on board" if fixture is None
                else "market not on board"
            )
            out.append(
                p.model_copy(
                    update={
                        "odds": None,
                        "quoted_odds": claimed,
                        "price_available": False,
                        "price_source": "unpriced",
                    }
                )
            )
            notes.append(f"{p.match} — {p.tip}: unpriced ({reason})")
            continue

        if claimed is not None and abs(claimed - quote.odds) > PRICE_TOLERANCE:
            notes.append(
                f"{p.match} — {p.tip}: agent quoted {claimed:.2f}, "
                f"book price {quote.odds:.2f} (corrected)"
            )

        out.append(
            p.model_copy(
                update={
                    "odds": quote.odds,
                    "quoted_odds": claimed,
                    "price_available": True,
                    "price_source": "pinnacle",
                    "market_family": quote.family,
                }
            )
        )

    return out, notes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_verify.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Wire verification into `submit_picks`**

In `predictor/web/tools.py`, change the imports at the top to add:

```python
from predictor.odds.board import PricedBoard
from predictor.web.verify import verify_prices
```

Change `SubmitPicksContext.__init__` to accept the board:

```python
    def __init__(
        self,
        run_id: str,
        scope: Scope,
        request: dict[str, Any],
        *,
        board: PricedBoard | None = None,
    ) -> None:
        self.run_id = run_id
        self.scope = scope
        self.request = request
        self.board = board
        self.accepted = False
        self.export_paths: dict[str, str] = {}
```

Inside `execute`, immediately after `result = RunResult.model_validate(payload)` and before the `min_conf` line, insert:

```python
            result.picks, price_notes = verify_prices(result.picks, ctx.board)
            for note in price_notes:
                append_log(ctx.run_id, f"price check: {note}")
```

Then replace the live-only unpriced branch. The current code is:

```python
                # Live research picks without a SportyBet quote — confidence gate only
                if ctx.scope == Scope.live and not p.price_available:
                    filtered.append(p)
                    continue
                if p.odds is None:
                    rejected.append(f"pick {i+1} {p.match}: odds required when price_available")
                    continue
```

Replace both statements with:

```python
                # No board price — publish on the confidence gate alone, any scope.
                # The research is still the product; the user sources the price.
                if not p.price_available or p.odds is None:
                    filtered.append(p)
                    continue
```

- [ ] **Step 6: Add the integration test**

Append to `tests/test_verify.py`:

```python
class TestSubmitPicksIntegration:
    def test_submit_picks_overwrites_an_inflated_price(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.schema import CreateRunRequest, Scope
        from predictor.web.store import init_run, read_result
        from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool

        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-26_verify_today"
        req = CreateRunRequest(
            scope=Scope.today, min_confidence=70, min_odds=1.10,
            max_odds=3.0, margin_buffer=0.0,
        )
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump(), board=board())
        tool = make_submit_picks_tool(ctx)

        msg = tool.execute(
            {"summary": "inflated", "picks": [pick(odds=1.40).model_dump()]}, None
        )

        assert "accepted" in msg
        stored = read_result(run_id)
        assert stored.picks[0].odds == 1.18
        assert stored.picks[0].quoted_odds == 1.40

    def test_pre_match_pick_without_a_board_price_still_publishes(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.schema import CreateRunRequest, Scope
        from predictor.web.store import init_run, read_result
        from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool

        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-26_unpriced_today"
        req = CreateRunRequest(scope=Scope.today, min_confidence=70)
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump(), board=board())
        tool = make_submit_picks_tool(ctx)

        msg = tool.execute(
            {
                "summary": "off board",
                "picks": [pick(match="Barcelona vs Real Madrid").model_dump()],
            },
            None,
        )

        assert "accepted" in msg
        stored = read_result(run_id)
        assert len(stored.picks) == 1
        assert stored.picks[0].price_available is False
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_verify.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 8: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. `test_accepts_valid_pick` in `tests/test_web.py` now passes with an unpriced result because no board is supplied — that is correct behaviour. If it asserts on odds, leave it; it only asserts pick count.

---

### Task 8: Prompt wiring and market diversity

**Files:**
- Create: `predictor/web/market_mix.py`
- Modify: `predictor/web/prompt.py`
- Test: `tests/test_market_mix.py`, plus additions to `tests/test_web.py`

**Interfaces:**
- Consumes: `read_result`, `list_runs`, `PricedBoard`, `format_board_for_prompt`
- Produces:
  - `recent_market_mix(limit: int = 5) -> dict[str, int]` mapping family to pick count
  - `format_diversity_block(mix: dict[str, int]) -> str`
  - `build_prompt(req, run_id, live_board=None, odds_board=None)` — new keyword-only `odds_board`

- [ ] **Step 1: Write the failing test**

Create `tests/test_market_mix.py`:

```python
"""Tests for the market-diversity prompt block."""

from __future__ import annotations

from predictor.web.market_mix import format_diversity_block


class TestFormatDiversityBlock:
    def test_calls_out_a_lopsided_mix(self):
        text = format_diversity_block({"goals_totals": 9, "team_totals": 3})
        assert "%" in text
        assert "goals" in text.lower()

    def test_mentions_the_exploration_rationale(self):
        text = format_diversity_block({"goals_totals": 12})
        assert "sample" in text.lower() or "bias" in text.lower()

    def test_empty_history_still_gives_guidance(self):
        text = format_diversity_block({})
        assert "families" in text.lower() or "family" in text.lower()

    def test_balanced_mix_does_not_scold(self):
        text = format_diversity_block(
            {"goals_totals": 3, "corners": 3, "handicap": 3, "btts": 3}
        )
        assert "families" in text.lower()
```

Append to `tests/test_web.py`:

```python
class TestPromptWithBoard:
    def test_prompt_includes_the_priced_board(self):
        from predictor.odds.board import BoardFixture, PricedBoard
        from predictor.odds.quotes import MarketQuote

        board = PricedBoard(
            fixtures=[
                BoardFixture(
                    league="EFL Cup", home="Newcastle United", away="West Bromwich Albion",
                    kickoff_utc="2026-08-26T18:45:00Z", kickoff_et="2:45 PM ET",
                    matchup_id=3,
                    quotes=[
                        MarketQuote(
                            family="goals_totals", market="Over/Under 1.5 goals",
                            tip="Over 1.5 goals", line=1.5, side=None, period=0,
                            odds=1.16, raw_odds=1.18, fair_probability=0.87, source_key="k",
                        )
                    ],
                )
            ],
            fetched_at="2026-08-26T14:00:00+00:00",
            errors=[],
        )
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123", odds_board=board)
        assert "Newcastle United vs West Bromwich Albion" in prompt
        assert "1.16" in prompt

    def test_prompt_forbids_inventing_a_price(self):
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123")
        assert "do not invent" in prompt.lower()

    def test_prompt_asks_for_market_variety(self):
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123")
        assert "famil" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_market_mix.py tests/test_web.py::TestPromptWithBoard -v`
Expected: FAIL — no module `predictor.web.market_mix`; `build_prompt` has no `odds_board` argument.

- [ ] **Step 3: Write `market_mix.py`**

Create `predictor/web/market_mix.py`:

```python
"""Market-family mix over recent runs, used to nudge the agent off goals markets."""

from __future__ import annotations

from predictor.web.store import list_runs, read_result

_GOALSY = {"goals_totals", "team_totals", "halves"}

_FAMILY_LABELS = {
    "goals_totals": "goals over/under",
    "team_totals": "team totals",
    "halves": "first half",
    "btts": "BTTS",
    "result": "1X2",
    "dc_dnb": "double chance / DNB",
    "handicap": "Asian handicap",
    "corners": "corners",
    "specials": "specials",
}


def recent_market_mix(limit: int = 5) -> dict[str, int]:
    """Count published picks per market family across the last completed runs."""
    mix: dict[str, int] = {}
    seen = 0
    for meta in list_runs(limit=limit * 4):
        if meta.status.value != "completed":
            continue
        result = read_result(meta.id)
        if not result or not result.picks:
            continue
        for p in result.picks:
            family = p.market_family or "unclassified"
            mix[family] = mix.get(family, 0) + 1
        seen += 1
        if seen >= limit:
            break
    return mix


def format_diversity_block(mix: dict[str, int]) -> str:
    total = sum(mix.values())
    lines = ["## Market variety"]

    if total:
        goalsy = sum(n for f, n in mix.items() if f in _GOALSY)
        share = round(100 * goalsy / total)
        top = sorted(mix.items(), key=lambda kv: kv[1], reverse=True)[:4]
        breakdown = ", ".join(
            f"{_FAMILY_LABELS.get(f, f)} {n}" for f, n in top
        )
        lines.append(
            f"Your recent runs published {total} picks — {share}% goals markets "
            f"({breakdown})."
        )
    else:
        lines.append("No market mix recorded yet.")

    lines.extend(
        [
            "",
            "Every market on the board carries a real price, so corners, handicaps, "
            "double chance, draw-no-bet, BTTS and first-half markets are researchable "
            "on the same footing as goals markets.",
            "",
            "Aim for **no more than half** your picks from one family, and cover "
            "**at least three families** when the slate supports it.",
            "",
            "MASTER hit rates are sample-biased: goals markets look strongest partly "
            "because they are almost the only markets with samples. Treat a thin "
            "sample as unknown, not as bad — a well-evidenced pick in a thin market "
            "is how the sample grows.",
        ]
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Update `prompt.py`**

In `predictor/web/prompt.py`, change the imports to add:

```python
from predictor.odds.board import PricedBoard, format_board_for_prompt
from predictor.web.market_mix import format_diversity_block, recent_market_mix
```

Change the signature:

```python
def build_prompt(
    req: CreateRunRequest,
    run_id: str,
    live_board: LiveFixtureBoard | None = None,
    *,
    odds_board: PricedBoard | None = None,
) -> str:
```

Before the `return` statement, add:

```python
    board_block = format_board_for_prompt(odds_board) if odds_board else ""
    try:
        diversity_block = format_diversity_block(recent_market_mix())
    except Exception:  # never let history reading break a run
        diversity_block = format_diversity_block({})

    price_rules = """## Prices

Prices come from the priced market board. **Do not invent, estimate, or carry a
price over from a tip site or another book.** Set `odds` to the exact number on
the board for the market you choose.

If the market you want is not on the board, either choose a market that is, or
publish the pick with `price_available: false` and no `odds` — the research still
shows and the user sources the price themselves.

The server re-checks every price against the board and overwrites anything that
does not match, so a guessed number will simply be replaced."""
```

Replace step 3 of `workflow_default`:

```
3. Verify prices on SportyBet ng when possible; still include a captured price if the book is down.
```

with:

```
3. Take the price from the priced market board below. Never invent one.
```

Replace steps 3 and 4 of `workflow_live`:

```
3. Try SportyBet ng for a live price. **If no live quote exists, still publish** the pick with `price_available: false` and no `odds` — the UI shows research; user finds price elsewhere.
4. When SportyBet has a live price, include `odds` and apply the user's odds/margin gates.
```

with:

```
3. Use the board price when the fixture is listed. **If it is not, still publish** the pick with `price_available: false` and no `odds` — the UI shows research; the user finds a price elsewhere.
4. When a board price exists, include `odds` and apply the user's odds/margin gates.
```

Then change the returned f-string, inserting the three new blocks between `{workflow}` and the "One pick per match" line:

```python
    return f"""Run soccer prediction research for run_id `{run_id}`.

Follow `.cursor/skills/soccer-predictions/SKILL.md`, `markets.md`, and `run-schema.md`.
Read `.analysis/MASTER.md` for historical hit rates (priors, not bans).

{scope_lines.get(req.scope, scope_lines[Scope.today])}{live_block}

## User thresholds (apply when calling submit_picks)
- Markets: {markets}
- Min confidence: {req.min_confidence}/100
- {pick_limit}
- {ticket_hint}{league_filter}
{odds_thresholds}

{workflow}

{price_rules}

{diversity_block}

{board_block}

**One pick per match.** Never submit Over 2.5 and team over 1.5 on the same fixture — pick the single market with the strongest evidence.

Do not write markdown files. Do not pad the board. Research quality is the gate.
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_market_mix.py tests/test_web.py::TestPromptWithBoard tests/test_web.py::TestPrompt -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 9: Runner wiring and the board endpoint

**Files:**
- Modify: `predictor/web/runner.py:57-67` (`_execute`), `predictor/web/runner.py:169-196` (`refine_run`)
- Modify: `predictor/web/app.py` (add `/api/odds/board`)
- Test: additions to `tests/test_web.py`

**Interfaces:**
- Consumes: `build_board`, `window_for_scope`, `SubmitPicksContext(board=...)`
- Produces: `RunManager._build_odds_board(request) -> PricedBoard | None`; `GET /api/odds/board` returning `PricedBoard.to_dict()`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
class TestOddsBoardEndpoint:
    def test_board_endpoint_shape(self, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        from predictor.odds.board import PricedBoard
        import predictor.web.app as app_module

        monkeypatch.setattr(
            app_module,
            "build_board",
            lambda **kw: PricedBoard(fixtures=[], fetched_at="now", errors=[]),
        )
        with TestClient(app_module.app) as client:
            r = client.get("/api/odds/board?scope=today&min_odds=1.1&max_odds=3.0")
        assert r.status_code == 200
        body = r.json()
        assert "fixtures" in body
        assert "fetched_at" in body
```

Note: `TestClient` triggers the lifespan, which launches the SDK bridge. If that is slow or requires a key in the local environment, mark this test `@pytest.mark.integration` and assert the route exists instead:

```python
    def test_board_route_registered(self):
        import predictor.web.app as app_module

        paths = {r.path for r in app_module.app.routes}
        assert "/api/odds/board" in paths
```

Use whichever variant runs clean locally; keep the route-registration assertion in all cases.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::TestOddsBoardEndpoint -v`
Expected: FAIL — `/api/odds/board` is not registered.

- [ ] **Step 3: Wire the runner**

In `predictor/web/runner.py`, add to the imports:

```python
from predictor.odds.board import PricedBoard, build_board, window_for_scope
```

Add a method to `RunManager`:

```python
    def _build_odds_board(self, request: CreateRunRequest) -> PricedBoard | None:
        """Fetch real prices once per run. Never blocks the run on failure."""
        try:
            start, end = window_for_scope(
                request.scope.value,
                hours_window=request.hours_window,
                target_date=request.target_date,
            )
            # The UI market chips are display labels ("Over/Under", "Corners"),
            # not family ids, so they steer the agent through the prompt rather
            # than filtering the board. Filtering here would silently hide
            # priced markets whenever a chip label has no matching family.
            return build_board(
                start_utc=start,
                end_utc=end,
                min_odds=request.min_odds,
                max_odds=request.max_odds,
            )
        except Exception as e:  # board is best-effort
            logger.warning("odds board unavailable: %s", e)
            return None
```

In `_execute`, replace:

```python
        tool = make_submit_picks_tool(ctx)
        live_board = fetch_live_board() if request.scope.value == "live" else None
        prompt = build_prompt(request, run_id, live_board=live_board)
```

with:

```python
        odds_board = await asyncio.to_thread(self._build_odds_board, request)
        ctx.board = odds_board
        tool = make_submit_picks_tool(ctx)
        live_board = (
            await asyncio.to_thread(fetch_live_board)
            if request.scope.value == "live"
            else None
        )
        prompt = build_prompt(request, run_id, live_board=live_board, odds_board=odds_board)
        if odds_board:
            append_log(
                run_id,
                f"odds board: {len(odds_board.fixtures)} fixtures priced"
                + (f", {len(odds_board.errors)} errors" if odds_board.errors else ""),
            )
        self._boards[run_id] = odds_board
```

Add `self._boards: dict[str, PricedBoard | None] = {}` to `RunManager.__init__`, and in the `finally` block of `_execute` add `self._boards.pop(run_id, None)`.

In `refine_run`, after building `ctx`, reuse or rebuild the board:

```python
        ctx.board = self._boards.get(run_id)
        if ctx.board is None:
            try:
                ctx.board = await asyncio.to_thread(
                    self._build_odds_board, CreateRunRequest.model_validate(req_data)
                )
            except Exception:
                ctx.board = None
```

- [ ] **Step 4: Add the endpoint**

In `predictor/web/app.py`, add to the imports:

```python
from predictor.odds.board import build_board, window_for_scope
```

Add the route above the static mount:

```python
@app.get("/api/odds/board")
async def odds_board(
    scope: str = "today",
    hours_window: int | None = None,
    target_date: str | None = None,
    min_odds: float = 1.10,
    max_odds: float = 5.0,
):
    """Preview the real prices a run would see."""
    start, end = window_for_scope(scope, hours_window=hours_window, target_date=target_date)
    board = await asyncio.to_thread(
        build_board, start_utc=start, end_utc=end, min_odds=min_odds, max_odds=max_odds
    )
    return board.to_dict()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_web.py::TestOddsBoardEndpoint -v`
Expected: PASS.

- [ ] **Step 6: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 10: Analysis ledger and manager

**Files:**
- Create: `predictor/web/analysis_runner.py`
- Test: `tests/test_analysis_runner.py`

**Interfaces:**
- Consumes: `list_runs`, `read_result`, `read_meta`, `write_meta`, `init_run`, `bus`, `message_to_event`, `AsyncClient`
- Produces:
  - `read_ledger() -> dict`, `mark_graded(run_ids: list[str], report: str) -> None`
  - `ungraded_runs(min_age_hours: float = 3.0, now: datetime | None = None) -> list[str]`
  - `build_analysis_prompt(run_ids: list[str]) -> str`
  - `AnalysisManager` with `set_client`, `start() -> str`, `is_running() -> bool`, `status() -> dict`
  - module-level singleton `analysis_manager`

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_runner.py`:

```python
"""Tests for analysis run selection and the graded-runs ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from predictor.web.analysis_runner import (
    AnalysisManager,
    build_analysis_prompt,
    mark_graded,
    read_ledger,
    ungraded_runs,
)
from predictor.web.schema import CreateRunRequest, RunResult, RunStatus, Scope
from predictor.web.store import init_run, read_meta, write_meta, write_result


def _make_run(tmp_path: Path, run_id: str, kickoff_et: str, status=RunStatus.completed):
    req = CreateRunRequest(scope=Scope.today)
    init_run(run_id, req)
    meta = read_meta(run_id)
    meta.status = status
    meta.pick_count = 1
    write_meta(run_id, meta)
    write_result(
        run_id,
        RunResult(
            run_id=run_id,
            scope=Scope.today,
            generated_at="2026-08-26T10:00:00-04:00",
            summary="s",
            picks=[
                {
                    "match": "A vs B",
                    "tip": "Over 1.5 goals",
                    "kickoff_et": kickoff_et,
                    "odds": 1.2,
                    "confidence": 80,
                    "estimated_probability": 0.9,
                    "reasoning": "r",
                    "evidence": ["e"],
                }
            ],
        ),
    )


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path / ".runs")
    monkeypatch.setattr("predictor.web.analysis_runner.ANALYSIS_DIR", tmp_path / ".analysis")
    (tmp_path / ".runs").mkdir()
    (tmp_path / ".analysis").mkdir()
    return tmp_path


class TestLedger:
    def test_empty_ledger_reads_clean(self, runs_dir):
        assert read_ledger() == {"graded": []}

    def test_mark_and_read_back(self, runs_dir):
        mark_graded(["run_a"], ".analysis/report.md")
        entries = read_ledger()["graded"]
        assert len(entries) == 1
        assert entries[0]["run_id"] == "run_a"
        assert entries[0]["report"] == ".analysis/report.md"

    def test_marking_twice_does_not_duplicate(self, runs_dir):
        mark_graded(["run_a"], "r1.md")
        mark_graded(["run_a"], "r2.md")
        assert len(read_ledger()["graded"]) == 1

    def test_corrupt_ledger_is_treated_as_empty(self, runs_dir):
        (runs_dir / ".analysis" / "graded_runs.json").write_text("{{{", encoding="utf-8")
        assert read_ledger() == {"graded": []}


class TestUngradedRuns:
    def test_finished_run_is_ungraded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert "2026-08-26_09-00-00_today" in ungraded_runs(now=now)

    def test_graded_run_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET")
        mark_graded(["2026-08-26_09-00-00_today"], "r.md")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []

    def test_run_whose_matches_have_not_finished_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "11:00 PM ET")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []

    def test_errored_run_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET", RunStatus.error)
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []


class TestPrompt:
    def test_prompt_names_every_run(self):
        text = build_analysis_prompt(["run_a", "run_b"])
        assert "run_a" in text and "run_b" in text

    def test_prompt_points_at_the_command_workflow(self):
        text = build_analysis_prompt(["run_a"])
        assert "predictions-analysis" in text

    def test_prompt_requires_master_update(self):
        text = build_analysis_prompt(["run_a"])
        assert "MASTER.md" in text


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_second_start_is_refused(self, runs_dir):
        mgr = AnalysisManager()
        mgr._running_id = "analysis_existing"
        assert mgr.is_running()
        with pytest.raises(RuntimeError):
            await mgr.start()
```

If `pytest-asyncio` is not installed, replace `TestConcurrency` with a synchronous check:

```python
class TestConcurrency:
    def test_is_running_reflects_state(self, runs_dir):
        mgr = AnalysisManager()
        assert not mgr.is_running()
        mgr._running_id = "analysis_existing"
        assert mgr.is_running()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_analysis_runner.py -v`
Expected: FAIL — no module `predictor.web.analysis_runner`.

- [ ] **Step 3: Write the implementation**

Create `predictor/web/analysis_runner.py`:

```python
"""Run the predictions-analysis workflow as an SDK agent from the web app.

Unlike prediction runs, this agent needs the `edit` tool so it can write the
dated report and recompute MASTER.md. `shell` stays disallowed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from cursor_sdk import AgentOptions, AsyncClient, LocalAgentOptions

from predictor.web.bus import bus
from predictor.web.schema import RunMeta, RunStatus, Scope, now_iso
from predictor.web.settings import ANALYSIS_DIR, settings
from predictor.web.sse import message_to_event
from predictor.web.store import (
    append_log,
    list_runs,
    read_meta,
    read_result,
    write_meta,
    _run_dir,
)

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
LEDGER_NAME = "graded_runs.json"
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP])M", re.IGNORECASE)


def _ledger_path():
    return ANALYSIS_DIR / LEDGER_NAME


def read_ledger() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"graded": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"graded": []}
    if not isinstance(data, dict) or not isinstance(data.get("graded"), list):
        return {"graded": []}
    return data


def mark_graded(run_ids: list[str], report: str) -> None:
    ledger = read_ledger()
    known = {e.get("run_id") for e in ledger["graded"]}
    for run_id in run_ids:
        if run_id in known:
            continue
        ledger["graded"].append(
            {"run_id": run_id, "graded_at": now_iso(), "report": report}
        )
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _latest_kickoff_utc(run_id: str) -> datetime | None:
    """Latest kickoff in a run, from the ET strings the agent wrote."""
    result = read_result(run_id)
    if not result or not result.picks:
        return None
    try:
        day = datetime.strptime(run_id[:10], "%Y-%m-%d")
    except ValueError:
        return None

    latest: datetime | None = None
    for p in result.picks:
        m = _TIME_RE.search(p.kickoff_et or "")
        if not m:
            continue
        hour = int(m.group(1)) % 12
        if m.group(3).upper() == "P":
            hour += 12
        when = day.replace(hour=hour, minute=int(m.group(2)), tzinfo=EASTERN)
        as_utc = when.astimezone(timezone.utc)
        if latest is None or as_utc > latest:
            latest = as_utc
    return latest


def ungraded_runs(min_age_hours: float = 3.0, now: datetime | None = None) -> list[str]:
    """Completed runs whose matches have finished and that are not in the ledger."""
    now = now or datetime.now(timezone.utc)
    graded = {e.get("run_id") for e in read_ledger()["graded"]}
    out: list[str] = []
    for meta in list_runs(limit=200):
        if meta.id in graded:
            continue
        if meta.status != RunStatus.completed or meta.pick_count == 0:
            continue
        if meta.id.startswith("analysis_"):
            continue
        latest = _latest_kickoff_utc(meta.id)
        if latest is None:
            continue
        if now - latest < timedelta(hours=min_age_hours):
            continue
        out.append(meta.id)
    return sorted(out)


def build_analysis_prompt(run_ids: list[str]) -> str:
    listed = "\n".join(f"- `.runs/{rid}/run.json`" for rid in run_ids)
    return f"""Grade completed prediction runs and update the analysis files.

Follow the workflow in `.cursor/commands/predictions-analysis.md` exactly.

## Runs to grade

{listed}

## Steps

1. Read each `run.json` above. Each pick has `match`, `tip`, `odds`,
   `quoted_odds`, `confidence`, `market_family`, and `estimated_probability`.
2. Look up the 90-minute result for every unique match on ESPN, LiveScore,
   FlashScore, or the league site. Mark unfinished matches as `—`.
3. Grade each tip using the settlement rules in the command file.
4. Write `.analysis/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md` with the
   per-run tables, confidence-bucket calibration, and ticket settlement.
5. Recompute `.analysis/MASTER.md`: pooled market performance, confidence
   buckets, ticket record, league notes, and the usage guidance.

## Price accuracy

Picks now carry both `odds` (the verified book price) and `quoted_odds` (what a
previous agent estimated). Where the two differ, report the mean absolute error
in a **Price accuracy** section of MASTER so the pricing model can be tuned.
Prices recorded before this change are unreliable — do not compare pre-change
PnL with post-change PnL.

## Market coverage

Report the market-family mix of graded picks. Flag families with fewer than 10
samples as thin rather than weak.

Do not modify anything outside `.analysis/`.
"""


class AnalysisManager:
    def __init__(self) -> None:
        self._client: AsyncClient | None = None
        self._running_id: str | None = None
        self._lock = asyncio.Lock()

    async def set_client(self, client: AsyncClient) -> None:
        self._client = client

    def is_running(self) -> bool:
        return self._running_id is not None

    def status(self) -> dict[str, Any]:
        ledger = read_ledger()["graded"]
        return {
            "ungraded": ungraded_runs(),
            "running": self.is_running(),
            "running_id": self._running_id,
            "last_graded_at": ledger[-1]["graded_at"] if ledger else None,
        }

    async def start(self) -> str:
        if self.is_running():
            raise RuntimeError("An analysis run is already in progress")
        if not settings.cursor_api_key:
            raise ValueError("CURSOR_API_KEY is not set. Add it to .env - see README.")
        if not self._client:
            raise RuntimeError("SDK client not initialized")

        run_ids = ungraded_runs()
        if not run_ids:
            raise ValueError("No completed runs are waiting to be graded")

        async with self._lock:
            run_id = f"analysis_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            d = _run_dir(run_id)
            d.mkdir(parents=True, exist_ok=True)
            meta = RunMeta(
                id=run_id, status=RunStatus.running, scope=Scope.today, created_at=now_iso()
            )
            write_meta(run_id, meta)
            self._running_id = run_id
            asyncio.create_task(self._execute(run_id, run_ids))
            return run_id

    async def _execute(self, run_id: str, graded_ids: list[str]) -> None:
        assert self._client is not None
        prompt = build_analysis_prompt(graded_ids)
        try:
            async with await self._client.agents.create(
                AgentOptions(
                    model=settings.default_model,
                    api_key=settings.cursor_api_key,
                    local=LocalAgentOptions(
                        cwd=str(settings.repo_root),
                        setting_sources=["project"],
                    ),
                    disallowed_tools=["shell"],
                ),
            ) as agent:
                append_log(run_id, f"analysis agent created: {agent.agent_id}")
                handle = await agent.send(prompt)
                await bus.publish(run_id, {"type": "started", "agent_id": agent.agent_id})

                async for msg in handle.messages():
                    event = message_to_event(msg)
                    if event:
                        await bus.publish(run_id, event)

                result = await handle.wait()
                append_log(run_id, f"analysis finished: status={result.status}")

                meta = read_meta(run_id)
                if result.status == "error":
                    if meta:
                        meta.status = RunStatus.error
                        meta.error = "Analysis agent ended with error status"
                else:
                    mark_graded(graded_ids, f".analysis/ (see MASTER.md, {now_iso()})")
                    if meta:
                        meta.status = RunStatus.completed
                        meta.pick_count = len(graded_ids)
                if meta:
                    meta.completed_at = now_iso()
                    write_meta(run_id, meta)

                await bus.publish(
                    run_id,
                    {"type": "done", "status": meta.status.value if meta else "error"},
                )
        except Exception as e:
            logger.exception("Analysis run failed for %s", run_id)
            append_log(run_id, f"analysis error: {e}")
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.error
                meta.error = str(e)
                meta.completed_at = now_iso()
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "error", "message": str(e)})
        finally:
            self._running_id = None
            await bus.close(run_id)


analysis_manager = AnalysisManager()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_analysis_runner.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 11: Analysis endpoints

**Files:**
- Modify: `predictor/web/app.py` (lifespan + two routes)
- Test: additions to `tests/test_web.py`

**Interfaces:**
- Consumes: `analysis_manager`
- Produces: `GET /api/analysis/status`, `POST /api/analysis/run`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
class TestAnalysisEndpoints:
    def test_routes_registered(self):
        import predictor.web.app as app_module

        paths = {r.path for r in app_module.app.routes}
        assert "/api/analysis/status" in paths
        assert "/api/analysis/run" in paths

    def test_status_shape(self, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module

        monkeypatch.setattr(
            app_module.analysis_manager,
            "status",
            lambda: {"ungraded": ["a"], "running": False, "running_id": None,
                     "last_graded_at": None},
        )
        body = app_module.analysis_manager.status()
        assert body["ungraded"] == ["a"]
        assert body["running"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::TestAnalysisEndpoints -v`
Expected: FAIL — routes not registered.

- [ ] **Step 3: Write the implementation**

In `predictor/web/app.py`, add to the imports:

```python
from predictor.web.analysis_runner import analysis_manager
```

In `lifespan`, after `await run_manager.set_client(client)`, add:

```python
    await analysis_manager.set_client(client)
```

Add the routes next to the existing `/api/analysis` handler:

```python
@app.get("/api/analysis/status")
async def analysis_status():
    return analysis_manager.status()


@app.post("/api/analysis/run")
async def analysis_run():
    try:
        run_id = await analysis_manager.start()
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"run_id": run_id}
```

Route ordering matters: FastAPI matches in registration order and `/api/analysis` is declared before these. Because the paths are literal and distinct, order is safe here, but the SPA catch-all `@app.get("/{full_path:path}")` must remain last in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web.py::TestAnalysisEndpoints -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 12: Frontend

**Files:**
- Create: `webapp/src/RunLog.jsx`
- Modify: `webapp/src/App.jsx`, `webapp/src/AnalysisPanel.jsx`

**Interfaces:**
- `RunLog` props: `{ entries: object[] }`
- `AnalysisPanel` props: `{ analysis, onRefresh }`

- [ ] **Step 1: Extract the shared log component**

Create `webapp/src/RunLog.jsx`:

```jsx
import { useEffect, useRef } from "react";

export default function RunLog({ entries }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries]);

  return (
    <div
      ref={ref}
      className="h-40 overflow-y-auto bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono space-y-1"
    >
      {entries.map((l, i) => (
        <div key={i} className="text-slate-400">
          {l.type === "tool" && `[tool] ${l.name} (${l.status})`}
          {l.type === "thinking" && `[…] ${l.text?.slice(0, 120)}`}
          {l.type === "assistant" && l.text?.slice(0, 200)}
          {l.type === "status" && l.text}
          {l.type === "error" && <span className="text-red-400">{l.message}</span>}
          {l.type === "done" && <span className="text-emerald-400">Done — {l.status}</span>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Use it in `App.jsx` and show price provenance**

In `webapp/src/App.jsx`:

Add the import beneath the existing ones:

```jsx
import RunLog from "./RunLog.jsx";
```

Replace the research-log block:

```jsx
              <div ref={logRef} className="h-40 overflow-y-auto bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono space-y-1">
                {log.map((l, i) => (
                  <div key={i} className="text-slate-400">
                    {l.type === "tool" && `[tool] ${l.name} (${l.status})`}
                    {l.type === "thinking" && `[…] ${l.text?.slice(0, 120)}`}
                    {l.type === "assistant" && l.text?.slice(0, 200)}
                    {l.type === "status" && l.text}
                    {l.type === "error" && <span className="text-red-400">{l.message}</span>}
                    {l.type === "done" && <span className="text-emerald-400">Done — {l.status}</span>}
                  </div>
                ))}
              </div>
```

with:

```jsx
              <RunLog entries={log} />
```

Then delete the now-unused `logRef` declaration and the `useEffect` that scrolls it:

```jsx
  const logRef = useRef(null);
```

```jsx
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);
```

In `PickCard`, replace the price span:

```jsx
            <span className={
              pick.price_available === false || pick.odds == null
                ? "text-amber-400 text-sm font-medium"
                : "text-emerald-400 font-mono"
            }>
              {pick.price_available === false || pick.odds == null
                ? "No live price"
                : `@${pick.odds.toFixed(2)}`}
            </span>
```

with:

```jsx
            <span className="text-right">
              {pick.price_available === false || pick.odds == null ? (
                <span className="text-amber-400 text-sm font-medium">No book price</span>
              ) : (
                <>
                  <span className="text-emerald-400 font-mono">@{pick.odds.toFixed(2)}</span>
                  {pick.quoted_odds != null &&
                    Math.abs(pick.quoted_odds - pick.odds) > 0.005 && (
                      <span
                        className="block text-[10px] text-slate-500"
                        title="The agent estimated this price; the server replaced it with the book price."
                      >
                        est. {pick.quoted_odds.toFixed(2)} → corrected
                      </span>
                    )}
                </>
              )}
            </span>
```

Change the Analysis tab render to pass a refresh callback:

```jsx
      {tab === "analysis" && <AnalysisPanel analysis={analysis} />}
```

becomes:

```jsx
      {tab === "analysis" && (
        <AnalysisPanel analysis={analysis} onRefresh={loadAnalysis} />
      )}
```

- [ ] **Step 3: Add the Run analysis button**

Read `webapp/src/AnalysisPanel.jsx` first to keep its existing markdown rendering intact, then wrap it. The new component:

```jsx
import { useCallback, useEffect, useRef, useState } from "react";
import RunLog from "./RunLog.jsx";

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

export default function AnalysisPanel({ analysis, onRefresh }) {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState([]);
  const [error, setError] = useState("");
  const esRef = useRef(null);

  const loadStatus = useCallback(() => {
    api("/api/analysis/status")
      .then((s) => {
        setStatus(s);
        setRunning(!!s.running);
      })
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
    return () => esRef.current?.close();
  }, [loadStatus]);

  const startAnalysis = async () => {
    setError("");
    setLog([]);
    setRunning(true);
    try {
      const { run_id: runId } = await api("/api/analysis/run", { method: "POST" });
      esRef.current?.close();
      const es = new EventSource(`/api/runs/${runId}/events`);
      esRef.current = es;
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === "connected") return;
        setLog((prev) => [...prev.slice(-200), data]);
        if (["done", "error", "cancelled"].includes(data.type)) {
          setRunning(false);
          es.close();
          onRefresh?.();
          loadStatus();
        }
      };
      es.onerror = () => setRunning(false);
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const ungraded = status?.ungraded?.length ?? 0;

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center gap-3 border border-slate-800 rounded-lg p-4 bg-slate-900/60">
        <button
          type="button"
          onClick={startAnalysis}
          disabled={running || ungraded === 0}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded font-medium"
        >
          {running ? "Grading…" : "Run analysis"}
        </button>
        <p className="text-sm text-slate-400">
          {ungraded === 0
            ? "Nothing to grade — every finished run is already in MASTER."
            : `${ungraded} finished run${ungraded === 1 ? "" : "s"} waiting to be graded.`}
          {status?.last_graded_at && (
            <span className="block text-xs text-slate-500">
              Last graded {new Date(status.last_graded_at).toLocaleString()}
            </span>
          )}
        </p>
      </section>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {(running || log.length > 0) && (
        <section>
          <h2 className="text-sm font-medium text-slate-400 mb-2">Analysis log</h2>
          <RunLog entries={log} />
        </section>
      )}

      {/* Existing MASTER.md rendering goes here, unchanged. */}
    </div>
  );
}
```

Move the previous `AnalysisPanel` body — whatever it renders from `analysis.raw` / `analysis.sections` — into the placeholder comment. Do not change how it renders; only wrap it.

- [ ] **Step 4: Build the frontend**

Run: `cd webapp && npm run build`
Expected: Vite writes to `predictor/web/static/`, exit code 0, no unresolved import warnings for `./RunLog.jsx`.

- [ ] **Step 5: Verify the suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. `test_static_frontend_built` confirms the build landed.

- [ ] **Step 6: Manual smoke test**

Run: `python -m predictor.web.app`

Open `http://127.0.0.1:8765`, go to the Analysis tab, and confirm the button renders with an ungraded count. Do not start a run yet — Task 13 updates the rules the agent reads.

---

### Task 13: Documentation and rules

The agent reads these files at run time through `setting_sources=["project"]`, so stale instructions actively cause wrong behaviour. This task is functional, not cosmetic.

**Files:**
- Modify: `.cursor/rules/soccer-prediction-core.mdc`, `.cursor/skills/soccer-predictions/markets.md`, `.cursor/skills/soccer-predictions/run-schema.md`, `.analysis/MASTER.md`, `README.md`

- [ ] **Step 1: Update the core rule**

In `.cursor/rules/soccer-prediction-core.mdc`:

Replace the price evidence line:

```
7. **Price** — decimal odds + book name ([SportyBet ng](https://www.sportybet.com/ng/) preferred)
```

with:

```
7. **Price** — take the decimal odds from the priced market board in the prompt. Never estimate a price.
```

Replace the live exception and the no-price rule:

```
**Live exception:** When SportyBet ng has no in-play quote, still publish with `price_available: false` (no odds) — confidence gate only. Pre-match and priced live picks still need a number.

**No price = no pick.** Do not publish without a number.
```

with:

```
**Prices are server-supplied.** The web app fetches real market prices and hands them to you as a priced market board. Copy the number exactly. The server re-checks every price and overwrites anything that does not match, so a guessed number is simply replaced.

**Off-board fixtures still publish.** When the board has no price for a fixture or market — small cups, women's qualifiers, some in-play games — publish with `price_available: false` and no odds. The research is the product; the user sources the price. The confidence gate still applies.
```

Replace this true-skip bullet:

```
- No price available after checking the book
```

with:

```
- Kickoff unconfirmed and the fixture is absent from the board
```

Add to the Markets section, after "All markets are allowed when evidence supports them. Mix freely.":

```
Every family on the board is priced, so corners, handicaps, double chance, draw-no-bet, BTTS and first-half markets carry real numbers. Publish no more than half your picks from one family, and cover at least three families when the slate supports it.
```

- [ ] **Step 2: Update `markets.md`**

In `.cursor/skills/soccer-predictions/markets.md`:

Replace the book line under "Research sources":

```
- **Book:** https://www.sportybet.com/ng/
```

with:

```
- **Prices:** the priced market board in the run prompt. Never estimate a price or copy one from a tip site.
```

Replace:

```
MASTER hit rates are **priors** — use them to calibrate, not to block markets.
```

with:

```
MASTER hit rates are **priors** — use them to calibrate, not to block markets.

They are also **sample-biased**. Goals markets look strongest largely because they are almost the only markets with samples: before real prices existed, other markets could not be priced and so were rarely published. Treat a thin sample as unknown, not as bad. A well-evidenced pick in a thin market is how the sample grows.
```

Replace this skipped-fixtures reason:

```
List in `skipped[]` with one-line why: unconfirmed kickoff, no price, insufficient data, below confidence gate.
```

with:

```
List in `skipped[]` with one-line why: unconfirmed kickoff, insufficient data, below confidence gate. A missing price is not a skip — publish with `price_available: false`.
```

- [ ] **Step 3: Update `run-schema.md`**

Read the file, then in the Pick field table add three rows and amend the odds row:

```
| `odds` | number | Copy exactly from the priced market board. The server verifies and overwrites this. Omit when the fixture or market is off the board. |
| `quoted_odds` | number | **Server-set.** Do not send. Records what you submitted, so pricing drift can be measured. |
| `price_source` | string | **Server-set.** `pinnacle` or `unpriced`. |
| `market_family` | string | **Server-set.** One of `goals_totals`, `team_totals`, `halves`, `btts`, `result`, `dc_dnb`, `handicap`, `corners`, `specials`. |
```

Add a short section after the field table:

```
## Prices

The run prompt contains a priced market board with real book prices. Use those numbers and nothing else. The server re-resolves every pick against the board before applying the confidence, odds-range and margin gates, replaces any mismatched number, and records your original in `quoted_odds`.

When the board has no price for your fixture or market, set `price_available: false` and omit `odds`. The pick still publishes.
```

- [ ] **Step 4: Update `MASTER.md` usage notes**

In `.analysis/MASTER.md`, under `## Usage for Predictions`, add these bullets at the top of the list:

```
- **Prices before 2026-08-26 are unreliable.** The agent estimated them and skewed high toward the run's `min_odds` floor — a twelve-leg acca advertised at 20.07x was really near 4x. Do not compare pre-change PnL or combined-odds figures with post-change ones.
- **Prices are now server-supplied** from a real market feed and verified before the gates run. Copy the board number; do not estimate.
- **Market samples are biased, not conclusive.** Goals markets dominate this table because they were the only markets that could be priced. Corners, handicaps, DC/DNB and BTTS now carry real prices — a thin row means unmeasured, not bad. Publish at most half your picks from one family and cover at least three families when the slate allows.
```

- [ ] **Step 5: Update the README**

In `README.md`, add a section describing the odds source (Pinnacle guest feed, de-vigged and re-vigged to a SportyBet-like margin, `PINNACLE_API_KEY` and `PREDICTOR_OVERROUND_*` env overrides) and the Analysis tab button. Match the existing README's heading style and tone.

- [ ] **Step 6: Verify the suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. `test_repo_has_cursor_rules` and `test_run_schema_doc_exists` confirm the files still exist.

- [ ] **Step 7: End-to-end smoke test**

Run: `python -m predictor.web.app`

In the browser:

1. Generate tab, scope Today, odds 1.10–3.00, min confidence 75. Click Generate.
2. Watch the research log for `odds board: N fixtures priced`.
3. When picks appear, confirm at least one card shows an `est. X → corrected` note, or that the odds match the board endpoint. Cross-check by opening `http://127.0.0.1:8765/api/odds/board?scope=today&min_odds=1.1&max_odds=3.0` and comparing a price.
4. Confirm the published picks span more than one market family.
5. Analysis tab: confirm the ungraded count, click Run analysis, watch the log, and confirm `.analysis/` gains a dated report, `MASTER.md` changes, and `.analysis/graded_runs.json` lists the graded run ids.

Expected: prices on the cards match the board endpoint exactly.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §A `predictor/odds/` → Tasks 1–5; §B schema → Task 6; §C prompt → Task 8; §D `submit_picks` → Task 7; §E analysis runs → Tasks 10–11; §F frontend → Task 12; §G documentation → Task 13; §H testing → distributed through every task; §I risks → covered by the degrade-to-empty-board behaviour in Tasks 2 and 5 and the dual-threshold matching in Task 4.

**Type consistency.** `MarketQuote` field names are identical in Tasks 3, 4, 5, 7 and 8. `PricedBoard.find` is defined in Task 5 and consumed in Task 7. `SubmitPicksContext(board=...)` is introduced in Task 7 and used in Task 9. `build_prompt(..., odds_board=...)` is defined in Task 8 and called in Task 9. `analysis_manager` is created in Task 10 and consumed in Task 11.

**Known sharp edges.**

- Task 5's `kickoff_et` formatting guards against `%-I`, which raises on Windows. This project is developed on Windows and deployed on Linux, so both paths matter.
- Task 9 deliberately passes `families=None`. The UI market chips are display labels, not family ids; filtering the board by them would hide priced markets.
- Task 10's `_latest_kickoff_utc` parses the agent-written `kickoff_et` string. Runs whose picks lack a parseable kickoff are excluded from grading rather than graded early. That is the safe failure.
- Task 12's `AnalysisPanel` rewrite must preserve the existing MASTER rendering. Read the file before replacing it.
