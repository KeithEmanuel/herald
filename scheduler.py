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
    from config import ProjectConfig
    from task_queue import AgentTask, TaskQueue

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

    async def _check_accountability(self) -> None:
        """
        Daily check: for each project, compute inactivity and post a message if warranted.
        Fires once per day at 9am. Only posts if the project has crossed a threshold.
        """
        from activity import accountability_message, days_since_activity

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
        from task_queue import AgentTask

        channel_id_int = int(channel_id)

        async def on_complete(output: str) -> None:
            from agent_runner import truncate_for_discord
            body = truncate_for_discord(output)
            await self._post_fn(
                channel_id_int,
                f"**Scheduled task complete** `[{project_name}]`\n```\n{body}\n```",
            )

        self._queue.enqueue(AgentTask(
            project_name=project_name,
            task=task,
            on_complete=on_complete,
            label=f"[scheduled] {task[:50]}",
        ))
        log.info("Scheduled task enqueued for project '%s'", project_name)

    def start(self) -> None:
        self._scheduler.start()
        log.info("Scheduler started with %d job(s).", len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
