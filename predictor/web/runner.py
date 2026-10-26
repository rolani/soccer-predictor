"""Cursor SDK agent runner for prediction runs."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from cursor_sdk import AgentOptions, AsyncClient, CursorAgentError, LocalAgentOptions

from predictor.gameweek.board import build_gameweek_board
from predictor.gameweek.types import GameweekBoard
from predictor.live_fixtures import fetch_live_board
from predictor.odds.board import PricedBoard, build_board, window_for_scope
from predictor.web.bus import bus
from predictor.web.prompt import build_prompt
from predictor.web.schema import (
    CreateRunRequest,
    RunResult,
    RunStatus,
    Scope,
    SuggestedTicket,
    now_iso,
)
from predictor.web.settings import settings
from predictor.web.sse import message_to_event
from predictor.web.store import (
    append_log,
    init_run,
    make_run_id,
    read_meta,
    read_result,
    write_meta,
    write_result,
)
from predictor.web.tools import SubmitPicksContext, make_submit_picks_tool

logger = logging.getLogger(__name__)


def gameweek_should_start_agent(board: GameweekBoard) -> bool:
    """True when remaining fixtures or skipped unfinished rows exist."""
    return bool(board.fixtures) or bool(board.skipped)


def gameweek_empty_reason(board: GameweekBoard) -> str | None:
    """None starts the agent. Zero sources vs a finished round are distinct."""
    if gameweek_should_start_agent(board):
        return None
    if board.sources_up == 0:
        return "No calendar sources"
    return "No remaining fixtures"


def gameweek_leagues_by_match(board: GameweekBoard) -> dict[str, str]:
    return {f.match: f.round_label for f in board.fixtures if f.round_label}


def apply_target_odds_ticket(
    run_id: str,
    request: CreateRunRequest,
    *,
    fill: bool = False,
    board: PricedBoard | None = None,
) -> RunResult | None:
    """Solve a target-odds acca onto a stored result. Skips gameweek. No agent."""
    if request.scope == Scope.gameweek:
        return None
    if not request.target_odds:
        return None
    result = read_result(run_id)
    if result is None:
        return None
    from predictor.web.odds_solver import solve_target_ticket

    ticket = solve_target_ticket(
        result.picks,
        float(request.target_odds),
        fill=fill,
        min_odds=request.min_odds,
        max_odds=request.max_odds,
        board=board,
    )
    if ticket.extra_picks:
        result.picks = list(result.picks) + list(ticket.extra_picks)
    result.suggested_tickets = [
        SuggestedTicket(
            type="acca",
            legs=ticket.leg_indices,
            combined_odds=ticket.combined_odds,
            joint_probability=ticket.joint_probability,
            label=ticket.label
            or (
                f"Target {request.target_odds:g}× (board fill)"
                if ticket.used_fill
                else f"Target {request.target_odds:g}× (researched)"
            ),
            in_band=ticket.in_band,
            used_fill=ticket.used_fill,
        )
    ]
    write_result(run_id, result)
    return result


class RunManager:
    def __init__(self) -> None:
        self._client: AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._active: dict[str, dict[str, Any]] = {}
        self._boards: dict[str, PricedBoard | None] = {}

    async def set_client(self, client: AsyncClient) -> None:
        self._client = client

    def get_agent(self, run_id: str) -> Any | None:
        entry = self._active.get(run_id)
        return entry.get("agent") if entry else None

    async def start_run(self, request: CreateRunRequest) -> str:
        if not settings.cursor_api_key:
            raise ValueError("CURSOR_API_KEY is not set. Add it to .env - see README.")
        if not self._client:
            raise RuntimeError("SDK client not initialized")

        async with self._lock:
            run_id = make_run_id(request.scope.value)
            init_run(run_id, request)
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.running
                write_meta(run_id, meta)

            asyncio.create_task(self._execute(run_id, request))
            return run_id

    def _build_odds_board(self, request: CreateRunRequest) -> PricedBoard | None:
        """Fetch real prices once per run. Never blocks the run on failure."""
        try:
            start, end = window_for_scope(
                request.scope.value,
                hours_window=request.hours_window,
                target_date=request.target_date,
            )
            # The UI market chips are display labels ("Over/Under", "Corners"),
            # not family ids, so they steer the agent through the prompt rather
            # than filtering the board. Filtering here would silently hide
            # priced markets whenever a chip label has no matching family.
            return build_board(
                start_utc=start,
                end_utc=end,
                min_odds=request.min_odds,
                max_odds=request.max_odds,
            )
        except Exception as e:  # board is best-effort
            logger.warning("odds board unavailable: %s", e)
            return None

    async def _execute(self, run_id: str, request: CreateRunRequest) -> None:
        assert self._client is not None
        ctx = SubmitPicksContext(
            run_id=run_id,
            scope=request.scope,
            request=request.model_dump(),
        )
        if request.scope == Scope.gameweek:
            odds_board = None
            live_board = None
            gw = await asyncio.to_thread(build_gameweek_board)
            reason = gameweek_empty_reason(gw)
            if reason:
                append_log(run_id, reason)
                meta = read_meta(run_id)
                if meta:
                    meta.status = RunStatus.error
                    meta.error = reason
                    meta.completed_at = now_iso()
                    write_meta(run_id, meta)
                await bus.publish(run_id, {"type": "error", "message": reason})
                await bus.close(run_id)
                return
            prompt = build_prompt(
                request, run_id, live_board=live_board, odds_board=odds_board, gameweek_board=gw
            )
            ctx.board = None
            ctx.leagues_by_match = gameweek_leagues_by_match(gw)
            self._boards[run_id] = None
        else:
            odds_board = await asyncio.to_thread(self._build_odds_board, request)
            ctx.board = odds_board
            live_board = (
                await asyncio.to_thread(fetch_live_board) if request.scope.value == "live" else None
            )
            prompt = build_prompt(request, run_id, live_board=live_board, odds_board=odds_board)
            if odds_board:
                append_log(
                    run_id,
                    f"odds board: {len(odds_board.fixtures)} fixtures priced"
                    + (f", {len(odds_board.errors)} errors" if odds_board.errors else ""),
                )
            self._boards[run_id] = odds_board

        tool = make_submit_picks_tool(ctx)

        try:
            async with await self._client.agents.create(
                AgentOptions(
                    model=request.model or settings.default_model,
                    api_key=settings.cursor_api_key,
                    local=LocalAgentOptions(
                        cwd=str(settings.repo_root),
                        setting_sources=["project"],
                        custom_tools={"submit_picks": tool},
                    ),
                    disallowed_tools=["shell", "edit"],
                ),
            ) as agent:
                self._active[run_id] = {"agent": agent, "run_handle": None}
                append_log(run_id, f"agent created: {agent.agent_id}")

                run_handle = await agent.send(prompt)
                self._active[run_id]["run_handle"] = run_handle
                append_log(run_id, f"run started: {run_handle.id}")

                meta = read_meta(run_id)
                if meta:
                    meta.agent_id = agent.agent_id
                    meta.sdk_run_id = run_handle.id
                    write_meta(run_id, meta)

                await bus.publish(run_id, {"type": "started", "agent_id": agent.agent_id})

                async for msg in run_handle.messages():
                    event = message_to_event(msg)
                    if event:
                        await bus.publish(run_id, event)

                result = await run_handle.wait()
                append_log(run_id, f"run finished: status={result.status}")

                if ctx.accepted:
                    apply_target_odds_ticket(
                        run_id,
                        request,
                        fill=False,
                        board=self._boards.get(run_id),
                    )

                meta = read_meta(run_id)
                if meta and meta.status != RunStatus.completed:
                    if result.status == "error":
                        meta.status = RunStatus.error
                        meta.error = "Agent run ended with error status"
                    elif ctx.accepted:
                        meta.status = RunStatus.completed
                    else:
                        meta.status = RunStatus.error
                        meta.error = "Agent finished without calling submit_picks"
                    meta.completed_at = now_iso()
                    if ctx.export_paths:
                        meta.export_paths = ctx.export_paths
                    write_meta(run_id, meta)

                await bus.publish(
                    run_id,
                    {
                        "type": "done",
                        "status": meta.status.value if meta else "error",
                        "accepted": ctx.accepted,
                    },
                )
        except CursorAgentError as e:
            logger.exception("SDK startup/run error for %s", run_id)
            append_log(run_id, f"CursorAgentError: {e.message}")
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.error
                meta.error = e.message
                meta.completed_at = now_iso()
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "error", "message": e.message})
        except asyncio.CancelledError:
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.cancelled
                meta.completed_at = now_iso()
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "cancelled"})
            raise
        except Exception as e:
            logger.exception("Run failed for %s", run_id)
            append_log(run_id, f"error: {e}")
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.error
                meta.error = str(e)
                meta.completed_at = now_iso()
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "error", "message": str(e)})
        finally:
            self._active.pop(run_id, None)
            self._boards.pop(run_id, None)
            await bus.close(run_id)

    async def cancel_run(self, run_id: str) -> bool:
        entry = self._active.get(run_id)
        if not entry:
            return False
        run_handle = entry.get("run_handle")
        if run_handle and run_handle.supports("cancel"):
            await run_handle.cancel()
            return True
        return False

    async def refine_run(self, run_id: str, message: str) -> None:
        if not self._client:
            raise RuntimeError("SDK client not initialized")
        if not settings.cursor_api_key:
            raise ValueError("CURSOR_API_KEY is not set")

        meta = read_meta(run_id)
        if not meta:
            raise ValueError("Run not found")

        from predictor.web.store import _run_dir

        req_path = _run_dir(run_id) / "request.json"
        req_data: dict[str, Any] = {}
        if req_path.exists():
            req_data = json.loads(req_path.read_text(encoding="utf-8"))

        ctx = SubmitPicksContext(
            run_id=run_id,
            scope=meta.scope,
            request=req_data,
        )
        ctx.board = self._boards.get(run_id)
        if ctx.board is None:
            try:
                ctx.board = await asyncio.to_thread(
                    self._build_odds_board, CreateRunRequest.model_validate(req_data)
                )
            except Exception:
                ctx.board = None
        tool = make_submit_picks_tool(ctx)
        prompt = (
            f"{message}\n\nUpdate picks and call **submit_picks** again with the revised payload."
        )

        meta.status = RunStatus.running
        write_meta(run_id, meta)

        try:
            if meta.agent_id:
                agent = await self._client.agents.resume(
                    meta.agent_id,
                    AgentOptions(
                        api_key=settings.cursor_api_key,
                        local=LocalAgentOptions(
                            cwd=str(settings.repo_root),
                            setting_sources=["project"],
                            custom_tools={"submit_picks": tool},
                        ),
                        disallowed_tools=["shell", "edit"],
                    ),
                )
            else:
                raise ValueError("No agent_id to resume — start a new run instead")

            run_handle = await agent.send(prompt)
            self._active[run_id] = {"agent": agent, "run_handle": run_handle}

            async for msg in run_handle.messages():
                event = message_to_event(msg)
                if event:
                    await bus.publish(run_id, event)

            result = await run_handle.wait()
            append_log(run_id, f"refine finished: status={result.status}")

            if ctx.accepted:
                meta = read_meta(run_id)
                if meta:
                    meta.status = RunStatus.completed
                    meta.completed_at = now_iso()
                    meta.pick_count = len(read_result(run_id).picks) if read_result(run_id) else 0
                    meta.export_paths = ctx.export_paths
                    write_meta(run_id, meta)
                if req_data:
                    apply_target_odds_ticket(
                        run_id,
                        CreateRunRequest.model_validate(req_data),
                        fill=False,
                        board=ctx.board,
                    )

            await bus.publish(
                run_id, {"type": "done", "status": "completed", "accepted": ctx.accepted}
            )
        except Exception as e:
            append_log(run_id, f"refine error: {e}")
            meta = read_meta(run_id)
            if meta:
                meta.status = RunStatus.error
                meta.error = str(e)
                write_meta(run_id, meta)
            await bus.publish(run_id, {"type": "error", "message": str(e)})
        finally:
            self._active.pop(run_id, None)
            await bus.close(run_id)


run_manager = RunManager()
