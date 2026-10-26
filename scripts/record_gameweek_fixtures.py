"""Record live gameweek calendar payloads. Run manually, not from tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TIMEOUT = 25
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "gameweek"

LEAGUES = (
    ("EPL", "PL", "eng.1", 47),
    ("Bundesliga", "BL1", "ger.1", 54),
    ("La Liga", "PD", "esp.1", 87),
    ("Serie A", "SA", "ita.1", 55),
    ("Ligue 1", "FL1", "fra.1", 53),
)


def _get(url: str, extra: dict[str, str] | None = None) -> object:
    headers = {"User-Agent": USER_AGENT}
    if extra:
        headers.update(extra)
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    for display, code, slug, fotmob_id in LEAGUES:
        slug_key = display.lower().replace(" ", "_")
        (OUT / f"fotmob_{slug_key}.json").write_text(
            json.dumps(
                _get(f"https://www.fotmob.com/api/data/leagues?id={fotmob_id}"),
                indent=1,
            ),
            encoding="utf-8",
        )
        (OUT / f"espn_{slug_key}.json").write_text(
            json.dumps(
                _get(
                    f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
                ),
                indent=1,
            ),
            encoding="utf-8",
        )
        if not token:
            continue
        auth = {"X-Auth-Token": token}
        (OUT / f"football_data_{code}_competition.json").write_text(
            json.dumps(
                _get(
                    f"https://api.football-data.org/v4/competitions/{code}",
                    extra=auth,
                ),
                indent=1,
            ),
            encoding="utf-8",
        )
        competition = json.loads(
            (OUT / f"football_data_{code}_competition.json").read_text(encoding="utf-8")
        )
        season = competition.get("currentSeason") or {}
        matchday = season.get("currentMatchday") or competition.get("currentMatchday")
        if matchday is None:
            continue
        (OUT / f"football_data_{code}_matches.json").write_text(
            json.dumps(
                _get(
                    f"https://api.football-data.org/v4/competitions/{code}/matches?matchday={matchday}",
                    extra=auth,
                ),
                indent=1,
            ),
            encoding="utf-8",
        )
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
