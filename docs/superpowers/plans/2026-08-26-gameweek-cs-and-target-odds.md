# Gameweek Correct Scores and Target-Odds Tickets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Gameweek tab that publishes a full remaining-round correct-score card for EPL, Bundesliga, La Liga, Serie A, and Ligue 1 (Twitter copy, no betting gates), and a Generate “target odds” solver that builds a researched ticket within ±15% with optional priced-board fill.

**Architecture:** A `predictor/gameweek/` package merges football-data.org, FotMob, and ESPN calendars with a two-of-three rule, then a `scope=gameweek` agent run fills every remaining fixture. Twitter formatters write clipboard text. A pure `odds_solver.py` runs after researched `submit_picks` when `target_odds` is set; Fill from board is a separate POST.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, `requests`, pytest, React 18 + Vite + Tailwind. No new runtime Python packages.

## Global Constraints

- **This repo is not under git version control.** Where a normal plan says "commit", run `python -m pytest tests/ -v` from the repo root and confirm it is green. Do not run `git init`.
- Python `>=3.10`. Use `from __future__ import annotations` at the top of every new module.
- New runtime dependencies: none. `requests` is already a base dependency.
- Tests must never make a network call. Calendar payloads are recorded under `tests/fixtures/gameweek/` and replayed.
- All football-data.org, FotMob, and ESPN **schedule** HTTP lives in `predictor/gameweek/calendars.py`. No other module may import `requests` for matchday calendars.
- A fixture is on the Gameweek slate only if **at least two** of those three sources list it in their current round and it is not finished — unless only one source is up, in which case the slate is built anyway and every fixture is `unconfirmed_slate=True`.
- Kickoff Eastern is locked only when two sources agree within 15 minutes. Mismatch → skipped (`kickoff mismatch`).
- Gameweek runs skip Pinnacle board fetch, skip `verify_prices`, skip odds/margin/confidence-floor drops, and skip SportyBet CSV. They write Twitter `.txt` instead.
- `low conf` means `confidence < 70`. Twitter copy never includes odds.
- Target-odds solver is server-side only. Band is ±15%. Fill families: `goals_totals`, `team_totals`, `btts` only. One leg per match. Cap researched candidates at 16.
- Fill legs: `reasoning` starts with `unresearched board fill`, `confidence` 50, `evidence` `["Board price only — not researched."]`, `odds` from the board quote.
- Run the suite with `python -m pytest tests/ -v` from the repo root.

---

## File Structure

**Create:**

| Path | Responsibility |
|------|----------------|
| `predictor/gameweek/__init__.py` | Re-export `GameweekBoard`, `build_gameweek_board`, `format_gameweek_for_prompt` |
| `predictor/gameweek/types.py` | `RawFixture`, `GameweekFixture`, `GameweekBoard` |
| `predictor/gameweek/merge.py` | Two-of-three inclusion, kickoff agreement |
| `predictor/gameweek/calendars.py` | HTTP + parsers for FD / FotMob / ESPN |
| `predictor/gameweek/board.py` | `build_gameweek_board()`, prompt formatter |
| `predictor/twitter.py` | Thread + full text from picks |
| `predictor/web/odds_solver.py` | `solve_target_ticket`, `TargetTicket` |
| `webapp/src/GameweekPanel.jsx` | Gameweek tab UI |
| `tests/fixtures/gameweek/**` | Recorded calendar JSON |
| `tests/test_gameweek_merge.py`, `tests/test_gameweek_board.py`, `tests/test_twitter_export.py`, `tests/test_odds_solver.py` | Unit tests |

**Modify:**

| Path | Change |
|------|--------|
| `predictor/web/schema.py` | `Scope.gameweek`, `CreateRunRequest.target_odds` |
| `predictor/web/tools.py` | Gameweek gate skip; Twitter export instead of SportyBet |
| `predictor/web/prompt.py` | Gameweek prompt + board inject |
| `predictor/web/runner.py` | Skip odds board on gameweek; run solver when `target_odds` set |
| `predictor/web/app.py` | `/api/gameweek/board`, `/api/runs/{id}/target-ticket`, twitter export fmt |
| `predictor/exports.py` | `write_twitter_exports` |
| `webapp/src/App.jsx` | Gameweek tab, target odds, Fill from board |
| Skill/README/env.example | Product docs |

---

### Task 1: Schema — gameweek scope and target_odds

**Files:**
- Modify: `predictor/web/schema.py`
- Test: `tests/test_web.py` (append class)

**Interfaces:**
- Consumes: existing `Scope`, `CreateRunRequest`
- Produces: `Scope.gameweek`; `CreateRunRequest.target_odds: float | None = None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
class TestGameweekSchema:
    def test_scope_accepts_gameweek(self):
        assert Scope("gameweek") == Scope.gameweek

    def test_target_odds_defaults_none(self):
        assert CreateRunRequest().target_odds is None

    def test_target_odds_accepted(self):
        req = CreateRunRequest(target_odds=8.0)
        assert req.target_odds == 8.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::TestGameweekSchema -v`
Expected: FAIL — `Scope` has no `gameweek`.

- [ ] **Step 3: Write the implementation**

In `predictor/web/schema.py`, add `gameweek = "gameweek"` to `Scope`.

On `CreateRunRequest`, after `book_overround`:

```python
    target_odds: float | None = Field(default=None, gt=1.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web.py::TestGameweekSchema -v`
Expected: PASS.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. Do not git commit.

---

### Task 2: Two-of-three merge (no HTTP)

**Files:**
- Create: `predictor/gameweek/__init__.py` (empty), `predictor/gameweek/types.py`, `predictor/gameweek/merge.py`
- Test: `tests/test_gameweek_merge.py`

**Interfaces:**
- Consumes: `normalize_team` from `predictor.odds.matching`
- Produces:
  - `RawFixture(source, league, home, away, kickoff_utc, round_label, finished)`
  - `GameweekFixture` and `GameweekBoard` as in the spec (`skipped` is `list[dict]` with `match` and `why` for JSON, not tuples)
  - `merge_raw_fixtures(raw: list[RawFixture], *, sources_up: int) -> GameweekBoard`

`sources_up` is the count of calendars that returned data (0–3), not the number of sources on one fixture.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gameweek_merge.py`:

```python
"""Two-of-three gameweek slate merge."""

from __future__ import annotations

from predictor.gameweek.merge import merge_raw_fixtures
from predictor.gameweek.types import RawFixture


def rf(source, home, away, kickoff="2026-08-29T14:00:00Z", finished=False, league="EPL", round_label="EPL GW3"):
    return RawFixture(
        source=source, league=league, home=home, away=away,
        kickoff_utc=kickoff, round_label=round_label, finished=finished,
    )


class TestTwoOfThree:
    def test_fotmob_and_fd_without_espn_is_included(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea"),
                rf("fotmob", "Arsenal", "Chelsea"),
            ],
            sources_up=3,
        )
        assert any(f.match == "Arsenal vs Chelsea" for f in board.fixtures)
        assert board.fixtures[0].unconfirmed_slate is False

    def test_espn_only_is_excluded_when_three_sources_up(self):
        board = merge_raw_fixtures(
            [rf("espn", "Arsenal", "Chelsea")],
            sources_up=3,
        )
        assert board.fixtures == []

    def test_finished_is_excluded(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", finished=True),
                rf("fotmob", "Arsenal", "Chelsea", finished=True),
            ],
            sources_up=2,
        )
        assert board.fixtures == []

    def test_kickoff_mismatch_is_skipped(self):
        board = merge_raw_fixtures(
            [
                rf("football-data", "Arsenal", "Chelsea", "2026-08-29T14:00:00Z"),
                rf("fotmob", "Arsenal", "Chelsea", "2026-08-29T17:00:00Z"),
            ],
            sources_up=2,
        )
        assert board.fixtures == []
        assert any("mismatch" in s["why"].lower() for s in board.skipped)

    def test_single_source_up_marks_unconfirmed(self):
        board = merge_raw_fixtures(
            [rf("espn", "Arsenal", "Chelsea")],
            sources_up=1,
        )
        assert len(board.fixtures) == 1
        assert board.fixtures[0].unconfirmed_slate is True

    def test_zero_sources_empty(self):
        board = merge_raw_fixtures([], sources_up=0)
        assert board.fixtures == []
        assert board.source_errors == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gameweek_merge.py -v`
Expected: FAIL — no module `predictor.gameweek.merge`.

- [ ] **Step 3: Write the implementation**

Create `predictor/gameweek/types.py`:

```python
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "leagues": list(self.leagues),
            "fixtures": [f.to_dict() for f in self.fixtures],
            "skipped": list(self.skipped),
            "source_errors": list(self.source_errors),
            "remaining": len(self.fixtures),
            "unconfirmed_slate": any(f.unconfirmed_slate for f in self.fixtures),
        }
```

Create `predictor/gameweek/merge.py` that:

- Groups raw rows by `(league, normalize_team(home), normalize_team(away))`.
- `sources_up >= 2`: keep a group only if `len(sources) >= 2` and not all finished; if all finished, drop (no skip row required). If two+ sources disagree on kickoff by more than 15 minutes, append skipped `{match, why: "kickoff mismatch"}`.
- `sources_up == 1`: include unfinished single-source rows with `unconfirmed_slate=True`.
- `sources_up == 0`: empty fixtures.
- Convert agreed `kickoff_utc` to Eastern display like `odds.board` (`America/New_York`, `%I:%M %p ET` with leading zero stripped).
- `round_label` from the first non-empty in the group.
- `fetched_at` ISO now; `leagues` unique display names in spec order: EPL, Bundesliga, La Liga, Serie A, Ligue 1.

Create empty `predictor/gameweek/__init__.py`.

Kickoff parse: `datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gameweek_merge.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

---

### Task 3: Calendar HTTP + `build_gameweek_board`

**Files:**
- Create: `predictor/gameweek/calendars.py`, `predictor/gameweek/board.py`, `scripts/record_gameweek_fixtures.py`
- Modify: `predictor/gameweek/__init__.py` re-exports
- Test: `tests/test_gameweek_board.py`
- Fixtures: `tests/fixtures/gameweek/` as needed (minimal synthetic JSON is enough if live record is inconvenient; parsers must accept the synthetic shape)

**Interfaces:**
- Consumes: `merge_raw_fixtures`, `RawFixture`
- Produces:
  - `fetch_football_data(league_code: str) -> list[RawFixture]` (raises internally, caller catches)
  - `fetch_fotmob(league_id: int, display: str) -> list[RawFixture]`
  - `fetch_espn(slug: str, display: str) -> list[RawFixture]`
  - `build_gameweek_board() -> GameweekBoard` — never raises
  - `format_gameweek_for_prompt(board: GameweekBoard) -> str`

League constants:

```python
LEAGUES = (
    ("EPL", "PL", "eng.1", 47),
    ("Bundesliga", "BL1", "ger.1", 54),
    ("La Liga", "PD", "esp.1", 87),
    ("Serie A", "SA", "ita.1", 55),
    ("Ligue 1", "FL1", "fra.1", 53),
)
```

HTTP:

- FD: `GET https://api.football-data.org/v4/competitions/{code}` then `.../matches?matchday={n}` with header `X-Auth-Token` from `FOOTBALL_DATA_API_KEY`. Missing key → treat FD as down (empty list + error string). Finished statuses: `FINISHED`, `AWARDED`.
- FotMob: `GET https://www.fotmob.com/api/leagues?id={id}`. Parse `fixtures.allMatches` or equivalent list of `{home.name, away.name, status.utcTime, status.finished}` — **inspect a recorded payload** and align keys; if the live shape differs, pin whatever the recorder captured.
- ESPN: `GET https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard` (and if the scoreboard is only “today”, also fetch `.../scoreboard?dates=` for the next 8 ET days and keep events whose `week.number` / `season.slug` matches the modal week). Finished: `status.type.state == "post"`. Prefer a **synthetic fixture** in tests via monkeypatch of the three `fetch_*` functions rather than depending on huge live dumps.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gameweek_board.py` that monkeypatches the three fetchers and asserts `build_gameweek_board()` never raises, two-of-three via merge, all-fetch-fail → empty fixtures + `source_errors`, and `format_gameweek_for_prompt` names remaining matches and says `unconfirmed slate` when flagged.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gameweek_board.py -v`
Expected: FAIL — missing `build_gameweek_board`.

- [ ] **Step 3: Write the implementation**

`calendars.py`: timeout 25s, User-Agent header, catch `requests` errors and return `([], "espn: timeout")` style errors from a wrapper `load_all() -> tuple[list[RawFixture], list[str], int]` where `sources_up` is how many of the three produced at least one raw row **or** a successful empty-but-200 parse of a known shape. A 403/401 on FD counts as down.

`board.py`:

```python
def build_gameweek_board() -> GameweekBoard:
    raw, errors, sources_up = load_all()
    board = merge_raw_fixtures(raw, sources_up=sources_up)
    board.source_errors = errors
    return board
```

Never raise.

`format_gameweek_for_prompt`: markdown list grouped by `round_label`, including `kickoff_et` and source names. If `unconfirmed_slate`, first line: `UNCONFIRMED SLATE — only one calendar responded.`

Re-export from `__init__.py`: `GameweekBoard`, `GameweekFixture`, `build_gameweek_board`, `format_gameweek_for_prompt`.

Optional `scripts/record_gameweek_fixtures.py` writes live JSON into `tests/fixtures/gameweek/` for later parser tightening. Tests must not call it.

- [ ] **Step 4–5: Pass focused + full suite**

---

### Task 4: Twitter export

**Files:**
- Create: `predictor/twitter.py`
- Modify: `predictor/exports.py` add `write_twitter_exports(picks, *, run_id, leagues_by_match=None)`
- Test: `tests/test_twitter_export.py`

**Interfaces:**
- Consumes: objects with `match`, `tip`, `league`, `confidence`, `estimated_probability`, `evidence` (list)
- Produces:
  - `LOW_CONF_THRESHOLD = 70`
  - `format_thread(picks) -> list[str]` each `len(s) <= 280`
  - `format_full(picks) -> str`
  - compact line: `{home or match} {tip} {pct}%` with ` · low conf` if confidence < 70
  - league header is `p.league` or `"Gameweek"`; first chunk of a league starts with that header
  - split between matches only
  - no `@` and no `odds` substring required-absent: assert `"@"` not in output and `"odds"` not in output.lower()

Use `match` as the team line if it contains `vs`: `Arsenal vs Chelsea` → still allowed; compact form in spec example is `Arsenal 2-1 Chelsea` i.e. `{home} {tip} {away} {pct}%`. Prefer splitting `match` on ` vs `.

- [ ] **Step 1–5:** TDD as usual. `write_twitter_exports` writes `{base}_gameweek_twitter.txt` and `{base}_gameweek_twitter_thread.txt` (thread chunks joined by `\n\n---\n\n`) under `.predictions/YYYY-MM-DD/` using the same date/run_id pattern as `write_exports_from_picks`.

---

### Task 5: Gameweek submit_picks + prompt

**Files:**
- Modify: `predictor/web/tools.py`, `predictor/web/prompt.py`
- Test: `tests/test_web.py` and/or `tests/test_verify.py` style submit helper

**Interfaces:**
- When `ctx.scope == Scope.gameweek`:
  - Do **not** call `verify_prices` (or call it with `board=None` and then ignore unpriced — spec says skip verify). Skip it.
  - Do **not** drop for `confidence < min_conf`.
  - Do **not** apply odds range or margin.
  - Still dedupe one pick per match.
  - Call `write_twitter_exports` instead of `write_exports_from_picks`. Set `ctx.export_paths` from twitter paths (`twitter_full`, `twitter_thread`).
- `build_prompt`: if `req.scope == Scope.gameweek`, take keyword `gameweek_board: GameweekBoard | None = None`. Workflow: one CS per remaining fixture, `price_available: false`, omit odds, full slate, LiveScore/FlashScore/Sofascore verification. Inject `format_gameweek_for_prompt`. Do not inject priced board or diversity scolding as the primary instruction (diversity N/A — all CS).

Existing `ticket_hint[req.ticket_mode.value]` will KeyError if we don't add a branch: **wrap ticket_hint in `if req.scope != Scope.gameweek`**.

- [ ] **Step 1:** Test a gameweek `submit_picks` with `estimated_probability` 0.18, `odds=None`, `price_available=False`, `confidence=65` is **accepted** even if request `min_confidence=75` and `margin_buffer=0.08`. Assert no `*_sportybet.csv` in `export_paths`.

- [ ] **Steps 2–5:** Implement, pytest green.

---

### Task 6: Gameweek API + runner board inject

**Files:**
- Modify: `predictor/web/app.py`, `predictor/web/runner.py`
- Test: `tests/test_web.py` `TestGameweekEndpoint`

**Interfaces:**
- `GET /api/gameweek/board` → `await asyncio.to_thread(build_gameweek_board)` then `to_dict()`. Never 500 on calendar failure (empty board + `source_errors`).
- `RunManager._execute`: if `request.scope == Scope.gameweek`, `odds_board = None`, `live_board = None`, `gw = await asyncio.to_thread(build_gameweek_board)`; if `not gw.fixtures and not gw.skipped` and sources all failed, still start the agent with the empty board text (agent submits empty picks + skipped) — spec says do not start agent if slate empty because zero sources. **If `sources_up==0` / no fixtures and no skipped unfinished: do not create an agent; mark run error `No calendar sources` and publish `type=error`.** If fixtures exist, `build_prompt(..., gameweek_board=gw)`.
- `start_run` for gameweek still requires API key.

Route registered test + monkeypatched board shape test (same TestClient pattern as odds board; keep route-registration always).

Twitter download: extend `/api/exports/{run_id}/{fmt}` so `fmt` in `twitter`, `twitter_thread` maps `meta.export_paths`.

- [ ] **Steps 1–5:** TDD, full suite.

---

### Task 7: Gameweek frontend

**Files:**
- Create: `webapp/src/GameweekPanel.jsx`
- Modify: `webapp/src/App.jsx`
- Then: `cd webapp && npm run build`

**UI (verbatim behaviour):**

- Nav includes `gameweek` (label **Gameweek**).
- Panel loads `/api/gameweek/board` on tab open: per-league remaining counts from fixtures grouped by `league` / `round_label`. Banner if `unconfirmed_slate`.
- **Generate scores** POST `/api/runs` `{ scope: "gameweek", model, min_confidence: 0, margin_buffer: 0, min_odds: 1.01, max_odds: 50, ticket_mode: "singles", markets: ["Correct score"], all_that_qualify: true }`.
- Reuse `connectEvents` / `RunLog`.
- Results grouped by `pick.league`. Row: match, tip, `(estimated_probability*100).toFixed(0)%`, first evidence, badge `low conf` if confidence < 70.
- Buttons **Copy thread** and **Copy full**: fetch `/api/exports/{runId}/twitter_thread` and `/api/exports/{runId}/twitter` as text, `navigator.clipboard.writeText`. Disabled when no picks.
- No SportyBet CSV links on this tab.

No new npm packages.

- [ ] **Step:** implement, `npm run build`, `python -m pytest tests/test_web.py::TestProjectLayout::test_static_frontend_built -v` and full suite.

---

### Task 8: Target-odds solver (pure)

**Files:**
- Create: `predictor/web/odds_solver.py`
- Test: `tests/test_odds_solver.py`

**Interfaces:**

```python
@dataclass
class TargetTicket:
    leg_indices: list[int]
    combined_odds: float | None
    joint_probability: float
    in_band: bool
    used_fill: bool
    label: str
    extra_picks: list[Pick]  # fill legs to append; empty on researched pass
```

```python
def solve_target_ticket(
    picks: list[Pick],
    target: float,
    *,
    band: float = 0.15,
    board: PricedBoard | None = None,
    fill: bool = False,
    min_odds: float = 1.10,
    max_odds: float = 5.0,
) -> TargetTicket: ...
```

Researched candidates: priced, not CS (`"correct score" in (market or tip).lower()` or `market_family == "specials"` with correct-score tip — simplest: skip if `market.lower() == "correct score"` or tip matches `^\d+-\d+$`). Cap 16 by confidence.

Enumerate subsets (bitmask). In-band: `target * (1-band) <= product <= target * (1+band)`. Tie-break fewer legs then higher joint prob. If none, closest `|log(product)-log(target)|`. Empty candidates → `leg_indices=[]`, `in_band=False`, `combined_odds=None`.

Fill: if researched already `in_band`, return it with `used_fill=False`. Else greedy add from board quotes in families `goals_totals`, `team_totals`, `btts`, odds in `[min_odds, max_odds]`, match not already used (`normalize_match_key(f"{home} vs {away}")`). Build extra `Pick`s as spec. Indices for extra picks are `len(picks) + i`.

- [ ] **Tests:** 1.25*1.30*2.10 ≈ 3.41 not 8; construct odds `[1.40, 1.50, 1.60, 2.20]` and target `8` so a subset hits (1.5*1.6*2.2*1.4=7.392, within 8*0.85=6.8). Prefer 3 legs over 4 if both in band. Fill adds a quote for a new match and never duplicates. CS quote on board is ignored.

- [ ] **Steps 2–5:** implement, suite green.

---

### Task 9: Wire solver into runner + target-ticket endpoint

**Files:**
- Modify: `predictor/web/runner.py`, `predictor/web/app.py`, `predictor/web/tools.py` (after gameweek accept, if not gameweek and `request.get("target_odds")`, do **not** solve inside the tool — runner solves after agent completes using `read_result`).
- Test: unit-test the endpoint with monkeypatched solver / in-memory result if TestClient is heavy; always register `POST /api/runs/{id}/target-ticket`.

**Behaviour:**

After a successful non-gameweek `_execute` / `refine_run` where `ctx.accepted` and `request.target_odds`:

```python
from predictor.web.odds_solver import solve_target_ticket
result = read_result(run_id)
ticket = solve_target_ticket(result.picks, float(request.target_odds), fill=False, min_odds=..., max_odds=...)
result.suggested_tickets = [SuggestedTicket(
    type="acca",
    legs=ticket.leg_indices,
    combined_odds=ticket.combined_odds,
    joint_probability=ticket.joint_probability,
    label=ticket.label or f"Target {request.target_odds:g}× (researched)",
)]
write_result(run_id, result)
```

`POST /api/runs/{run_id}/target-ticket` body `{ "fill": true }`: 404 if no result; 400 if no `target_odds` on stored request; run `solve_target_ticket(..., fill=True, board=run_manager._boards.get(run_id) or rebuild)`. If `extra_picks`, append to `result.picks` then remap legs. `used_fill` label `Target {n}× (board fill)`.

Need a small Pydantic model `TargetTicketRequest(fill: bool = False)`.

- [ ] **Steps 1–5:** TDD route exists; fill refuses when no board and rebuild returns empty (still 200 with `in_band` false, no crash).

---

### Task 10: Generate UI — target odds + Fill from board

**Files:**
- Modify: `webapp/src/App.jsx`
- Then `npm run build`

**UI:**

- Number input **Target odds** (empty default). Include in POST body as `target_odds: targetOdds || null`.
- After result, if `suggested_tickets[0]`, `setSelected(new Set(t.legs))`.
- If suggested ticket exists and (no `in_band` field on ticket — **add** `in_band` onto `SuggestedTicket` schema in this task if missing: `in_band: bool | None = None`) is `False`, show **Fill from board**.
- Spec `SuggestedTicket` did not include `in_band`. **Add** `in_band: bool | None = None` and `used_fill: bool = False` so the UI does not guess.

Fill button: `POST /api/runs/${runId}/target-ticket` `{fill:true}`, replace `result`, reselect legs.

- [ ] **Also** persist `in_band`/`used_fill` on `SuggestedTicket` in `schema.py` with tests in `TestGameweekSchema` or a small new class.
- Build frontend, full pytest.

---

### Task 11: Documentation

**Files:**
- Modify: `.cursor/skills/soccer-predictions/SKILL.md`, `.cursor/commands/predictions-correct-score.md`, `.cursor/skills/soccer-predictions/run-schema.md`, `.cursor/rules/soccer-prediction-core.mdc`, `README.md`, `.env.example`

**Copy to add (do not rewrite betting CS command):**

SKILL table row:

`| Web Gameweek tab | Full-slate correct scores for EPL/Bundesliga/La Liga/Serie A/Ligue 1 | core + gameweek board (two-of-three calendars) |`

predictions-correct-score.md add: `The web **Gameweek** tab is a different product: every remaining Big-5 matchday fixture gets a score for Twitter. This command stays 1–2 gated betting singles.`

Core evidence price bullet stays board-based; add under true skips that Gameweek membership needs two calendars.

README: Gameweek tab, Twitter copy, `FOOTBALL_DATA_API_KEY`, Target odds + Fill from board.

`.env.example`: `# FOOTBALL_DATA_API_KEY=`

- [ ] Full suite still green.

---

## Spec coverage (self-review)

| Spec section | Task |
|--------------|------|
| A matchday helper / two-of-three | 2, 3 |
| B gameweek runs / gates / tab | 1, 5, 6, 7 |
| C Twitter | 4, 7 |
| D solver + fill | 8, 9, 10 |
| E API | 6, 9 |
| F docs | 11 |
| G tests | 2–10 |
| Unconfirmed slate / zero sources | 2, 3, 6 |
| No ESPN-only authority | 2 |
| No SportyBet CSV on gameweek | 5 |
| `low conf` < 70 | 4, 7 |
| Fill families | 8 |
