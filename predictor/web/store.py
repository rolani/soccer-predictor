"""Filesystem persistence for runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from predictor.web.schema import CreateRunRequest, RunMeta, RunResult, RunStatus, now_iso
from predictor.web.settings import RUNS_DIR


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def make_run_id(scope: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{stamp}_{scope}"


def init_run(run_id: str, request: CreateRunRequest) -> Path:
    d = _run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    meta = RunMeta(
        id=run_id,
        status=RunStatus.pending,
        scope=request.scope,
        created_at=now_iso(),
    )
    write_meta(run_id, meta)
    return d


def write_meta(run_id: str, meta: RunMeta) -> None:
    (_run_dir(run_id) / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def read_meta(run_id: str) -> RunMeta | None:
    path = _run_dir(run_id) / "meta.json"
    if not path.exists():
        return None
    return RunMeta.model_validate_json(path.read_text(encoding="utf-8"))


def write_result(run_id: str, result: RunResult) -> Path:
    path = _run_dir(run_id) / "run.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_result(run_id: str) -> RunResult | None:
    path = _run_dir(run_id) / "run.json"
    if not path.exists():
        return None
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs(limit: int = 50) -> list[RunMeta]:
    if not RUNS_DIR.exists():
        return []
    metas: list[RunMeta] = []
    for child in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        meta = read_meta(child.name)
        if meta:
            metas.append(meta)
        if len(metas) >= limit:
            break
    return metas


def append_log(run_id: str, line: str) -> None:
    path = _run_dir(run_id) / "agent.log"
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def read_master_summary() -> dict[str, Any]:
    from predictor.web.settings import ANALYSIS_DIR

    master = ANALYSIS_DIR / "MASTER.md"
    if not master.exists():
        return {"raw": "", "sections": {}}
    text = master.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current = "intro"
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return {"raw": text, "sections": sections}
