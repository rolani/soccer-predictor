"""Resolve agent-written match and tip strings against the Pinnacle board.

Prefers returning None over a wrong answer: a mismatched price is worse than
no price, because a wrong price silently passes the margin gate.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.quotes import MarketQuote

_NOISE = {
    "fc",
    "cf",
    "afc",
    "sc",
    "ac",
    "as",
    "sk",
    "nk",
    "gnk",
    "hk",
    "fk",
    "bk",
    "cd",
    "ca",
    "sv",
    "vfl",
    "vfb",
    "tsg",
    "ss",
    "ssc",
    "us",
    "usa",
    "aj",
    "club",
    "de",
    "the",
}
_SEPARATOR = re.compile(r"\s+(?:vs?\.?|@|-|–|—)\s+", re.IGNORECASE)


def normalize_team(name: str) -> str:
    """Lowercase, strip accents and punctuation, drop club-noise tokens."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE]
    return " ".join(tokens)


def split_match(match: str) -> tuple[str, str] | None:
    parts = _SEPARATOR.split((match or "").strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def _similarity(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, overlap)
    return ratio


def match_fixture(
    match: str,
    candidates: list[PinnacleMatchup],
    *,
    min_side: float = 0.72,
    min_combined: float = 0.80,
) -> PinnacleMatchup | None:
    """Best-scoring candidate above both thresholds, else None."""
    split = split_match(match)
    if not split:
        return None
    home, away = split

    best: PinnacleMatchup | None = None
    best_score = 0.0
    for c in candidates:
        if c.kind != "main":
            continue
        hs, as_ = _similarity(home, c.home), _similarity(away, c.away)
        if hs < min_side or as_ < min_side:
            continue
        score = (hs + as_) / 2.0
        if score >= min_combined and score > best_score:
            best, best_score = c, score
    return best


def _canonical_tip(text: str) -> str:
    """Collapse phrasing variants so 'BTTS Yes' and 'Both teams to score - Yes' agree."""
    s = normalize_team(text)
    s = s.replace("both teams to score", "btts")
    s = re.sub(r"\bgoals?\b", "", s)
    s = re.sub(r"\bteam total\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def resolve_quote(
    tip: str,
    market: str,
    quotes: list[MarketQuote],
) -> MarketQuote | None:
    """Find the quote a pick refers to. Exact canonical match, then containment."""
    if not quotes:
        return None
    target = _canonical_tip(tip)
    if not target:
        return None

    by_canonical = {_canonical_tip(q.tip): q for q in quotes}
    if target in by_canonical:
        return by_canonical[target]

    combined = _canonical_tip(f"{market} {tip}") if market else target
    if combined in by_canonical:
        return by_canonical[combined]

    target_tokens = set(target.split())
    best: MarketQuote | None = None
    best_score = 0.0
    for canonical, quote in by_canonical.items():
        tokens = set(canonical.split())
        if not tokens:
            continue
        # Never cross over/under or yes/no boundaries.
        for opposites in (("over", "under"), ("yes", "no")):
            if (opposites[0] in tokens) != (opposites[0] in target_tokens):
                break
            if (opposites[1] in tokens) != (opposites[1] in target_tokens):
                break
        else:
            overlap = len(tokens & target_tokens) / len(tokens | target_tokens)
            if overlap > best_score:
                best, best_score = quote, overlap
    return best if best_score >= 0.6 else None
