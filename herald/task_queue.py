"""
task_queue.py — Serial asyncio task queue for agent runs.

One agent runs at a time across all projects. This prevents:
  - Token rate limit collisions (Anthropic has per-minute limits)
  - Confusing concurrent writes to the same repo
  - Unpredictable token costs

If tasks pile up, they run back-to-back in arrival order.
The queue is unbounded — we trust the scheduling layer not to flood it.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """A unit of work to be executed by the queue worker."""

    # Which project to run in (must match a key in ProjectConfig dict)
    project_name: str

    # The task prompt for agent runs, or a description for non-agent tasks
    # (e.g. "[deploy] enchiridion")
    task: str

    # Called with the output string when the run completes (or errors).
    # Typically posts the result to a Discord channel.
    on_complete: Callable[[str], Awaitable[None]]

    # Optional display label for `!status` — defaults to first 60 chars of task
    label: str = field(default="")

    # If set, called instead of the queue's default run_fn (the Claude Code agent).
    # Signature: async (project_path: str, task: str) -> str
    # Use this for non-agent tasks (e.g. docker deploys) that still need queue
    # serialization but shouldn't invoke the Claude Code CLI.
    run_fn: Callable[[str, str], Awaitable[str]] | None = None

    # If False, this task does not update the project's activity timestamp.
    # Set to False for non-agent tasks so they don't reset the inactivity clock.
    record_activity: bool = True

    # Wall-clock seconds the run took. Set by the worker after completion.
    # Available in on_complete callbacks (evaluated after the worker sets it).
    duration_seconds: float | None = None

    # Total API tokens consumed (input + output). Set by the worker from the
    # run_agent return value. None for non-agent tasks (deploys, custom run_fns).
    tokens_used: int | None = None

    # Optional Claude model override for this task. Passed as --model to the CLI.
    # None = use the CLI's default model.
    model: str | None = None

    # Optional cap on agentic iterations. Passed as --max-turns to the CLI.
    # None = use the CLI default (no explicit cap).
    max_turns: int | None = None

    def __post_init__(self):
        if not self.label:
            self.label = self.task[:60] + ("…" if len(self.task) > 60 else "")


class TaskQueue:
    """
    Serial FIFO queue: dequeues one AgentTask at a time, runs it, then dequeues the next.

    The `worker()` coroutine is the long-running consumer. Start it as a background task
    on bot startup and it runs for the lifetime of the process.
    """

    def __init__(self):
        self._queue: asyncio.Queue[AgentTask] = asyncio.Queue()
        # The task currently executing (None when idle)
        self._current: AgentTask | None = None

    def enqueue(self, task: AgentTask) -> None:
        """Add a task to the back of the queue. Non-blocking."""
        self._queue.put_nowait(task)
        log.info("Task enqueued: [%s] %s (queue depth: %d)", task.project_name, task.label, self.depth)

    def cancel(self, project_name: str) -> bool:
        """
        Remove the first pending task for project_name from the queue.

        Does NOT cancel the currently-running task — only tasks waiting in the queue.
        Returns True if a task was found and removed, False if none was waiting.

        Implementation: asyncio.Queue doesn't support selective removal, so we drain
        the queue, skip the first match, and re-enqueue the rest. This is safe because
        enqueue() and cancel() both run on the event loop thread — no concurrent access.
        """
        items: list[AgentTask] = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        cancelled = False
        for item in items:
            if not cancelled and item.project_name == project_name:
                # Skip this task — it's the one being cancelled
                cancelled = True
                log.info("Task cancelled: [%s] %s", item.project_name, item.label)
            else:
                self._queue.put_nowait(item)

        return cancelled

    @property
    def depth(self) -> int:
        """Number of tasks waiting (not counting the currently running one)."""
        return self._queue.qsize()

    @property
    def current(self) -> AgentTask | None:
        """The task currently being executed, or None if idle."""
        return self._current

    @property
    def pending(self) -> list[AgentTask]:
        """
        Snapshot of queued tasks in arrival order (not including the running one).

        Safe to call at any point — returns a list copy so callers can't mutate
        the internal queue. Implemented the same way as cancel(): drain then re-enqueue.
        """
        items: list[AgentTask] = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        for item in items:
            self._queue.put_nowait(item)
        return list(items)

    async def worker(self, projects: Any, run_fn: Any) -> None:
        """
        Long-running queue consumer. Call as an asyncio background task.

        Args:
            projects: dict[str, ProjectConfig] — looks up project.path by name
            run_fn: async function(project_path, task_prompt, *, model, max_turns)
                    -> tuple[str, int]   (output text, total tokens)
                    Typically agent_runner.run_agent.
        """
        log.info("Task queue worker started.")
        while True:
            task = await self._queue.get()
            self._current = task

            log.info("Running task: [%s] %s", task.project_name, task.label)
            try:
                project = projects.get(task.project_name)
                if project is None:
                    output = f"[ERROR] Unknown project '{task.project_name}'. Is it configured?"
                else:
                    _start = time.monotonic()
                    if task.run_fn is not None:
                        # Custom run function (deploys, non-agent tasks) — returns str
                        output = await task.run_fn(project.path, task.task)
                        task.tokens_used = None
                    else:
                        # Default agent runner — returns tuple[str, int] (text, tokens).
                        # Pass task-specific model/max_turns overrides from the task.
                        result = await run_fn(
                            project.path,
                            task.task,
                            model=task.model,
                            max_turns=task.max_turns,
                        )
                        if isinstance(result, tuple):
                            output, tokens = result
                        else:
                            output, tokens = result, 0
                        task.tokens_used = tokens
                    task.duration_seconds = time.monotonic() - _start
                    if task.record_activity:
                        from .activity import record_activity
                        record_activity(task.project_name)

                await task.on_complete(output)

            except Exception as exc:
                # on_complete itself raised — log it but don't crash the worker
                log.exception("Exception in task completion callback: %s", exc)

            finally:
                self._current = None
                self._queue.task_done()
                log.info("Task complete: [%s] %s", task.project_name, task.label)
