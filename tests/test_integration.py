"""Integration tests against a running predictor web server."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"


@pytest.fixture(scope="module")
def server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "predictor.web.app"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 45
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=2.0)
            if r.status_code == 200:
                break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    else:
        proc.kill()
        out, err = proc.communicate(timeout=5)
        pytest.fail(
            f"Server did not start: {last_err}\nstderr: {err.decode()[:500]}\nstdout: {out.decode()[:500]}"
        )

    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.integration
def test_live_fixtures_endpoint(server):
    r = httpx.get(f"{BASE}/api/live/fixtures")
    assert r.status_code == 200
    data = r.json()
    assert "in_play_count" in data
    assert "fixtures" in data
    assert "agent_verify_urls" in data


@pytest.mark.integration
def test_health(server):
    r = httpx.get(f"{BASE}/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["has_api_key"] is True


@pytest.mark.integration
def test_models(server):
    r = httpx.get(f"{BASE}/api/models")
    assert r.status_code == 200
    models = r.json().get("models", [])
    assert len(models) >= 1


@pytest.mark.integration
def test_analysis(server):
    r = httpx.get(f"{BASE}/api/analysis")
    assert r.status_code == 200
    assert "sections" in r.json()


@pytest.mark.integration
def test_runs_list(server):
    r = httpx.get(f"{BASE}/api/runs")
    assert r.status_code == 200
    assert "runs" in r.json()


@pytest.mark.integration
def test_spa_index(server):
    r = httpx.get(BASE + "/")
    assert r.status_code == 200
    assert "Soccer Predictor" in r.text


@pytest.mark.integration
def test_create_run_returns_meta(server):
    r = httpx.post(
        f"{BASE}/api/runs",
        json={
            "scope": "today",
            "min_confidence": 75,
            "all_that_qualify": True,
            "ticket_mode": "singles",
            "model": "composer-2.5",
        },
        timeout=30.0,
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["id"]
    assert meta["status"] in ("pending", "running")

    detail = httpx.get(f"{BASE}/api/runs/{meta['id']}", timeout=10.0)
    assert detail.status_code == 200
    assert detail.json()["meta"]["id"] == meta["id"]
