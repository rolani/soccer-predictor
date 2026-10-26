# Gameweek correct scores and target-odds tickets

**Date:** 2026-08-26  
**Status:** Approved

## Problem

Two product gaps, independent of the priced-board work.

**No Big-5 scorecard.** The existing `/predictions-correct-score` path publishes 1–2 gated singles because MASTER correct-score hit rate is ~25%. There is no way to produce a full-round card (score, probability, evidence) for EPL, Bundesliga, La Liga, Serie A, and Ligue 1 that can be pasted to Twitter.

**Target combined odds are a range, not a number.** Generate already has acca combined min/max, but there is no “make this 8×” control that selects a subset of researched legs and, if that fails, fills from the priced board.

## Solution overview

Two surfaces on the existing web app and `RunManager`.

1. **Gameweek tab** — a dedicated content run. A multi-source matchday helper builds the current official round for the five leagues. An agent fills every remaining fixture with one correct score, a probability, and 1–2 evidence lines. Export is Twitter copy, not a SportyBet CSV. Betting odds/margin gates are off.
2. **Target odds on Generate** — optional number on a normal researched run. A server solver (not a new agent) picks a subset of priced researched legs within ±15% of the target. **Fill from board** adds unresearched priced markets only when the researched subset cannot hit the band.

They do not share gates. Gameweek is a full-slate poster. Target odds is an honest-first acca builder.

## Goals

1. One button produces a complete remaining-round correct-score card for the five leagues, with % and evidence on every line.
2. Thin cases still publish, marked `low conf` (confidence < 70).
3. Twitter export is copy-paste (thread chunks ≤280 characters, plus a full text with evidence). No odds on the tweet.
4. Matchday membership is never ESPN-only: a fixture must appear on at least two of football-data.org, FotMob, and ESPN.
5. User can type a target combined price; the app selects researched legs that add up to it, with optional board fill.

## Non-goals

- Automated bet placement.
- Poisson-only / no-agent scores.
- Live in-play correct-score gameweek.
- Rewriting MASTER priors this pass (CS remains a weak betting market; the card is content).
- Scraping FlashScore/SportyBet (bot-blocked). FlashScore stays an **agent** verification source.
- Changing the one-pick-per-match rule.
- Using correct-score lines as acca fill legs.

## Decisions already locked

| Topic | Choice |
|--------|--------|
| CS coverage | Full remaining slate, not gated skips |
| Round window | Official current matchday per league; finished matches skipped |
| Tweet line | Score + % + evidence; `low conf` tag; **no odds** |
| Odds finder | Researched picks first; Fill from board if the band cannot be hit |
| Architecture | New Gameweek tab + solver on Generate (not bolted onto betting gates) |
| Slate authority | Two-of-three: football-data.org, FotMob, ESPN |

---

## A. Matchday helper — `predictor/gameweek.py`

Isolated from `predictor.web`. HTTP for the three calendars lives here (and only here), same pattern as `live_fixtures.py` / `odds/pinnacle.py`.

### League set

| Display | football-data.org | ESPN slug | FotMob |
|---------|-------------------|-----------|--------|
| EPL | `PL` | `eng.1` | Premier League |
| Bundesliga | `BL1` | `ger.1` | Bundesliga |
| La Liga | `PD` | `esp.1` | LaLiga |
| Serie A | `SA` | `ita.1` | Serie A |
| Ligue 1 | `FL1` | `fra.1` | Ligue 1 |

### Sources

1. **football-data.org** — `currentMatchday` on the competition, then matches for that matchday. Token via `FOOTBALL_DATA_API_KEY` (optional; if missing, this source is treated as down).
2. **FotMob** — current-round fixtures for the same five leagues. Parser pinned to recorded payloads in `tests/fixtures/gameweek/fotmob/`. HTTP failure or unexpected shape counts as this source **down**.
3. **ESPN** — `site.api.espn.com` soccer scoreboard/schedule for the slugs above (already used for live).

Any source that 4xx/5xx/timeouts is **down**, not fatal.

### Inclusion rule

For each league, compute that source’s current round number independently. A fixture is **on the slate** when:

- at least **two** sources list it in their current round, **and**
- it is not finished (`FT` / `AET` / `PEN` / ESPN `post`).

Kickoff Eastern is locked when two sources agree within **15 minutes**. Opponent or time mismatch → `skipped` with why `kickoff mismatch`, not a guessed time.

Postponed / TBD that still belong to the round: on the slate as skipped (`kickoff unconfirmed`).

### Degrade

| Sources up | Behaviour |
|------------|-----------|
| 2 or 3 | Normal two-of-three rule |
| 1 | Still build a slate from that source; every pick must be tagged **unconfirmed slate** in the prompt and UI |
| 0 | Empty slate, **do not** start an agent |

### Agent verification (not server HTTP)

Prompt still requires LiveScore, FlashScore, and Sofascore checks for form/H2H/injuries, matching live-fixtures policy. Those sites are not server-fetched.

### Types

```python
@dataclass
class GameweekFixture:
    league: str           # display name
    round_label: str      # e.g. "EPL GW3"
    match: str            # "Home vs Away"
    home: str
    away: str
    kickoff_et: str
    sources: list[str]    # which calendars agreed
    unconfirmed_slate: bool

@dataclass
class GameweekBoard:
    fetched_at: str
    leagues: list[str]
    fixtures: list[GameweekFixture]
    skipped: list[tuple[str, str]]  # match, why
    source_errors: list[str]
```

`GET /api/gameweek/board` returns `GameweekBoard.to_dict()` for the tab header (round numbers + counts) without starting an agent.

Tests replay recorded payloads under `tests/fixtures/gameweek/`. No live network in tests.

---

## B. Gameweek runs

### Request

`CreateRunRequest` gains nothing required for Gameweek besides:

- `scope: gameweek` (new `Scope` value)
- `ticket_mode` ignored for gates; treat as content singles
- `markets` forced to correct score in the prompt

`make_run_id("gameweek")` → `YYYY-MM-DD_HH-MM-SS_gameweek`.

Gameweek runs **do not** fetch a Pinnacle priced board (no odds on the card). Target-odds Generate runs still fetch the board once, as today.

### Prompt

Inject the `GameweekBoard` (remaining fixtures only). Instructions:

- Exactly one correct score per remaining fixture.
- `tip` is the scoreline (`2-1`), `market` is `Correct score`.
- `estimated_probability` is the fair chance of **that score** (0–1).
- `evidence` is 1–2 bullets with numbers (form, H2H, xG, injuries).
- `confidence` 0–100; UI/export treat `< 70` as `low conf`.
- Set `price_available: false` and omit `odds` (content product).
- Do not skip a match for weak evidence — publish and let confidence reflect it.
- List finished/mismatch/unconfirmed kickoffs in `skipped`.

### `submit_picks` for `scope=gameweek`

After validation and one-per-match dedupe:

- **Do not** apply min_odds, max_odds, or margin buffer.
- Confidence floor **does not drop** lines (full slate). Still store `confidence`.
- Do **not** write SportyBet CSV/TXT search files. Write Twitter text instead (see C).
- `verify_prices` is skipped (no book price on the card).

### Frontend — Gameweek tab

Nav: Generate · History · Analysis · **Gameweek**.

On open: `GET /api/gameweek/board` shows per-league round label and remaining count.

**Generate scores** → `POST /api/runs` with `scope=gameweek`. SSE log reused (`RunLog`).

Results grouped by league. Row: match, score (`tip`), `(p*100)%`, first evidence line, `low conf` badge if confidence < 70. Unconfirmed-slate banner if the board was single-source.

Skipped block unchanged.

---

## C. Twitter export

`predictor/exports.py` (or a small `predictor/twitter.py` used by exports) formats a completed gameweek `RunResult`.

**Copy thread** — list of strings, each ≤280 characters:

```
EPL GW3
Arsenal 2-1 Chelsea 18%
Liverpool 1-1 Man City 14% · low conf
```

League header on the first chunk of that league. Split between matches, never mid-line. No odds. `low conf` suffix when confidence < 70. Probability is integer percent from `estimated_probability`.

**Copy full** — one string: same scores plus the evidence bullet(s) under each match, for a screenshot or long post.

UI: two buttons. Empty picks → buttons disabled / copy is a no-op.

Also persist `export_paths.twitter_thread` and `export_paths.twitter_full` as `.txt` under `.predictions/YYYY-MM-DD/` for History download. Filenames `*_gameweek_twitter.txt` and `*_gameweek_twitter_thread.txt`.

---

## D. Target-odds solver — `predictor/web/odds_solver.py`

Pure functions. No HTTP. No agent.

```python
def solve_target_ticket(
    picks: list[Pick],
    target: float,
    *,
    band: float = 0.15,
    board: PricedBoard | None = None,
    fill: bool = False,
    min_odds: float,
    max_odds: float,
) -> TargetTicket
```

`TargetTicket`: `leg_indices` (into the picks list, and/or synthetic fill picks appended), `combined_odds`, `joint_probability`, `in_band: bool`, `used_fill: bool`, `label`.

### Researched pass (`fill=False`)

Candidates: `price_available` and `odds` set; not correct-score (`market` / `market_family` / tip). One pick per match already guaranteed.

Search subsets (n is small; cap at 16 highest-confidence priced legs if longer). Keep subsets whose product `P` satisfies `target * (1-band) <= P <= target * (1+band)`. Tie-break: fewer legs, then higher joint probability (`product of estimated_probability`).

If none in band: return the closest product as `in_band=False` (still a ticket the UI can show).

### Fill pass (`fill=True`)

Start from the researched result (in-band or closest). If already in band, return it unchanged.

Otherwise add quotes from `board` for fixtures **not** already on the ticket:

- `min_odds <= odds <= max_odds`
- families `goals_totals`, `team_totals`, `btts` only (no correct score, specials, or 1X2)
- one per match

Greedy: repeatedly add the quote that brings the running product closest to `target` without exceeding `target * (1+band)` if possible; stop when in band or no unused quotes remain.

Fill legs are appended as `Pick`s with `reasoning` starting with `unresearched board fill`, `confidence` 50, `evidence` `["Board price only — not researched."]`, `price_source=pinnacle`, `odds` copied from the board quote (never invented).

**Wiring (mandatory):** the research agent does not hit the target. After `submit_picks` accepts a non-gameweek run with `target_odds` set, the runner calls `solve_target_ticket(..., fill=False)` and writes `suggested_tickets`. **Fill from board** is only `POST /api/runs/{id}/target-ticket` with `{ "fill": true }`, which may append fill picks to `run.json` and rewrite `suggested_tickets`. Use the in-memory board snapshot if present, else rebuild `build_board` for the original request window.

### Request / UI

`CreateRunRequest.target_odds: float | None = None` (`gt=1.0` when set).

Generate form: **Target odds** number, empty by default. When set, after the run completes the server stores `suggested_tickets` from the researched pass. Checkboxes select those legs.

If `in_band` is false, show the closest ticket and enable **Fill from board**. That calls `POST /api/runs/{id}/target-ticket` with `fill=true`, using the run’s stored board snapshot if still in `RunManager._boards`, else rebuild via `window_for_scope` + `build_board`.

Blank `target_odds`: no solver. Existing `target_combined_odds_min/max` still passed to the agent as today.

---

## E. Schema and API

| Change | Detail |
|--------|--------|
| `Scope.gameweek` | New |
| `CreateRunRequest.target_odds` | `float \| None` |
| `Pick` | No new required fields; `low conf` is `confidence < 70` |
| `GET /api/gameweek/board` | Slate preview |
| `POST /api/runs` | Already exists; `scope=gameweek` or `target_odds` set |
| `POST /api/runs/{id}/target-ticket` | `{ "fill": bool }` → updated result + suggested ticket |
| `GET /api/exports/{id}/twitter` | `?kind=thread\|full` |

`SuggestedTicket.label` examples: `Target 8× (researched)`, `Target 8× (board fill)`.

---

## F. Documentation

- `.cursor/skills/soccer-predictions/SKILL.md` — product row for Gameweek (full-slate CS, not the 1–2 singles command).
- `.cursor/commands/predictions-correct-score.md` — leave the **betting** 1–2 singles command unchanged; add one line pointing Gameweek UI to the full-slate product.
- `run-schema.md` — `scope=gameweek`, `target_odds`, Twitter export, solver.
- `README.md` — Gameweek tab, `FOOTBALL_DATA_API_KEY`, target odds + Fill from board.
- `.env.example` — optional `FOOTBALL_DATA_API_KEY`.
- Core rule: Gameweek kickoffs verified on two calendars plus LiveScore/FlashScore/Sofascore; ESPN is not sole authority.

---

## G. Testing

Network is not touched. Record football-data, FotMob, and ESPN round payloads.

| Test | Asserts |
|------|---------|
| `test_gameweek_board.py` | Two-of-three includes a fixture listed on FotMob+FD but not ESPN; ESPN-only fixture excluded; finished excluded; kickoff mismatch skipped; one source up → `unconfirmed_slate`; zero sources → empty, no raise |
| `test_twitter_export.py` | Compact lines, integer %, `low conf` suffix, no `@` odds, each thread chunk ≤280, split on match boundaries |
| `test_odds_solver.py` | Known set hits 8× inside ±15%; prefers fewer legs; closest when none in band; fill adds a board quote and refuses duplicate match; fill ignores correct-score quotes; blank target not tested here (API) |
| `test_web.py` | `scope=gameweek` skips margin/odds gates; gameweek run does not write `*_sportybet.csv`; `/api/gameweek/board` route registered |

---

## H. Risks

| Risk | Mitigation |
|------|------------|
| FotMob or football-data.org change/block | Isolate HTTP; one-source degrade with `unconfirmed_slate`; empty only if all three fail |
| football-data.org rate limit / missing key | Source counts as down; ESPN+FotMob still two-of-three |
| Agent omits a remaining fixture | Gaps go to `skipped`; Twitter exports what was submitted |
| 50-match CS run is slow / expensive | One run, compact schema, no odds verification; user can cancel |
| Fill from board looks like research | Explicit `unresearched` reasoning + UI tag |
| Solver explosion | Cap researched candidates at 16 |
