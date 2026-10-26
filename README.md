# Soccer Predictor

Research-first soccer predictions powered by the **Cursor Python SDK**. The web app runs a Cursor agent against this repo — same depth as chat `/predictions-*` commands, with UI controls for scope, markets, odds, and confidence.

[![CI](https://github.com/rolani/soccer-predictor/actions/workflows/ci.yml/badge.svg)](https://github.com/rolani/soccer-predictor/actions/workflows/ci.yml)

This is research software, not betting advice. You are responsible for any wagers you place.

## Setup

```bash
git clone https://github.com/rolani/soccer-predictor.git
cd soccer-predictor
pip install -e ".[web,dev]"
```

Copy `.env.example` to `.env` and add your API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations):

```
CURSOR_API_KEY=
```

Never commit `.env`. See [SECURITY.md](SECURITY.md).

## Web app (recommended)

**Windows:**

```powershell
.\scripts\run-web.ps1
```

**Manual:**

```bash
cd webapp && npm install && npm run build
python -m predictor.web.app
```

Open **http://127.0.0.1:8765**

### Web app features

- **Scope:** Live, today, tomorrow, next N hours, or a specific date
- **Markets:** All types (O/U, BTTS, DNB, DC, AH, corners, 1X2, correct score, …)
- **Filters:** Odds range, confidence floor, margin buffer, league include/exclude
- **Ticket mode:** Singles, acca, or hybrid
- **Target odds** on Generate: optional combined price; **Fill from board** adds unresearched quotes when the researched subset misses ±15%
- **Gameweek tab:** full remaining Big-5 matchday correct scores (EPL, Bundesliga, La Liga, Serie A, Ligue 1) with Twitter copy (thread + full), not a SportyBet CSV
- **Live research log** via SSE while the agent runs
- **Pick cards** with reasoning, evidence, confidence bar, risks
- **Auto CSV export** to `.predictions/YYYY-MM-DD/` for the Edge extension
- **History** tab, and **Analysis** with a **Run analysis** button that grades finished runs into `.analysis/MASTER.md`
- **Refine** a completed run with follow-up prompts

### SDK smoke test

```bash
python scripts/sdk_spike.py
```

### Automated tests

```bash
pip install -e ".[web,dev]"
ruff check predictor tests predict.py
ruff format --check predictor tests predict.py
python -m pytest tests/ -m "not integration" -q   # unit tests (CI)
python -m pytest tests/test_integration.py -v     # starts server, needs API key
```

## Odds source

The web app fetches soccer prices from **Pinnacle's guest feed**, strips the sharp-book vig, then re-applies a SportyBet-like soft-book margin so advertised odds match what you would see on SportyBet. The priced market board is handed to the agent; the server re-checks every submitted number and overwrites mismatches.

Optional env overrides (add to `.env`):

```
PINNACLE_API_KEY=                    # defaults to Pinnacle's public guest key
PREDICTOR_OVERROUND_GOALS_TOTALS=1.055
FOOTBALL_DATA_API_KEY=               # optional; Gameweek football-data.org calendar
```

Use `PREDICTOR_OVERROUND_<FAMILY>` for any market family (`goals_totals`, `team_totals`, `halves`, `btts`, `result`, `dc_dnb`, `handicap`, `corners`, `specials`).

The **Analysis** tab **Run analysis** button grades finished runs into `.analysis/MASTER.md` and records graded run ids in `.analysis/graded_runs.json`. Chat `/predictions-analysis` still works.

## Research-first rules

Picks are gated by **evidence and confidence**, not hard caps:

- Every pick needs kickoff verification, form, price, confidence (0–100), estimated probability, reasoning, and evidence bullets
- Scenario risks (sit-in knockout, clean-sheet streaks, thin data) lower confidence — they are not blanket bans
- `.analysis/MASTER.md` provides historical priors for calibration

See `.cursor/skills/soccer-predictions/run-schema.md` for the `submit_picks` JSON contract.

## CLI (legacy scraper)

```bash
predict today -n 5
predict export
```

The CLI still scrapes tip sites for quick accumulators. **Use the web app for real research.**

## Cursor chat commands

Still available — share the same rewritten skill/rules:

| Command | Description |
|---------|-------------|
| `/predictions-today` | Hybrid for today (EST) |
| `/predictions-tomorrow` | Hybrid for tomorrow |
| `/predictions-singles` | Singles only |
| `/predictions-accumulator` | Acca from researched picks |
| `/predictions-safe` | Safest picks |
| `/predictions-live` | In-play |
| `/predictions-analysis` | Grade results (prefers `run.json`) |
| `/predictions-export` | Export latest CSV |

## Edge extension

Load unpacked from `extension/` in Edge. Point the side panel at `*_sportybet.csv` in `.predictions/` — auto-created after each web run.

## Docker (optional)

```bash
docker build -t soccer-predictor .
docker run --rm -p 8765:8765 -e CURSOR_API_KEY -e PREDICTOR_HOST=0.0.0.0 soccer-predictor
```

Pass the key at runtime. Do not bake it into the image.

## Project layout

```
predictor/web/     FastAPI + Cursor SDK runner
webapp/            React UI (Vite + Tailwind)
.runs/             Structured run.json per generation (local, gitignored)
.predictions/      Auto CSV for SportyBet extension (local, gitignored)
.cursor/           Rules, skills, commands
.analysis/         MASTER.md performance tracking
```

## License

MIT. See [LICENSE](LICENSE). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
