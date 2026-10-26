# Export predictions for SportyBet

Export the latest saved predictions to SportyBet-friendly CSV and text.

## What to do

1. Use the file the user named, or the most recent `.md` under `.predictions/` (all day folders, by mtime).
2. Run `predict export [file]` (latest if omitted).
3. Confirm files next to the source:
   - `*_sportybet.csv` — Match, Tip, Odds
   - `*_sportybet.txt` — one line per pick
   - `*_sportybet_search.txt` — match names for SportyBet search
4. **Hybrid files** have two tables. Export **singles** as the default CSV (that is the stake-each-pick product). If the exporter cannot split tables, say so and tell the user to place the short acca from the markdown table separately.
5. Report output paths. Reminder: stake singles separately; the short acca is optional.
