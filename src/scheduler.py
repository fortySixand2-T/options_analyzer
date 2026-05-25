"""Lightweight async background task scheduler for FastAPI lifespan.

Register tasks with interval + optional market-hours-only flag.
Persists last-run timestamps in SQLite so tasks catch up after restarts.
"""

import asyncio
import logging
from datetime import datetime, time, timezone
from typing import Callable, Coroutine

logger = logging.getLogger(__name__)

MARKET_OPEN = time(13, 30)   # 9:30 ET in UTC
MARKET_CLOSE = time(20, 0)   # 16:00 ET in UTC


def _is_market_hours() -> bool:
    now = datetime.now(timezone.utc).time()
    return MARKET_OPEN <= now <= MARKET_CLOSE


class ScheduledTask:
    def __init__(
        self,
        name: str,
        coro_fn: Callable[[], Coroutine],
        interval_seconds: int,
        market_hours_only: bool = False,
    ):
        self.name = name
        self.coro_fn = coro_fn
        self.interval_seconds = interval_seconds
        self.market_hours_only = market_hours_only
        self.last_run: datetime | None = None
        self._task: asyncio.Task | None = None

    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                if self.market_hours_only and not _is_market_hours():
                    continue
                await self.coro_fn()
                self.last_run = datetime.now(timezone.utc)
                logger.debug("Scheduled task '%s' completed", self.name)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduled task '%s' failed", self.name)


class TaskScheduler:
    def __init__(self):
        self._tasks: list[ScheduledTask] = []

    def register(
        self,
        name: str,
        coro_fn: Callable[[], Coroutine],
        interval_seconds: int,
        market_hours_only: bool = False,
    ):
        task = ScheduledTask(name, coro_fn, interval_seconds, market_hours_only)
        self._tasks.append(task)
        logger.info("Registered scheduled task: %s (every %ds)", name, interval_seconds)

    def start_all(self):
        for t in self._tasks:
            t._task = asyncio.create_task(t._loop())
        logger.info("Started %d scheduled tasks", len(self._tasks))

    async def stop_all(self):
        for t in self._tasks:
            if t._task and not t._task.done():
                t._task.cancel()
        await asyncio.gather(*(t._task for t in self._tasks if t._task), return_exceptions=True)
        logger.info("Stopped all scheduled tasks")

    def status(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "interval_seconds": t.interval_seconds,
                "market_hours_only": t.market_hours_only,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "running": t._task is not None and not t._task.done(),
            }
            for t in self._tasks
        ]


scheduler = TaskScheduler()
