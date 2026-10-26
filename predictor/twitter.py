"""Twitter copy for gameweek correct-score cards. No odds."""

from __future__ import annotations

from typing import Any

LOW_CONF_THRESHOLD = 70


def _get(p: Any, name: str, default: Any = "") -> Any:
    if isinstance(p, dict):
        return p.get(name, default)
    return getattr(p, name, default)


def _league(p: Any, leagues_by_match: dict[str, str] | None = None) -> str:
    league = str(_get(p, "league", "") or "").strip()
    if league:
        return league
    match = _get(p, "match", "") or ""
    if leagues_by_match:
        mapped = leagues_by_match.get(match)
        if mapped:
            return str(mapped)
    return "Gameweek"


def _percent(p: Any) -> int:
    return int(round(float(_get(p, "estimated_probability", 0) or 0) * 100))


def compact_line(p: Any) -> str:
    """`{home} {tip} {away} {pct}%` plus ` · low conf` when confidence < 70."""
    match = str(_get(p, "match", "") or "")
    tip = str(_get(p, "tip", "") or "")
    pct = _percent(p)
    if " vs " in match:
        home, away = match.split(" vs ", 1)
        line = f"{home.strip()} {tip} {away.strip()} {pct}%"
    else:
        line = f"{match} {tip} {pct}%"
    confidence = int(_get(p, "confidence", 100) or 0)
    if confidence < LOW_CONF_THRESHOLD:
        line += " · low conf"
    return line


def format_thread(
    picks,
    *,
    leagues_by_match: dict[str, str] | None = None,
) -> list[str]:
    """Compact tweets, each ≤280 characters, split only between matches."""
    chunks: list[str] = []
    current: list[str] = []
    header_emitted: set[str] = set()

    def flush() -> None:
        if current:
            chunks.append("\n".join(current))
            current.clear()

    for p in picks:
        league = _league(p, leagues_by_match)
        line = compact_line(p)
        block = [league, line] if league not in header_emitted else [line]
        candidate = current + block
        text = "\n".join(candidate)
        if current and len(text) > 280:
            flush()
            block = [league, line] if league not in header_emitted else [line]
            current.extend(block)
        else:
            current.extend(block)
        header_emitted.add(league)

    flush()
    return chunks


def format_full(
    picks,
    *,
    leagues_by_match: dict[str, str] | None = None,
) -> str:
    """Scores plus evidence bullets under each match."""
    if not picks:
        return ""
    parts: list[str] = []
    last_league: str | None = None
    for p in picks:
        league = _league(p, leagues_by_match)
        if league != last_league:
            if parts:
                parts.append("")
            parts.append(league)
            last_league = league
        parts.append(compact_line(p))
        for bullet in _get(p, "evidence", None) or []:
            text = str(bullet).strip()
            if text:
                parts.append(f"- {text}")
    return "\n".join(parts)
