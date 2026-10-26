"""Tests for analysis run selection and the graded-runs ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from predictor.web.analysis_runner import (
    AnalysisManager,
    build_analysis_prompt,
    mark_graded,
    read_ledger,
    ungraded_runs,
)
from predictor.web.schema import CreateRunRequest, RunResult, RunStatus, Scope
from predictor.web.store import init_run, read_meta, write_meta, write_result


def _make_run(tmp_path: Path, run_id: str, kickoff_et: str, status=RunStatus.completed):
    req = CreateRunRequest(scope=Scope.today)
    init_run(run_id, req)
    meta = read_meta(run_id)
    meta.status = status
    meta.pick_count = 1
    write_meta(run_id, meta)
    write_result(
        run_id,
        RunResult(
            run_id=run_id,
            scope=Scope.today,
            generated_at="2026-08-26T10:00:00-04:00",
            summary="s",
            picks=[
                {
                    "match": "A vs B",
                    "tip": "Over 1.5 goals",
                    "kickoff_et": kickoff_et,
                    "odds": 1.2,
                    "confidence": 80,
                    "estimated_probability": 0.9,
                    "reasoning": "r",
                    "evidence": ["e"],
                }
            ],
        ),
    )


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("predictor.web.store.RUNS_DIR", tmp_path / ".runs")
    monkeypatch.setattr("predictor.web.analysis_runner.ANALYSIS_DIR", tmp_path / ".analysis")
    (tmp_path / ".runs").mkdir()
    (tmp_path / ".analysis").mkdir()
    return tmp_path


class TestLedger:
    def test_empty_ledger_reads_clean(self, runs_dir):
        assert read_ledger() == {"graded": []}

    def test_mark_and_read_back(self, runs_dir):
        mark_graded(["run_a"], ".analysis/report.md")
        entries = read_ledger()["graded"]
        assert len(entries) == 1
        assert entries[0]["run_id"] == "run_a"
        assert entries[0]["report"] == ".analysis/report.md"

    def test_marking_twice_does_not_duplicate(self, runs_dir):
        mark_graded(["run_a"], "r1.md")
        mark_graded(["run_a"], "r2.md")
        assert len(read_ledger()["graded"]) == 1

    def test_corrupt_ledger_is_treated_as_empty(self, runs_dir):
        (runs_dir / ".analysis" / "graded_runs.json").write_text("{{{", encoding="utf-8")
        assert read_ledger() == {"graded": []}


class TestUngradedRuns:
    def test_finished_run_is_ungraded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert "2026-08-26_09-00-00_today" in ungraded_runs(now=now)

    def test_graded_run_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET")
        mark_graded(["2026-08-26_09-00-00_today"], "r.md")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []

    def test_run_whose_matches_have_not_finished_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "11:00 PM ET")
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []

    def test_errored_run_is_excluded(self, runs_dir):
        _make_run(runs_dir, "2026-08-26_09-00-00_today", "9:00 AM ET", RunStatus.error)
        now = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
        assert ungraded_runs(now=now) == []


class TestPrompt:
    def test_prompt_names_every_run(self):
        text = build_analysis_prompt(["run_a", "run_b"])
        assert "run_a" in text and "run_b" in text

    def test_prompt_points_at_the_command_workflow(self):
        text = build_analysis_prompt(["run_a"])
        assert "predictions-analysis" in text

    def test_prompt_requires_master_update(self):
        text = build_analysis_prompt(["run_a"])
        assert "MASTER.md" in text


class TestConcurrency:
    def test_is_running_reflects_state(self, runs_dir):
        mgr = AnalysisManager()
        assert not mgr.is_running()
        mgr._running_id = "analysis_existing"
        assert mgr.is_running()
