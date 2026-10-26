"""Tests for server-side price verification."""

from __future__ import annotations

import pytest
from predictor.odds.board import BoardFixture, PricedBoard
from predictor.odds.quotes import MarketQuote
from predictor.web.schema import Pick
from predictor.web.verify import verify_prices


def quote(tip, odds, family="goals_totals"):
    return MarketQuote(
        family=family,
        market="m",
        tip=tip,
        line=1.5,
        side=None,
        period=0,
        odds=odds,
        raw_odds=odds + 0.02,
        fair_probability=0.80,
        source_key="k",
    )


def board() -> PricedBoard:
    return PricedBoard(
        fixtures=[
            BoardFixture(
                league="UEFA - Champions League Qualifiers",
                home="Viking",
                away="Dinamo Zagreb",
                kickoff_utc="2026-08-26T19:00:00Z",
                kickoff_et="3:00 PM ET",
                matchup_id=1,
                quotes=[quote("Over 1.5 goals", 1.18), quote("BTTS Yes", 1.70, "btts")],
            )
        ],
        fetched_at="2026-08-26T14:00:00+00:00",
        errors=[],
    )


def pick(**kw) -> Pick:
    defaults = dict(
        match="Viking FK vs GNK Dinamo Zagreb",
        market="Over 1.5",
        tip="Over 1.5 goals",
        odds=1.40,
        confidence=79,
        estimated_probability=0.82,
        reasoning="Level aggregate forces both sides forward.",
        evidence=["First leg 2-2 with four goals before half-time"],
    )
    defaults.update(kw)
    return Pick(**defaults)


class TestOverwrite:
    def test_inflated_price_is_replaced_with_the_book_price(self):
        out, notes = verify_prices([pick()], board())
        assert out[0].odds == 1.18
        assert notes

    def test_original_quote_is_retained(self):
        out, _ = verify_prices([pick()], board())
        assert out[0].quoted_odds == 1.40

    def test_provenance_is_recorded(self):
        out, _ = verify_prices([pick()], board())
        assert out[0].price_source == "pinnacle"
        assert out[0].market_family == "goals_totals"
        assert out[0].price_available is True

    def test_flashscore_quote_keeps_flashscore_source(self):
        fs_board = PricedBoard(
            fixtures=[
                BoardFixture(
                    league="Ligue 1",
                    home="Paris Saint-Germain",
                    away="Lyon",
                    kickoff_utc="2026-10-26T19:30:00Z",
                    kickoff_et="3:30 PM ET",
                    matchup_id=9,
                    quotes=[
                        MarketQuote(
                            family="goals_totals",
                            market="m",
                            tip="Over 1.5 goals",
                            line=1.5,
                            side=None,
                            period=0,
                            odds=1.45,
                            raw_odds=1.45,
                            fair_probability=0.69,
                            source_key="fs",
                            source="flashscore",
                        )
                    ],
                )
            ],
            fetched_at="now",
            errors=[],
        )
        out, _ = verify_prices(
            [pick(match="Paris Saint-Germain vs Lyon", odds=1.60)],
            fs_board,
        )
        assert out[0].price_available is True
        assert out[0].odds == 1.45
        assert out[0].price_source == "flashscore"
        assert out[0].book == "Flashscore (approx)"

    def test_matching_price_produces_no_note(self):
        out, notes = verify_prices([pick(odds=1.18)], board())
        assert out[0].odds == 1.18
        assert not notes

    def test_note_names_both_numbers(self):
        _, notes = verify_prices([pick()], board())
        assert "1.40" in notes[0] and "1.18" in notes[0]


class TestUnpriced:
    def test_unknown_fixture_becomes_unpriced(self):
        out, _ = verify_prices([pick(match="Barcelona vs Real Madrid")], board())
        assert out[0].price_available is False
        assert out[0].odds is None
        assert out[0].price_source == "unpriced"

    def test_unknown_fixture_keeps_the_agent_quote_for_reference(self):
        out, _ = verify_prices([pick(match="Barcelona vs Real Madrid")], board())
        assert out[0].quoted_odds == 1.40

    def test_unknown_market_on_a_known_fixture_becomes_unpriced(self):
        out, _ = verify_prices([pick(tip="Correct score 2-1", market="Correct score")], board())
        assert out[0].price_available is False

    def test_absent_board_leaves_picks_unpriced(self):
        out, notes = verify_prices([pick()], None)
        assert out[0].price_available is False
        assert notes


class TestGateInteraction:
    """Verification runs before the gates, so the gates see the true price."""

    def test_true_price_can_fail_a_margin_gate_the_fake_price_passed(self):
        out, _ = verify_prices([pick(odds=1.40, estimated_probability=0.82)], board())
        implied_at_true_price = 1.0 / out[0].odds
        assert out[0].estimated_probability < implied_at_true_price + 0.05


class TestSubmitPicksIntegration:
    def test_submit_picks_overwrites_an_inflated_price(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.schema import CreateRunRequest, Scope
        from predictor.web.store import init_run, read_result
        from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool

        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-26_verify_today"
        req = CreateRunRequest(
            scope=Scope.today,
            min_confidence=70,
            min_odds=1.10,
            max_odds=3.0,
            margin_buffer=0.0,
        )
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump(), board=board())
        tool = make_submit_picks_tool(ctx)

        msg = tool.execute(
            {
                "summary": "inflated",
                "picks": [pick(odds=1.40, estimated_probability=0.90).model_dump()],
            },
            None,
        )

        assert "accepted" in msg
        stored = read_result(run_id)
        assert stored.picks[0].odds == 1.18
        assert stored.picks[0].quoted_odds == 1.40

    def test_pre_match_pick_without_a_board_price_still_publishes(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.schema import CreateRunRequest, Scope
        from predictor.web.store import init_run, read_result
        from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool

        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-26_unpriced_today"
        req = CreateRunRequest(scope=Scope.today, min_confidence=70)
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump(), board=board())
        tool = make_submit_picks_tool(ctx)

        msg = tool.execute(
            {
                "summary": "off board",
                "picks": [pick(match="Barcelona vs Real Madrid").model_dump()],
            },
            None,
        )

        assert "accepted" in msg
        stored = read_result(run_id)
        assert len(stored.picks) == 1
        assert stored.picks[0].price_available is False
