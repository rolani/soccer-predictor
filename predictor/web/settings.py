"""App configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / ".runs"
PREDICTIONS_DIR = REPO_ROOT / ".predictions"
ANALYSIS_DIR = REPO_ROOT / ".analysis"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Settings:
    cursor_api_key: str
    host: str = "127.0.0.1"
    port: int = 8765
    default_model: str = "composer-2.5"
    repo_root: Path = REPO_ROOT

    @classmethod
    def load(cls) -> Settings:
        key = os.environ.get("CURSOR_API_KEY", "").strip()
        on_render = os.environ.get("RENDER", "").lower() in {"1", "true", "yes"}
        port_raw = os.environ.get("PREDICTOR_PORT") or os.environ.get("PORT") or "8765"
        default_host = "0.0.0.0" if on_render or os.environ.get("PORT") else "127.0.0.1"
        host = os.environ.get("PREDICTOR_HOST") or default_host
        model = os.environ.get("PREDICTOR_MODEL", "composer-2.5")
        return cls(cursor_api_key=key, host=host, port=int(port_raw), default_model=model)


settings = Settings.load()
