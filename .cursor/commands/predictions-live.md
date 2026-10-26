# Live predictions — in-play

Check **current live games** on LiveScore, FlashScore, Sofascore, and ESPN. Research-first; prefer **no bet** over a weak pick.

Follow `.cursor/skills/soccer-predictions/SKILL.md`, **`live-fixtures.md`**, and `.cursor/rules/soccer-live.mdc`.

## Steps

1. **Live board** — Web app injects ESPN in-play snapshot; you **must still verify** on:
   - https://www.livescore.com/en/football/live/
   - https://www.flashscore.com/
   - https://www.sofascore.com/
   - https://www.fotmob.com/live (xG/corners backup)
2. Read `.analysis/MASTER.md` as prior.
3. Per in-play match: confirm minute, score, shots/xG/corners on Sofascore (or FotMob).
4. Board price when available; **no quote still publish** (`price_available: false`, omit odds).
5. One pick per match; consider all live markets when the state fits.
6. If nothing qualifies: **No live edge — do not bet** — list every checked game in `skipped` with minute/score/why.

Web app: `scope: live`, call `submit_picks` with `status: "live"`, `minute`, `score`. Chat: save `_live.md` if requested.

Never a live accumulator.
