"""submit_picks custom tool for Cursor SDK agents."""

from __future__ import annotations

import json
from typing import Any

from cursor_sdk import CustomTool, CustomToolContext
from pydantic import ValidationError

from predictor.exports import write_exports_from_picks, write_twitter_exports
from predictor.odds.board import PricedBoard
from predictor.web.match_utils import dedupe_picks_by_match
from predictor.web.schema import (
    Pick,
    RunResult,
    RunStatus,
    Scope,
    now_iso,
    submit_picks_json_schema,
)
from predictor.web.store import append_log, read_meta, write_meta, write_result
from predictor.web.verify import verify_prices


class SubmitPicksContext:
    """Mutable state shared with the custom tool callback."""

    def __init__(
        self,
        run_id: str,
        scope: Scope,
        request: dict[str, Any],
        *,
        board: PricedBoard | None = None,
        leagues_by_match: dict[str, str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.scope = scope
        self.request = request
        self.board = board
        self.leagues_by_match = leagues_by_match
        self.accepted = False
        self.export_paths: dict[str, str] = {}


def make_submit_picks_tool(ctx: SubmitPicksContext) -> CustomTool:
    schema = submit_picks_json_schema()

    def execute(args: dict[str, Any], _tool_ctx: CustomToolContext) -> str:
        try:
            payload = dict(args)
            payload.setdefault("run_id", ctx.run_id)
            payload.setdefault("scope", ctx.scope.value)
            payload.setdefault("generated_at", now_iso())
            payload["request"] = ctx.request

            result = RunResult.model_validate(payload)
            is_gameweek = ctx.scope == Scope.gameweek

            if not is_gameweek:
                result.picks, price_notes = verify_prices(result.picks, ctx.board)
                for note in price_notes:
                    append_log(ctx.run_id, f"price check: {note}")

            # Enforce request filters post-validation (skipped for gameweek full-slate CS).
            min_conf = ctx.request.get("min_confidence", 0)
            min_odds = ctx.request.get("min_odds", 1.01)
            max_odds = ctx.request.get("max_odds", 50.0)
            margin = ctx.request.get("margin_buffer", 0.08)

            filtered: list[Pick] = []
            rejected: list[str] = []
            if is_gameweek:
                filtered = list(result.picks)
            else:
                for i, p in enumerate(result.picks):
                    if p.confidence < min_conf:
                        rejected.append(
                            f"pick {i + 1} {p.match}: confidence {p.confidence} < {min_conf}"
                        )
                        continue
                    # No board price — publish on the confidence gate alone, any scope.
                    # The research is still the product; the user sources the price.
                    if not p.price_available or p.odds is None:
                        filtered.append(p)
                        continue
                    if not (min_odds <= p.odds <= max_odds):
                        rejected.append(
                            f"pick {i + 1} {p.match}: odds {p.odds} outside {min_odds}-{max_odds}"
                        )
                        continue
                    implied = 1.0 / p.odds
                    if p.estimated_probability < implied + margin:
                        rejected.append(
                            f"pick {i + 1} {p.match}: est_prob {p.estimated_probability:.2f} "
                            f"< implied+margin {implied + margin:.2f}"
                        )
                        continue
                    filtered.append(p)

            if rejected and not filtered:
                return (
                    "Validation failed: no picks passed confidence/odds/margin gates. "
                    + "; ".join(rejected[:5])
                )

            max_picks = ctx.request.get("max_picks")
            if max_picks and not ctx.request.get("all_that_qualify", True) and not is_gameweek:
                filtered = sorted(filtered, key=lambda x: x.confidence, reverse=True)[:max_picks]

            filtered, dup_notes = dedupe_picks_by_match(filtered)
            rejected.extend(dup_notes)

            result.picks = filtered
            write_result(ctx.run_id, result)

            if is_gameweek:
                export_paths = write_twitter_exports(
                    result.picks,
                    run_id=ctx.run_id,
                    leagues_by_match=ctx.leagues_by_match,
                )
            else:
                export_paths = write_exports_from_picks(
                    result.picks,
                    run_id=ctx.run_id,
                    scope=ctx.scope.value,
                )
            ctx.export_paths = {k: str(v) for k, v in export_paths.items()}
            ctx.accepted = True

            meta = read_meta(ctx.run_id)
            if meta:
                meta.status = RunStatus.completed
                meta.completed_at = now_iso()
                meta.pick_count = len(result.picks)
                meta.export_paths = ctx.export_paths
                write_meta(ctx.run_id, meta)

            msg = f"accepted: {len(result.picks)} picks"
            if rejected:
                msg += f" ({len(rejected)} rejected by gates)"
            append_log(ctx.run_id, f"submit_picks: {msg}")
            return msg
        except ValidationError as e:
            err = json.dumps(e.errors(), indent=2)
            append_log(ctx.run_id, f"submit_picks validation error: {err}")
            return f"Validation error - fix and call submit_picks again:\n{err}"
        except Exception as e:
            append_log(ctx.run_id, f"submit_picks error: {e}")
            return f"Error: {e}"

    return CustomTool(
        description=(
            "Submit final researched picks. Call exactly once when research is complete. "
            "Exactly ONE pick per match — choose the single best market for that game. "
            "Every pick needs confidence, estimated_probability, reasoning, and evidence. "
            "If the board has no price, set price_available=false and omit odds — "
            "research picks still publish for display."
        ),
        input_schema=schema,
        execute=execute,
    )
