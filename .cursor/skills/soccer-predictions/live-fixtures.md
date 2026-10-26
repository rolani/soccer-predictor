# Live fixture discovery

Use when `scope: live` (web app or `/predictions-live`). The web server pre-fetches an ESPN in-play board; **you must still verify** on Sofascore, FlashScore, and LiveScore before publishing a pick.

## Programmatic pre-check (web app)

`GET /api/live/fixtures` returns ESPN API in-play games (minute, score, league). This is a **starting list**, not the final slate — ESPN can miss leagues or lag by a minute.

## Agent verification sources (required)

Check **all three** live hubs, then drill into match pages for stats:

| Source | Live hub | Use for |
|--------|----------|---------|
| **LiveScore** | https://www.livescore.com/en/football/live/ | Confirm match is in play; quick score/minute |
| **FlashScore** | https://www.flashscore.com/ | Same; good for lower-tier leagues |
| **Sofascore** | https://www.sofascore.com/ | Minute, score, **xG, shots, corners**, cards |
| **FotMob** | https://www.fotmob.com/live | Backup xG/corners when Sofascore thin |
| **ESPN** | https://www.espn.com/soccer/scoreboard | Kickoff lock; links to match stats |

### Per-match deep dive (when considering a bet)

1. Open the match on **Sofascore** (or FotMob) — note minute, score, xG, SOT, corners, reds.
2. Confirm the same minute/score on **FlashScore** or **LiveScore**.
3. Copy the live/remaining line from the priced market board when it is there. If the board has no quote, still publish with `price_available: false`.
4. Read `.analysis/MASTER.md` for sit-in / altitude / pens scenario penalties.

## When nothing is live

If all sources show no in-play games (or only unscouted leagues with no stats/price):

- Submit **zero picks**.
- Populate `skipped` with every game checked: `{ "match": "...", "why": "1H 0-0, no xG, no live price" }`.
- Summary: **No live edge — do not bet**.

## Typical live windows

- **Before 55'** on a 0-0 with no chances → usually **skip** (not the remaining-time window yet).
- **After 55'** 0-0 with chances → Over 0.5 remaining / next goal.
- **After 75'** 2-0 sit-in → no more goals / under remaining.
- **After 88'** → skip unless 6+ added minutes announced.

## Web app workflow

```
1. User selects Live → UI shows /api/live/fixtures board
2. Agent prompt includes ESPN snapshot + this checklist
3. Agent verifies Sofascore / FlashScore / LiveScore per candidate
4. submit_picks with status: "live", minute, score on each pick
```

Never a live accumulator. One pick per match.
