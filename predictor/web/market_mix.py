"""Market-family mix over recent runs, used to nudge the agent off goals markets."""

from __future__ import annotations

from predictor.web.store import list_runs, read_result

_GOALSY = {"goals_totals", "team_totals", "halves"}

_FAMILY_LABELS = {
    "goals_totals": "goals over/under",
    "team_totals": "team totals",
    "halves": "first half",
    "btts": "BTTS",
    "result": "1X2",
    "dc_dnb": "double chance / DNB",
    "handicap": "Asian handicap",
    "corners": "corners",
    "specials": "specials",
}


def recent_market_mix(limit: int = 5) -> dict[str, int]:
    """Count published picks per market family across the last completed runs."""
    mix: dict[str, int] = {}
    seen = 0
    for meta in list_runs(limit=limit * 4):
        if meta.status.value != "completed":
            continue
        result = read_result(meta.id)
        if not result or not result.picks:
            continue
        for p in result.picks:
            family = p.market_family or "unclassified"
            mix[family] = mix.get(family, 0) + 1
        seen += 1
        if seen >= limit:
            break
    return mix


def format_diversity_block(mix: dict[str, int]) -> str:
    total = sum(mix.values())
    lines = ["## Market variety"]

    if total:
        goalsy = sum(n for f, n in mix.items() if f in _GOALSY)
        share = round(100 * goalsy / total)
        top = sorted(mix.items(), key=lambda kv: kv[1], reverse=True)[:4]
        breakdown = ", ".join(f"{_FAMILY_LABELS.get(f, f)} {n}" for f, n in top)
        lines.append(
            f"Your recent runs published {total} picks — {share}% goals markets ({breakdown})."
        )
    else:
        lines.append("No market mix recorded yet.")

    lines.extend(
        [
            "",
            "Every market on the board carries a real price, so corners, handicaps, "
            "double chance, draw-no-bet, BTTS and first-half markets are researchable "
            "on the same footing as goals markets.",
            "",
            "Aim for **no more than half** your picks from one family, and cover "
            "**at least three families** when the slate supports it.",
            "",
            "MASTER hit rates are sample-biased: goals markets look strongest partly "
            "because they are almost the only markets with samples. Treat a thin "
            "sample as unknown, not as bad — a well-evidenced pick in a thin market "
            "is how the sample grows.",
        ]
    )
    return "\n".join(lines)
