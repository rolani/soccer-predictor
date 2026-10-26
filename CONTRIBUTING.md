# Contributing

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[web,dev]"
cp .env.example .env               # add CURSOR_API_KEY locally — never commit it
cd webapp && npm ci && npm run build && cd ..
```

To run the app: `bash scripts/run-web.sh` (Linux/macOS) or `.\scripts\run-web.ps1` (Windows).

## Checks (same as CI)

```bash
ruff check predictor tests predict.py
ruff format --check predictor tests predict.py
python -m pytest tests/ -m "not integration" -q
```

Integration tests start a local server and expect a Cursor API key:

```bash
python -m pytest tests/test_integration.py -v
```

## Secrets

Do not commit `.env`, API keys, `.runs/`, or `.predictions/`. CI fails if a `crsr_…` Cursor key appears in tracked files.
