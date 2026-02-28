"""
tests/test_queue.py — Tests for the serial task queue.

The core invariant: one task runs at a time, in FIFO order.
No Discord or Claude Code required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from task_queue import AgentTask, TaskQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_project(name: str, path: str = "/tmp") -> MagicMock:
    """Minimal ProjectConfig stand-in."""
    p = MagicMock()
    p.path = path
    return p


def make_task(name: str, run_fn=None, record_activity=True, on_complete=None) -> AgentTask:
    return AgentTask(
        project_name=name,
        task=f"task for {name}",
        on_complete=on_complete or AsyncMock(),
        run_fn=run_fn,
        record_activity=record_activity,
    )


async def run_queue(queue: TaskQueue, projects: dict, run_fn) -> None:
    """Run the queue worker until all currently enqueued tasks are done."""
    worker = asyncio.create_task(queue.worker(projects, run_fn))
    await queue._queue.join()   # blocks until all task_done() calls match get() calls
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tasks_run_in_fifo_order():
    """Tasks must execute in the order they were enqueued."""
    order = []
    queue = TaskQueue()
    projects = {"a": make_project("a"), "b": make_project("b"), "c": make_project("c")}

    async def run_fn(path, task):
        order.append(task)
        return f"done: {task}"

    queue.enqueue(make_task("a", run_fn=AsyncMock(side_effect=lambda p, t: (order.append("a"), "")[1] or "done")))
    queue.enqueue(make_task("b", run_fn=AsyncMock(side_effect=lambda p, t: (order.append("b"), "")[1] or "done")))
    queue.enqueue(make_task("c", run_fn=AsyncMock(side_effect=lambda p, t: (order.append("c"), "")[1] or "done")))

    await run_queue(queue, projects, run_fn)

    assert order == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_only_one_task_runs_at_a_time():
    """While a task is running, current is set. It must be None before and after."""
    queue = TaskQueue()
    projects = {"p": make_project("p")}

    states_during = []

    async def slow_run_fn(path, task):
        # Record queue state while we're "running"
        states_during.append(queue.current)
        await asyncio.sleep(0)  # yield to event loop
        states_during.append(queue.current)
        return "done"

    assert queue.current is None

    task = make_task("p", run_fn=slow_run_fn)
    queue.enqueue(task)
    await run_queue(queue, projects, slow_run_fn)

    assert queue.current is None
    # Both snapshots during the run should be the same task (not None)
    assert all(s is not None for s in states_during)
    assert all(s.project_name == "p" for s in states_during)


@pytest.mark.asyncio
async def test_run_fn_override_is_used():
    """If AgentTask.run_fn is set, it should be called instead of the default run_fn."""
    default_run_fn = AsyncMock(return_value="from default")
    custom_run_fn = AsyncMock(return_value="from custom")

    queue = TaskQueue()
    projects = {"p": make_project("p")}

    task = make_task("p", run_fn=custom_run_fn)
    queue.enqueue(task)
    await run_queue(queue, projects, default_run_fn)

    custom_run_fn.assert_awaited_once()
    default_run_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_run_fn_used_when_no_override():
    """If AgentTask.run_fn is None, the queue's default run_fn should be called."""
    default_run_fn = AsyncMock(return_value="from default")

    queue = TaskQueue()
    projects = {"p": make_project("p")}

    task = make_task("p", run_fn=None)
    queue.enqueue(task)
    await run_queue(queue, projects, default_run_fn)

    default_run_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_activity_false_does_not_record():
    """Tasks with record_activity=False must not update the activity log."""
    queue = TaskQueue()
    projects = {"p": make_project("p")}
    run_fn = AsyncMock(return_value="done")

    task = make_task("p", run_fn=run_fn, record_activity=False)
    queue.enqueue(task)

    with patch("activity.record_activity") as mock_record:
        await run_queue(queue, projects, run_fn)
        mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_record_activity_true_does_record():
    """Tasks with record_activity=True (default) must update the activity log."""
    queue = TaskQueue()
    projects = {"p": make_project("p")}
    run_fn = AsyncMock(return_value="done")

    task = make_task("p", run_fn=run_fn, record_activity=True)
    queue.enqueue(task)

    with patch("activity.record_activity") as mock_record:
        await run_queue(queue, projects, run_fn)
        mock_record.assert_called_once_with("p")


@pytest.mark.asyncio
async def test_unknown_project_returns_error():
    """If the project name isn't in the projects dict, on_complete gets an error message."""
    queue = TaskQueue()
    projects = {}  # empty — no projects registered
    run_fn = AsyncMock(return_value="should not be called")

    on_complete = AsyncMock()
    task = AgentTask(project_name="nonexistent", task="do stuff", on_complete=on_complete)
    queue.enqueue(task)

    await run_queue(queue, projects, run_fn)

    on_complete.assert_awaited_once()
    output = on_complete.await_args[0][0]
    assert "nonexistent" in output
    assert "ERROR" in output.upper() or "Unknown" in output
    run_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_complete_receives_run_fn_output():
    """on_complete must be called with the string returned by run_fn."""
    queue = TaskQueue()
    projects = {"p": make_project("p")}
    run_fn = AsyncMock(return_value="hello from agent")

    on_complete = AsyncMock()
    task = make_task("p", run_fn=run_fn, on_complete=on_complete)
    queue.enqueue(task)

    await run_queue(queue, projects, run_fn)

    on_complete.assert_awaited_once_with("hello from agent")


@pytest.mark.asyncio
async def test_queue_depth_tracks_correctly():
    """depth should reflect the number of waiting tasks (not including current)."""
    queue = TaskQueue()

    assert queue.depth == 0

    # Enqueue without running — depth should increase
    task_a = make_task("a")
    task_b = make_task("b")
    queue.enqueue(task_a)
    assert queue.depth == 1
    queue.enqueue(task_b)
    assert queue.depth == 2


@pytest.mark.asyncio
async def test_label_defaults_to_truncated_task():
    """AgentTask.label should default to the first 60 chars of task."""
    short_task = make_task("p")
    short_task.task = "short task"
    # Re-create to trigger __post_init__
    t = AgentTask(project_name="p", task="short task", on_complete=AsyncMock())
    assert t.label == "short task"

    long_task_text = "x" * 80
    t2 = AgentTask(project_name="p", task=long_task_text, on_complete=AsyncMock())
    assert len(t2.label) <= 63  # 60 chars + "…"
    assert t2.label.endswith("…")
