# Run output schema (submit_picks)

Web app runs end with one call to the **`submit_picks`** custom tool. Chat runs may also follow this shape when saving JSON to `.runs/`.

## Top-level fields

| Field | Required | Description |
|-------|----------|-------------|
| `run_id` | yes | Matches the run folder id |
| `scope` | yes | `live`, `today`, `tomorrow`, `window`, `date`, or `gameweek` |
| `generated_at` | yes | ISO timestamp |
| `summary` | yes | 1–3 sentence overview of the slate |
| `picks` | yes | Array of researched picks (may be empty) |
| `skipped` | no | Fixtures considered but not published |
| `suggested_tickets` | no | Optional acca/hybrid suggestions referencing pick indices |

## Pick object

| Field | Required | Description |
|-------|----------|-------------|
| `league` | no | Competition name |
| `match` | yes | `Home vs Away` |
| `kickoff_et` | no | Eastern kickoff time |
| `status` | no | `pre` or `live` |
| `minute` | live | Current minute |
| `score` | live | e.g. `1-0` |
| `market` | no | e.g. `Over 1.5`, `BTTS No`, `DNB Home` |
| `tip` | yes | Full bet text as on the slip |
| `odds` | number | Copy exactly from the priced market board. The server verifies and overwrites this. Omit when the fixture or market is off the board. |
| `quoted_odds` | number | **Server-set.** Do not send. Records what you submitted, so pricing drift can be measured. |
| `price_source` | string | **Server-set.** `pinnacle`, `oddsfilter`, `flashscore`, or `unpriced`. |
| `market_family` | string | **Server-set.** One of `goals_totals`, `team_totals`, `halves`, `btts`, `result`, `dc_dnb`, `handicap`, `corners`, `specials`. |
| `price_available` | no | Default `true`; set `false` when the board has no price |
| `book` | no | Default `SportyBet ng (modelled)` |
| `confidence` | yes | 0–100 |
| `estimated_probability` | yes | 0–1 |
| `reasoning` | yes | 1–2 sentences |
| `evidence` | yes | 2–4 bullet strings |
| `risks` | no | Named scenario penalties |
| `sources` | no | `{label, url}` refs |

## Prices

The run prompt contains a priced market board with real book prices. Use those numbers and nothing else. The server re-resolves every pick against the board before applying the confidence, odds-range and margin gates, replaces any mismatched number, and records your original in `quoted_odds`.

When the board has no price for your fixture or market, set `price_available: false` and omit `odds`. The pick still publishes.

## Skipped object

```json
{ "match": "Team A vs Team B", "why": "Kickoff unconfirmed on ESPN" }
```

## Suggested ticket

```json
{
  "type": "acca",
  "legs": [0, 1, 3],
  "combined_odds": 4.2,
  "joint_probability": 0.52,
  "label": "Core acca"
}
```

## Example (minimal)

```json
{
  "run_id": "2026-08-22_14-30-00_today",
  "scope": "today",
  "generated_at": "2026-08-22T14:35:00-04:00",
  "summary": "Three MLS evening picks with verified kickoffs and SportyBet prices.",
  "picks": [
    {
      "league": "MLS",
      "match": "Inter Miami vs Orlando City",
      "kickoff_et": "7:30 PM ET",
      "status": "pre",
      "market": "Over 1.5",
      "tip": "Over 1.5 goals",
      "odds": 1.45,
      "book": "SportyBet ng",
      "confidence": 82,
      "estimated_probability": 0.76,
      "reasoning": "Both sides averaged 2.4 total goals last 5; book total 2.5 leaning over.",
      "evidence": [
        "Miami scored in 9/10 home games",
        "Orlando conceded in 8/10 away",
        "H2H last 4: 3 went Over 1.5"
      ],
      "risks": ["Heavy rain forecast — slight under bias"],
      "sources": [{"label": "ESPN fixtures", "url": "https://www.espn.com/soccer/"}]
    }
  ],
  "skipped": [
    { "match": "Dimayor TBD", "why": "Kickoff not locked" }
  ],
  "suggested_tickets": []
}
```

Do **not** write markdown prediction files during web app runs. CSV export is automatic after `submit_picks` accepts.

**One pick per match.** If two markets fit the same fixture, submit only the stronger one (highest confidence). Duplicates are dropped server-side, keeping the highest-confidence leg.

## Gameweek (`scope=gameweek`)

Full-slate correct scores for remaining Big-5 matchday fixtures (content card, not betting). One score per remaining fixture; `tip` is the scoreline, `market` is `Correct score`. Set `price_available: false` and omit `odds`. Min/max odds and margin buffer are **not** applied. Do not skip a match for weak evidence — publish and let `confidence` reflect it (`< 70` is `low conf` in the UI/export).

Twitter export keys (no SportyBet CSV): `export_paths.twitter_full` and `export_paths.twitter_thread` — `.txt` files under `.predictions/YYYY-MM-DD/` (`*_gameweek_twitter.txt`, `*_gameweek_twitter_thread.txt`). Fetch via `GET /api/exports/{id}/twitter` (`?kind=thread|full`, or path aliases `twitter` / `twitter_full` / `twitter_thread`).

## Target odds

`CreateRunRequest.target_odds` (optional, `> 1.0`) is a Generate-form combined-price target. After a **non-gameweek** run is accepted, the server solves a researched subset within ±15% of that target and writes `suggested_tickets` (labels like `Target 8× (researched)`). Blank `target_odds` skips the solver.

**Fill from board:** `POST /api/runs/{id}/target-ticket` with `{ "fill": true }` may append unresearched priced quotes and rewrite `suggested_tickets` (`Target {n}× (board fill)`). `{ "fill": false }` is the researched-only pass. Gameweek runs do not use this endpoint.
