"""OddsFilter screener JSON used as a public-book fallback."""

from __future__ import annotations

from predictor.odds.oddsfilter import quotes_from_row, rows_to_events


def test_quotes_from_row_emit_1x2_over25_and_btts():
    row = {
        "i": 42,
        "t": 1793040300,
        "h": "Santa Clara",
        "a": "Benfica",
        "l": 1000000094,
        "o": [8.68, 4.64, 1.36],
        "ou": [1.76, 2.03],
        "bt": [2.04, 1.71],
        "st": 0,
    }
    quotes = {q.tip: q for q in quotes_from_row(row)}
    assert quotes["Santa Clara win"].odds == 8.68
    assert quotes["Draw"].odds == 4.64
    assert quotes["Benfica win"].odds == 1.36
    assert quotes["Over 2.5 goals"].odds == 1.76
    assert quotes["Under 2.5 goals"].odds == 2.03
    assert quotes["BTTS Yes"].odds == 2.04
    assert quotes["BTTS No"].odds == 1.71
    assert all(q.source == "oddsfilter" for q in quotes.values())

    events = rows_to_events({"rows": [row], "leagues": {"1000000094": {"n": "Primeira Liga"}}})
    assert events[0].league == "Primeira Liga"
    assert events[0].home == "Santa Clara"
    assert events[0].kickoff_utc.endswith("Z")
