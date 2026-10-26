---
name: soccer-predictions
description: Builds soccer betting slips using research-first confidence scoring, MASTER analysis, and server-verified book prices. Use for web app runs, today's or tomorrow's football predictions, accumulators, singles, safe slips, live betting, or SportyBet picks.
---

# Soccer predictions

Read [markets.md](markets.md), [run-schema.md](run-schema.md), and for live runs [live-fixtures.md](live-fixtures.md). Follow `.cursor/rules/soccer-prediction-core.mdc` plus the product rule when applicable.

## Product routing

| User / command / UI | Product | Rule |
|---------------------|---------|------|
| Web app (default) | User-selected ticket mode | core + run-schema |
| Web Gameweek tab | Full-slate correct scores for EPL/Bundesliga/La Liga/Serie A/Ligue 1 | core + gameweek board (two-of-three calendars) |
| `/predictions-today` or `/predictions-tomorrow` | Hybrid | `soccer-hybrid.mdc` |
| `/predictions-singles` | Singles | `soccer-singles.mdc` |
| `/predictions-accumulator` | Acca | `soccer-short-acca.mdc` |
| `/predictions-safe` | Safest picks | `soccer-singles.mdc` |
| `/predictions-correct-score` | Correct score | singles, never acca |
| `/predictions-live` | In-play | `soccer-live.mdc` + **`live-fixtures.md`** |
| Unspecified tips | Hybrid | `soccer-hybrid.mdc` |

## Workflow

```
- [ ] Duplicates: scan `.predictions/**/*.md` and recent `.runs/`
- [ ] MASTER.md — use hit rates as priors
- [ ] Kickoffs verified in EST
- [ ] Independent form / H2H / injuries per pick
- [ ] Price from the priced market board (off-board: `price_available: false`, omit odds)
- [ ] Confidence + estimated_probability + reasoning + evidence
- [ ] Web: call submit_picks once | Chat: save .md if requested
- [ ] Auto CSV to .predictions/ for extension
```

## Output shape

- **Web app:** structured JSON via `submit_picks` — no markdown required
- **Chat:** group by league, full-text tips, evidence cites confidence gate
- Hybrid chat: singles first, then optional suggested acca from same picks
- List skipped fixtures with one-line why

## Filename suffixes (chat only)

`_today` / `_tomorrow` = hybrid · `_singles-*` · `_acca-*` · `_safe-*` · `_correct-score-*` · `_live`
