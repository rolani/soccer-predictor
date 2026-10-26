"""Normalize Pinnacle market payloads into one betting vocabulary.

Tip strings must match `.cursor/skills/soccer-predictions/markets.md` so that
MASTER.md market rows stay comparable across this change.
"""

from __future__ import annotations

from dataclasses import dataclass

from predictor.odds.pinnacle import PinnacleMatchup
from predictor.odds.pricing import american_to_decimal, devig, overround_for, revig

FAMILIES = (
    "goals_totals",
    "team_totals",
    "halves",
    "btts",
    "result",
    "dc_dnb",
    "handicap",
    "corners",
    "specials",
)


@dataclass(frozen=True)
class MarketQuote:
    family: str
    market: str
    tip: str
    line: float | None
    side: str | None
    period: int
    odds: float
    raw_odds: float
    fair_probability: float
    source_key: str
    source: str = "pinnacle"


def _price_group(
    labels: list[str],
    american: list[float],
    *,
    family: str,
    market: str,
    line: float | None,
    side: str | None,
    period: int,
    source_key: str,
) -> list[MarketQuote]:
    """De-vig a complete market, re-vig to the book margin, emit one quote per outcome."""
    if len(american) < 2 or len(labels) != len(american):
        return []
    try:
        raw = [american_to_decimal(a) for a in american]
    except (TypeError, ValueError, ZeroDivisionError):
        return []
    if any(d <= 1.0 for d in raw):
        return []
    fair = devig(raw)
    adjusted = revig(fair, overround_for(family))
    out: list[MarketQuote] = []
    for label, raw_d, f, adj in zip(labels, raw, fair, adjusted):
        out.append(
            MarketQuote(
                family=family,
                market=market,
                tip=label,
                line=line,
                side=side,
                period=period,
                odds=round(1.0 / adj, 3),
                raw_odds=round(raw_d, 3),
                fair_probability=round(f, 5),
                source_key=source_key,
            )
        )
    return out


def _half(period: int) -> str:
    return "1H " if period == 1 else ""


def _totals(m: dict, period: int, is_corners: bool) -> list[MarketQuote]:
    prices = m.get("prices") or []
    over = next((p for p in prices if p.get("designation") == "over"), None)
    under = next((p for p in prices if p.get("designation") == "under"), None)
    if not over or not under:
        return []
    line = over.get("points")
    if line is None:
        return []
    family = "corners" if is_corners else ("halves" if period == 1 else "goals_totals")
    noun = "corners" if is_corners else "goals"
    prefix = "" if is_corners else _half(period)
    return _price_group(
        [f"{prefix}Over {line} {noun}", f"{prefix}Under {line} {noun}"],
        [over["price"], under["price"]],
        family=family,
        market=f"{prefix}Over/Under {line} {noun}",
        line=line,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


def _team_totals(m: dict, period: int, home: str, away: str) -> list[MarketQuote]:
    prices = m.get("prices") or []
    over = next((p for p in prices if p.get("designation") == "over"), None)
    under = next((p for p in prices if p.get("designation") == "under"), None)
    if not over or not under:
        return []
    line = over.get("points")
    side = m.get("side")
    if line is None or side not in ("home", "away"):
        return []
    team = home if side == "home" else away
    prefix = _half(period)
    family = "halves" if period == 1 else "team_totals"
    return _price_group(
        [f"{prefix}{team} over {line} goals", f"{prefix}{team} under {line} goals"],
        [over["price"], under["price"]],
        family=family,
        market=f"{prefix}{team} team total {line}",
        line=line,
        side=side,
        period=period,
        source_key=m.get("key", ""),
    )


def _moneyline(m: dict, period: int, home: str, away: str) -> list[MarketQuote]:
    prices = {p.get("designation"): p.get("price") for p in m.get("prices") or []}
    if not {"home", "away"} <= set(prices):
        return []
    prefix = _half(period)
    labels = [f"{prefix}{home} win", f"{prefix}Draw", f"{prefix}{away} win"]
    american = [prices["home"], prices.get("draw"), prices["away"]]
    if american[1] is None:
        labels = [labels[0], labels[2]]
        american = [american[0], american[2]]
    return _price_group(
        labels,
        american,
        family="result",
        market=f"{prefix}Match result",
        line=None,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


def _spread(m: dict, period: int, home: str, away: str, is_corners: bool) -> list[MarketQuote]:
    prices = m.get("prices") or []
    h = next((p for p in prices if p.get("designation") == "home"), None)
    a = next((p for p in prices if p.get("designation") == "away"), None)
    if not h or not a:
        return []
    hl, al = h.get("points"), a.get("points")
    if hl is None or al is None:
        return []
    prefix = _half(period)
    noun = " corners" if is_corners else ""
    family = "corners" if is_corners else "handicap"
    return _price_group(
        [f"{prefix}{home} {hl:+g}{noun} AH", f"{prefix}{away} {al:+g}{noun} AH"],
        [h["price"], a["price"]],
        family=family,
        market=f"{prefix}Asian handicap {hl:+g}{noun}",
        line=hl,
        side=None,
        period=period,
        source_key=m.get("key", ""),
    )


_SPECIAL_FAMILIES = {
    "both teams to score?": "btts",
    "draw no bet": "dc_dnb",
    "double chance": "dc_dnb",
}


def _special_family(description: str) -> str:
    return _SPECIAL_FAMILIES.get(description.strip().lower(), "specials")


def _special_tip(description: str, participant: str) -> str:
    desc = description.strip().lower()
    if desc == "both teams to score?":
        return f"BTTS {participant}"
    if desc == "draw no bet":
        return f"{participant} draw no bet"
    if desc == "double chance":
        return f"Double chance {participant}"
    if desc.endswith("?"):
        return f"{description[:-1].strip()}: {participant}"
    return f"{description}: {participant}"


def _special(m: dict, special: PinnacleMatchup) -> list[MarketQuote]:
    prices = m.get("prices") or []
    labels: list[str] = []
    american: list[float] = []
    for p in prices:
        pid = p.get("participantId")
        name = special.participant_names.get(pid) if pid is not None else None
        if name is None or p.get("price") is None:
            continue
        labels.append(_special_tip(special.special_description, name))
        american.append(p["price"])
    return _price_group(
        labels,
        american,
        family=_special_family(special.special_description),
        market=special.special_description,
        line=None,
        side=None,
        period=int(m.get("period") or 0),
        source_key=m.get("key", ""),
    )


def build_quotes(
    main: PinnacleMatchup,
    related: list[PinnacleMatchup],
    markets: list[dict],
) -> list[MarketQuote]:
    """Normalize every market attached to a fixture and its related matchups."""
    by_id = {r.id: r for r in related}
    by_id.setdefault(main.id, main)
    out: list[MarketQuote] = []

    for m in markets or []:
        mid = m.get("matchupId")
        owner = by_id.get(mid)
        if owner is None:
            continue
        if owner.kind == "bookings":
            continue

        period = int(m.get("period") or 0)
        mtype = m.get("type")

        if owner.kind == "special":
            if mtype == "moneyline":
                out.extend(_special(m, owner))
            continue

        if period not in (0, 1):
            continue
        is_corners = owner.kind == "corners"

        if mtype == "total":
            out.extend(_totals(m, period, is_corners))
        elif mtype == "team_total" and not is_corners:
            out.extend(_team_totals(m, period, main.home, main.away))
        elif mtype == "moneyline" and not is_corners:
            out.extend(_moneyline(m, period, main.home, main.away))
        elif mtype == "spread":
            out.extend(_spread(m, period, main.home, main.away, is_corners))

    seen: set[tuple[str, int]] = set()
    unique: list[MarketQuote] = []
    for q in out:
        key = (q.tip.lower(), q.period)
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique
