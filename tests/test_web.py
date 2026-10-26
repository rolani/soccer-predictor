"""Tests for predictor web app, exports, and schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from predictor.exports import (
    ExportedPick,
    export_file,
    parse_prediction_md,
    write_exports,
)
from predictor.web.match_utils import dedupe_picks_by_match, normalize_match_key
from predictor.web.prompt import build_prompt
from predictor.web.schema import (
    CreateRunRequest,
    Pick,
    RunResult,
    Scope,
    SuggestedTicket,
    submit_picks_json_schema,
)
from predictor.web.settings import REPO_ROOT, STATIC_DIR
from predictor.web.sse import message_to_event
from predictor.web.store import init_run, make_run_id, read_meta, read_result, write_result
from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool


def _sample_pick(**kwargs) -> Pick:
    defaults = dict(
        match="Alpha vs Beta",
        tip="Over 1.5 goals",
        odds=1.55,
        confidence=82,
        estimated_probability=0.72,
        reasoning="Both sides score regularly.",
        evidence=["Alpha scored in 8/10 home games", "Beta conceded in 7/10 away"],
    )
    defaults.update(kwargs)
    return Pick(**defaults)


class TestSchema:
    def test_submit_picks_schema_has_required_fields(self):
        schema = submit_picks_json_schema()
        assert schema["type"] == "object"
        assert "summary" in schema.get("required", [])
        assert "picks" in schema.get("properties", {})

    def test_pick_rejects_empty_evidence(self):
        with pytest.raises(Exception):
            _sample_pick(evidence=[])

    def test_run_result_roundtrip(self):
        run_id = "test_run_id"
        result = RunResult(
            run_id=run_id,
            scope=Scope.today,
            generated_at="2026-08-22T12:00:00-04:00",
            summary="Test summary",
            picks=[_sample_pick()],
        )
        restored = RunResult.model_validate_json(result.model_dump_json())
        assert restored.picks[0].match == "Alpha vs Beta"


class TestExports:
    def test_write_exports_creates_three_files(self, tmp_path: Path):
        picks = [ExportedPick(league="MLS", match="A vs B", tip="Over 1.5", odds=1.5)]
        paths = write_exports(picks, tmp_path, "test_base")
        assert paths["csv"].exists()
        assert paths["txt"].exists()
        assert paths["search"].exists()
        csv_text = paths["csv"].read_text(encoding="utf-8")
        assert "A vs B" in csv_text
        assert "Over 1.5" in csv_text

    def test_parse_prediction_md(self):
        md = """
| # | Match | Tip | Odds |
|---|-------|-----|------|
| 1 | Foo vs Bar | Over 1.5 | 1.45 |
"""
        picks = parse_prediction_md(md)
        assert len(picks) == 1
        assert picks[0].match == "Foo vs Bar"

    def test_export_file_from_markdown(self, tmp_path: Path):
        md_path = tmp_path / "sample_today.md"
        md_path.write_text(
            "| # | Match | Tip | Odds |\n|---|---|---|---|\n| 1 | X vs Y | BTTS Yes | 1.60 |\n",
            encoding="utf-8",
        )
        result = export_file(md_path)
        assert "csv" in result
        assert result["csv"].exists()


class TestStore:
    def test_init_and_read_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        req = CreateRunRequest(scope=Scope.today, min_confidence=75)
        run_id = make_run_id("today")
        init_run(run_id, req)
        meta = read_meta(run_id)
        assert meta is not None
        assert meta.scope == Scope.today

        result = RunResult(
            run_id=run_id,
            scope=Scope.today,
            generated_at="2026-08-22T12:00:00-04:00",
            summary="ok",
            picks=[_sample_pick()],
        )
        write_result(run_id, result)
        assert read_result(run_id).summary == "ok"


class TestSubmitPicksTool:
    def test_accepts_valid_pick(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-22_test_today"
        req = CreateRunRequest(
            scope=Scope.today,
            min_confidence=75,
            min_odds=1.1,
            max_odds=2.0,
            margin_buffer=0.05,
        )
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump())
        tool = make_submit_picks_tool(ctx)
        msg = tool.execute(
            {
                "summary": "One pick",
                "picks": [_sample_pick().model_dump()],
            },
            None,
        )
        assert "accepted" in msg
        assert ctx.accepted
        stored = read_result(run_id)
        assert stored is not None
        assert len(stored.picks) == 1

    def test_accepts_live_pick_without_price(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-23_test_live"
        req = CreateRunRequest(
            scope=Scope.live,
            min_confidence=75,
            min_odds=1.1,
            max_odds=2.0,
            margin_buffer=0.08,
        )
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.live, req.model_dump())
        tool = make_submit_picks_tool(ctx)
        pick = _sample_pick(
            status="live",
            minute="67'",
            score="2-1",
            price_available=False,
            odds=None,
            book="SportyBet ng (no live quote)",
        )
        msg = tool.execute({"summary": "Live without price", "picks": [pick.model_dump()]}, None)
        assert "accepted" in msg
        assert ctx.accepted
        stored = read_result(run_id)
        assert stored is not None
        assert len(stored.picks) == 1
        assert stored.picks[0].price_available is False
        assert stored.picks[0].odds is None

    def test_dedupes_same_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_exports_from_picks",
            lambda picks, run_id, scope: {"csv": tmp_path / "x.csv"},
        )
        run_id = "2026-08-22_dedupe_today"
        req = CreateRunRequest(scope=Scope.today, min_confidence=70, margin_buffer=0.01)
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump())
        tool = make_submit_picks_tool(ctx)
        msg = tool.execute(
            {
                "summary": "Dup test",
                "picks": [
                    _sample_pick(
                        match="Manchester City vs Bournemouth",
                        tip="Over 2.5 goals",
                        confidence=80,
                        estimated_probability=0.75,
                    ).model_dump(),
                    _sample_pick(
                        match="Manchester City vs Bournemouth",
                        tip="Man City over 1.5 team goals",
                        confidence=85,
                        estimated_probability=0.78,
                    ).model_dump(),
                ],
            },
            None,
        )
        assert "accepted" in msg
        stored = read_result(run_id)
        assert len(stored.picks) == 1
        assert "over 1.5" in stored.picks[0].tip.lower()

    def test_rejects_low_confidence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        run_id = "2026-08-22_reject_today"
        req = CreateRunRequest(scope=Scope.today, min_confidence=90)
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.today, req.model_dump())
        tool = make_submit_picks_tool(ctx)
        msg = tool.execute(
            {
                "summary": "Bad pick",
                "picks": [_sample_pick(confidence=70).model_dump()],
            },
            None,
        )
        assert "Validation failed" in msg or "rejected" in msg.lower()
        assert not ctx.accepted

    def test_gameweek_accepts_low_confidence_unpriced_cs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        monkeypatch.setattr(
            "predictor.exports.write_twitter_exports",
            lambda picks, **kwargs: {
                "twitter_full": tmp_path / "full.txt",
                "twitter_thread": tmp_path / "thread.txt",
            },
        )
        monkeypatch.setattr(
            "predictor.web.tools.write_twitter_exports",
            lambda picks, **kwargs: {
                "twitter_full": tmp_path / "full.txt",
                "twitter_thread": tmp_path / "thread.txt",
            },
            raising=False,
        )
        run_id = "2026-08-26_test_gameweek"
        req = CreateRunRequest(
            scope=Scope.gameweek,
            min_confidence=75,
            margin_buffer=0.08,
        )
        init_run(run_id, req)
        ctx = SubmitPicksContext(run_id, Scope.gameweek, req.model_dump())
        tool = make_submit_picks_tool(ctx)
        pick = _sample_pick(
            tip="2-1",
            market="Correct score",
            odds=None,
            price_available=False,
            confidence=65,
            estimated_probability=0.18,
        )
        msg = tool.execute(
            {"summary": "Gameweek CS card", "picks": [pick.model_dump()]},
            None,
        )
        assert "accepted" in msg
        assert ctx.accepted
        stored = read_result(run_id)
        assert stored is not None
        assert len(stored.picks) == 1
        assert stored.picks[0].confidence == 65
        assert stored.picks[0].estimated_probability == 0.18
        assert stored.picks[0].odds is None
        assert stored.picks[0].price_available is False
        assert set(ctx.export_paths) == {"twitter_full", "twitter_thread"}
        assert not any("sportybet.csv" in str(v) for v in ctx.export_paths.values())
        assert not any("sportybet.csv" in k for k in ctx.export_paths)

    def test_gameweek_twitter_passes_leagues_by_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        captured: dict = {}

        def fake_write(picks, **kwargs):
            captured.update(kwargs)
            return {
                "twitter_full": tmp_path / "full.txt",
                "twitter_thread": tmp_path / "thread.txt",
            }

        monkeypatch.setattr("predictor.web.tools.write_twitter_exports", fake_write)
        run_id = "2026-08-26_gw_leagues"
        req = CreateRunRequest(scope=Scope.gameweek)
        init_run(run_id, req)
        mapping = {"Alpha vs Beta": "EPL GW3"}
        ctx = SubmitPicksContext(
            run_id,
            Scope.gameweek,
            req.model_dump(),
            leagues_by_match=mapping,
        )
        tool = make_submit_picks_tool(ctx)
        pick = _sample_pick(
            tip="2-1",
            market="Correct score",
            odds=None,
            price_available=False,
            league="",
        )
        msg = tool.execute(
            {"summary": "Gameweek CS card", "picks": [pick.model_dump()]},
            None,
        )
        assert "accepted" in msg
        assert captured.get("leagues_by_match") == mapping


class TestMatchDedupe:
    def test_normalize_match_key(self):
        assert normalize_match_key("A v B") == normalize_match_key("A vs B")

    def test_dedupe_keeps_highest_confidence(self):
        picks = [
            _sample_pick(match="X vs Y", tip="Over 2.5", confidence=80),
            _sample_pick(match="X vs Y", tip="Team over 1.5", confidence=90),
        ]
        out, notes = dedupe_picks_by_match(picks)
        assert len(out) == 1
        assert out[0].confidence == 90
        assert notes


class TestPrompt:
    def test_build_prompt_live_includes_fixture_sources(self):
        req = CreateRunRequest(scope=Scope.live, min_confidence=80)
        prompt = build_prompt(req, "run123")
        assert "sofascore" in prompt.lower()
        assert "livescore" in prompt.lower()
        assert "flashscore" in prompt.lower()
        assert "price_available" in prompt.lower() or "no live quote" in prompt.lower()

    def test_build_prompt_gameweek_includes_remaining_match(self):
        from predictor.gameweek.types import GameweekBoard, GameweekFixture

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[
                GameweekFixture(
                    league="EPL",
                    round_label="EPL GW3",
                    match="Arsenal vs Chelsea",
                    home="Arsenal",
                    away="Chelsea",
                    kickoff_et="10:00 AM ET",
                    kickoff_utc="2026-08-29T14:00:00Z",
                    sources=["football-data", "fotmob"],
                    unconfirmed_slate=False,
                )
            ],
        )
        req = CreateRunRequest(scope=Scope.gameweek)
        prompt = build_prompt(req, "run_gw", gameweek_board=board)
        assert "Arsenal vs Chelsea" in prompt
        assert "round_label" in prompt
        assert "EPL GW3" in prompt


class TestSSE:
    def test_assistant_message_dict(self):
        event = message_to_event(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Researching MLS..."}]},
            }
        )
        assert event is not None
        assert event["type"] == "assistant"
        assert "MLS" in event["text"]

    def test_tool_call_dict(self):
        event = message_to_event({"type": "tool_call", "name": "submit_picks", "status": "running"})
        assert event["type"] == "tool"
        assert event["name"] == "submit_picks"


class TestProjectLayout:
    def test_repo_has_cursor_rules(self):
        assert (REPO_ROOT / ".cursor" / "rules" / "soccer-prediction-core.mdc").exists()

    def test_run_schema_doc_exists(self):
        assert (REPO_ROOT / ".cursor" / "skills" / "soccer-predictions" / "run-schema.md").exists()

    def test_static_frontend_built(self):
        index = STATIC_DIR / "index.html"
        assert index.exists(), "Run: cd webapp && npm run build"

    def test_env_example_exists(self):
        assert (REPO_ROOT / ".env.example").exists()


class TestSettings:
    def test_api_key_loaded_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CURSOR_API_KEY", "test_key_abc")
        from predictor.web.settings import Settings

        s = Settings.load()
        assert s.cursor_api_key == "test_key_abc"

    def test_local_defaults_stay_loopback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PREDICTOR_HOST", raising=False)
        monkeypatch.delenv("PREDICTOR_PORT", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("RENDER", raising=False)
        from predictor.web.settings import Settings

        s = Settings.load()
        assert s.host == "127.0.0.1"
        assert s.port == 8765

    def test_render_binds_platform_port(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PREDICTOR_HOST", raising=False)
        monkeypatch.delenv("PREDICTOR_PORT", raising=False)
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.setenv("PORT", "10000")
        from predictor.web.settings import Settings

        s = Settings.load()
        assert s.host == "0.0.0.0"
        assert s.port == 10000


class TestPriceProvenance:
    def test_pick_defaults_to_unpriced_source(self):
        p = _sample_pick()
        assert p.price_source == "unpriced"
        assert p.quoted_odds is None
        assert p.market_family == ""

    def test_pick_carries_provenance_through_a_roundtrip(self):
        p = _sample_pick(
            odds=1.18, quoted_odds=1.40, price_source="pinnacle", market_family="goals_totals"
        )
        restored = Pick.model_validate_json(p.model_dump_json())
        assert restored.odds == 1.18
        assert restored.quoted_odds == 1.40
        assert restored.price_source == "pinnacle"
        assert restored.market_family == "goals_totals"

    def test_request_accepts_overround_override(self):
        req = CreateRunRequest(book_overround={"goals_totals": 1.09})
        assert req.book_overround["goals_totals"] == 1.09

    def test_request_overround_defaults_to_none(self):
        assert CreateRunRequest().book_overround is None


class TestPromptWithBoard:
    def test_prompt_includes_the_priced_board(self):
        from predictor.odds.board import BoardFixture, PricedBoard
        from predictor.odds.quotes import MarketQuote

        board = PricedBoard(
            fixtures=[
                BoardFixture(
                    league="EFL Cup",
                    home="Newcastle United",
                    away="West Bromwich Albion",
                    kickoff_utc="2026-08-26T18:45:00Z",
                    kickoff_et="2:45 PM ET",
                    matchup_id=3,
                    quotes=[
                        MarketQuote(
                            family="goals_totals",
                            market="Over/Under 1.5 goals",
                            tip="Over 1.5 goals",
                            line=1.5,
                            side=None,
                            period=0,
                            odds=1.16,
                            raw_odds=1.18,
                            fair_probability=0.87,
                            source_key="k",
                        )
                    ],
                )
            ],
            fetched_at="2026-08-26T14:00:00+00:00",
            errors=[],
        )
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123", odds_board=board)
        assert "Newcastle United vs West Bromwich Albion" in prompt
        assert "1.16" in prompt

    def test_prompt_forbids_inventing_a_price(self):
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123")
        assert "do not invent" in prompt.lower()

    def test_prompt_asks_for_market_variety(self):
        req = CreateRunRequest(scope=Scope.today)
        prompt = build_prompt(req, "run123")
        assert "famil" in prompt.lower()


class TestHealthEndpoint:
    def test_health_route_registered(self):
        import predictor.web.app as app_module

        paths = {r.path for r in app_module.app.routes}
        assert "/api/health" in paths


class TestOddsBoardEndpoint:
    def test_board_route_registered(self):
        import predictor.web.app as app_module

        paths = {r.path for r in app_module.app.routes}
        assert "/api/odds/board" in paths

    def test_board_endpoint_shape(self, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient
        from predictor.odds.board import PricedBoard

        monkeypatch.setattr(
            app_module,
            "build_board",
            lambda **kw: PricedBoard(fixtures=[], fetched_at="now", errors=[]),
        )
        with TestClient(app_module.app) as client:
            r = client.get("/api/odds/board?scope=today&min_odds=1.1&max_odds=3.0")
        assert r.status_code == 200
        body = r.json()
        assert "fixtures" in body
        assert "fetched_at" in body


class TestAnalysisEndpoints:
    def test_routes_registered(self):
        import predictor.web.app as app_module

        paths = {r.path for r in app_module.app.routes}
        assert "/api/analysis/status" in paths
        assert "/api/analysis/run" in paths

    def test_status_shape(self, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module

        monkeypatch.setattr(
            app_module.analysis_manager,
            "status",
            lambda: {
                "ungraded": ["a"],
                "running": False,
                "running_id": None,
                "last_graded_at": None,
            },
        )
        body = app_module.analysis_manager.status()
        assert body["ungraded"] == ["a"]
        assert body["running"] is False


class TestGameweekSchema:
    def test_scope_accepts_gameweek(self):
        assert Scope("gameweek") == Scope.gameweek

    def test_target_odds_defaults_none(self):
        assert CreateRunRequest().target_odds is None

    def test_target_odds_accepted(self):
        req = CreateRunRequest(target_odds=8.0)
        assert req.target_odds == 8.0

    def test_suggested_ticket_in_band_defaults_none(self):
        dumped = SuggestedTicket().model_dump()
        assert dumped.get("in_band") is None
        assert dumped.get("used_fill") is False

    def test_suggested_ticket_persists_in_band_and_used_fill(self):
        dumped = SuggestedTicket(in_band=False, used_fill=True).model_dump()
        assert dumped.get("in_band") is False
        assert dumped.get("used_fill") is True

    def test_target_ticket_request_fill_defaults_false(self):
        from predictor.web import schema as schema_mod

        assert hasattr(schema_mod, "TargetTicketRequest")
        assert schema_mod.TargetTicketRequest().fill is False


def _sample_gameweek_fixture(**kwargs):
    from predictor.gameweek.types import GameweekFixture

    defaults = dict(
        league="EPL",
        round_label="EPL GW3",
        match="Arsenal vs Chelsea",
        home="Arsenal",
        away="Chelsea",
        kickoff_et="10:00 AM ET",
        kickoff_utc="2026-08-29T14:00:00Z",
        sources=["football-data", "fotmob"],
        unconfirmed_slate=False,
    )
    defaults.update(kwargs)
    return GameweekFixture(**defaults)


class TestGameweekEndpoint:
    def test_board_route_registered(self):
        import predictor.web.app as app_module

        routes = list(app_module.app.routes)
        paths = [r.path for r in routes]
        assert "/api/gameweek/board" in paths
        gw = paths.index("/api/gameweek/board")
        catchalls = [i for i, p in enumerate(paths) if p == "/{full_path:path}"]
        if catchalls:
            assert gw < catchalls[0], "SPA catch-all must remain last"

    def test_board_endpoint_shape(self, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient
        from predictor.gameweek.types import GameweekBoard

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[_sample_gameweek_fixture()],
            skipped=[],
            source_errors=[],
        )
        monkeypatch.setattr(app_module, "build_gameweek_board", lambda: board)
        with TestClient(app_module.app) as client:
            r = client.get("/api/gameweek/board")
        assert r.status_code == 200
        body = r.json()
        assert "fixtures" in body
        assert "remaining" in body
        assert "unconfirmed_slate" in body
        assert "source_errors" in body
        assert body["remaining"] == 1
        assert body["fixtures"][0]["match"] == "Arsenal vs Chelsea"
        assert body["unconfirmed_slate"] is False
        assert body["source_errors"] == []

    def test_board_never_500_on_empty_errors(self, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient
        from predictor.gameweek.types import GameweekBoard

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=[],
            fixtures=[],
            skipped=[],
            source_errors=["espn: timeout", "fotmob: 403"],
        )
        monkeypatch.setattr(app_module, "build_gameweek_board", lambda: board)
        with TestClient(app_module.app) as client:
            r = client.get("/api/gameweek/board")
        assert r.status_code == 200
        body = r.json()
        assert body["fixtures"] == []
        assert body["remaining"] == 0
        assert body["source_errors"]

    def test_twitter_export_alias_finds_full_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient
        from predictor.web.schema import RunMeta, RunStatus

        full = tmp_path / "gw_gameweek_twitter.txt"
        full.write_text("FULL TWITTER BODY", encoding="utf-8")
        thread = tmp_path / "gw_gameweek_twitter_thread.txt"
        thread.write_text("THREAD TWITTER BODY", encoding="utf-8")
        meta = RunMeta(
            id="gw-run-1",
            status=RunStatus.completed,
            scope=Scope.gameweek,
            created_at="2026-08-26T18:00:00+00:00",
            export_paths={
                "twitter_full": str(full),
                "twitter_thread": str(thread),
            },
        )
        monkeypatch.setattr(app_module, "read_meta", lambda run_id: meta)
        with TestClient(app_module.app) as client:
            r = client.get("/api/exports/gw-run-1/twitter")
        assert r.status_code == 200
        assert "FULL TWITTER BODY" in r.text

        with TestClient(app_module.app) as client:
            r_full = client.get("/api/exports/gw-run-1/twitter_full")
            r_thread = client.get("/api/exports/gw-run-1/twitter_thread")
        assert r_full.status_code == 200
        assert "FULL TWITTER BODY" in r_full.text
        assert r_thread.status_code == 200
        assert "THREAD TWITTER BODY" in r_thread.text

    def test_empty_board_does_not_start_agent(self):
        from predictor.gameweek.types import GameweekBoard
        from predictor.web.runner import gameweek_empty_reason, gameweek_should_start_agent

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=[],
            fixtures=[],
            skipped=[],
            source_errors=["espn: timeout"],
            sources_up=0,
        )
        assert gameweek_should_start_agent(board) is False
        assert gameweek_empty_reason(board) == "No calendar sources"

    def test_finished_round_is_no_remaining_fixtures_not_calendar_failure(self):
        from predictor.gameweek.types import GameweekBoard
        from predictor.web.runner import gameweek_empty_reason, gameweek_should_start_agent

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=[],
            fixtures=[],
            skipped=[],
            sources_up=2,
        )
        assert gameweek_should_start_agent(board) is False
        assert gameweek_empty_reason(board) == "No remaining fixtures"

    def test_gameweek_leagues_by_match_maps_round_label(self):
        from predictor.gameweek.types import GameweekBoard
        from predictor.web.runner import gameweek_leagues_by_match

        board = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[_sample_gameweek_fixture()],
            sources_up=2,
        )
        assert gameweek_leagues_by_match(board) == {"Arsenal vs Chelsea": "EPL GW3"}

    def test_fixtures_or_skipped_start_agent(self):
        from predictor.gameweek.types import GameweekBoard
        from predictor.web.runner import gameweek_empty_reason, gameweek_should_start_agent

        with_fixture = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=["EPL"],
            fixtures=[_sample_gameweek_fixture()],
            sources_up=2,
        )
        assert gameweek_should_start_agent(with_fixture) is True
        assert gameweek_empty_reason(with_fixture) is None

        with_skipped = GameweekBoard(
            fetched_at="2026-08-26T18:00:00+00:00",
            leagues=[],
            skipped=[{"match": "A vs B", "why": "kickoff mismatch"}],
            sources_up=2,
        )
        assert gameweek_should_start_agent(with_skipped) is True
        assert gameweek_empty_reason(with_skipped) is None


def _store_target_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_odds: float | None = 8.0,
    scope: Scope = Scope.today,
    picks: list[Pick] | None = None,
    run_id: str = "target-ticket-run",
) -> tuple[str, CreateRunRequest]:
    monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
    req = CreateRunRequest(scope=scope, target_odds=target_odds)
    init_run(run_id, req)
    result = RunResult(
        run_id=run_id,
        scope=scope,
        generated_at="2026-08-26T12:00:00-04:00",
        summary="stored",
        picks=picks or [_sample_pick()],
        request=req.model_dump(),
    )
    write_result(run_id, result)
    return run_id, req


class TestTargetTicketEndpoint:
    def test_route_registered(self):
        import predictor.web.app as app_module

        routes = list(app_module.app.routes)
        paths = [r.path for r in routes]
        assert "/api/runs/{run_id}/target-ticket" in paths
        idx = paths.index("/api/runs/{run_id}/target-ticket")
        catchalls = [i for i, p in enumerate(paths) if p == "/{full_path:path}"]
        if catchalls:
            assert idx < catchalls[0], "SPA catch-all must remain last"

    def test_404_when_run_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient

        monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path)
        with TestClient(app_module.app) as client:
            r = client.post("/api/runs/missing-run/target-ticket", json={"fill": False})
        assert r.status_code == 404
        assert r.json()["detail"] == "Run not found"

    def test_200_suggested_tickets_with_monkeypatched_solver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from dataclasses import dataclass

        import predictor.web.app as app_module
        from fastapi.testclient import TestClient

        run_id, _req = _store_target_run(tmp_path, monkeypatch)

        @dataclass
        class _FakeTicket:
            leg_indices: list
            combined_odds: float
            joint_probability: float
            label: str
            in_band: bool
            used_fill: bool
            extra_picks: list

        def fake_solve(*_a, **_k):
            return _FakeTicket(
                leg_indices=[0],
                combined_odds=8.0,
                joint_probability=0.5,
                label="Target 8× (researched)",
                in_band=True,
                used_fill=False,
                extra_picks=[],
            )

        monkeypatch.setattr("predictor.web.odds_solver.solve_target_ticket", fake_solve)
        with TestClient(app_module.app) as client:
            r = client.post(f"/api/runs/{run_id}/target-ticket", json={"fill": False})
        assert r.status_code == 200
        body = r.json()
        tickets = body.get("suggested_tickets")
        if tickets is None:
            tickets = body.get("result", {}).get("suggested_tickets")
        assert tickets
        assert tickets[0]["legs"] == [0]
        assert tickets[0]["combined_odds"] == 8.0

    def test_fill_true_empty_board_returns_200(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import predictor.web.app as app_module
        from fastapi.testclient import TestClient
        from predictor.odds.board import PricedBoard
        from predictor.web.runner import run_manager

        picks = [
            _sample_pick(match="A vs B", odds=1.25, estimated_probability=0.80),
            _sample_pick(match="C vs D", odds=1.30, estimated_probability=0.76),
            _sample_pick(match="E vs F", odds=2.10, estimated_probability=0.45),
        ]
        run_id, _req = _store_target_run(tmp_path, monkeypatch, picks=picks)
        monkeypatch.setattr(
            run_manager,
            "_build_odds_board",
            lambda request: PricedBoard(fixtures=[], fetched_at="now", errors=[]),
        )
        with TestClient(app_module.app) as client:
            r = client.post(f"/api/runs/{run_id}/target-ticket", json={"fill": True})
        assert r.status_code == 200
        body = r.json()
        tickets = body.get("suggested_tickets")
        if tickets is None:
            tickets = body.get("result", {}).get("suggested_tickets")
        assert tickets
        assert tickets[0]["in_band"] is False

    def test_apply_target_odds_ticket_in_band_for_target_8(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.runner import apply_target_odds_ticket

        picks = [
            _sample_pick(match="A vs B", odds=1.40, estimated_probability=0.70),
            _sample_pick(match="C vs D", odds=1.50, estimated_probability=0.66),
            _sample_pick(match="E vs F", odds=1.60, estimated_probability=0.62),
            _sample_pick(match="G vs H", odds=2.20, estimated_probability=0.44),
        ]
        run_id, req = _store_target_run(tmp_path, monkeypatch, picks=picks)
        apply_target_odds_ticket(run_id, req, fill=False)
        result = read_result(run_id)
        assert result is not None
        assert result.suggested_tickets
        ticket = result.suggested_tickets[0]
        assert ticket.in_band is True
        assert ticket.used_fill is False
        assert ticket.combined_odds == pytest.approx(1.40 * 1.50 * 1.60 * 2.20)
        assert set(ticket.legs) == {0, 1, 2, 3}

    def test_gameweek_scope_does_not_auto_solve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from predictor.web.runner import apply_target_odds_ticket

        run_id, req = _store_target_run(
            tmp_path, monkeypatch, scope=Scope.gameweek, target_odds=8.0
        )
        apply_target_odds_ticket(run_id, req, fill=False)
        result = read_result(run_id)
        assert result is not None
        assert result.suggested_tickets == []
