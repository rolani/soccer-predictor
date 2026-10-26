"""Replace agent-supplied odds with verified board prices.

The agent cannot read a sportsbook, so any price it writes is an estimate.
Estimates skew high because the odds-range gate rejects anything below
`min_odds`, which rewards pricing to the floor. Everything published must
therefore be re-priced from the board before the gates run.
"""

from __future__ import annotations

from predictor.odds.board import PricedBoard
from predictor.odds.matching import resolve_quote
from predictor.web.schema import Pick

PRICE_TOLERANCE = 0.005
_BOOK_LABEL = {
    "pinnacle": "SportyBet ng (modelled)",
    "flashscore": "Flashscore (approx)",
    "oddsfilter": "OddsFilter (approx)",
}


def verify_prices(
    picks: list[Pick],
    board: PricedBoard | None,
) -> tuple[list[Pick], list[str]]:
    """Re-price every pick from the board. Returns (picks, notes)."""
    notes: list[str] = []
    out: list[Pick] = []

    for p in picks:
        claimed = p.odds
        fixture = board.find(p.match) if board else None
        quote = resolve_quote(p.tip, p.market, fixture.quotes) if fixture else None

        if quote is None:
            reason = (
                "no board"
                if board is None
                else "fixture not on board"
                if fixture is None
                else "market not on board"
            )
            out.append(
                p.model_copy(
                    update={
                        "odds": None,
                        "quoted_odds": claimed,
                        "price_available": False,
                        "price_source": "unpriced",
                    }
                )
            )
            notes.append(f"{p.match} — {p.tip}: unpriced ({reason})")
            continue

        if claimed is not None and abs(claimed - quote.odds) > PRICE_TOLERANCE:
            notes.append(
                f"{p.match} — {p.tip}: agent quoted {claimed:.2f}, "
                f"book price {quote.odds:.2f} (corrected)"
            )

        source = quote.source or "pinnacle"
        out.append(
            p.model_copy(
                update={
                    "odds": quote.odds,
                    "quoted_odds": claimed,
                    "price_available": True,
                    "price_source": source,
                    "market_family": quote.family,
                    "book": _BOOK_LABEL.get(source, p.book),
                }
            )
        )

    return out, notes
