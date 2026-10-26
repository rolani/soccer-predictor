"""Pydantic models for prediction runs — shared by API, custom tool, and exports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Scope(str, Enum):
    live = "live"
    today = "today"
    tomorrow = "tomorrow"
    window = "window"
    date = "date"
    gameweek = "gameweek"


class TicketMode(str, Enum):
    singles = "singles"
    acca = "acca"
    hybrid = "hybrid"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    error = "error"
    cancelled = "cancelled"


class SourceRef(BaseModel):
    label: str
    url: str = ""


class Pick(BaseModel):
    league: str = ""
    match: str
    kickoff_et: str = ""
    status: str = "pre"  # pre | live
    minute: str | None = None
    score: str | None = None
    market: str = ""
    tip: str
    odds: float | None = Field(default=None, gt=1.0)
    quoted_odds: float | None = None
    price_source: str = "unpriced"  # pinnacle | unpriced
    market_family: str = ""
    price_available: bool = True
    book: str = "SportyBet ng (modelled)"
    confidence: int = Field(ge=0, le=100)
    estimated_probability: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def evidence_not_empty(cls, v: list[str]) -> list[str]:
        cleaned = [e.strip() for e in v if e and e.strip()]
        if not cleaned:
            raise ValueError("evidence must contain at least one item")
        return cleaned

    @model_validator(mode="after")
    def odds_when_price_available(self) -> Pick:
        if self.price_available and self.odds is None:
            raise ValueError("odds required when price_available is true")
        return self


class SkippedMatch(BaseModel):
    match: str
    why: str


class SuggestedTicket(BaseModel):
    type: str = "acca"  # acca | singles
    legs: list[int] = Field(default_factory=list)
    combined_odds: float | None = None
    joint_probability: float | None = None
    label: str = ""
    in_band: bool | None = None
    used_fill: bool = False


class RunResult(BaseModel):
    run_id: str
    scope: Scope
    generated_at: str
    summary: str = ""
    picks: list[Pick] = Field(default_factory=list)
    skipped: list[SkippedMatch] = Field(default_factory=list)
    suggested_tickets: list[SuggestedTicket] = Field(default_factory=list)
    request: dict[str, Any] | None = None


class CreateRunRequest(BaseModel):
    scope: Scope = Scope.today
    hours_window: int | None = Field(default=None, ge=1, le=72)
    target_date: str | None = None  # YYYY-MM-DD when scope=date
    markets: list[str] = Field(default_factory=lambda: ["all"])
    min_odds: float = Field(default=1.10, ge=1.01)
    max_odds: float = Field(default=5.0, le=50.0)
    min_confidence: int = Field(default=75, ge=0, le=100)
    margin_buffer: float = Field(default=0.08, ge=0.0, le=0.5)
    max_picks: int | None = Field(default=None, ge=1, le=50)
    all_that_qualify: bool = True
    ticket_mode: TicketMode = TicketMode.hybrid
    acca_legs: int | None = Field(default=4, ge=2, le=15)
    target_combined_odds_min: float | None = Field(default=4.0, ge=1.0)
    target_combined_odds_max: float | None = Field(default=12.0, le=500.0)
    league_include: str = ""
    league_exclude: str = ""
    model: str = "composer-2.5"
    book_overround: dict[str, float] | None = None
    target_odds: float | None = Field(default=None, gt=1.0)


class RefineRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class TargetTicketRequest(BaseModel):
    fill: bool = False


class RunMeta(BaseModel):
    id: str
    status: RunStatus
    scope: Scope
    created_at: str
    completed_at: str | None = None
    agent_id: str | None = None
    sdk_run_id: str | None = None
    error: str | None = None
    pick_count: int = 0
    export_paths: dict[str, str] = Field(default_factory=dict)


def submit_picks_json_schema() -> dict[str, Any]:
    """JSON Schema for the submit_picks custom tool input."""
    schema = RunResult.model_json_schema()
    # Agent fills run_id/scope/generated_at — keep them optional in tool schema
    props = schema.get("properties", {})
    for key in ("run_id", "scope", "generated_at"):
        if key in props:
            props[key].pop("default", None)
    schema["required"] = ["summary", "picks"]
    schema["additionalProperties"] = False
    return schema


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
