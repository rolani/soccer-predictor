# Predictions analysis — pick rate and ticket result

Look up results for a predictions folder or web run and write a success report. **Prediction runs read `.analysis/MASTER.md` only** — update MASTER after each analysis.

Follow `.cursor/skills/soccer-predictions/SKILL.md` for market names. Winning means **tickets** as well as picks.

## Output

1. `.analysis/YYYY-MM-DD_HH-MM-SS.md`
2. Updated `.analysis/MASTER.md`

## Steps

1. Source = user path, latest `.runs/<id>/run.json`, or latest `.predictions/YYYY-MM-DD/`.
2. **Prefer `run.json`** from `.runs/` — structured picks with confidence scores. Fall back to `*_sportybet.csv` and prediction `*.csv`. Skip unrelated CSVs. Columns: League, Match, Tip, Odds (League optional).
3. For hybrid markdown with two tables and no split CSVs, score **each table as its own ticket** (singles list vs short acca).
4. Look up each unique match+tip (ESPN, LiveScore, FlashScore, Transfermarkt, league sites). Final 90-minute score. Future matches = —.
5. Grade tips (90' unless the tip is a half):
   - FT over/under, BTTS, DNB, team over X, double chance — as written
   - **1st half O/U:** HT score only
   - **2nd half O/U:** (FT goals − HT goals) vs the line
   - **Corners O/U:** full-time corner count (not shots)
   - **Asian handicap:** apply the stated line to FT score (quarter lines split stake; push = neither ✓ nor ✗, exclude from hit rate or mark push)
   - **No more goals / Under 0.5 remaining:** FT goals equal the snapshot score (✓) or any later goal (✗)
   - **BTTS No:** at least one team scored 0 at FT
   - **Live DNB / double chance:** settle on FT 1X2 from the live tip's side
   - **Live next goal / remaining O/U:** snapshot Minute + Score vs FT

## Report (mandatory)

- Per run/file/table: picks, verified, correct, pick success %.
- **Confidence calibration:** group picks by confidence bucket (70–74, 75–79, 80–84, 85–89, 90+) and report hit rate per bucket. Add to MASTER for future calibration.
- **Ticket settlement:**
  - **Acca / suggested_tickets:** Won only if every leg correct. One miss = Lost.
  - **Singles / live:** not all-must-win. Report hits, misses, and 1u PnL: sum(winning odds) − n_bets on verified picks.
- Match-by-match: # | Match | Tip | Odds | Confidence | Result | Verdict (✓/✗/—).
- What worked / missed; market table; league notes; sources.

## MASTER.md

Recompute Market Performance from **one report per predictions folder or run**. Sum Correct/Total per market. Add **Confidence buckets** table when run.json data exists.

Also keep a **Ticket record** line: accas Won/Total and singles 1u PnL when available.

Last updated = now. Output a short user summary including **ticket won/lost**, not only pick %.
