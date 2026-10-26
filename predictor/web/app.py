"""FastAPI web app for soccer predictions."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from cursor_sdk import AsyncClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from predictor.gameweek.board import build_gameweek_board
from predictor.live_fixtures import fetch_live_board
from predictor.odds.board import build_board, window_for_scope
from predictor.web.analysis_runner import analysis_manager
from predictor.web.bus import bus
from predictor.web.runner import apply_target_odds_ticket, run_manager
from predictor.web.schema import CreateRunRequest, RefineRequest, RunMeta, TargetTicketRequest
from predictor.web.settings import STATIC_DIR, settings
from predictor.web.store import list_runs, read_master_summary, read_meta, read_result

EXPORT_KEY_ALIASES = {
    "twitter": "twitter_full",
    "twitter_full": "twitter_full",
    "twitter_thread": "twitter_thread",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = await AsyncClient.launch_bridge(workspace=str(settings.repo_root))
    await run_manager.set_client(client)
    await analysis_manager.set_client(client)
    app.state.sdk_client = client
    logger.info("Cursor SDK bridge started for %s", settings.repo_root)
    try:
        yield
    finally:
        await client.aclose()
        logger.info("Cursor SDK bridge closed")


app = FastAPI(title="Soccer Predictor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/live/fixtures")
async def live_fixtures():
    """In-play board from ESPN API; agent still verifies Sofascore/FlashScore/LiveScore."""
    board = fetch_live_board()
    return board.to_dict()


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "has_api_key": bool(settings.cursor_api_key),
        "repo": str(settings.repo_root),
    }


@app.get("/api/models")
async def list_models(request: Request):
    if not settings.cursor_api_key:
        raise HTTPException(503, "CURSOR_API_KEY not configured")
    client: AsyncClient = request.app.state.sdk_client
    try:
        models = await client.models.list()
        items = []
        for m in getattr(models, "items", models) or []:
            mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else str(m))
            items.append({"id": mid})
        if not items:
            items = [{"id": settings.default_model}, {"id": "composer-2.5"}]
        return {"models": items}
    except Exception as e:
        logger.warning("models.list failed: %s", e)
        return {"models": [{"id": settings.default_model}, {"id": "composer-2.5"}]}


@app.post("/api/runs", response_model=RunMeta)
async def create_run(req: CreateRunRequest):
    try:
        run_id = await run_manager.start_run(req)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    meta = read_meta(run_id)
    if not meta:
        raise HTTPException(500, "Run created but meta missing")
    return meta


@app.get("/api/runs")
async def get_runs(limit: int = 50):
    return {"runs": list_runs(limit)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    meta = read_meta(run_id)
    if not meta:
        raise HTTPException(404, "Run not found")
    result = read_result(run_id)
    return {"meta": meta, "result": result}


@app.delete("/api/runs/{run_id}")
async def cancel_run(run_id: str):
    meta = read_meta(run_id)
    if not meta:
        raise HTTPException(404, "Run not found")
    cancelled = await run_manager.cancel_run(run_id)
    return {"cancelled": cancelled}


@app.post("/api/runs/{run_id}/refine")
async def refine_run(run_id: str, body: RefineRequest):
    meta = read_meta(run_id)
    if not meta:
        raise HTTPException(404, "Run not found")
    try:
        asyncio.create_task(run_manager.refine_run(run_id, body.message))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "run_id": run_id}


@app.post("/api/runs/{run_id}/target-ticket")
async def target_ticket(run_id: str, body: TargetTicketRequest):
    result = read_result(run_id)
    if not result:
        raise HTTPException(404, "Run not found")

    from predictor.web.store import _run_dir

    req: CreateRunRequest | None = None
    req_path = _run_dir(run_id) / "request.json"
    if req_path.exists():
        req = CreateRunRequest.model_validate_json(req_path.read_text(encoding="utf-8"))
    elif result.request:
        req = CreateRunRequest.model_validate(result.request)
    if req is None or not req.target_odds:
        raise HTTPException(400, "No target_odds on stored request")

    board = run_manager._boards.get(run_id)
    if body.fill and board is None:
        board = run_manager._build_odds_board(req)

    apply_target_odds_ticket(run_id, req, fill=body.fill, board=board)
    updated = read_result(run_id)
    return updated


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    meta = read_meta(run_id)
    if not meta:
        raise HTTPException(404, "Run not found")

    async def event_stream():
        q = bus.subscribe(run_id)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error", "cancelled"):
                    break
        finally:
            bus.unsubscribe(run_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/gameweek/board")
async def gameweek_board():
    """Slate preview for remaining Big-5 matchdays. Never 500 on calendar failure."""
    board = await asyncio.to_thread(build_gameweek_board)
    return board.to_dict()


@app.get("/api/odds/board")
async def odds_board(
    scope: str = "today",
    hours_window: int | None = None,
    target_date: str | None = None,
    min_odds: float = 1.10,
    max_odds: float = 5.0,
):
    """Preview the real prices a run would see."""
    start, end = window_for_scope(scope, hours_window=hours_window, target_date=target_date)
    board = await asyncio.to_thread(
        build_board, start_utc=start, end_utc=end, min_odds=min_odds, max_odds=max_odds
    )
    return board.to_dict()


@app.get("/api/analysis")
async def analysis():
    return read_master_summary()


@app.get("/api/analysis/status")
async def analysis_status():
    return analysis_manager.status()


@app.post("/api/analysis/run")
async def analysis_run():
    try:
        run_id = await analysis_manager.start()
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"run_id": run_id}


@app.get("/api/exports/{run_id}/{fmt}")
async def download_export(run_id: str, fmt: str):
    meta = read_meta(run_id)
    if not meta or not meta.export_paths:
        raise HTTPException(404, "Export not found")
    key = EXPORT_KEY_ALIASES.get(fmt, fmt)
    path_str = meta.export_paths.get(key)
    if not path_str:
        raise HTTPException(404, f"Format {fmt} not found")
    path = Path(path_str)
    if not path.exists():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(path, filename=path.name)


# Static SPA (built by Vite into predictor/web/static)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "Frontend not built — run npm run build in webapp/")


def main():
    import uvicorn

    uvicorn.run(
        "predictor.web.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
