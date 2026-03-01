"""
scheduler.py — Cron-triggered agent tasks using APScheduler.

Each project config can define one or more scheduled tasks (e.g. daily reflection
at 8am). Herald registers them all at startup and fires them into the serial queue.

Cron tasks for different projects are automatically staggered by 15 minutes to
prevent them from piling up at the same time and queuing back-to-back anyway
(e.g. two 8am tasks become 8:00 and 8:15).
"""

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from .config import ProjectConfig
    from .task_queue import AgentTask, TaskQueue

log = logging.getLogger(__name__)

# Minutes to stagger each successive project's scheduled tasks.
# If project A fires at 8:00 and project B has the same cron, B gets shifted to 8:15.
STAGGER_MINUTES = 15


class HeraldScheduler:
    """
    Wraps APScheduler to fire per-project cron tasks into the agent queue.

    post_fn: async (channel_id: int, message: str) -> None
        Called when a scheduled task completes to post the result to Discord.
    """

    def __init__(
        self,
        queue: "TaskQueue",
        projects: dict[str, "ProjectConfig"],
        post_fn: Callable[[int, str], Awaitable[None]],
    ):
        self._queue = queue
        self._projects = projects
        self._post_fn = post_fn
        self._scheduler = AsyncIOScheduler()
        self._register_all()

    def _register_all(self) -> None:
        """
        Register all scheduled tasks from all project configs.

        Projects are staggered: the first project's tasks fire at the configured cron time,
        the second project's tasks are shifted forward by STAGGER_MINUTES, etc.
        """
        for project_index, project in enumerate(self._projects.values()):
            stagger = project_index * STAGGER_MINUTES

            for task_index, entry in enumerate(project.schedule):
                trigger = self._build_trigger(entry.cron, stagger)
                job_id = f"{project.name}-schedule-{task_index}"

                self._scheduler.add_job(
                    self._fire_task,
                    trigger=trigger,
                    args=[project.name, entry.task, project.discord_channel_id],
                    id=job_id,
                    # If Herald was offline when a job was supposed to fire, run it
                    # within the grace window rather than skipping it entirely.
                    misfire_grace_time=300,  # 5 minutes
                    replace_existing=True,
                )
                log.info(
                    "Scheduled: %s (stagger: +%dm) — %s",
                    job_id, stagger, entry.cron
                )

        # Accountability check — runs daily at 9am (Herald-level, not per-project)
        self._scheduler.add_job(
            self._check_accountability,
            CronTrigger(hour=9, minute=0),
            id="herald-accountability-check",
            misfire_grace_time=300,
            replace_existing=True,
        )
        log.info("Scheduled: accountability check (daily 09:00)")

        # Autonomous development check — daily at 10am per project (staggered).
        # Only registered for projects with autonomous.enabled = True.
        for project_index, project in enumerate(self._projects.values()):
            if not project.autonomous.enabled:
                continue
            stagger = project_index * STAGGER_MINUTES
            trigger = self._build_trigger("0 10 * * *", stagger)
            job_id = f"{project.name}-autonomy-check"
            self._scheduler.add_job(
                self._fire_autonomous_check,
                trigger=trigger,
                args=[project.name],
                id=job_id,
                misfire_grace_time=300,
                replace_existing=True,
            )
            log.info(
                "Scheduled: %s (autonomy check, stagger: +%dm)",
                job_id, stagger,
            )

    async def _check_accountability(self) -> None:
        """
        Daily check: for each project, compute inactivity and post a message if warranted.
        Fires once per day at 9am. Only posts if the project has crossed a threshold.
        """
        from .activity import accountability_message, days_since_activity

        for project in self._projects.values():
            days = days_since_activity(project.name)
            msg = accountability_message(project.name, days)
            if msg:
                await self._post_fn(int(project.discord_channel_id), msg)

    def _build_trigger(self, cron_expr: str, stagger_minutes: int) -> CronTrigger:
        """
        Parse a cron expression and apply a minute stagger.

        Cron expressions are 5-field: minute hour dom month dow.
        We add stagger_minutes to the minute field, rolling over into hours as needed.
        If the original minute field isn't a plain integer (e.g. it's "*" or "*/15"),
        we leave it alone and add the stagger only when it's safe to do so.
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression (expected 5 fields): '{cron_expr}'")

        minute_str, hour_str, dom, month, dow = parts

        # Only apply stagger if the minute and hour are simple integers
        if stagger_minutes > 0 and minute_str.isdigit() and hour_str.isdigit():
            total_minutes = int(hour_str) * 60 + int(minute_str) + stagger_minutes
            new_hour = (total_minutes // 60) % 24
            new_minute = total_minutes % 60
            minute_str = str(new_minute)
            hour_str = str(new_hour)

        return CronTrigger(
            minute=minute_str,
            hour=hour_str,
            day=dom,
            month=month,
            day_of_week=dow,
        )

    async def _fire_task(self, project_name: str, task: str, channel_id: str) -> None:
        """
        APScheduler calls this when a cron job fires.
        Enqueues an AgentTask with an on_complete callback that posts to Discord.
        """
        # Import here to avoid circular imports (bot imports scheduler, scheduler uses AgentTask)
        from .task_queue import AgentTask

        project = self._projects.get(project_name)
        channel_id_int = int(channel_id)

        async def on_complete(output: str) -> None:
            from .agent_runner import is_usage_limit_error, truncate_for_discord

            # If the API refused due to usage/rate limits, skip quietly rather than
            # posting a scary error to the project channel. The agent will retry on
            # the next scheduled run. Log a warning so it's visible in Herald's logs.
            if is_usage_limit_error(output):
                log.warning(
                    "Scheduled task for '%s' skipped — API usage/rate limit reached. "
                    "Will retry at next scheduled run.",
                    project_name,
                )
                return

            body = truncate_for_discord(output)
            await self._post_fn(
                channel_id_int,
                f"**Scheduled task** `[{project_name}]`\n```\n{body}\n```",
            )

        self._queue.enqueue(AgentTask(
            project_name=project_name,
            task=task,
            on_complete=on_complete,
            label=f"[scheduled] {task[:50]}",
            model=project.model or None if project else None,
            max_turns=project.max_turns or None if project else None,
        ))
        log.info("Scheduled task enqueued for project '%s'", project_name)

    async def _fire_autonomous_check(self, project_name: str) -> None:
        """
        Daily autonomous development check for a single project.

        Runs the pre-flight checklist (entirely local — no API calls). If all checks
        pass, enqueues an agent run to pick and implement one roadmap item.

        Autonomous tasks use record_activity=False so they don't reset the
        accountability clock — that clock measures operator engagement, not agent work.
        """
        from .autonomy import DEFAULT_TASK, record_run, should_run_autonomous
        from .task_queue import AgentTask

        project = self._projects.get(project_name)
        if project is None:
            return

        ok, reason = should_run_autonomous(project)
        if not ok:
            log.info("Autonomy check skipped for '%s': %s", project_name, reason)
            return

        task_prompt = project.autonomous.task or DEFAULT_TASK
        channel_id_int = int(project.discord_channel_id)

        # Capture agent_task in the closure via a mutable container so we can
        # read duration_seconds after the worker sets it (closures are late-binding).
        _task_ref: list["AgentTask"] = []

        async def on_complete(output: str) -> None:
            from .agent_runner import is_usage_limit_error, truncate_for_discord

            if is_usage_limit_error(output):
                log.warning(
                    "Autonomous run for '%s' hit usage/rate limit — skipping record.",
                    project_name,
                )
                return

            # Record wall-clock duration and token count now that the task has completed.
            # tokens_used is set by the worker from the run_agent return tuple.
            task_obj = _task_ref[0] if _task_ref else None
            duration = task_obj.duration_seconds if task_obj else 0.0
            tokens = task_obj.tokens_used if task_obj else 0
            record_run(project_name, duration or 0.0, tokens=tokens or 0)

            body = truncate_for_discord(output)
            await self._post_fn(
                channel_id_int,
                f"**Autonomous run** `[{project_name}]`\n```\n{body}\n```",
            )

        agent_task = AgentTask(
            project_name=project_name,
            task=task_prompt,
            on_complete=on_complete,
            label=f"[autonomous] {task_prompt[:50]}…",
            record_activity=False,  # must not reset the accountability clock
            model=project.model or None,
            max_turns=project.max_turns or None,
        )
        _task_ref.append(agent_task)
        self._queue.enqueue(agent_task)
        log.info("Autonomous run enqueued for project '%s'", project_name)

    def start(self) -> None:
        self._scheduler.start()
        log.info("Scheduler started with %d job(s).", len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
