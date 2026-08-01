"""Live event bus for the console, plus audit and alert helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Alert, AuditEvent

log = logging.getLogger("sentinel.events")


class EventBus:
    def __init__(self, history: int = 80) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = asyncio.Lock()

    async def publish(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        event = {
            "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(),
            "data": payload or {},
        }
        self._history.append(event)
        async with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def publish_soon(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.publish(kind, payload))

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=400)
        async with self._lock:
            self._subscribers.add(queue)
        for event in list(self._history)[-20:]:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def recent(self, limit: int = 40) -> list[dict[str, Any]]:
        return list(self._history)[-limit:][::-1]


bus = EventBus()

EVENT_KINDS = (
    "hello",
    "request.completed",
    "request.failed",
    "cache.hit",
    "route.decision",
    "circuit.changed",
    "loadtest.stage",
    "loadtest.finished",
    "budget.warning",
    "alert",
    "audit",
    "catalog.changed",
    "policy.changed",
)


def sse(event: dict[str, Any]) -> str:
    return f"event: {event['kind']}\ndata: {json.dumps(event, default=str)}\n\n"


async def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    target: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(AuditEvent(actor=actor, action=action, target=target, meta=meta or {}))
    await bus.publish("audit", {"actor": actor, "action": action, "target": target})


async def raise_alert(
    session: AsyncSession,
    *,
    level: str,
    title: str,
    message: str = "",
    source: str = "gateway",
    meta: dict[str, Any] | None = None,
) -> Alert:
    alert = Alert(level=level, title=title, message=message, source=source, meta=meta or {})
    session.add(alert)
    await bus.publish("alert", {"level": level, "title": title, "message": message})
    return alert
