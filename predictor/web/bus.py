"""In-memory pub/sub for SSE run events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=500)
        self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        subs = self._queues.get(run_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            self._queues.pop(run_id, None)

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for q in list(self._queues.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def close(self, run_id: str) -> None:
        for q in list(self._queues.get(run_id, [])):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._queues.pop(run_id, None)


bus = EventBus()
