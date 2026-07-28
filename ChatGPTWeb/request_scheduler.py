"""Priority admission control shared by every ChatGPTWeb transport."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from dataclasses import dataclass, field
from typing import Callable


@dataclass(order=True)
class _WaitingRequest:
    priority: int
    sequence: int
    future: asyncio.Future["RequestLease"] = field(compare=False)
    client_id: str = field(compare=False)


class RequestLease:
    """One admitted request; releasing it lets the next request proceed."""

    def __init__(self, scheduler: "RequestScheduler", client_id: str):
        self._scheduler = scheduler
        self.client_id = client_id
        self._released = False

    async def release(self) -> None:
        if not self._released:
            self._released = True
            await self._scheduler.release()


class RequestScheduler:
    """A small priority queue with a capacity supplied by the owning runtime."""

    def __init__(self, capacity_provider: Callable[[], int]):
        self._capacity_provider = capacity_provider
        self._lock = asyncio.Lock()
        self._waiting: list[_WaitingRequest] = []
        self._sequence = itertools.count()
        self._active = 0

    def _capacity(self) -> int:
        try:
            return max(1, int(self._capacity_provider()))
        except Exception:
            return 1

    def _drain_locked(self) -> None:
        while self._active < self._capacity() and self._waiting:
            waiting = heapq.heappop(self._waiting)
            if waiting.future.cancelled() or waiting.future.done():
                continue
            self._active += 1
            waiting.future.set_result(RequestLease(self, waiting.client_id))

    async def acquire(
        self,
        *,
        priority: int,
        client_id: str,
        timeout_seconds: float,
    ) -> RequestLease:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RequestLease] = loop.create_future()
        async with self._lock:
            heapq.heappush(self._waiting, _WaitingRequest(
                priority=max(0, int(priority)),
                sequence=next(self._sequence),
                future=future,
                client_id=client_id,
            ))
            self._drain_locked()
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=max(0.1, timeout_seconds))
        except BaseException:
            # A release can grant this request at the same instant the caller
            # times out. Return that slot immediately instead of leaking it.
            granted = future.result() if future.done() and not future.cancelled() else None
            if granted is None:
                future.cancel()
            async with self._lock:
                self._drain_locked()
            if granted is not None:
                await granted.release()
            raise

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)
            self._drain_locked()

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return {
                "capacity": self._capacity(),
                "active": self._active,
                "queued": sum(1 for item in self._waiting if not item.future.done()),
            }
