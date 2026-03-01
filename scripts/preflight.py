#!/usr/bin/env python3
"""
scripts/preflight.py — Herald pre-deployment connectivity and permissions check.

Run this before starting Herald (locally or in Docker) to catch config problems early.
It checks:
  - Required env vars are set
  - Claude Code CLI is installed and reachable
  - Discord bot token is valid
  - Each registered project's channel exists and has the required permissions
  - HERALD_OPERATOR_ID resolves to a real user

Usage:
    python scripts/preflight.py
    # or from Herald root:
    python -m scripts.preflight

Exits 0 if all checks pass, 1 if any required check fails.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import discord
from dotenv import load_dotenv

from herald.config import load_projects

load_dotenv()

# ANSI colours for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

PASS = f"{GREEN}✓{RESET}"
WARN = f"{YELLOW}!{RESET}"
FAIL = f"{RED}✗{RESET}"


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def warn(msg: str) -> None:
    print(f"  {WARN} {YELLOW}{msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {FAIL} {RED}{msg}{RESET}")


# ---------------------------------------------------------------------------
# Env var checks (no network needed)
# ---------------------------------------------------------------------------

def check_env() -> bool:
    print(f"\n{BOLD}Environment variables{RESET}")
    passed = True

    token = os.environ.get("DISCORD_TOKEN")
    if token:
        ok(f"DISCORD_TOKEN is set ({token[:8]}…)")
    else:
        fail("DISCORD_TOKEN is not set — Herald cannot connect to Discord")
        passed = False

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        ok(f"ANTHROPIC_API_KEY is set ({api_key[:8]}…)")
    else:
        # Not fatal if using subscription auth, but warn
        warn("ANTHROPIC_API_KEY is not set — agent runs will use Claude subscription auth (claude login)")

    operator_id = os.environ.get("HERALD_OPERATOR_ID")
    if operator_id:
        try:
            int(operator_id)
            ok(f"HERALD_OPERATOR_ID is set ({operator_id})")
        except ValueError:
            fail(f"HERALD_OPERATOR_ID is set but not a valid integer: {operator_id!r}")
            passed = False
    else:
        warn("HERALD_OPERATOR_ID is not set — any server member can approve push proposals")

    return passed


# ---------------------------------------------------------------------------
# Claude CLI check
# ---------------------------------------------------------------------------

def check_claude_cli() -> bool:
    print(f"\n{BOLD}Claude Code CLI{RESET}")
    claude_bin = os.environ.get("HERALD_CLAUDE_BIN", "claude")

    try:
        result = subprocess.run(
            [claude_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            ok(f"claude CLI found: {version}")
            return True
        else:
            fail(f"claude CLI returned exit code {result.returncode}: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        fail(f"claude CLI not found on PATH (looking for: {claude_bin!r})")
        fail("Install Claude Code: https://claude.ai/code")
        return False
    except subprocess.TimeoutExpired:
        fail("claude --version timed out after 10s")
        return False


# ---------------------------------------------------------------------------
# Project config check (no network needed)
# ---------------------------------------------------------------------------

def check_projects(projects_dir: Path) -> dict:
    print(f"\n{BOLD}Project configs{RESET}")

    if not projects_dir.exists():
        fail(f"Projects directory not found: {projects_dir}")
        return {}

    try:
        projects = load_projects(projects_dir)
    except Exception as e:
        fail(f"Failed to load projects: {e}")
        return {}

    if not projects:
        warn(f"No project YAML files found in {projects_dir}")
        return {}

    ok(f"Loaded {len(projects)} project(s): {', '.join(projects.keys())}")

    for name, project in projects.items():
        path = Path(project.path)
        if path.exists():
            ok(f"  [{name}] path exists: {project.path}")
        else:
            warn(f"  [{name}] path not found: {project.path} (may be correct if this is a container path)")

        if project.discord_channel_id in ("REPLACE_WITH_CHANNEL_ID", "YOUR_CHANNEL_ID_HERE", ""):
            fail(f"  [{name}] discord_channel_id is a placeholder — update projects/{name}.yaml")
        else:
            ok(f"  [{name}] discord_channel_id: {project.discord_channel_id}")

    return projects


# ---------------------------------------------------------------------------
# Discord connectivity and permissions check
# ---------------------------------------------------------------------------

# Permissions Herald needs in each project channel
REQUIRED_PERMISSIONS = [
    ("view_channel",       "View Channel",           True),
    ("send_messages",      "Send Messages",           True),
    ("read_message_history", "Read Message History", True),
    ("add_reactions",      "Add Reactions",           True),
    ("attach_files",       "Attach Files",            True),
    ("manage_webhooks",    "Manage Webhooks",         True),   # for per-agent webhook creation
]

# Permissions needed at the guild (server) level
REQUIRED_GUILD_PERMISSIONS = [
    ("manage_channels",    "Manage Channels",         False),  # for !addproject channel creation (warn only)
]


class PreflightBot(discord.Client):
    def __init__(self, projects: dict, operator_id: int | None):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.projects = projects
        self.operator_id = operator_id
        self.all_passed = True

    async def on_ready(self) -> None:
        print(f"\n{BOLD}Discord connectivity{RESET}")
        ok(f"Connected as {self.user} (ID: {self.user.id})")

        guilds = self.guilds
        if not guilds:
            fail("Bot is not in any Discord server — invite it first")
            self.all_passed = False
            await self.close()
            return

        ok(f"Bot is in {len(guilds)} server(s): {', '.join(g.name for g in guilds)}")

        # Check guild-level permissions
        print(f"\n{BOLD}Guild permissions{RESET}")
        for guild in guilds:
            me = guild.me
            guild_perms = me.guild_permissions
            for perm_attr, perm_name, required in REQUIRED_GUILD_PERMISSIONS:
                has_perm = getattr(guild_perms, perm_attr, False)
                if has_perm:
                    ok(f"  [{guild.name}] {perm_name}")
                elif required:
                    fail(f"  [{guild.name}] {perm_name} — MISSING (required)")
                    self.all_passed = False
                else:
                    warn(f"  [{guild.name}] {perm_name} — missing (needed for !addproject)")

        # Check operator ID
        if self.operator_id:
            print(f"\n{BOLD}Operator check{RESET}")
            found = False
            for guild in guilds:
                member = guild.get_member(self.operator_id)
                if member:
                    ok(f"Operator found: {member.display_name} ({self.operator_id}) in {guild.name}")
                    found = True
                    break
            if not found:
                warn(f"HERALD_OPERATOR_ID {self.operator_id} not found in any server member list")

        # Check each project channel
        print(f"\n{BOLD}Project channels{RESET}")
        for project_name, project in self.projects.items():
            channel_id_str = project.discord_channel_id
            if channel_id_str in ("REPLACE_WITH_CHANNEL_ID", "YOUR_CHANNEL_ID_HERE", ""):
                fail(f"  [{project_name}] skipped — channel ID is a placeholder")
                self.all_passed = False
                continue

            try:
                channel_id = int(channel_id_str)
            except ValueError:
                fail(f"  [{project_name}] invalid channel ID: {channel_id_str!r}")
                self.all_passed = False
                continue

            channel = self.get_channel(channel_id)
            if channel is None:
                fail(f"  [{project_name}] channel {channel_id} not found — wrong ID or bot lacks access")
                self.all_passed = False
                continue

            ok(f"  [{project_name}] found channel: #{channel.name} in {channel.guild.name}")

            # Check permissions in this specific channel
            me = channel.guild.me
            perms = channel.permissions_for(me)
            channel_ok = True
            for perm_attr, perm_name, required in REQUIRED_PERMISSIONS:
                has_perm = getattr(perms, perm_attr, False)
                if has_perm:
                    ok(f"    {perm_name}")
                elif required:
                    fail(f"    {perm_name} — MISSING (required)")
                    self.all_passed = False
                    channel_ok = False
                else:
                    warn(f"    {perm_name} — missing (optional)")

        await self.close()

    async def on_error(self, event: str, *args, **kwargs) -> None:
        print(f"\n{RED}Discord error in {event}: {args}{RESET}")
        self.all_passed = False
        await self.close()


async def check_discord(token: str, projects: dict, operator_id: int | None) -> bool:
    print(f"\n{BOLD}Discord connection{RESET}")
    print(f"  Connecting…", end="", flush=True)
    try:
        bot = PreflightBot(projects, operator_id)
        await bot.start(token)
        return bot.all_passed
    except discord.LoginFailure:
        print()
        fail("Discord login failed — DISCORD_TOKEN is invalid or expired")
        return False
    except Exception as e:
        print()
        fail(f"Discord connection failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    print(f"{BOLD}Herald preflight check{RESET}")
    print("=" * 40)

    all_passed = True

    # Env vars
    if not check_env():
        all_passed = False

    # Claude CLI
    if not check_claude_cli():
        all_passed = False

    # Project configs
    projects_dir_str = os.environ.get("HERALD_PROJECTS_DIR", str(Path(__file__).parent.parent / "projects"))
    projects_dir = Path(projects_dir_str)
    projects = check_projects(projects_dir)
    if not projects:
        all_passed = False

    # Discord (only if we have a token)
    token = os.environ.get("DISCORD_TOKEN")
    operator_id_str = os.environ.get("HERALD_OPERATOR_ID")
    operator_id = int(operator_id_str) if operator_id_str else None

    if token:
        discord_ok = await check_discord(token, projects, operator_id)
        if not discord_ok:
            all_passed = False
    else:
        warn("Skipping Discord checks — DISCORD_TOKEN not set")

    # Summary
    print(f"\n{'=' * 40}")
    if all_passed:
        print(f"{GREEN}{BOLD}All checks passed. Herald is ready to run.{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}Some checks failed. Fix the issues above before running Herald.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
