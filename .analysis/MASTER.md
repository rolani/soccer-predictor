# Analysis Master — Aggregated Insights for Predictions

**Purpose:** Single optimized file for prediction commands. Updated when `/predictions-analysis` runs. **Read this file only** — do not read individual analysis files.

**Last updated:** 2026-09-05 19:36:25

---

## Ticket record

*Pick % is not a winning slip. Acca needs every live leg.*

| Type | Record | Notes |
|------|--------|-------|
| Short acca (3–4 legs) | **2 Won / 5 Total** | Aug 24 **Won 3.82×** (4/4 Over 1.5). Losses elsewhere were 7–12 leg tickets. |
| Long acca (7–12+ legs) | **1 Won / 10 Total** | Aug 25 morning **Won 18.95×**. **Lost:** Aug 22 BTTS ~18.7×, goal accas ~14–15×, Aug 24 morning ~17.7×, Aug 25 evening ~16×, Aug 26 midday ~20×, Aug 28 ~18–25×, Aug 30 morning 13-fold ~39× (Bjarg/Sunderland/Botosani/Derby). |
| Singles 1u PnL | **+23.49u** | Prior **+24.43u** through Aug 30 batch. Aug 30 morning slate **−0.94u** on 13 verified singles. Pre-2026-08-26 prices **not** merged into post-cutover PnL. Sep 5 gameweek CS unpriced — no PnL. |

---

## Confidence buckets

*From `run.json` verified picks. Prior pool + Aug 22–30 batch + Aug 30 morning run + Sep 5 gameweek CS (13 verified, all sub-70).*

| Bucket | Correct | Total | Rate | Notes |
|--------|---------|-------|------|-------|
| 70–74 | — | 0 | — | Below default publish floor |
| 75–79 | 250 | 313 | **80%** | Aug 30 morning 6/9; Sunderland O1.5 77 ✗; Botosani o0.5 78 ✗ |
| 80–84 | 106 | 130 | **82%** | Chelsea O2.0 82 ✓; Bjarg O2.0 81 ✗ |
| 85–89 | 12 | 14 | 86% | Palmeiras team overs; thin sample |
| 90+ | — | 0 | — | — |

75 is a publish floor, not a lock. 80+ is stronger on goals/team-over; **not** a BTTS or Under 3.5 licence. Sep 5 gameweek CS legs (50–66 conf) are research-only — **1/13** on finished Saturday legs, not mixed into 75+ calibration.

---

## Price accuracy

*Post–2026-08-26 only: picks with both `odds` (board-verified) and `quoted_odds` (agent estimate).*

| Metric | Value |
|--------|-------|
| Pairs | 199 |
| Mean absolute error | **0.011** |
| Typical gap | ≤0.02 on 1.25–1.75 legs |

Aug 30 morning run MAE **0.003** on 13 legs — tightest batch yet. Sep 5 gameweek CS run had **0 pairs** (all unpriced). Prices before 2026-08-26 were agent-estimated and skewed high — **do not** compare pre-change PnL or combined-odds with post-change runs.

---

## Market Performance (Pooled — Accurate)

*One report per folder or run; Aug 26 test iterations deduped to one canonical midday slate + evening + gameweek CS subset. Adds Sep 5 gameweek CS partial (13 verified).*

| Market | Correct | Total | Rate |
|--------|---------|-------|------|
| Team over 0.5 goals | 91 | 107 | 85% |
| Over 1.5 goals | 112 | 135 | 83% |
| Under 3.5 goals | 17 | 19 | 89% |
| Under 2.5 goals | 43 | 57 | 75% |
| Team over 1.5 | 8 | 10 | 80% |
| Over 2.5 goals | 25 | 39 | 64% |
| Over 2.0 goals | 1 | 3 | 33% |
| Over 1.75 goals | 1 | 1 | 100% |
| Home win | 16 | 26 | 62% |
| Both teams to score | 40 | 72 | 56% |
| Over 3.5 goals | 6 | 8 | 75% |
| Draw no bet / 1UP | 6 | 6 | 100% |
| Asian handicap | 10 | 18 | 56% |
| Away win | 6 | 13 | 46% |
| Double chance (1X) | 2 | 5 | 40% |
| Team under 0.5 / no goal | 2 | 2 | 100% |
| Over 4.5 goals | 2 | 2 | 100% |
| 2H Over 0.5 | 0 | 3 | 0% |
| Correct score | 13 | 63 | 21% |
| BTTS No | 4 | 6 | 67% |

**Favor:** Team over 0.5, Over 1.5, Under 2.5, Under 3.5 (with script)  
**Require extra evidence:** BTTS Yes (56%, improving but still coin-flip territory), Over 2.0 (33% — **thin**, three samples), Over 2.5, home/away win, Asian handicap, correct score, live 2H Over, live remaining Over vs CS machines  
**Thin samples (&lt;10 in pool):** Over 2.0, Over 1.75, DNB/1UP, team under 0.5, Over 4.5, 2H Over — treat as unmeasured not proven

AH: Santa Fe +0.25 on 0-0 = half-win (0.5). Atlético-MG AH 0 on 2-2 = **push, excluded**.

---

## Market coverage (graded batch)

| Family | Share of verified picks | Samples | Flag |
|--------|-------------------------|---------|------|
| goals_totals | 41% | 186 | measured |
| team_totals | 27% | 121 | measured |
| btts | 12% | 54 | measured |
| correct_score | 11% | 51 | gameweek research |
| result | 5% | 22 | **thin** |
| handicap | 3% | 14 | **thin** |

Publish at most half from one family; cover ≥3 families when the slate allows.

---

## What Worked

- **10-fold mixed acca at 1.30–1.36** — Aug 25 **Won 18.95×**; same 12 as singles **+4.23u**.
- **4-leg Over 1.5 acca 1.29–1.51** — Aug 24 **Won 3.82×**.
- **EFL / Carabao Cup** — Aug 25 O1.5 **6/6**; Aug 26 Spurs **5-1**, Everton **0-4**, Newcastle **3-2** team/goal legs.
- **UCL/UEL playoff Overs** — Viking **3-1**, Lyon **1-2**, AEK **4-0**, Rapid **2-2**.
- **PL openers when tempo confirmed** — Chelsea **4-3** Brighton Over 2.0 ✓ (Aug 30).
- **Women's NL overs on mismatch** — Cambridge **3-2** Dulwich O2.5 ✓.
- **La Liga Under 3.5** — Betis/Valencia 1-0 scripts (prior); **not** automatic vs Madrid open game (**4-1** miss).
- **Live late unders** — Lanús **1-1** from 65′ 0-0; Libertad **1-0**; San Luis **1-1** from 86′ 1-0.
- **Team over 0.5** — pooled **85%**. Wolves/Hull, Palmeiras, Vendsyssel **2-0**, Oddevold in **3-1**.
- **Post-cutover pricing** — MAE **0.011** vs quoted; Aug 30 morning **0.003** on 13 legs.
- **Bundesliga away CS when model aligned** — Hoffenheim **2-3** Dortmund **1-2** ✓ (Sep 5 gameweek partial).

---

## What Missed

- **7–13 leg accas** — Aug 22 BTTS **Lost ~18.7×**; Aug 22 goal **Lost ~14–15×**; Aug 24 morning **Lost ~17.7×**; Aug 26 **Lost ~20×** (Madrid U3.5, Vasco O1.5); Aug 28 **Lost ~18–25×**; Aug 30 morning **Lost ~39×** (four legs: Bjarg O2.0, Sunderland O1.5, Botosani o0.5, Derby O2.0).
- **7-fold evening acca** — Aug 25 **Lost ~16×** on IDV **3-1** Under 2.5.
- **PL 1-0 grinds** — Sunderland **1-0** Fulham killed Over 1.5; Derby W **1-0** Boro killed Over 2.0.
- **Real Madrid Under 3.5** — **4-1** vs Sociedad (Mbappé hat-trick); do not use U3.5 only because visitor is blunt.
- **Cup first-leg grind** — Vasco **1-0** killed Over 1.5; Macará **0-0** (prior); América **2-0** killed BTTS.
- **Romania 0-0 blanks** — Farul **0-0** Botosani; penalty miss + VAR disallowed goal killed away team o0.5.
- **Live NWSL Over 1.5** — Angel City **0-0** Gotham after 53′ 0-0.
- **Live 2H Over 0.5** — Racing **1-1** (0 second-half goals).
- **BTTS Yes on openers / blanks** — Brighton **4-0**, Le Havre **0-1**, Angers **0-2** (prior); Aug 30 reserve BTTS **2-2** ✓ shows league context matters.
- **USL Under after late equaliser** — El Paso **2-1** in 90+3′.
- **Correct score gameweek** — **13/63 (21%)** pooled; Sep 5 Saturday **1/13** (only Dortmund **1-2**); EPL **0/8**, research-only not ticket engine.
- **Sep 5 EPL CS misses** — Newcastle **2-2**, Brentford **1-1**, City **1-0**, Forest **0-0** Spurs, Hull **0-0** Villa, Fulham **2-3** Palace.
- **Sep 5 Ligue 1 CS** — Lens **0-1** Lorient; Nice **1-1** Le Mans.

---

## League Performance

| League | Strong markets | Notes |
|--------|----------------|-------|
| England Premier League | Under 2.5/3.5; team over; open-game Overs | Chelsea **4-3** O2.0 ✓; Sunderland **1-0** O1.5 ✗; Sep 5 CS **0/8** — grinds, late EQs |
| EFL / Carabao Cup | Over 1.5; favourite team over 0.5 | Aug 25 **6/6** O1.5; Aug 26 Spurs/Everton/Newcastle ✓ |
| England League One | Under 3.5 on bottom-table grind | Wimbledon **1-0** Wigan U3.5 ✓ |
| Denmark 1. Division | Team over 0.5 away | Vendsyssel **2-0** at Esbjerg ✓ |
| Norway 2nd Division | BTTS in open groups; Over 2.0 needs proof | Trygg/Lade **1-1** BTTS ✓; Bjarg **1-0** O2.0 ✗ |
| Switzerland Promotion League | BTTS on reserve sides | YB II **2-2** Luzern II ✓ |
| England WNL (SE / North) | Over 2.5 on mismatch; not auto Over 2.0 | Cambridge **3-2** ✓; Derby **1-0** ✗ |
| Romania SuperLiga | Team o0.5 needs both sides attacking | Farul **0-0** Botosani ✗ |
| Sweden Superettan | Team over 0.5 visitor | Oddevold scored in **3-1** ✓ |
| Uganda Premier League | Under 2.5 MD1 openers | BUL **1-0** Express U2.5 ✓ |
| Armenia Premier League | Over 1.75 when away side scores | Gandzasar **0-3** BKMA ✓ |
| France Ligue 1 | Under 3.5, team over 0.5; BTTS extra proof | Aug 23 BTTS **1/3**; Angers **0-2** O1.5 ✗; Lens **0-1** Lorient CS ✗ |
| Germany Bundesliga | Away fav CS when xG edge clear | Dortmund **2-3** Hoffenheim **1-2** ✓; Elversberg **4-3** Gladbach variance |
| Spain La Liga | Under 3.5 when grind; not vs open Sociedad | Madrid **4-1** U3.5 ✗; Betis/Valencia U3.5 ✓ |
| Italy Serie A | Over 1.5; 1UP home floor | Roma **4-0** 1UP ✓; Frosinone **0-1** O1.5 ✗; Fiorentina **1-2** Torino CS ✗ |
| Eredivisie | Over 2.5 on PSV-type hosts | PSV **5-1** ✓ |
| Brazil Série A / Copa | Team over 0.5 home fav; cup O1.5 needs script | Palmeiras **3-0** / **4-1** ✓; Vasco **1-0** O1.5 ✗ |
| MLS / Leagues Cup | Over 1.5 must-attack; BTTS extra proof | América **2-0** BTTS ✗; Chicago/León O1.5 ✓ |
| USA USL | Under grind with altitude/heat check | El Paso **2-1** U2.25 ✗; New Mexico **2-1** O2.5 ✓ |
| Colombia Primera A | Team over / Under when Dimayor confirmed | Nacional **2-1** team O1.5 ✓; Cúcuta U2.5 ✓ |
| Central American Cup | Over 2.5 group deciders | Alajuelense **3-1** ✓ |
| Copa Libertadores / Sudamericana | Team over 2nd leg if home must score; U2.5 first legs | River **1-1** team over ✓; IDV **3-1** U2.5 ✗ |
| Saudi / HK / China early | Team over 0.5; HK totals | Al-Ahli **1-0** ✓; Shenzhen **2-1** ✓; Lee Man **3-1** ✓ |
| UEFA qualifiers | Over 1.5 level aggregates | Viking, Lyon, AEK ✓ |
| NWSL | Over 1.5 extra proof vs CS machines | Angel City **0-0** live ✗ |
| Argentina Liga | 2H Over not automatic after 1-1 HT | Racing **1-1** ✗ |
| Liga MX live | Late Under from 1-0/1-1 snapshot | San Luis **1-1** ✓ |

---

## Usage for Predictions

- **Prices before 2026-08-26 are unreliable.** Agent-estimated; twelve-leg accas advertised at 20× were often ~4× real. **Post-cutover:** copy board `odds`; MAE **0.011** vs `quoted_odds`.
- **Do not compare pre-change PnL with post-change PnL** or combined-odds figures across the cutover.
- **Market samples:** Goals/team markets dominate history because they were the first priced families. Corners/handicaps/DC now have board prices — **thin row = unmeasured**, not bad. Max half from one family; ≥3 families per slate.
- **Construction:** Hybrid = **4–6** core singles **1.15–1.75** + **one** 3–4 leg acca from the same list. **Never 7+ leg BTTS** (Lost ~18.7×). **10-fold at 1.30–1.36** can cash (Aug 25 Won) — one miss voids it. **13-fold Aug 30 Lost ~39×** on four PL/low-event legs — do not stack PL openers with Nordic O2.0 without tempo proof.
- **PL MD2 grinds:** Sunderland **1-0**, Derby W **1-0** — penalize blind Over 1.5/2.0 on “both scored GW1” alone; check shots/xG and visitor bluntness (Fulham 0 SOT).
- **PL MD3 Sep 5:** Multiple **0-0** and **1-0** scripts (Forest–Spurs, Hull–Villa, City–Coventry) — CS and blind Overs both punished; late EQs (Newcastle **2-2**, Brentford **1-1**).
- **Romania 0-0:** Farul **0-0** Botosani — team o0.5 needs both sides' chance creation, not H2H alone.
- **Do not pad long accas with Libertadores 2nd-leg Under 2.5** vs live home attack (IDV **3-1**).
- **Real Madrid / open La Liga favourites:** Under 3.5 needs grind evidence — **4-1** Sociedad miss.
- **Cup first legs:** Vasco **1-0**, Macará **0-0** — prefer team over or no-more-goals, not blind Over 1.5.
- **BTTS pooled 56%** — extra proof; reserve/youth leagues can hit (YB II **2-2**). Not an acca engine.
- **Live:** No Over 1.5 after 50′+ **0-0** vs Gotham-type CS profile; 2H Over after **1-1** HT not automatic; team over on **0-2** trailing needs shots/xG.
- **USL Unders:** Late 90+ goals (El Paso **2-1**) — penalize altitude/heat chase scripts.
- **Correct score gameweek:** ~**21%** pooled (**13/63**); Sep 5 partial **1/13** — research card only, unpriced; not ticket engine.
- **Bundesliga MD2 variance:** Promoted Elversberg **4-3** at Gladbach after Leverkusen upset — do not auto-home CS vs bold visitors.
- **Dimayor:** Include only confirmed kickoffs (Nacional ✓).
- **League preference:** EFL Cup O1.5; UCL playoff O1.5 on level agg; La Liga U3.5 on grind not vs Sociedad; Série B U2.5 lean; CAC O2.5 deciders; Saudi/HK team over when visitor concedes; Uganda MD1 Unders when total line ≤1.75.
