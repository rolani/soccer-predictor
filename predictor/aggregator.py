"""Rank and select top N predictions for accumulator bets."""

from predictor.fetchers import Prediction


def rank_for_accumulator(predictions: list[Prediction], count: int) -> list[Prediction]:
    """
    Select top N high-probability picks for accumulator.
    Prefer lower odds (higher probability) — typical accumulator range 1.2–2.0.
    """
    # Filter to accumulator-friendly odds (1.15–2.5)
    filtered = [p for p in predictions if 1.15 <= p.odds <= 2.5]
    # Sort by odds ascending (lower = higher probability)
    sorted_preds = sorted(filtered, key=lambda p: p.odds)
    # Deduplicate by match (keep first/best odds)
    seen = set()
    unique = []
    for p in sorted_preds:
        key = (p.match.lower(), p.tip.lower())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique[:count]


def format_accumulator(predictions: list[Prediction]) -> str:
    """Format predictions for accumulator display."""
    if not predictions:
        return "No high-probability predictions found."
    lines = []
    total_odds = 1.0
    for i, p in enumerate(predictions, 1):
        total_odds *= p.odds
        lines.append(f"  {i}. {p.match} | {p.tip} @ {p.odds:.2f} ({p.source})")
    lines.append("")
    lines.append(f"  Combined odds: {total_odds:.2f}")
    return "\n".join(lines)
