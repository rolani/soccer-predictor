"""Record live Pinnacle payloads as test fixtures. Run manually, not in CI."""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R",
    "Accept": "application/json",
}
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pinnacle"


def get(path: str):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _matchups_for_fixture(all_matchups: list, matchup_id: int) -> list:
    base = all_matchups[:400]
    included_ids = {e.get("id") for e in base if isinstance(e, dict)}
    extra = [
        e
        for e in all_matchups
        if isinstance(e, dict)
        and (e.get("id") == matchup_id or e.get("parentId") == matchup_id)
        and e.get("id") not in included_ids
    ]
    return base + extra


def main(matchup_id: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_matchups = get("/sports/29/matchups?withSpecials=false&brandId=0")
    (OUT / "matchups.json").write_text(
        json.dumps(_matchups_for_fixture(all_matchups, matchup_id), indent=1),
        encoding="utf-8",
    )
    (OUT / f"related_{matchup_id}.json").write_text(
        json.dumps(get(f"/matchups/{matchup_id}/related"), indent=1), encoding="utf-8"
    )
    (OUT / f"straight_{matchup_id}.json").write_text(
        json.dumps(
            get(f"/matchups/{matchup_id}/markets/related/straight?primaryOnly=false"),
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    import sys

    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1634269216)
