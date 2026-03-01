"""
config.py — Project config loader for Herald.

Each project is defined by a YAML file in the projects/ directory.
Pydantic validates the schema so we get a clear error if a config is malformed
rather than a cryptic KeyError at runtime.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class DeployConfig(BaseModel):
    """Controls how Herald builds and deploys a project's Docker container."""

    # Absolute path to the project's compose.yaml on the host.
    # Herald runs: docker compose -f <compose_path> up --build -d
    # If None, Herald-managed deployment is disabled for this project.
    compose_path: str | None = None

    # If True, Herald automatically triggers a deploy after the operator approves
    # a git push (👍 reaction). If False, deploy only happens via !deploy.
    auto_deploy_on_push: bool = False


class GitConfig(BaseModel):
    """Controls how Herald handles git operations for a project."""

    # If True, the Claude agent is allowed to commit locally during a run.
    # This is always safe — commits are local only until the operator approves a push.
    auto_commit: bool = True

    # If True, Herald posts a push-approval request to Discord before pushing.
    # Operator reacts 👍 to approve or 👎 to discard the branch.
    push_requires_approval: bool = True

    # All agent commits go to branches with this prefix (e.g. agent/enchiridion-20260224-0800)
    branch_prefix: str = "agent/"


class ScheduleEntry(BaseModel):
    """A single cron-triggered task for an agent."""

    # Standard cron expression (5-field: minute hour dom month dow)
    cron: str

    # The task prompt sent to Claude Code via `claude -p "<task>" --print`
    task: str


class ProjectConfig(BaseModel):
    """Full config for one registered project."""

    # Short identifier used in Discord commands: `!run enchiridion <task>`
    name: str

    # Human-readable name shown in Herald messages and status outputs
    display_name: str

    # Absolute path to the project repo on the host (bind-mounted into Herald container)
    path: str

    # Discord channel ID where Herald posts results for this project
    discord_channel_id: str

    # Optional: name the agent uses when posting via webhook (e.g. "Argent").
    # Falls back to display_name if not set.
    agent_name: str | None = None

    # Optional: webhook URL for posting agent results with a custom identity.
    # Create in Discord: channel settings → Integrations → Webhooks → New Webhook.
    # Without this, results are posted by the Herald bot account.
    webhook_url: str | None = None

    # Optional: URL to an image to use as the agent's avatar in webhook posts.
    # If not set, uses the webhook's default avatar (configured in Discord).
    webhook_avatar_url: str | None = None

    git: GitConfig = GitConfig()
    deploy: DeployConfig = DeployConfig()

    # Optional cron-triggered scheduled tasks
    schedule: list[ScheduleEntry] = []

    @field_validator("path")
    @classmethod
    def path_must_exist(cls, v: str) -> str:
        """Fail fast at startup if the project path doesn't exist."""
        p = Path(v)
        if not p.exists():
            raise ValueError(f"Project path does not exist: {v}")
        if not p.is_dir():
            raise ValueError(f"Project path is not a directory: {v}")
        return v


def load_projects(projects_dir: Path) -> dict[str, ProjectConfig]:
    """
    Load all *.yaml files from projects_dir and return a name → ProjectConfig mapping.

    Raises ValueError if any config is invalid or a project name is duplicated.
    """
    if not projects_dir.exists():
        raise FileNotFoundError(f"Projects directory not found: {projects_dir}")

    projects: dict[str, ProjectConfig] = {}

    for yaml_file in sorted(projects_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping in {yaml_file}, got {type(data)}")

        config = ProjectConfig(**data)

        if config.name in projects:
            raise ValueError(
                f"Duplicate project name '{config.name}' in {yaml_file}"
            )

        projects[config.name] = config

    return projects
