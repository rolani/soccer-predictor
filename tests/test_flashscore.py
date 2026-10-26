"""Flashscore delimited feed + GraphQL odds used when Pinnacle is blocked."""

from __future__ import annotations

from predictor.odds.flashscore import (
    median,
    parse_events,
    parse_feed,
    quotes_from_odds,
)

DIV = "\u00f7"
NOT = "\u00ac"


def _feed(*records: dict[str, str]) -> str:
    blocks = []
    for rec in records:
        parts = [f"{k}{DIV}{v}" for k, v in rec.items()]
        blocks.append(NOT.join(parts))
    return "~".join(blocks) + "~"


def test_parse_feed_splits_records_and_fields():
    text = _feed({"ZA": "La Liga"}, {"AA": "abc12xyz", "AE": "Sevilla", "AF": "Osasuna"})
    recs = parse_feed(text)
    assert recs[0]["ZA"] == "La Liga"
    assert recs[1]["AA"] == "abc12xyz"
    assert recs[1]["AE"] == "Sevilla"


def test_parse_events_carries_league_and_kickoff():
    text = _feed(
        {"ZA": "Ligue 1"},
        {
            "AA": "psgLyon1",
            "AE": "Paris Saint-Germain",
            "AF": "Lyon",
            "ADE": "1793052000",
            "JA": "homePid",
            "JB": "awayPid",
        },
    )
    events = parse_events(text)
    assert len(events) == 1
    ev = events[0]
    assert ev.league == "Ligue 1"
    assert ev.home == "Paris Saint-Germain"
    assert ev.away == "Lyon"
    assert ev.event_id == "psgLyon1"
    assert ev.home_pid == "homePid"
    assert ev.kickoff_utc.endswith("Z") or "+" in ev.kickoff_utc


def test_median_picks_the_middle_decimal():
    assert median([1.40, 1.50, 1.80]) == 1.50
    assert median([1.40, 1.60]) == 1.50


def test_quotes_include_over_15_btts_and_1x2():
    odds = [
        {
            "bookmakerId": 1,
            "bettingType": "HOME_DRAW_AWAY",
            "bettingScope": "FULL_TIME",
            "odds": [
                {"eventParticipantId": "H", "value": "1.55", "active": True},
                {"eventParticipantId": "A", "value": "5.50", "active": True},
                {"eventParticipantId": None, "value": "4.20", "active": True},
            ],
        },
        {
            "bookmakerId": 2,
            "bettingType": "HOME_DRAW_AWAY",
            "bettingScope": "FULL_TIME",
            "odds": [
                {"eventParticipantId": "H", "value": "1.65", "active": True},
                {"eventParticipantId": "A", "value": "5.00", "active": True},
                {"eventParticipantId": None, "value": "4.00", "active": True},
            ],
        },
        {
            "bookmakerId": 1,
            "bettingType": "OVER_UNDER",
            "bettingScope": "FULL_TIME",
            "odds": [
                {
                    "selection": "OVER",
                    "value": "1.40",
                    "active": True,
                    "handicap": {"value": "1.5"},
                },
                {
                    "selection": "UNDER",
                    "value": "2.80",
                    "active": True,
                    "handicap": {"value": "1.5"},
                },
            ],
        },
        {
            "bookmakerId": 1,
            "bettingType": "BOTH_TEAMS_TO_SCORE",
            "bettingScope": "FULL_TIME",
            "odds": [
                {"bothTeamsToScore": True, "value": "1.75", "active": True},
                {"bothTeamsToScore": False, "value": "2.05", "active": True},
            ],
        },
        {
            "bookmakerId": 1,
            "bettingType": "DRAW_NO_BET",
            "bettingScope": "FULL_TIME",
            "odds": [
                {"eventParticipantId": "H", "value": "1.22", "active": True},
                {"eventParticipantId": "A", "value": "4.10", "active": True},
            ],
        },
    ]
    quotes = quotes_from_odds(
        home="PSG",
        away="Lyon",
        home_pid="H",
        away_pid="A",
        odds=odds,
    )
    by_tip = {q.tip: q for q in quotes}
    assert by_tip["Over 1.5 goals"].odds == 1.40
    assert by_tip["Over 1.5 goals"].source == "flashscore"
    assert by_tip["BTTS Yes"].odds == 1.75
    assert by_tip["PSG win"].odds == 1.60  # median of 1.55 and 1.65
    assert by_tip["Draw"].odds == 4.10
    assert "PSG draw no bet" in by_tip
    assert all(q.source == "flashscore" for q in quotes)
