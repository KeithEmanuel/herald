"""
bot.py — Discord bot for Herald.

Receives commands from the operator, routes tasks to the queue, posts results to the project
channels, and handles the git push-approval flow (👍 / 👎 reactions).

Commands:
  !run <project> <task>   — trigger a one-off agent run
  !deploy <project>       — build and deploy the project's Docker container
  !status                 — show queue depth and currently running job
  !projects               — list registered projects

Git approval flow:
  After each agent run, Herald checks for unpushed agent/* branches.
  If found, it posts a proposal message to the project channel.
  Operator reacts 👍 to push or 👎 to discard.
  If the project has auto_deploy_on_push enabled, a deploy is queued after a push.
"""

import logging
from pathlib import Path

import discord
from discord.ext import commands

from agent_runner import run_agent, truncate_for_discord
from config import ProjectConfig, load_projects
from deploy import deploy_project
from git_ops import delete_branch, get_unpushed_agent_branches, push_branch
from scheduler import HeraldScheduler
from task_queue import AgentTask, TaskQueue

log = logging.getLogger(__name__)

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"


class HeraldBot(commands.Bot):
    """
    The main Herald Discord bot.

    Lifecycle:
      1. __init__: set up state and intents
      2. setup_hook: start background tasks (queue worker, scheduler) — runs before on_ready
      3. on_ready: log that we're online
    """

    def __init__(self, projects_dir: Path):
        intents = discord.Intents.default()
        # message_content: needed to read the content of !commands
        intents.message_content = True
        # reactions: needed to receive 👍/👎 for git approval
        intents.reactions = True

        super().__init__(command_prefix="!", intents=intents)

        self.projects: dict[str, ProjectConfig] = load_projects(projects_dir)
        self.task_queue = TaskQueue()

        # Pending push-approval requests.
        # Maps Discord message_id → {"project_name": str, "branch": str}
        # When the operator reacts, we look up the message here to know what to push/discard.
        self._pending_pushes: dict[int, dict] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """
        Called by discord.py before the bot connects. Start background tasks here.

        We start the queue worker and scheduler here (not in on_ready) so they're
        running before we receive any messages.
        """
        # Queue worker — runs forever, consuming tasks one at a time
        self.loop.create_task(
            self.task_queue.worker(self.projects, run_agent),
            name="herald-queue-worker",
        )

        # Scheduler — fires cron tasks into the queue
        self._scheduler = HeraldScheduler(
            queue=self.task_queue,
            projects=self.projects,
            post_fn=self._post_to_channel,
        )
        self._scheduler.start()

        log.info(
            "Herald setup complete — %d project(s) loaded: %s",
            len(self.projects),
            ", ".join(self.projects.keys()),
        )

    async def on_ready(self) -> None:
        project_names = ", ".join(self.projects.keys())
        log.info("Herald is online as %s — projects: %s", self.user, project_names)
        print(f"Herald online as {self.user} | Projects: {project_names}")
        # Check that each project has a SOUL.md — a project without a soul is just files.
        await self._check_project_souls()

    async def _check_project_souls(self) -> None:
        """
        On startup, check each project for a SOUL.md file.
        If a project is missing one, post a notice to its Discord channel.

        A SOUL.md gives the project agent a persistent identity and cross-session memory.
        Without one, the agent starts each run with no context about itself or the project.
        """
        from pathlib import Path

        for name, project in self.projects.items():
            soul_path = Path(project.path) / "SOUL.md"
            if not soul_path.exists():
                channel = self.get_channel(int(project.discord_channel_id))
                if channel:
                    await channel.send(
                        f"👻 **`{name}` has no SOUL.md.** "
                        f"The agent will run without persistent identity or memory.\n"
                        f"Use `!run {name} <task>` to create one, or add SOUL.md manually. "
                        f"See `projects/example.yaml` for a suggested task prompt."
                    )
                    log.warning("Project '%s' is missing SOUL.md at %s", name, project.path)

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------

    @commands.command(name="run")
    async def cmd_run(self, ctx: commands.Context, project: str, *, task: str) -> None:
        """
        !run <project> <task>

        Trigger a one-off agent run. The agent runs asynchronously — Herald posts the
        result when it's done, which could be several minutes later.
        """
        if project not in self.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        # Acknowledge immediately — the user shouldn't wonder if it worked
        await ctx.send(f"Queued task for `{project}` (position {self.task_queue.depth + 1}). I'll reply here when done.")

        channel_id = ctx.channel.id

        async def on_complete(output: str) -> None:
            body = truncate_for_discord(output)
            await ctx.send(f"**Agent run complete** `[{project}]`\n```\n{body}\n```")
            # After each run, check for unpushed agent branches and propose a push if needed
            await self._check_and_propose_push(project, ctx.channel)

        self.task_queue.enqueue(AgentTask(
            project_name=project,
            task=task,
            on_complete=on_complete,
        ))

    @commands.command(name="status")
    async def cmd_status(self, ctx: commands.Context) -> None:
        """!status — show queue depth and currently running job."""
        current = self.task_queue.current
        depth = self.task_queue.depth

        if current is None and depth == 0:
            await ctx.send("Herald is idle — queue is empty.")
            return

        lines = []
        if current:
            lines.append(f"**Running:** `[{current.project_name}]` {current.label}")
        if depth > 0:
            lines.append(f"**Queued:** {depth} task(s) waiting")

        await ctx.send("\n".join(lines))

    @commands.command(name="projects")
    async def cmd_projects(self, ctx: commands.Context) -> None:
        """!projects — list registered projects."""
        if not self.projects:
            await ctx.send("No projects registered. Drop a YAML file in the projects/ directory.")
            return

        lines = ["**Registered projects:**"]
        for name, project in self.projects.items():
            channel = self.get_channel(int(project.discord_channel_id))
            channel_mention = channel.mention if channel else f"#{project.discord_channel_id}"
            schedule_count = len(project.schedule)
            lines.append(
                f"• `{name}` — {project.display_name} | channel: {channel_mention} | "
                f"{schedule_count} scheduled task(s)"
            )

        await ctx.send("\n".join(lines))

    @commands.command(name="deploy")
    async def cmd_deploy(self, ctx: commands.Context, project: str) -> None:
        """
        !deploy <project>

        Build and deploy the project's Docker container via `docker compose up --build -d`.
        Runs through the serial queue so it won't overlap with an active agent run.

        Requires deploy.compose_path to be set in the project's YAML config.
        """
        if project not in self.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        project_config = self.projects[project]
        if not project_config.deploy.compose_path:
            await ctx.send(
                f"`{project}` has no deploy config. "
                f"Add `deploy.compose_path` to `projects/{project}.yaml`."
            )
            return

        await ctx.send(
            f"Deploy queued for `{project}` (position {self.task_queue.depth + 1}). "
            f"I'll post output when done."
        )
        await self._enqueue_deploy(project, ctx.channel)

    # -------------------------------------------------------------------------
    # Git push-approval flow
    # -------------------------------------------------------------------------

    async def _check_and_propose_push(
        self, project_name: str, channel: discord.TextChannel
    ) -> None:
        """
        After an agent run, check for unpushed agent/* branches.
        If found, post a push proposal and await the operator's reaction.
        """
        project = self.projects[project_name]
        if not project.git.push_requires_approval:
            return

        unpushed = get_unpushed_agent_branches(project.path, project.git.branch_prefix)

        for item in unpushed:
            branch = item["branch"]
            commits = item["commits"]
            n = len(commits)
            commit_list = "\n".join(f"  • {c}" for c in commits[:10])
            if n > 10:
                commit_list += f"\n  … and {n - 10} more"

            msg_text = (
                f"**Push proposal** `[{project_name}]`\n"
                f"Branch: `{branch}` — {n} commit(s)\n"
                f"```\n{commit_list}\n```\n"
                f"React {THUMBS_UP} to push or {THUMBS_DOWN} to discard."
            )

            msg = await channel.send(msg_text)
            await msg.add_reaction(THUMBS_UP)
            await msg.add_reaction(THUMBS_DOWN)

            # Register the pending push so on_raw_reaction_add can find it
            self._pending_pushes[msg.id] = {
                "project_name": project_name,
                "branch": branch,
            }
            log.info(
                "Push proposal posted for %s branch %s (message %d)",
                project_name, branch, msg.id,
            )

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Handle 👍/👎 reactions on push-proposal messages.

        We use on_raw_reaction_add (not on_reaction_add) because the proposal message
        may not be in the message cache when Herald restarts, and we need to handle
        reactions on older messages too.
        """
        # Ignore reactions from the bot itself
        if payload.user_id == self.user.id:
            return

        # Only handle reactions on messages we're tracking as pending pushes
        if payload.message_id not in self._pending_pushes:
            return

        emoji = str(payload.emoji)
        if emoji not in (THUMBS_UP, THUMBS_DOWN):
            return

        pending = self._pending_pushes.pop(payload.message_id)
        project_name = pending["project_name"]
        branch = pending["branch"]
        project = self.projects[project_name]

        channel = self.get_channel(payload.channel_id)
        if channel is None:
            log.warning("Reaction received but channel %d not found", payload.channel_id)
            return

        if emoji == THUMBS_UP:
            success, message = push_branch(project.path, branch)
            if success:
                await channel.send(f"Pushed `{branch}` to origin. {message}")
                # Auto-deploy if the project is configured for it
                if project.deploy.auto_deploy_on_push and project.deploy.compose_path:
                    await channel.send(f"Auto-deploying `{project_name}`...")
                    await self._enqueue_deploy(project_name, channel)
            else:
                await channel.send(f"Push failed for `{branch}`:\n```\n{message}\n```")
        else:
            success, message = delete_branch(project.path, branch)
            await channel.send(message)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _enqueue_deploy(self, project_name: str, channel: discord.TextChannel) -> None:
        """
        Enqueue a deploy task for project_name. Posts output to channel when complete.

        Uses the queue so deploys can't overlap with active agent runs — both are
        writing to the same project directory, and a deploy rebuilds from current state.

        Shared by !deploy and the auto_deploy_on_push flow.
        """
        compose_path = self.projects[project_name].deploy.compose_path

        async def deploy_run_fn(project_path: str, task: str) -> str:
            return await deploy_project(compose_path)

        async def on_complete(output: str) -> None:
            body = truncate_for_discord(output)
            await channel.send(f"**Deploy complete** `[{project_name}]`\n```\n{body}\n```")

        self.task_queue.enqueue(AgentTask(
            project_name=project_name,
            task=f"[deploy] {project_name}",
            on_complete=on_complete,
            label=f"[deploy] {project_name}",
            run_fn=deploy_run_fn,
            record_activity=False,  # deploys don't count as project activity
        ))
        log.info("Deploy task enqueued for project '%s'", project_name)

    async def _post_to_channel(self, channel_id: int, content: str) -> None:
        """Post a message to a Discord channel by ID. Used by the scheduler."""
        channel = self.get_channel(channel_id)
        if channel is None:
            log.error("Cannot post to channel %d — not found (wrong ID or missing access?)", channel_id)
            return
        await channel.send(content)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Send a helpful error message instead of silently swallowing command errors."""
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. Try `!help {ctx.command}`")
        elif isinstance(error, commands.CommandNotFound):
            pass  # Ignore unknown commands — noisy in shared channels
        else:
            log.exception("Command error in %s: %s", ctx.command, error)
            await ctx.send(f"Error: {error}")
