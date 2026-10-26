"""Tests for odds conversion and the soft-book pricing model."""

from __future__ import annotations

import pytest
from predictor.odds.pricing import (
    DEFAULT_OVERROUND,
    american_to_decimal,
    devig,
    overround_for,
    revig,
    to_book_prices,
)


class TestConversion:
    def test_negative_american(self):
        assert american_to_decimal(-152) == pytest.approx(1.658, abs=0.001)

    def test_positive_american(self):
        assert american_to_decimal(127) == pytest.approx(2.27, abs=0.001)

    def test_even_money(self):
        assert american_to_decimal(100) == pytest.approx(2.0, abs=0.001)


class TestDevig:
    def test_fair_probabilities_sum_to_one(self):
        fair = devig([1.237, 4.18])
        assert sum(fair) == pytest.approx(1.0, abs=1e-6)

    def test_favourite_keeps_the_larger_share(self):
        fair = devig([1.237, 4.18])
        assert fair[0] > fair[1]

    def test_three_way_sums_to_one(self):
        fair = devig([1.962, 3.66, 3.87])
        assert sum(fair) == pytest.approx(1.0, abs=1e-6)

    def test_devig_lowers_the_favourite_probability(self):
        raw_favourite = 1 / 1.237
        assert devig([1.237, 4.18])[0] < raw_favourite


class TestRevig:
    def test_hits_the_target_overround(self):
        adjusted = revig([0.7855, 0.2145], 1.055)
        assert sum(adjusted) == pytest.approx(1.055, abs=1e-6)

    def test_longshot_absorbs_more_margin_than_favourite(self):
        fair = [0.7855, 0.2145]
        adjusted = revig(fair, 1.055)
        fav_uplift = adjusted[0] / fair[0]
        dog_uplift = adjusted[1] / fair[1]
        assert dog_uplift > fav_uplift


class TestSportybetCalibration:
    """Reference prices captured from SportyBet ng on 2026-08-26."""

    @pytest.mark.parametrize(
        "pinnacle_pair,sportybet",
        [
            ((1.237, 4.18), 1.25),  # Lyon v Fenerbahce, Over 1.5
            ((1.181, 4.98), 1.18),  # Viking v Dinamo Zagreb, Over 1.5
            ((1.324, 3.42), 1.33),  # Celje v Slovan Bratislava, Over 1.5
        ],
    )
    def test_model_lands_near_the_real_book(self, pinnacle_pair, sportybet):
        modelled = to_book_prices(list(pinnacle_pair), "goals_totals")[0]
        assert modelled == pytest.approx(sportybet, abs=0.03)

    def test_model_never_overstates_a_short_favourite(self):
        """Understating is safe for advertised combined odds; overstating is the bug."""
        modelled = to_book_prices([1.237, 4.18], "goals_totals")[0]
        assert modelled <= 1.25 + 0.001


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw",
        [
            [1.237, 4.18],
            [1.962, 3.66, 3.87],
        ],
    )
    def test_devig_revig_reproduces_implied_probabilities(self, raw):
        implied = [1.0 / d for d in raw]
        source_overround = sum(implied)
        round_trip = revig(devig(raw), source_overround)
        for expected, actual in zip(implied, round_trip):
            assert actual == pytest.approx(expected, abs=1e-6)


class TestSolveCDegenerateInput:
    def test_empty_input_returns_empty_lists(self):
        assert devig([]) == []
        assert revig([], 1.055) == []

    def test_boundary_probabilities_use_identity_transform(self):
        adjusted = revig([0.0, 1.0], 1.055)
        assert adjusted[0] == pytest.approx(0.0)
        assert adjusted[1] == pytest.approx(1.0)

    def test_all_boundary_implied_probs_stay_unchanged(self):
        fair = devig([1.0, 1.0])
        assert fair[0] == pytest.approx(1.0)
        assert fair[1] == pytest.approx(1.0)


class TestOverroundConfig:
    def test_defaults_present_for_every_family(self):
        for family in (
            "goals_totals",
            "team_totals",
            "halves",
            "btts",
            "handicap",
            "result",
            "dc_dnb",
            "corners",
            "specials",
        ):
            assert family in DEFAULT_OVERROUND

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PREDICTOR_OVERROUND_GOALS_TOTALS", "1.09")
        assert overround_for("goals_totals") == pytest.approx(1.09)

    def test_unknown_family_falls_back(self):
        assert overround_for("nonsense") == pytest.approx(DEFAULT_OVERROUND["specials"])
