"""Tests for the market-diversity prompt block."""

from __future__ import annotations

from predictor.web.market_mix import format_diversity_block


class TestFormatDiversityBlock:
    def test_calls_out_a_lopsided_mix(self):
        text = format_diversity_block({"goals_totals": 9, "team_totals": 3})
        assert "%" in text
        assert "goals" in text.lower()

    def test_mentions_the_exploration_rationale(self):
        text = format_diversity_block({"goals_totals": 12})
        assert "sample" in text.lower() or "bias" in text.lower()

    def test_empty_history_still_gives_guidance(self):
        text = format_diversity_block({})
        assert "families" in text.lower() or "family" in text.lower()

    def test_balanced_mix_does_not_scold(self):
        text = format_diversity_block({"goals_totals": 3, "corners": 3, "handicap": 3, "btts": 3})
        assert "families" in text.lower()
