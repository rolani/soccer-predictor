# Markets, research, confidence

Research quality is the gate. No fixed pick counts, odds caps, or league bans.

## Confidence

| Field | Meaning |
|-------|---------|
| `confidence` | 0–100 overall certainty after full research |
| `estimated_probability` | Fair win probability for this specific bet |
| `reasoning` | 1–2 sentences shown in the web app |
| `evidence` | 2–4 bullets with numbers (form, H2H, injuries, market stats) |
| `risks` | Named penalties that lowered confidence |

**Publish gate:** `estimated_probability >= (1/odds) + margin_buffer` and confidence ≥ user floor.

MASTER hit rates are **priors** — use them to calibrate, not to block markets.

They are also **sample-biased**. Goals markets look strongest largely because they are almost the only markets with samples: before real prices existed, other markets could not be priced and so were rarely published. Treat a thin sample as unknown, not as bad. A well-evidenced pick in a thin market is how the sample grows.

## All markets (when evidenced)

| Market | Research focus |
|--------|----------------|
| Goals O/U (FT, 1H, 2H) | Last 5–10 totals, book line, both attacks/defences |
| BTTS Yes/No | Scoring consistency both sides; No = grind/sit-in |
| No goal / remaining under | Live sit-in, 2-0 after 75', 0-0 no chances |
| Team over 0.5 / next goal | Attack scored 4+/5; live favourite with xG |
| Double chance / DNB / AH | Favourite should not lose; name AH line |
| Corners O/U | Last 5–10 corner counts; live chase script |
| 1X2 / correct score | Strong multi-source alignment only |

## Scenario penalties (→ risks[], lower confidence)

- Sit-in knockout 2nd leg (visitor leads agg) — overs penalized
- 3+ clean sheets vs Over 1.5
- Thin-data cup / unscouted league
- Parked underdog / 1-0 grind — don't force Over 1.5
- DNB/DC because "visitor hasn't scored yet" — weak story

## Live (in-play)

Read **`live-fixtures.md`**. Web app pre-fetches ESPN in-play list; **verify on LiveScore, FlashScore, Sofascore** before any pick.

Need minute, score, cards, shots/xG, corners; board price when available (not required to publish).

- 0-0 after 55' **with chances** → remaining over / next goal
- 0-0 **no chances** / sit-in → no more goals / remaining under
- Favourite 0-1 with xG lead → team over remaining, DNB, DC
- 2-0+ after 75' → no more goals / under remaining
- Skip after 88' unless 6+ added minutes

## Research sources

- **Fixtures (live):** LiveScore, FlashScore, Sofascore, FotMob, ESPN — see `live-fixtures.md`
- **Stats:** Sofascore, FotMob, Goal.com, Football Whispers
- **Screens:** soccersite, footystats, forebet, windrawwin (verify independently)
- **Prices:** the priced market board in the run prompt. Never estimate a price or copy one from a tip site.

## Skipped fixtures

List in `skipped[]` with one-line why: unconfirmed kickoff, insufficient data, below confidence gate. A missing price is not a skip — publish with `price_available: false`.
