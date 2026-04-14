"""Periodic task scheduler for background workflows.

Runs recurring tasks (fast loop, slow loop, bias audit, viability checkpoints,
absence monitoring) at configured intervals using asyncio.

All scheduling is deterministic (Tier D). Individual tasks may invoke
LLM-backed workflows internally.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

import structlog

from workflows.types import ScheduledTaskState

_log = structlog.get_logger(component="workflow_scheduler")

# Task function signature: async () -> None
TaskFunc = Callable[[], Awaitable[None]]


class PeriodicTask:
    """A single recurring task with error isolation."""

    def __init__(
        self,
        name: str,
        func: TaskFunc,
        interval_hours: float,
        *,
        initial_delay_seconds: float = 10.0,
    ) -> None:
        self.name = name
        self._func = func
        self._interval_hours = interval_hours
        self._initial_delay = initial_delay_seconds
        self._task: asyncio.Task | None = None
        self.state = ScheduledTaskState(
            task_name=name,
            interval_hours=interval_hours,
        )

    async def start(self) -> None:
        """Start the periodic execution loop."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name=f"periodic_{self.name}")
        _log.info(
            "periodic_task_started",
            task=self.name,
            interval_hours=self._interval_hours,
        )

    async def stop(self) -> None:
        """Cancel the periodic task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        _log.info("periodic_task_stopped", task=self.name, run_count=self.state.run_count)

    async def _loop(self) -> None:
        """Main loop: initial delay, then run at interval."""
        try:
            await asyncio.sleep(self._initial_delay)
        except asyncio.CancelledError:
            return

        interval_seconds = self._interval_hours * 3600

        while True:
            self.state.is_running = True
            started = datetime.now(tz=UTC)

            try:
                await self._func()
                self.state.last_run_at = started
                self.state.run_count += 1
                self.state.last_error = None
                self.state.next_run_at = started + timedelta(seconds=interval_seconds)

                _log.info(
                    "periodic_task_completed",
                    task=self.name,
                    run_count=self.state.run_count,
                    next_run=self.state.next_run_at.isoformat(),
                )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.state.last_error = str(exc)
                _log.error(
                    "periodic_task_error",
                    task=self.name,
                    error=str(exc),
                    run_count=self.state.run_count,
                )
            finally:
                self.state.is_running = False

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break


class WorkflowScheduler:
    """Manages all periodic background tasks.

    Usage:
        scheduler = WorkflowScheduler()
        scheduler.register("fast_loop", fast_loop_func, interval_hours=24)
        scheduler.register("slow_loop", slow_loop_func, interval_hours=168)
        await scheduler.start_all()
        # ...
        await scheduler.stop_all()
    """

    def __init__(self) -> None:
        self._tasks: dict[str, PeriodicTask] = {}

    def register(
        self,
        name: str,
        func: TaskFunc,
        interval_hours: float,
        *,
        initial_delay_seconds: float = 10.0,
    ) -> None:
        """Register a periodic task."""
        task = PeriodicTask(
            name=name,
            func=func,
            interval_hours=interval_hours,
            initial_delay_seconds=initial_delay_seconds,
        )
        self._tasks[name] = task
        _log.info(
            "task_registered",
            task=name,
            interval_hours=interval_hours,
        )

    async def start_all(self) -> None:
        """Start all registered periodic tasks."""
        for task in self._tasks.values():
            await task.start()
        _log.info("scheduler_started", task_count=len(self._tasks))

    async def stop_all(self) -> None:
        """Stop all running periodic tasks."""
        for task in self._tasks.values():
            await task.stop()
        _log.info("scheduler_stopped")

    def get_task_states(self) -> list[ScheduledTaskState]:
        """Get states of all registered tasks."""
        return [t.state for t in self._tasks.values()]

    @property
    def task_count(self) -> int:
        return len(self._tasks)
