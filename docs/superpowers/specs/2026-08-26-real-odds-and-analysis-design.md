# Real odds, analysis runs, and market diversity

**Date:** 2026-08-26
**Status:** Approved

## Problem

Three defects, one shared root cause.

**Odds are fabricated.** `sportybet.com` answers every programmatic request with an empty `202` (bot challenge), including the plain HTML page. The agent has never read the book. It estimates a price and labels it `"book": "SportyBet ng"`.

The estimate is biased upward by the run's own filter. `predictor/web/tools.py` rejects any pick priced below `min_odds`, so the agent prices to clear the gate. In run `2026-08-26_10-45-53_today` (`min_odds` 1.30), nine of twelve legs came back at exactly 1.30. Measured against the real book:

| Pick | Agent | SportyBet |
|---|---|---|
| Lyon–Fenerbahce Over 1.5 | 1.40 | 1.25 |
| Viking–Dinamo Over 1.5 | 1.40 | 1.18 |
| Celje–Slovan Over 1.5 | 1.36 | 1.33 |
| AEK Athens over 0.5 | 1.30 | 1.15 |
| Newcastle–WBA Over 1.5 | 1.30 | 1.16 |

The ticket was advertised at 20.07x. The real combined price was roughly a quarter of that.

**Analysis is manual.** `.analysis/MASTER.md` is only refreshed by running the `/predictions-analysis` chat command by hand. Nothing in the web app triggers it, so priors drift stale.

**Markets are monotonous.** Almost every pick is a goals market. Partly `MASTER.md` favours them on hit rate, but mostly they are the only markets the agent felt able to price by guessing. Corners, handicaps, DNB, BTTS and half-markets were effectively unbettable. The hit-rate table then reinforces itself, because only goals markets accumulate samples.

## Solution overview

Pinnacle publishes a free, unauthenticated odds feed at `guest.api.arcadia.pinnacle.com` that is not bot-blocked. Verified against the real SportyBet prices above, it lands within about 0.02 on every one, and it covers every market this product uses.

The server fetches prices, builds a **priced market board**, hands it to the agent in the prompt, and re-verifies every submitted pick against it. Odds become server-supplied facts rather than agent claims. That fixes the pricing defect directly and the market-diversity defect as a side effect.

## Goals

1. Every published price traces to a real market quote, not an estimate.
2. Displayed odds approximate SportyBet, so advertised combined odds are honest.
3. The agent can research non-goals markets on equal footing with goals markets.
4. Analysis runs from a button in the web app and updates `MASTER.md`.

## Non-goals

- Scraping SportyBet itself. It is bot-protected; a headless browser is out of scope.
- Automated bet placement.
- Server-side rejection of picks on market-family grounds. Diversity is prompt guidance only.
- Reworking the legacy CLI (`predict.py`, `fetchers.py`, `aggregator.py`).

## A. `predictor/odds/` package

New package, no dependencies on `predictor.web`.

### `pinnacle.py`

Isolates all Pinnacle contact. If it fails, callers degrade to "no price" rather than raising.

```python
PINNACLE_BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
SOCCER_SPORT_ID = 29
GUEST_API_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"  # public guest key, overridable via env
```

| Function | Returns |
|---|---|
| `list_matchups()` | `list[PinnacleMatchup]` for soccer, all upcoming |
| `straight_markets(matchup_id)` | raw market list (totals, team totals, spreads, moneyline) |
| `related(matchup_id)` | related matchups: specials, corners, bookings |
| `american_to_decimal(price)` | decimal odds |

`PinnacleMatchup` carries `id`, `parent_id`, `league`, `home`, `away`, `start_time_utc`, and `kind` (`main` / `corners` / `bookings` / `special`), derived from the league name suffix and `special.description`.

Caching: in-process TTL of 90 seconds keyed by URL, plus an on-disk mirror under `.cache/odds/` used only as a same-process fallback when a request fails. The cache is disposable; nothing depends on it surviving a restart.

### `quotes.py`

Normalizes Pinnacle's shapes into one vocabulary the rest of the app speaks.

```python
@dataclass(frozen=True)
class MarketQuote:
    family: str        # goals_totals | team_totals | btts | result | dc_dnb
                       # | handicap | corners | halves | specials
    market: str        # "Over/Under 1.5", "Team total 0.5", "Draw no bet", ...
    tip: str           # "Over 1.5 goals", "Everton over 0.5 goals", "BTTS Yes"
    line: float | None
    side: str | None   # home | away | None
    period: int        # 0 = full time, 1 = first half
    odds: float        # decimal, after the soft-book adjustment
    raw_odds: float    # decimal, straight from Pinnacle
    fair_probability: float
    source_key: str    # Pinnacle market key, for debugging
```

Coverage mapped from the feed, all confirmed present on a live fixture:

| Family | Source | Examples |
|---|---|---|
| `goals_totals` | straight `total`, period 0 | Over/Under 1.5 through 4.5, quarter lines |
| `team_totals` | straight `team_total`, period 0 | team over 0.5 / 1.5 / 2.5 |
| `halves` | straight `total` / `team_total`, period 1 | 1H Over 0.5, 1H team over 0.5 |
| `result` | straight `moneyline`, period 0 | home / draw / away |
| `handicap` | straight `spread` | AH -1.5 through +1.5 including quarter lines |
| `dc_dnb` | specials `Draw No Bet`, `Double Chance` | 1X, X2, 12, DNB home/away |
| `btts` | specials `Both Teams To Score?` | Yes / No |
| `corners` | related matchup, league suffix `Corners` | corner totals, corner handicap |
| `specials` | remaining specials | win to nil, team to score, HT/FT, correct score |

`tip` strings must match the vocabulary already used in `.cursor/skills/soccer-predictions/markets.md` and the historical `run.json` files, so `MASTER.md` market rows stay comparable across the change.

### `pricing.py`

Pinnacle is a sharp book with roughly 4.8% overround. SportyBet is soft. Empirically the two agree on heavy favourites and diverge on longer prices, which is exactly the shape produced by loading margin onto longshots. So: strip Pinnacle's vig, then re-apply a soft-book overround using the odds-ratio method.

```python
def odds_ratio(p: float, c: float) -> float:
    return (c * p) / (c * p - p + 1)

def solve_c(probs: Sequence[float], target_sum: float) -> float:
    """Bisection for c such that sum(odds_ratio(p, c)) == target_sum."""

def devig(raw_decimals: Sequence[float]) -> list[float]:
    """Solve for c < 1 that normalizes implied probabilities to 1.0."""

def revig(fair: Sequence[float], target_overround: float) -> list[float]:
    """Solve for c > 1 that inflates fair probabilities to the target overround."""
```

Default target overrounds, overridable per family by env var:

| Family | Overround |
|---|---|
| `goals_totals`, `team_totals`, `halves`, `btts`, `handicap` | 1.055 |
| `result`, `corners` | 1.070 |
| `dc_dnb` | 1.060 |
| `specials` | 1.150 |

Calibration check against the reference prices, using 1.055 on two-way totals:

| Pick | Pinnacle raw | Model | SportyBet | Error |
|---|---|---|---|---|
| Lyon Over 1.5 | 1.237 | 1.232 | 1.25 | −0.018 |
| Viking Over 1.5 | 1.181 | 1.176 | 1.18 | −0.004 |
| Celje Over 1.5 | 1.324 | 1.319 | 1.33 | −0.011 |

All three err low, which is the safe direction: advertised combined odds understate rather than overstate.

### `matching.py`

Maps an agent-written match string like `"Viking FK vs Dinamo Zagreb"` to a Pinnacle matchup.

- Normalize: strip accents, lowercase, drop club-noise tokens (`fc`, `cf`, `sk`, `nk`, `gnk`, `afc`, `united` kept, `city` kept).
- Split on `vs` / `v` / `-`.
- Score home and away separately with `difflib.SequenceMatcher`; require both above 0.72 and the combined above 0.80.
- Constrain candidates to kickoffs within ±36 hours of the run's scope window, which removes almost all cross-fixture collisions (for example the three separate `Dinamo Zagreb` fixtures visible in one feed).
- Unmatched names are logged to the run log so coverage gaps are visible.

### `board.py`

```python
@dataclass
class BoardFixture:
    league: str
    home: str
    away: str
    kickoff_utc: str
    kickoff_et: str
    matchup_id: int
    quotes: list[MarketQuote]

@dataclass
class PricedBoard:
    fixtures: list[BoardFixture]
    fetched_at: str
    errors: list[str]

def build_board(scope, *, min_odds, max_odds, markets, hours_window=None,
                target_date=None) -> PricedBoard: ...

def format_board_for_prompt(board: PricedBoard, max_fixtures: int = 60) -> str: ...
```

The prompt formatter emits compact markdown: one block per fixture, quotes filtered to the user's odds range and selected market families, grouped by family. Fixtures are capped and the cap is stated in the text so the agent knows the board is truncated rather than complete.

## B. Schema changes

`predictor/web/schema.py`:

```python
class Pick(BaseModel):
    ...
    odds: float | None = Field(default=None, gt=1.0)      # book price, server-verified
    quoted_odds: float | None = None                       # what the agent claimed
    price_source: str = "unpriced"                         # pinnacle | unpriced
    market_family: str = ""                                # set by the server
    book: str = "SportyBet ng (modelled)"
```

The `odds_when_price_available` validator is retained, but `tools.py` now sets `price_available` from board resolution rather than trusting the agent.

`CreateRunRequest` gains `book_overround: dict[str, float] | None = None` for per-run override of the pricing defaults. It is not surfaced in the UI initially.

## C. Prompt changes

`predictor/web/prompt.py` gains three blocks.

**Priced board.** Rendered for every non-live scope, and for live scopes alongside the existing ESPN board.

**Price discipline.** Replaces the current "verify prices on SportyBet ng" instruction:

> Prices come from the board below. Do not invent, estimate, or carry over a price from a tip site. Set `odds` to the exact number on the board for the market you choose. If the market you want is not on the board, either choose a market that is, or publish with `price_available: false` and no odds.

**Market diversity.** The server computes the market-family mix over the last five completed runs and injects it:

> Your last 5 runs published 82% goals-market picks. Every family on the board carries a real price, so non-goals markets are now researchable. Aim for no more than half your picks from one family and at least three families when the slate supports it. MASTER hit rates are sample-biased: goals markets look best partly because they are nearly the only markets with samples.

## D. `submit_picks` changes

`predictor/web/tools.py`, after Pydantic validation and before the existing gates:

1. Resolve each pick to a `BoardFixture` via `matching.py`, then to a `MarketQuote` via the pick's `market` and `tip`.
2. On a hit: move the agent's number to `quoted_odds`, set `odds` to the quote, set `price_source = "pinnacle"`, `market_family`, `price_available = True`.
3. On a miss: `price_available = False`, `odds = None`, `price_source = "unpriced"`. The pick still publishes — the research is the product, the user sources the price. This applies to pre-match as well as live, which is a deliberate change from the current "no price, no pick" rule.
4. Run the existing confidence, odds-range and margin gates against the verified price. Unpriced picks pass on confidence alone, as live picks do today.
5. Record every overwrite in the run log with both numbers, so drift is auditable.

The board is fetched once per run in `runner.py` and passed into `SubmitPicksContext`, so the prompt and the verifier see identical prices and a refine call re-uses the same snapshot.

`predictor/exports.py` is unchanged: unpriced picks stay out of the SportyBet CSV, because a bet slip needs a price.

## E. Analysis runs

New `predictor/web/analysis_runner.py`.

**Ledger.** `.analysis/graded_runs.json` records which run ids have been folded into `MASTER.md`:

```json
{"graded": [{"run_id": "...", "graded_at": "...", "report": ".analysis/2026-08-26_10-45-00.md"}]}
```

**Candidate selection.** `ungraded_runs()` returns completed runs, not in the ledger, whose latest `kickoff_et` is more than three hours past — long enough for a 90-minute match plus stoppage and reporting lag.

**Agent.** `AnalysisManager.start()` mirrors `RunManager` but differs in two ways: `disallowed_tools=["shell"]` so the `edit` tool is available for writing `.analysis/*.md` and `MASTER.md`, and the prompt is built from the existing `/predictions-analysis` workflow with the candidate run ids injected. It streams to the same `bus`, under a run id of the form `analysis_<timestamp>`, with its own directory under `.runs/` for `meta.json` and `agent.log`.

On success the manager appends to the ledger.

**Endpoints** in `predictor/web/app.py`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/analysis/status` | `{ ungraded: [run_id], running: bool, last_graded_at }` |
| `POST` | `/api/analysis/run` | starts a run, returns `{ run_id }` |

SSE reuses `/api/runs/{run_id}/events`.

Only one analysis run at a time; a second `POST` while one is active returns 409.

## F. Frontend

`webapp/src/AnalysisPanel.jsx`:

- A "Run analysis" button showing the ungraded count, disabled while running.
- A live log pane reusing the SSE rendering from the Generate tab, extracted into a shared `RunLog` component rather than duplicated.
- On completion, re-fetch `/api/analysis` so MASTER refreshes in place.

`webapp/src/App.jsx`:

- `PickCard` shows price provenance. When `quoted_odds` differs from `odds`, render the book price with a small note that the agent's estimate was corrected. When `price_source === "unpriced"`, keep the existing "No live price" treatment.
- The footer combined-odds calculation is unchanged; it already skips unpriced legs, and it now multiplies verified prices.

## G. Documentation updates

- `.cursor/rules/soccer-prediction-core.mdc` — replace "No price = no pick" with the board rule and the unpriced-publish policy; replace the SportyBet verification step with "use the board price".
- `.cursor/skills/soccer-predictions/markets.md` — same, plus a note that MASTER hit rates are sample-biased toward goals markets.
- `.cursor/skills/soccer-predictions/run-schema.md` — document `quoted_odds`, `price_source`, `market_family`, and that the server overwrites `odds`.
- `.analysis/MASTER.md` usage section — note the exploration quota and that historic odds before this change are unreliable, so pre-change PnL figures should not be compared with post-change ones.
- `README.md` — the odds source and the Analysis button.

## H. Testing

Network is not touched in tests. Real Pinnacle payloads for the 2026-08-26 fixtures are recorded to `tests/fixtures/pinnacle/` and replayed.

| Test | Asserts |
|---|---|
| `test_pricing.py` | `american_to_decimal` round-trips; `devig` sums to 1.0; `revig` hits the target overround; the three calibration fixtures land within ±0.03 of the recorded SportyBet prices |
| `test_quotes.py` | a recorded fixture yields quotes in every expected family with correct tip strings and lines |
| `test_matching.py` | "Viking FK vs Dinamo Zagreb" resolves to the UCL qualifier and not the HNL fixture; unmatched names return `None` rather than a wrong fixture |
| `test_board.py` | odds-range and market filters apply; prompt formatting stays under the fixture cap |
| `test_tools.py` | an inflated quote is overwritten with the board price and `quoted_odds` retains the original; a pick whose true price fails the margin gate is rejected; an unresolvable fixture publishes unpriced |
| `test_analysis_runner.py` | `ungraded_runs()` excludes ledger entries and runs whose kickoffs have not passed; a second concurrent start is refused |

## I. Risks

| Risk | Mitigation |
|---|---|
| Pinnacle rotates the guest key or changes the endpoint | All contact isolated in `pinnacle.py`; env override for the key; failure yields an empty board and unpriced picks, never a failed run |
| Fixture outside Pinnacle coverage (women's qualifiers, NCAA, minor cups) | Publishes unpriced; the board formatter lists uncovered fixtures so the agent knows why |
| Name-matching false positive attaches the wrong price | Dual-threshold scoring plus a ±36h kickoff constraint; unmatched is preferred over mismatched |
| Soft-book model drifts from SportyBet | `quoted_odds` and `raw_odds` are both retained, so analysis runs can measure error and the overrounds are env-tunable without a code change |
| Analysis agent has `edit` access to the repo | `shell` stays disallowed; the prompt scopes writes to `.analysis/` |
