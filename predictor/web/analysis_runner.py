"""Run the predictions-analysis workflow as an SDK agent from the web app.

Unlike prediction runs, this agent needs the `edit` tool so it can write the
dated report and recompute MASTER.md. `shell` stays disallowed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from cursor_sdk import AgentOptions, AsyncClient, LocalAgentOptions

from predictor.web.bus import bus
from predictor.web.schema import RunMeta, RunStatus, Scope, now_iso
from predictor.web.settings import ANALYSIS_DIR, settings
from predictor.web.sse import message_to_event
from predictor.web.store import (
    _run_dir,
    append_log,
    list_runs,
    read_meta,
    read_result,
    write_meta,
)

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
LEDGER_NAME = "graded_runs.json"
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP])M", re.IGNORECASE)


def _ledger_path():
    return ANALYSIS_DIR / LEDGER_NAME


def read_ledger() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"graded": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"graded": []}
    if not isinstance(data, dict) or not isinstance(data.get("graded"), list):
        return {"graded": []}
    return data


def mark_graded(run_ids: list[str], report: str) -> None:
    ledger = read_ledger()
    known = {e.get("run_id") for e in ledger["graded"]}
    for run_id in run_ids:
        if run_id in known:
            continue
        ledger["graded"].append({"run_id": run_id, "graded_at": now_iso(), "report": report})
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _latest_kickoff_utc(run_id: str) -> datetime | None:
    """Latest kickoff in a run, from the ET strings the agent wrote."""
    result = read_result(run_id)
    if not result or not result.picks:
        return None
    try:
        day = datetime.strptime(run_id[:10], "%Y-%m-%d")
    except ValueError:
        return None

    latest: datetime | None = None
    for p in result.picks:
        m = _TIME_RE.search(p.kickoff_et or "")
        if not m:
            continue
        hour = int(m.group(1)) % 12
        if m.group(3).upper() == "P":
            hour += 12
        when = day.replace(hour=hour, minute=int(m.group(2)), tzinfo=EASTERN)
        as_utc = when.astimezone(timezone.utc)
        if latest is None or as_utc > latest:
            latest = as_utc
    return latest


def ungraded_runs(min_age_hours: float = 3.0, now: datetime | None = None) -> list[str]:
    """Completed runs whose matches have finished and that are not in the ledger."""
    now = now or datetime.now(timezone.utc)
    graded = {e.get("run_id") for e in read_ledger()["graded"]}
    out: list[str] = []
    for meta in list_runs(limit=200):
        if meta.id in graded:
            continue
        if meta.status != RunStatus.completed or meta.pick_count == 0:
            continue
        if meta.id.startswith("analysis_"):
            continue
        latest = _latest_kickoff_utc(meta.id)
        if latest is None:
            continue
        if now - latest < timedelta(hours=min_age_hours):
            continue
        out.append(meta.id)
    return sorted(out)


def build_analysis_prompt(run_ids: list[str]) -> str:
    listed = "\n".join(f"- `.runs/{rid}/run.json`" for rid in run_ids)
    return f"""Grade completed prediction runs and update the analysis files.

Follow the workflow in `.cursor/commands/predictions-analysis.md` exactly.

## Runs to grade

{listed}

## Steps

1. Read each `run.json` above. Each pick has `match`, `tip`, `odds`,
   `quoted_odds`, `confidence`, `market_family`, and `estimated_probability`.
2. Look up the 90-minute result for every unique match on ESPN, LiveScore,
   FlashScore, or the league site. Mark unfinished matches as `—`.
3. Grade each tip using the settlement rules in the command file.
4. Write `.analysis/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.md` with the
   per-run tables, confidence-bucket calibration, and ticket settlement.
5. Recompute `.analysis/MASTER.md`: pooled market performance, confidence
   buckets, ticket record, league notes, and the usage guidance.

## Price accuracy

Picks now carry both `odds` (the verified book price) and `quoted_odds` (what a
previous agent estimated). Where the two differ, report the mean absolute error
in a **Price accuracy** section of MASTER so the pricing model can be tuned.
Prices recorded before this change are unreliable — do not compare pre-change
PnL with post-change PnL.

## Market coverage

Report the market-family mix of graded picks. Flag families with fewer than 10
samples as thin rather than weak.

Do not modify anything outside `.analysis/`.
"""


class AnalysisManager:
    def __init__(self) -> None:
        self._client: AsyncClient | None = None
        self._running_id: str | None = None
        self._lock = asyncio.Lock()

    async def set_client(self, client: AsyncClient) -> None:
        self._client = client

    def is_running(self) -> bool:
        return self._running_id is not None

    def status(self) -> dict[str, Any]:
        ledger = read_ledger()["graded"]
        return {
            "ungraded": ungraded_runs(),
            "running": self.is_running(),
            "running_id": self._running_id,
            "last_graded_at": ledger[-1]["graded_at"] if ledger else None,
        }

    async def start(self) -> str:
        if self.is_running():
            raise RuntimeError("An analysis run is already in progress")
        if not settings.cursor_api_key:
            raise ValueError("CURSOR_API_KEY is not set. Add it to .env - see README.")
        if not self._client:
            raise RuntimeError("SDK client not initialized")

        run_ids = ungraded_runs()
        if not run_ids:
            raise ValueError("No completed runs are waiting to be graded")

        async with self._lock:
            if self.is_running():
                raise RuntimeError("An analysis run is already in progress")
            run_id = f"analysis_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            d = _run_dir(run_id)
            d.mkdir(parents=True, exist_ok=True)
            meta = RunMeta(
                id=run_id, status=RunStatus.running, scope=Scope.today, created_at=now_iso()
            )
            write_meta(run_id, meta)
            self._running_id = run_id
            asyncio.create_task(self._execute(run_id, run_ids))
            return run_id

    async def _execute(self, run_id: str, graded_ids: list[str]) -> None:
        assert self._client is not None
        prompt = build_analysis_prompt(graded_ids)
        try:
            async with await self._client.agents.create(
                AgentOptions(
                    model=settings.default_model,
                    api_key=settings.cursor_api_key,
                    local=LocalAgentOptions(
                        cwd=str(settings.repo_root),
                        setting_sources=["project"],
                    ),
                    disallowed_tools=["shell"],
                ),
            ) as agent:
                append_log(run_id, f"analysis agent created: {agent.agent_id}")
                handle = await agent.send(prompt)
                await bus.publish(run_id, {"type": "started", "agent_id": agent.agent_id})

                async for msg in handle.messages():
                    event = message_to_event(msg)
                    if event:
                        await bus.publish(run_id, event)

                result = await handle.wait()
                append_log(run_id, f"analysis finished: status={result.status}")

                meta = read_meta(run_id)
                if result.status == "error":
                    if meta:
                        meta.status = RunStatus.error
                        meta.error = "Analysis agent ended with error status"
                else:
                    mark_graded(graded_ids, f".analysis/ (see MASTER.md, {now_iso()})")
                    if meta:
                        meta.status = RunStatus.completed
                        meta.pick_count = len(graded_ids)
                if meta:
                    meta.completed_at = now_iso()
                    write_meta(run_id, meta)

                await bus.publish(
                    run_id,
                    {"type": "done", "status": meta.status.value if meta else "error"},
                )
        except Exception as e:
            logger.exception("Analysis run failed for %s", run_id)
            append_log(run_id, f"analysis error: {e}")
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.error
                meta.error = str(e)
                meta.completed_at = now_iso()
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "error", "message": str(e)})
        finally:
            self._running_id = None
            await bus.close(run_id)


analysis_manager = AnalysisManager()
