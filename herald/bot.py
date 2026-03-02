"""
bot.py — Discord bot for Herald.

Receives commands from the operator, routes tasks to the queue, posts results to the project
channels, and handles the git push-approval flow (👍 / 👎 reactions).

Commands:
  !run <project> <task>                              — trigger a one-off agent run
  !deploy [project]                                  — build and deploy project container; project inferred from channel if omitted
  !push [project]                                    — check for unpushed agent branches and propose a push
  !cancel [project]                                  — cancel next queued (not running) task for a project
  !status                                            — show queue depth and running job
  !projects                                          — list registered projects
  !webhook <project>                                 — create/update agent webhook
  !schedule <project> <cron>                         — set cron schedule
  !autonomy <project> <on|off|status|budget|reserve> — manage autonomous dev mode
  !addproject <name> <repo_url> [agent_name] [#ch]  — register a new project end-to-end

Direct messages:
  Posting a plain message in a project's Discord channel automatically queues a task
  for that project's agent. Results are posted back in the same channel via the agent
  webhook (i.e. as the agent's own identity). No !run needed.
  File attachments in project channel messages are downloaded and their paths injected
  into the task prompt so the agent can read them (images, screenshots, text files —
  anything Claude Code's Read tool supports).

Git approval flow:
  After each agent run, Herald checks for unpushed agent/* branches.
  If found, it posts a proposal message to the project channel.
  Operator reacts 👍 to push or 👎 to discard.
  If the project has auto_deploy_on_push enabled, a deploy is queued after a push.
"""

import asyncio
import json
import logging
import os
import random
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

import discord
from discord.ext import commands

from .agent_runner import is_error_output, run_agent, split_for_discord, truncate_for_discord
from .config import ProjectConfig, load_projects
from .deploy import deploy_project
from .git_ops import delete_branch, get_unpushed_agent_branches, push_branch
from .scheduler import HeraldScheduler
from .task_queue import AgentTask, TaskQueue

log = logging.getLogger(__name__)

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"

# Thinking message pool — shown while an agent task is queued/running.
# Displayed as italics in the agent's voice before the real response arrives.
_THINKING_MESSAGES = [
    "Rallying the peasants...",
    "Tooting the horns...",
    "Polishing the armor...",
    "Consulting the stars...",
    "Unfurling the banners...",
    "Sharpening the quills...",
    "Reading the omens...",
    "Penning the proclamation...",
    "Summoning the scribes...",
    "Lighting the beacon fires...",
    "Dispatching the messengers...",
    "Ringing the tower bell...",
    "Checking the feudal tax records...",
    "Commissioning the herald...",
    "Dusting off the grimoire...",
    "Consulting the oracle...",
    "Sounding the war drums...",
    "Updating the royal ledgers...",
    "Raising the drawbridge...",
    "Oiling the trebuchet...",
]


class HeraldCommands(commands.Cog, name="Herald"):
    """
    Discord commands for Herald. Registered as a Cog so discord.py properly
    discovers and routes them — commands on a Bot subclass aren't auto-registered
    in discord.py 2.x.
    """

    def __init__(self, bot: "HeraldBot") -> None:
        self.bot = bot

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------

    @commands.command(name="run")
    async def cmd_run(self, ctx: commands.Context, project: str, *, task: str) -> None:
        """
        !run <project> <task>

        Trigger a one-off agent run. The agent runs asynchronously — Herald posts the
        result to the project's channel when done (not the channel where !run was typed).
        """
        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        # Results go to the project's dedicated channel, not wherever !run was typed.
        # This keeps the herald channel clean and agent output in the right place.
        project_channel = self.bot.get_channel(
            int(self.bot.projects[project].discord_channel_id)
        ) or ctx.channel

        # Acknowledge immediately in the command channel
        dest = project_channel.mention if project_channel != ctx.channel else "here"
        await ctx.send(
            f"Queued task for `{project}` (position {self.bot.task_queue.depth + 1}). "
            f"I'll post results in {dest}."
        )

        async def on_complete(output: str) -> None:
            if is_error_output(output):
                await project_channel.send(f"⚠️ {truncate_for_discord(output)}")
            else:
                for chunk in split_for_discord(output):
                    await self.bot._post_as_agent(project, chunk, project_channel)
            # After each run, check for unpushed agent branches and propose a push if needed
            await self.bot._check_and_propose_push(project, project_channel)

        proj_cfg = self.bot.projects[project]
        self.bot.task_queue.enqueue(AgentTask(
            project_name=project,
            task=task,
            on_complete=on_complete,
            model=proj_cfg.model or None,
            max_turns=proj_cfg.max_turns or None,
        ))

    @commands.command(name="status")
    async def cmd_status(self, ctx: commands.Context) -> None:
        """!status — show queue depth and currently running job."""
        current = self.bot.task_queue.current
        depth = self.bot.task_queue.depth

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
        if not self.bot.projects:
            await ctx.send("No projects registered. Drop a YAML file in the projects/ directory.")
            return

        lines = ["**Registered projects:**"]
        for name, project in self.bot.projects.items():
            channel = self.bot.get_channel(int(project.discord_channel_id))
            channel_mention = channel.mention if channel else f"#{project.discord_channel_id}"
            schedule_count = len(project.schedule)
            lines.append(
                f"• `{name}` — {project.display_name} | channel: {channel_mention} | "
                f"{schedule_count} scheduled task(s)"
            )

        await ctx.send("\n".join(lines))

    @commands.command(name="deploy")
    async def cmd_deploy(self, ctx: commands.Context, project: str = None) -> None:
        """
        !deploy [project]

        Build and deploy the project's Docker container via `docker compose up --build -d`.
        Runs through the serial queue so it won't overlap with an active agent run.

        In a project's own channel, the project name is optional — it's inferred from
        the channel. Use `!deploy <project>` from any other channel.

        Requires deploy.compose_path to be set in the project's YAML config.
        """
        # Infer project from channel when not explicitly given
        if project is None:
            project = self.bot._channel_to_project.get(ctx.channel.id)
            if project is None:
                await ctx.send(
                    "Not a project channel. Use `!deploy <project>` or run this "
                    "from a project's own channel."
                )
                return

        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        project_config = self.bot.projects[project]
        if not project_config.deploy.compose_path:
            await ctx.send(
                f"`{project}` has no deploy config. "
                f"Add `deploy.compose_path` to `projects/{project}.yaml`."
            )
            return

        # Reject stale commands — Discord replays missed messages when Herald resumes
        # after a container restart. A self-deploy restarts Herald in ~30s; any command
        # older than 20s when we receive it was almost certainly replayed, not fresh.
        age = (discord.utils.utcnow() - ctx.message.created_at).total_seconds()
        if age > 20:
            log.info(
                "Ignoring stale !deploy command for '%s' (age=%.1fs) — replayed after restart",
                project, age,
            )
            return

        # Detect self-deployment: Herald can't send a completion message after
        # restarting itself, so we send a special ack that sets expectations.
        is_self = project == "herald"
        if is_self:
            await ctx.send(
                f"Deploying Herald (position {self.bot.task_queue.depth + 1}) — "
                f"I'll go quiet while I restart. Back in ~30 seconds."
            )
        else:
            await ctx.send(
                f"Deploy queued for `{project}` (position {self.bot.task_queue.depth + 1}). "
                f"I'll post output when done."
            )
        await self.bot._enqueue_deploy(project, ctx.channel)

    @commands.command(name="push")
    async def cmd_push(self, ctx: commands.Context, project: str = None) -> None:
        """
        !push [project]

        Manually check for unpushed agent branches and post push proposals if any are found.
        Useful when a proposal didn't appear after a run, or when you've committed manually.

        In a project's own channel, the project name is optional — it's inferred from
        the channel. Use `!push <project>` from any other channel.
        """
        if project is None:
            project = self.bot._channel_to_project.get(ctx.channel.id)
            if project is None:
                await ctx.send(
                    "Not a project channel. Use `!push <project>` or run this "
                    "from a project's own channel."
                )
                return

        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        project_channel = (
            self.bot.get_channel(int(self.bot.projects[project].discord_channel_id))
            or ctx.channel
        )
        count = await self.bot._check_and_propose_push(project, project_channel)
        if count == 0:
            await ctx.send(f"No unpushed agent branches for `{project}`.")

    @commands.command(name="cancel")
    async def cmd_cancel(self, ctx: commands.Context, project: str = None) -> None:
        """
        !cancel [project]

        Remove the next pending (not currently running) queued task for a project.
        Does not abort a task that's already executing — use !status to see what's running.

        In a project's own channel, the project name is optional — it's inferred from
        the channel. Use `!cancel <project>` from any other channel.
        """
        if project is None:
            project = self.bot._channel_to_project.get(ctx.channel.id)
            if project is None:
                await ctx.send(
                    "Not a project channel. Use `!cancel <project>` or run this "
                    "from a project's own channel."
                )
                return

        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        current = self.bot.task_queue.current
        if current and current.project_name == project:
            await ctx.send(
                f"`{project}` is currently running — `!cancel` only removes pending tasks, "
                f"not in-progress ones. Use `!status` to see what's running."
            )
            return

        cancelled = self.bot.task_queue.cancel(project)
        if cancelled:
            await ctx.send(f"Cancelled next queued task for `{project}`.")
        else:
            await ctx.send(f"No queued tasks for `{project}`.")

    @commands.command(name="webhook")
    async def cmd_webhook(self, ctx: commands.Context, project: str) -> None:
        """
        !webhook <project>

        Create (or replace) the agent webhook for a project. The webhook makes agent
        output appear as the agent's own Discord identity instead of the Herald bot.

        Attach an image to this message to set the agent's avatar. No attachment means
        Discord's default webhook avatar is used.

        Requires the Herald bot to have Manage Webhooks permission in the project channel.
        """
        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        project_config = self.bot.projects[project]
        channel = self.bot.get_channel(int(project_config.discord_channel_id))
        if channel is None:
            await ctx.send(f"Cannot find channel for `{project}` — check the channel ID in the project config.")
            return

        # Download avatar bytes from attachment if one was included with the command
        avatar_bytes: bytes | None = None
        if ctx.message.attachments:
            avatar_bytes = await ctx.message.attachments[0].read()

        username = project_config.agent_name or project_config.display_name

        try:
            webhook = await channel.create_webhook(
                name=username,
                avatar=avatar_bytes,
                reason=f"Herald agent webhook for project '{project}'",
            )
        except discord.Forbidden:
            await ctx.send(
                f"Missing **Manage Webhooks** permission in {channel.mention}. "
                f"Grant it to the Herald bot in the channel's permission settings."
            )
            return
        except Exception as e:
            log.exception("Failed to create webhook for project '%s'", project)
            await ctx.send(f"Failed to create webhook: {e}")
            return

        self.bot._save_webhook(project, webhook.url)
        avatar_note = " with custom avatar" if avatar_bytes else " (no avatar set — attach an image to this command to set one)"
        await ctx.send(
            f"Webhook created for `{project}`{avatar_note}. "
            f"Agent will post as **{username}** in {channel.mention}."
        )
        log.info("Webhook created for project '%s' in channel %d", project, channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Direct message listener for project channels.

        When the operator posts a plain message in a project's dedicated channel, treat it
        as a task for that project's agent — no `!run` needed. This gives each project
        channel a Claude Code-like conversational feel: type your request, get a response.

        Ignores:
          - Messages from bots (including Herald itself)
          - Messages starting with '!' (handled by command processing)
          - Messages in channels that aren't a project channel
        """
        if message.author.bot:
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        project_name = self.bot._channel_to_project.get(message.channel.id)
        if project_name is None:
            return

        task_text = message.content.strip()
        if not task_text and not message.attachments:
            return

        # Reject messages that are too old — they may be replayed by Discord after a
        # container restart resumes the gateway session. Skip anything > 20s old so
        # a normal restart cycle (~30s) doesn't re-process the message that triggered it.
        age = (discord.utils.utcnow() - message.created_at).total_seconds()
        if age > 20:
            log.debug(
                "Ignoring stale message in #%s (age=%.1fs) — possible replay after restart",
                message.channel.name, age,
            )
            return

        channel = message.channel

        # Download any file attachments to a temp dir so the agent can read them.
        # Paths are injected into the task prompt; cleanup runs in on_complete (try/finally).
        attachment_paths: list[str] = []
        attachment_dir: Path | None = None
        if message.attachments:
            attachment_dir = Path(f"/tmp/herald-attachments/{channel.id}-{message.id}")
            attachment_dir.mkdir(parents=True, exist_ok=True)
            for att in message.attachments:
                dest = attachment_dir / att.filename
                try:
                    await att.save(dest)
                    attachment_paths.append(str(dest))
                    log.info("Saved attachment '%s' for %s", att.filename, project_name)
                except Exception:
                    log.warning(
                        "Failed to download attachment '%s'", att.filename, exc_info=True
                    )

        # Fetch recent channel history so the agent has conversation context.
        # This is what lets the agent understand short replies like "yes" or "actually,
        # make it dark mode instead" — it can see what it said in previous messages.
        recent: list[discord.Message] = []
        async for msg in channel.history(limit=15, before=message, oldest_first=False):
            recent.append(msg)
        recent.reverse()  # oldest first so it reads like a conversation

        context_lines = []
        for msg in recent:
            body = msg.content.strip()
            if not body:
                continue  # skip image-only or embed-only messages
            # Webhook messages are from the agent (Argent); label them by display_name.
            # Regular messages are from humans; label them by display_name too.
            context_lines.append(f"{msg.author.display_name}: {body}")

        if context_lines:
            context_block = "\n".join(context_lines)
            full_task = (
                f"[Recent conversation in #{channel.name}:]\n"
                f"{context_block}\n\n"
                f"[New message from {message.author.display_name}:]\n"
                f"{task_text or '[attachment only — no text]'}"
            )
        else:
            full_task = task_text or "[attachment only — no text]"

        if attachment_paths:
            paths_str = "\n".join(f"- {p}" for p in attachment_paths)
            full_task += f"\n\nAttached files (use the Read tool to view them):\n{paths_str}"

        # Post a "thinking" placeholder as the agent identity. We capture the returned
        # message so on_complete can edit it in-place — the placeholder transforms into
        # the actual response rather than posting a separate follow-up message.
        queue_pos = self.bot.task_queue.depth + 1
        thinking_phrase = random.choice(_THINKING_MESSAGES)
        thinking_msg = await self.bot._post_as_agent(
            project_name,
            f"_{thinking_phrase}_ (queue position {queue_pos})",
            channel,
        )

        async def on_complete(output: str) -> None:
            try:
                # Infrastructure errors (non-zero exit, timeout, missing binary) come from
                # Herald bot, not the agent webhook — they're Herald's problem, not the agent's.
                # Delete the thinking placeholder and post the error as the Herald bot.
                if is_error_output(output):
                    if thinking_msg is not None:
                        try:
                            await thinking_msg.delete()
                        except Exception:
                            pass
                    await channel.send(f"⚠️ {truncate_for_discord(output)}")
                    return

                # Successful agent output: split into chunks so long responses arrive as
                # multiple messages instead of being truncated. Edit the thinking placeholder
                # in-place with the first chunk, then post the rest as follow-up messages.
                chunks = split_for_discord(output)
                if thinking_msg is not None:
                    try:
                        await thinking_msg.edit(content=chunks[0])
                        for chunk in chunks[1:]:
                            await self.bot._post_as_agent(project_name, chunk, channel)
                        await self.bot._check_and_propose_push(project_name, channel)
                        return
                    except Exception:
                        log.warning(
                            "Could not edit thinking message for %s — posting fresh", project_name
                        )
                for chunk in chunks:
                    await self.bot._post_as_agent(project_name, chunk, channel)
                await self.bot._check_and_propose_push(project_name, channel)
            finally:
                # Clean up downloaded attachment files once the agent run completes,
                # whether it succeeded, failed, or raised. /tmp lives in the container
                # so this is belt-and-suspenders; a restart would clean it anyway.
                if attachment_dir is not None:
                    await asyncio.to_thread(shutil.rmtree, attachment_dir, ignore_errors=True)

        proj_cfg = self.bot.projects[project_name]
        self.bot.task_queue.enqueue(AgentTask(
            project_name=project_name,
            task=full_task,
            on_complete=on_complete,
            model=proj_cfg.model or None,
            max_turns=proj_cfg.max_turns or None,
        ))

    @commands.command(name="reload")
    async def cmd_reload(self, ctx: commands.Context) -> None:
        """
        !reload

        Hot-reload all project configs from the projects/ directory without restarting Herald.
        Use this after manually editing a project YAML or adding a new one by hand.

        Projects added via !addproject are already live and don't need a reload.
        """
        try:
            new_projects = load_projects(self.bot.projects_dir)
        except Exception as e:
            await ctx.send(f"Reload failed — config error:\n```\n{e}\n```")
            return

        old_names = set(self.bot.projects.keys())
        new_names = set(new_projects.keys())
        added = new_names - old_names
        removed = old_names - new_names

        # Swap in new project config in-place (queue worker holds a ref to this dict,
        # so we update it rather than replacing it to keep the reference valid)
        self.bot.projects.clear()
        self.bot.projects.update(new_projects)

        # Rebuild the channel → project lookup map
        self.bot._channel_to_project = {
            int(p.discord_channel_id): name for name, p in self.bot.projects.items()
        }

        # Restart the scheduler so new/updated cron schedules take effect
        self.bot._scheduler.shutdown()
        self.bot._scheduler = HeraldScheduler(
            queue=self.bot.task_queue,
            projects=self.bot.projects,
            post_fn=self.bot._post_to_channel,
        )
        self.bot._scheduler.start()

        lines = [f"Reloaded — {len(new_projects)} project(s) active."]
        if added:
            lines.append(f"Added: {', '.join(f'`{n}`' for n in sorted(added))}")
        if removed:
            lines.append(f"Removed: {', '.join(f'`{n}`' for n in sorted(removed))}")
        if not added and not removed:
            lines.append("Schedules refreshed — no projects added or removed.")

        await ctx.send("\n".join(lines))
        log.info("Config hot-reloaded — projects now: %s", list(self.bot.projects.keys()))

    @commands.command(name="schedule")
    async def cmd_schedule(self, ctx: commands.Context, project: str, *, cron: str) -> None:
        """
        !schedule <project> <cron>

        Set or update the daily cron schedule for a project.

        <cron> is a 5-field cron expression: minute hour dom month dow
        Examples:
          !schedule herald 0 8 * * *     → 8:00am every day
          !schedule herald 30 9 * * 1    → 9:30am every Monday

        This replaces the project's first scheduled task's cron time (task content unchanged).
        If the project has no scheduled tasks, adds the default morning check-in task.

        Writes the updated YAML and hot-reloads the scheduler — no restart needed.
        """
        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        cron = cron.strip()

        # Validate cron expression by trying to build a trigger from it
        try:
            self.bot._scheduler._build_trigger(cron, stagger_minutes=0)
        except (ValueError, Exception) as e:
            await ctx.send(
                f"Invalid cron expression `{cron}`: {e}\n"
                f"Format: `minute hour dom month dow` (e.g. `0 8 * * *` for 8am daily)"
            )
            return

        project_config = self.bot.projects[project]
        yaml_path = self.bot.projects_dir / f"{project}.yaml"

        # Load raw YAML to preserve comments and structure, then update schedule
        try:
            import yaml as _yaml
            raw = _yaml.safe_load(yaml_path.read_text()) if yaml_path.exists() else {}
        except Exception:
            raw = {}

        # Default task content used when a project has no existing schedule
        default_task = (
            "Read .herald/SOUL.md and .herald/MEMORY.md. Check the recent git log (last 5 commits). "
            "What is the current state of the project? What is the single most "
            "important thing to work on next? Post a short status — 2-3 sentences "
            "— and end with a specific proposal: what you'd do if given the go-ahead. "
            "Keep it conversational. Wait for a reply before acting."
        )

        existing_schedule = raw.get("schedule", [])
        if existing_schedule:
            # Update the cron on the first task, preserve its task content
            existing_schedule[0]["cron"] = cron
        else:
            existing_schedule = [{"cron": cron, "task": default_task}]

        raw["schedule"] = existing_schedule

        # Write updated YAML and hot-reload the scheduler
        yaml_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

        new_projects = load_projects(self.bot.projects_dir)
        self.bot.projects.clear()
        self.bot.projects.update(new_projects)
        self.bot._channel_to_project = {
            int(p.discord_channel_id): name for name, p in self.bot.projects.items()
        }
        self.bot._scheduler.shutdown()
        self.bot._scheduler = HeraldScheduler(
            queue=self.bot.task_queue,
            projects=self.bot.projects,
            post_fn=self.bot._post_to_channel,
        )
        self.bot._scheduler.start()

        action = "added" if not existing_schedule else "updated"
        await ctx.send(
            f"Schedule {action} for `{project}` — cron: `{cron}`.\n"
            f"Scheduler reloaded. New schedule is active immediately."
        )
        log.info("Schedule %s for project '%s': cron=%s", action, project, cron)

    @commands.command(name="autonomy")
    async def cmd_autonomy(
        self, ctx: commands.Context, project: str, action: str, *args: str
    ) -> None:
        """
        !autonomy <project> <action> [value]

        Manage autonomous development mode for a project.

        Actions:
          on [minutes]      — enable (optionally set weekly_minutes budget)
          off               — disable
          status            — show this week's usage stats and pre-flight result
          budget <minutes>  — update weekly_minutes
          reserve <minutes> — update reserve_minutes (informational)

        Examples:
          !autonomy herald on 210
          !autonomy herald status
          !autonomy herald budget 300
          !autonomy herald off
        """
        if project not in self.bot.projects:
            await ctx.send(
                f"Unknown project `{project}`. Try `!projects` to see registered projects."
            )
            return

        action = action.lower().strip()

        if action == "status":
            await self._autonomy_status(ctx, project)
            return

        if action not in ("on", "off", "budget", "reserve"):
            await ctx.send(
                f"Unknown action `{action}`. "
                f"Valid actions: `on`, `off`, `status`, `budget`, `reserve`"
            )
            return

        # All remaining actions write the YAML — load it first
        yaml_path = self.bot.projects_dir / f"{project}.yaml"
        try:
            raw = yaml.safe_load(yaml_path.read_text()) if yaml_path.exists() else {}
        except Exception:
            raw = {}

        raw.setdefault("autonomous", {})

        if action == "on":
            raw["autonomous"]["enabled"] = True
            if args:
                try:
                    raw["autonomous"]["weekly_minutes"] = int(args[0])
                except ValueError:
                    await ctx.send(f"Invalid minutes value: `{args[0]}`")
                    return
            msg = f"Autonomous mode **enabled** for `{project}`."
            if "weekly_minutes" in raw["autonomous"]:
                msg += f" Budget: {raw['autonomous']['weekly_minutes']}m/week."

        elif action == "off":
            raw["autonomous"]["enabled"] = False
            msg = f"Autonomous mode **disabled** for `{project}`."

        elif action == "budget":
            if not args:
                await ctx.send("Usage: `!autonomy <project> budget <minutes>`")
                return
            try:
                raw["autonomous"]["weekly_minutes"] = int(args[0])
            except ValueError:
                await ctx.send(f"Invalid minutes value: `{args[0]}`")
                return
            msg = f"Weekly budget for `{project}` set to **{raw['autonomous']['weekly_minutes']}m**."

        elif action == "reserve":
            if not args:
                await ctx.send("Usage: `!autonomy <project> reserve <minutes>`")
                return
            try:
                raw["autonomous"]["reserve_minutes"] = int(args[0])
            except ValueError:
                await ctx.send(f"Invalid minutes value: `{args[0]}`")
                return
            msg = f"Reserve for `{project}` set to **{raw['autonomous']['reserve_minutes']}m**."

        # Write YAML and hot-reload
        yaml_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))
        new_projects = load_projects(self.bot.projects_dir)
        self.bot.projects.clear()
        self.bot.projects.update(new_projects)
        self.bot._channel_to_project = {
            int(p.discord_channel_id): name for name, p in self.bot.projects.items()
        }
        self.bot._scheduler.shutdown()
        self.bot._scheduler = HeraldScheduler(
            queue=self.bot.task_queue,
            projects=self.bot.projects,
            post_fn=self.bot._post_to_channel,
        )
        self.bot._scheduler.start()

        await ctx.send(msg + " Scheduler reloaded.")
        log.info("Autonomy %s for project '%s' — args: %s", action, project, args)

    async def _autonomy_status(self, ctx: commands.Context, project: str) -> None:
        """Post a formatted autonomy status summary for a project."""
        from .autonomy import get_weekly_stats, has_roadmap_items, should_run_autonomous

        project_config = self.bot.projects[project]
        cfg = project_config.autonomous
        stats = get_weekly_stats(project)

        autonomous_minutes = stats.get("autonomous_minutes", 0.0)
        autonomous_tokens = stats.get("autonomous_tokens", 0)
        runs_this_week = stats.get("runs_this_week", 0)
        runs_today = stats.get("runs_today", 0)
        week_key = stats.get("week_key", "—")
        last_run_ts = stats.get("last_run_ts")

        last_str = (
            datetime.fromisoformat(last_run_ts).strftime("%Y-%m-%d %H:%M UTC")
            if last_run_ts
            else "never"
        )

        # Show token budget if configured, otherwise show minute budget
        if cfg.weekly_tokens > 0:
            pct = (autonomous_tokens / cfg.weekly_tokens * 100) if cfg.weekly_tokens else 0
            budget_str = (
                f"{autonomous_tokens:,} tokens used / {cfg.weekly_tokens:,} ({pct:.0f}%)"
                f"  •  ({autonomous_minutes:.0f}m wall-clock)"
            )
        else:
            pct = (autonomous_minutes / cfg.weekly_minutes * 100) if cfg.weekly_minutes else 0
            budget_str = (
                f"{autonomous_minutes:.0f}m used / {cfg.weekly_minutes}m ({pct:.0f}%)"
                f"  •  Reserve: {cfg.reserve_minutes}m for operator"
            )

        roadmap_ok = has_roadmap_items(project_config.path, cfg.roadmap_paths)
        roadmap_str = "✅ items remaining" if roadmap_ok else "❌ no unchecked items"

        ok, reason = should_run_autonomous(project_config)
        preflight_str = "✅ ready to run" if ok else f"⏸ {reason}"

        enabled_str = "✅ enabled" if cfg.enabled else "❌ disabled"
        model_str = project_config.model or "(default)"
        max_turns_str = str(project_config.max_turns) if project_config.max_turns else "(default)"

        lines = [
            f"**Autonomy — {project}** ({week_key})",
            f"Status: {enabled_str}  •  Model: `{model_str}`  •  Max turns: {max_turns_str}",
            f"Budget: {budget_str}",
            f"Runs: {runs_this_week} this week, {runs_today} today  •  Last: {last_str}",
            f"Roadmap: {roadmap_str}  •  Next check: daily ~10:00 UTC (staggered)",
            f"Pre-flight: {preflight_str}",
        ]
        await ctx.send("\n".join(lines))

    @commands.command(name="addproject")
    async def cmd_addproject(
        self,
        ctx: commands.Context,
        name: str,
        repo_url: str,
        agent_name: str = None,
        channel_ref: str = None,
    ) -> None:
        """
        !addproject <name> <repo_url> [agent_name] [channel]

        Register a new project end-to-end:
          1. Clone the repo to repos/<name> (skips if already cloned)
          2. Create a private agent channel (or use an existing one if provided)
          3. Create the agent webhook (attach an image for the avatar)
          4. Write projects/<name>.yaml
          5. Hot-reload the project into Herald immediately

        agent_name defaults to the project name (title-cased) if not provided.

        channel can be:
          - A channel name:    sable
          - A channel mention: #sable
          - A channel ID:      1234567890123456789
        Omit to create a new private channel automatically.

        Requires Herald bot to have Manage Channels and Manage Webhooks permissions.
        """
        if ctx.guild is None:
            await ctx.send("This command must be run in a server channel, not a DM.")
            return

        if name in self.bot.projects:
            await ctx.send(f"Project `{name}` is already registered. Use `!projects` to see all projects.")
            return

        if agent_name is None:
            agent_name = name.replace("-", " ").replace("_", " ").title()
        display_name = name.replace("-", " ").replace("_", " ").title()

        # Resolve channel_ref to a TextChannel by ID, mention, or name.
        # Using a plain string param avoids discord.py's converter raising ChannelNotFound
        # when the user types a channel name without a # prefix.
        channel: discord.TextChannel | None = None
        if channel_ref is not None:
            raw = channel_ref.strip().lstrip("#")
            # Try as numeric ID first
            if raw.isdigit():
                channel = ctx.guild.get_channel(int(raw))
            # Try stripping mention formatting (<#1234>)
            if channel is None and raw.startswith("<#") and raw.endswith(">"):
                cid = raw[2:-1]
                if cid.isdigit():
                    channel = ctx.guild.get_channel(int(cid))
            # Try by name (case-insensitive)
            if channel is None:
                channel = discord.utils.find(
                    lambda c: c.name.lower() == raw.lower() and isinstance(c, discord.TextChannel),
                    ctx.guild.channels,
                )
            if channel is None:
                await ctx.send(
                    f"Channel `{channel_ref}` not found. "
                    f"Use a channel name, `#mention`, or channel ID. "
                    f"Omit the argument to create a new private channel automatically."
                )
                return

        await ctx.send(f"Setting up project `{name}` (agent: **{agent_name}**)...")

        # --- Step 1: Clone or verify repo ---
        repo_path = self.bot.repos_dir / name
        clone_ok, clone_msg = await self.bot._clone_or_verify_repo(repo_url, repo_path)
        if not clone_ok:
            await ctx.send(f"Repo setup failed: {clone_msg}")
            return
        await ctx.send(f"Repo: {clone_msg}")

        # --- Step 2: Create private agent channel (or use provided existing one) ---
        if channel is None:
            guild = ctx.guild
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_webhooks=True,
                ),
            }
            # Grant operator explicit access to their own agent channel
            if self.bot.operator_id:
                operator_member = guild.get_member(self.bot.operator_id)
                if operator_member:
                    overwrites[operator_member] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    )
            try:
                channel = await guild.create_text_channel(
                    name=agent_name.lower(),
                    overwrites=overwrites,
                    topic=f"{agent_name} — agent for {display_name}, managed by Herald",
                )
            except discord.Forbidden:
                await ctx.send("Missing **Manage Channels** permission. Grant it to the Herald bot in server settings.")
                return
            except Exception as e:
                await ctx.send(f"Failed to create channel: {e}")
                return
            await ctx.send(f"Channel: {channel.mention} (private)")
        else:
            await ctx.send(f"Channel: {channel.mention} (existing)")

        # --- Step 3: Create webhook ---
        avatar_bytes: bytes | None = None
        if ctx.message.attachments:
            avatar_bytes = await ctx.message.attachments[0].read()

        webhook_ok = False
        try:
            webhook = await channel.create_webhook(
                name=agent_name,
                avatar=avatar_bytes,
                reason=f"Herald agent webhook for project '{name}'",
            )
            self.bot._save_webhook(name, webhook.url)
            webhook_ok = True
            avatar_note = " with avatar" if avatar_bytes else ""
            await ctx.send(f"Webhook: created{avatar_note}")
        except Exception as e:
            log.exception("Failed to create webhook for '%s'", name)
            await ctx.send(f"Webhook: failed ({e}) — run `!webhook {name}` later to set it up")

        # --- Step 4: Write project YAML ---
        # Default daily task: a morning check-in that ends with a proposal the operator
        # can reply to directly in the channel (conversational flow via on_message).
        default_schedule = [
            {
                "cron": "0 8 * * *",
                "task": (
                    "Read .herald/SOUL.md and .herald/MEMORY.md. Check the recent git log (last 5 commits). "
                    "What is the current state of the project? What is the single most "
                    "important thing to work on next? Post a short status — 2-3 sentences "
                    "— and end with a specific proposal: what you'd do if given the go-ahead. "
                    "Keep it conversational. Wait for a reply before acting."
                ),
            }
        ]

        yaml_data = {
            "name": name,
            "display_name": display_name,
            "agent_name": agent_name,
            "path": str(repo_path),
            "discord_channel_id": str(channel.id),
            "git": {
                "push_requires_approval": True,
                "branch_prefix": f"agent/{name}",
            },
            "schedule": default_schedule,
        }
        yaml_path = self.bot.projects_dir / f"{name}.yaml"
        yaml_path.write_text(yaml.dump(yaml_data, default_flow_style=False, sort_keys=False))
        await ctx.send(f"Config: `projects/{name}.yaml` written")

        # --- Step 5: Hot-reload into active projects (no restart needed) ---
        self.bot.projects[name] = ProjectConfig(**yaml_data)
        # Keep the channel → project map in sync so on_message picks up the new channel
        self.bot._channel_to_project[channel.id] = name
        log.info("Project '%s' added via !addproject, active immediately", name)

        # --- Step 6: Scaffold Herald framework files if missing ---
        project_type = self.bot.projects[name].project_type
        scaffolded = await self.bot._scaffold_project_files(repo_path, display_name, project_type)
        if scaffolded:
            await ctx.send(
                f"Scaffolded: {', '.join(scaffolded)} — template placeholders will be "
                f"filled in during the soul bootstrap."
            )

        await ctx.send(
            f"**`{name}` is ready.** Daily morning check-in scheduled at 8am.\n"
            f"Talk to the agent by posting in {channel.mention}, or use `!run {name} <task>`.\n"
            f"To change the schedule: `!schedule {name} <cron>` or edit the YAML and `!reload`."
        )

        # --- Step 7: Bootstrap soul if missing (don't wait for next restart) ---
        await self.bot._maybe_bootstrap_soul(name, self.bot.projects[name], channel)


class HeraldBot(commands.Bot):
    """
    The main Herald Discord bot.

    Lifecycle:
      1. __init__: set up state and intents
      2. setup_hook: register Cog, start background tasks (queue worker, scheduler)
      3. on_ready: log that we're online
    """

    def __init__(self, projects_dir: Path, herald_root: Path | None = None, operator_id: int | None = None):
        intents = discord.Intents.default()
        # message_content: needed to read the content of !commands
        intents.message_content = True
        # reactions: needed to receive 👍/👎 for git approval
        intents.reactions = True

        super().__init__(command_prefix="!", intents=intents)

        self.projects: dict[str, ProjectConfig] = load_projects(projects_dir)
        self.task_queue = TaskQueue()

        # Stored for !addproject: writing new project YAMLs and cloning repos.
        # repos_dir uses HERALD_ROOT if available (passed via compose.yaml environment),
        # falling back to the projects/ parent directory as a best-guess default.
        self.projects_dir = projects_dir
        self.repos_dir = (herald_root if herald_root else projects_dir.parent) / "repos"

        # Inverted map: channel_id (int) → project_name.
        # Used by the on_message listener to route messages from project channels to
        # their agent without a linear scan through all projects on every message.
        self._channel_to_project: dict[int, str] = {
            int(p.discord_channel_id): name for name, p in self.projects.items()
        }

        # If set, only this Discord user ID can approve/discard push proposals.
        # Sourced from HERALD_OPERATOR_ID env var. None = any server member (not recommended).
        self.operator_id: int | None = operator_id

        # Pending push-approval requests.
        # Maps Discord message_id → {"project_name": str, "branch": str}
        # When the operator reacts, we look up the message here to know what to push/discard.
        self._pending_pushes: dict[int, dict] = {}

        # Webhook URLs for per-agent Discord identity.
        # Maps project_name → webhook URL. Loaded from data/webhooks.json on startup,
        # updated by !webhook command. Persisted via the herald_data named volume.
        self._webhook_urls: dict[str, str] = self._load_webhooks()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """
        Called by discord.py before the bot connects. Start background tasks here.

        We start the queue worker and scheduler here (not in on_ready) so they're
        running before we receive any messages.
        """
        # Register commands — discord.py 2.x requires commands to be in a Cog;
        # methods on the Bot subclass itself are not auto-discovered.
        await self.add_cog(HeraldCommands(self))
        log.info("HeraldCommands cog registered — commands: %s", list(self.all_commands.keys()))

        # Queue worker — runs forever, consuming tasks one at a time
        # Use asyncio.get_event_loop() — self.loop is deprecated in discord.py 2.x
        asyncio.get_event_loop().create_task(
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
        project_names = ", ".join(self.projects.keys()) or "none"
        log.info("Herald is online as %s — projects: %s", self.user, project_names)
        print(f"Herald online as {self.user} | Projects: {project_names}")

        # Optional startup ping — set HERALD_GENERAL_CHANNEL_ID in .env to receive it
        general_channel_id = os.environ.get("HERALD_GENERAL_CHANNEL_ID")
        if general_channel_id:
            channel = self.get_channel(int(general_channel_id))
            if channel:
                n = len(self.projects)
                project_list = f": {project_names}" if self.projects else ""
                await channel.send(
                    f"Herald online — {n} project(s) loaded{project_list}\n"
                    f"Type `!help` for available commands."
                )

        # Check that each project has a .herald/SOUL.md — a project without a soul is just files.
        await self._check_project_souls()

    async def _scaffold_project_files(
        self, repo_path: Path, display_name: str, project_type: str = "solo"
    ) -> list[str]:
        """
        Copy Herald framework template files into a project repo if they don't exist.

        Creates CLAUDE.md at the repo root (Claude Code requires it there) and a .herald/
        directory containing MEMORY.md and humans/ with operator profiles copied from
        Herald's own .herald/humans/ directory — so the new agent knows who they're
        working with from the first bootstrap run.

        Type-specific templates are used when available (templates/<project_type>/);
        falls back to the base templates/ directory if no type-specific variant exists.
        Only touches files that are missing — existing files are never overwritten.

        Commits any newly created files to the repo so they persist.
        Returns a list of file paths that were scaffolded.
        """
        templates_dir = Path(__file__).parent.parent / "templates"
        # Type-specific templates override base templates when present
        type_templates_dir = templates_dir / project_type
        herald_dir = repo_path / ".herald"
        herald_dir.mkdir(exist_ok=True)
        scaffolded: list[str] = []

        # CLAUDE.md stays at the repo root — Claude Code auto-discovers it there.
        # Use type-specific template if available, fall back to base template.
        claude_dest = repo_path / "CLAUDE.md"
        if not claude_dest.exists():
            template_path = type_templates_dir / "CLAUDE.md"
            if not template_path.exists():
                template_path = templates_dir / "CLAUDE.md"
            if template_path.exists():
                content = template_path.read_text().replace("[Project Name]", display_name)
                claude_dest.write_text(content)
                scaffolded.append("CLAUDE.md")

        # MEMORY.md goes into .herald/ — it's a Herald framework file, not a project artifact.
        memory_dest = herald_dir / "MEMORY.md"
        if not memory_dest.exists():
            template_path = type_templates_dir / "MEMORY.md"
            if not template_path.exists():
                template_path = templates_dir / "MEMORY.md"
            if template_path.exists():
                content = template_path.read_text().replace("[Project Name]", display_name)
                memory_dest.write_text(content)
                scaffolded.append(".herald/MEMORY.md")

        # Copy operator profile files from Herald's own .herald/humans/ directory.
        # This ensures every new agent knows who they're working with from day one.
        herald_humans_dir = Path(__file__).parent.parent / ".herald" / "humans"
        humans_dir = herald_dir / "humans"
        if not humans_dir.exists():
            humans_dir.mkdir()
        if herald_humans_dir.is_dir():
            for profile in herald_humans_dir.glob("*.md"):
                dest_profile = humans_dir / profile.name
                if not dest_profile.exists():
                    dest_profile.write_text(profile.read_text())
                    scaffolded.append(f".herald/humans/{profile.name}")
        # If no profiles were copied and the directory is empty, add .gitkeep
        if not any(humans_dir.iterdir()):
            (humans_dir / ".gitkeep").touch()
            scaffolded.append(".herald/humans/.gitkeep")

        if scaffolded:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "add", *scaffolded,
                    cwd=repo_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                proc = await asyncio.create_subprocess_exec(
                    "git", "commit", "-m",
                    "chore: scaffold Herald agent framework files\n\n"
                    "Added by !addproject: CLAUDE.md template, .herald/MEMORY.md template, "
                    ".herald/humans/ (with operator profiles)",
                    cwd=repo_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception as e:
                log.warning("Scaffold commit failed for '%s': %s", repo_path.name, e)

        return scaffolded

    async def _maybe_bootstrap_soul(
        self, name: str, project, channel: discord.TextChannel | None
    ) -> None:
        """
        If a project is missing SOUL.md, post a notice and queue a bootstrap run.

        Called both at startup (for all projects) and immediately after !addproject
        (for the newly registered project). A project without a soul gets generic
        output — the bootstrap gives it an identity, memory, and an introduction.
        """
        soul_path = Path(project.path) / ".herald" / "SOUL.md"
        if soul_path.exists():
            return

        if channel:
            await channel.send(
                f"👻 **`{name}` has no .herald/SOUL.md.** "
                f"Bootstrapping agent soul — I'll introduce myself when ready."
            )
        log.warning("Project '%s' missing .herald/SOUL.md — queuing bootstrap run", name)

        bootstrap_task = (
            "You are a new agent on this project. This is your first run. "
            "Do the following:\n"
            "1. Read CLAUDE.md — it's your project instructions. Fill in any template "
            "placeholders ([...]) with real information based on what you find in the repo.\n"
            "2. Look in the .herald/humans/ directory for any operator profiles — "
            "they tell you how this person works and what they care about.\n"
            "3. Briefly explore the codebase (README, main source files, "
            "package files, any existing docs).\n"
            "4. Write .herald/SOUL.md. Choose a name that fits this project and the people "
            "here — something that reflects the project's character, not just the "
            "first available name from any list. Write your role, your values, "
            "and a personality that reflects how you'll actually work here.\n"
            "5. Update .herald/MEMORY.md Core Memories with what you learned about the "
            "architecture and key decisions. The template sections are already there.\n"
            "6. Post a short introduction: your name, your read on the project, "
            "and what you're here to do. 2-3 sentences. No fluff."
        )

        def make_on_complete(proj_name: str, proj_channel):
            async def on_complete(output: str) -> None:
                chunks = split_for_discord(output)
                for chunk in chunks:
                    await self._post_as_agent(proj_name, chunk, proj_channel)
            return on_complete

        self.task_queue.enqueue(AgentTask(
            project_name=name,
            task=bootstrap_task,
            on_complete=make_on_complete(name, channel),
            label=f"[soul bootstrap] {name}",
            record_activity=False,
        ))

    async def _check_project_souls(self) -> None:
        """
        On startup, check each project for a SOUL.md file and bootstrap any that are missing.
        """
        for name, project in self.projects.items():
            channel = self.get_channel(int(project.discord_channel_id))
            await self._maybe_bootstrap_soul(name, project, channel)

    # -------------------------------------------------------------------------
    # Git push-approval flow
    # -------------------------------------------------------------------------

    async def _check_and_propose_push(
        self, project_name: str, channel: discord.TextChannel
    ) -> int:
        """
        After an agent run, check for unpushed agent/* branches.
        If found, post a push proposal and await the operator's reaction.
        Returns the number of proposals posted (0 if no unpushed branches).
        """
        project = self.projects[project_name]
        if not project.git.push_requires_approval:
            return 0

        # Run sync git ops in a thread pool — they use blocking subprocess and would
        # stall the event loop if called directly from async context.
        unpushed = await asyncio.to_thread(
            get_unpushed_agent_branches, project.path, project.git.branch_prefix
        )

        for item in unpushed:
            branch = item["branch"]
            commits = item["commits"]
            n = len(commits)
            commit_lines = "\n".join(f"• {c}" for c in commits[:10])
            if n > 10:
                commit_lines += f"\n… and {n - 10} more"

            embed = discord.Embed(
                title="Push Proposal",
                color=discord.Color.yellow(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Project", value=f"`{project_name}`", inline=True)
            embed.add_field(name="Branch", value=f"`{branch}`", inline=True)
            embed.add_field(name="Commits", value=str(n), inline=True)
            embed.add_field(
                name="Changes",
                value=f"```\n{commit_lines}\n```",
                inline=False,
            )
            embed.set_footer(text=f"{THUMBS_UP} approve  •  {THUMBS_DOWN} discard")

            msg = await channel.send(embed=embed)
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

        return len(unpushed)

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

        # Only the operator can approve or discard push proposals
        if self.operator_id is not None and payload.user_id != self.operator_id:
            log.warning(
                "Push reaction from non-operator user %d ignored (operator is %d)",
                payload.user_id, self.operator_id,
            )
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
            success, message = await asyncio.to_thread(push_branch, project.path, branch)
            if success:
                embed = discord.Embed(
                    title="Pushed",
                    description=f"`{branch}` → origin",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Project", value=f"`{project_name}`", inline=True)
                if message:
                    embed.add_field(name="Details", value=message, inline=False)
                await channel.send(embed=embed)
                # Auto-deploy if the project is configured for it
                if project.deploy.auto_deploy_on_push and project.deploy.compose_path:
                    await channel.send(f"Auto-deploying `{project_name}`...")
                    await self._enqueue_deploy(project_name, channel)
            else:
                embed = discord.Embed(
                    title="Push Failed",
                    description=f"`{branch}`",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Project", value=f"`{project_name}`", inline=True)
                embed.add_field(
                    name="Error",
                    value=f"```\n{message}\n```" if message else "Unknown error",
                    inline=False,
                )
                await channel.send(embed=embed)
        else:
            success, message = await asyncio.to_thread(delete_branch, project.path, branch)
            embed = discord.Embed(
                title="Branch Discarded",
                description=f"`{branch}` deleted",
                color=discord.Color.dark_grey(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Project", value=f"`{project_name}`", inline=True)
            await channel.send(embed=embed)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _post_as_agent(
        self, project_name: str, content: str, channel: discord.TextChannel
    ) -> discord.Message | discord.WebhookMessage | None:
        """
        Post a message as the project's agent identity. Returns the posted message.

        If the project has a webhook_url configured, posts via that webhook using
        agent_name (or display_name). This makes agent output appear as a distinct
        Discord identity (e.g. "Argent") rather than the Herald bot account.

        Always returns the posted message object — callers can edit it later to
        replace a "thinking..." placeholder with the actual response in-place.

        Falls back to channel.send if no webhook is configured or if the webhook fails.
        """
        project = self.projects[project_name]
        # Prefer dynamically-created webhook (from !webhook command) over static config URL
        webhook_url = self._webhook_urls.get(project_name) or project.webhook_url
        if webhook_url:
            try:
                webhook = discord.Webhook.from_url(webhook_url, client=self)
                username = project.agent_name or project.display_name
                # wait=True returns the WebhookMessage so callers can edit it later
                return await webhook.send(content, username=username, wait=True)
            except Exception:
                log.exception(
                    "Webhook post failed for %s, falling back to bot post", project_name
                )
        return await channel.send(content)

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
            # Herald self-deploy kills the container mid-run — any output we capture is
            # unreliable (usually a spurious "exit code 1" from the killed process). The
            # "I'll go quiet while I restart" ack already sets the right expectation.
            if project_name == "herald":
                return
            # Build output is long; errors appear at the end. Show the tail.
            body = truncate_for_discord(output, from_end=True)
            failed = is_error_output(output)
            embed = discord.Embed(
                title="Deploy Failed" if failed else "Deploy Complete",
                description=f"`{project_name}`",
                color=discord.Color.red() if failed else discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="Output",
                value=f"```\n{body}\n```",
                inline=False,
            )
            await channel.send(embed=embed)

        self.task_queue.enqueue(AgentTask(
            project_name=project_name,
            task=f"[deploy] {project_name}",
            on_complete=on_complete,
            label=f"[deploy] {project_name}",
            run_fn=deploy_run_fn,
            record_activity=False,  # deploys don't count as project activity
        ))
        log.info("Deploy task enqueued for project '%s'", project_name)

    async def _clone_or_verify_repo(self, repo_url: str, repo_path: Path) -> tuple[bool, str]:
        """
        Clone repo_url to repo_path, or verify it already exists.
        Returns (success, message) for confirmation/error reporting.
        """
        if repo_path.exists():
            if (repo_path / ".git").exists():
                return True, f"using existing repo at `{repo_path}`"
            else:
                return False, f"`{repo_path}` exists but is not a git repo"

        repo_path.parent.mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", repo_url, str(repo_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, f"cloned `{repo_url}` to `{repo_path}`"
        else:
            return False, f"git clone failed:\n```\n{result.stderr.strip()}\n```"

    _WEBHOOKS_FILE = Path(os.environ.get("HERALD_DATA_DIR", "data")) / "webhooks.json"

    @staticmethod
    def _load_webhooks() -> dict[str, str]:
        """Load webhook URLs from data/webhooks.json, returning {} if the file doesn't exist."""
        if HeraldBot._WEBHOOKS_FILE.exists():
            try:
                return json.loads(HeraldBot._WEBHOOKS_FILE.read_text())
            except Exception:
                log.warning("Failed to load webhooks file — starting with empty webhook map")
        return {}

    def _save_webhook(self, project_name: str, url: str) -> None:
        """Persist a webhook URL for a project to data/webhooks.json."""
        self._webhook_urls[project_name] = url
        self._WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._WEBHOOKS_FILE.write_text(json.dumps(self._webhook_urls, indent=2))
        log.info("Saved webhook for project '%s'", project_name)

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
