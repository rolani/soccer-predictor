"""Match identity helpers for one-pick-per-game enforcement."""

from __future__ import annotations

import re

from predictor.web.schema import Pick


def normalize_match_key(match: str) -> str:
    """Normalize match string for duplicate detection."""
    s = match.strip().lower()
    s = re.sub(r"\s+v\.?\s+", " vs ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def dedupe_picks_by_match(picks: list[Pick]) -> tuple[list[Pick], list[str]]:
    """
    Keep one pick per match — highest confidence wins; ties keep first seen.
    Returns (deduped picks, notes about dropped duplicates).
    """
    best: dict[str, Pick] = {}
    notes: list[str] = []

    for p in picks:
        key = normalize_match_key(p.match)
        if key not in best:
            best[key] = p
            continue
        kept = best[key]
        if p.confidence > kept.confidence:
            notes.append(
                f"Dropped duplicate for {p.match}: {kept.tip} "
                f"(kept {p.tip}, confidence {p.confidence} > {kept.confidence})"
            )
            best[key] = p
        else:
            notes.append(
                f"Dropped duplicate for {p.match}: {p.tip} "
                f"(kept {kept.tip}, confidence {kept.confidence} >= {p.confidence})"
            )

    seen: set[str] = set()
    ordered: list[Pick] = []
    for p in picks:
        key = normalize_match_key(p.match)
        if key in seen:
            continue
        ordered.append(best[key])
        seen.add(key)
    return ordered, notes
