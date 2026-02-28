"""
tests/test_config.py — Tests for project config loading and validation.

No Discord or Claude Code required.
"""

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import DeployConfig, GitConfig, ProjectConfig, ScheduleEntry, load_projects


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path: Path, name: str, content: str) -> Path:
    """Write a YAML file to tmp_path and return its path."""
    f = tmp_path / f"{name}.yaml"
    f.write_text(textwrap.dedent(content))
    return f


def minimal_yaml(tmp_path: Path, name: str = "myproject") -> str:
    """Return a minimal valid project YAML using tmp_path as the project path."""
    return f"""\
        name: {name}
        display_name: "My Project"
        path: {tmp_path}
        discord_channel_id: "123456789"
    """


# ---------------------------------------------------------------------------
# ProjectConfig validation
# ---------------------------------------------------------------------------

def test_valid_config_loads(tmp_path):
    config = ProjectConfig(
        name="myproject",
        display_name="My Project",
        path=str(tmp_path),
        discord_channel_id="123456789",
    )
    assert config.name == "myproject"
    assert config.display_name == "My Project"
    assert config.path == str(tmp_path)
    assert config.discord_channel_id == "123456789"


def test_defaults_are_correct(tmp_path):
    config = ProjectConfig(
        name="p",
        display_name="P",
        path=str(tmp_path),
        discord_channel_id="1",
    )
    # Git defaults
    assert config.git.auto_commit is True
    assert config.git.push_requires_approval is True
    assert config.git.branch_prefix == "agent/"

    # Deploy defaults
    assert config.deploy.compose_path is None
    assert config.deploy.auto_deploy_on_push is False

    # No schedule by default
    assert config.schedule == []


def test_missing_name_raises():
    with pytest.raises((ValidationError, TypeError)):
        ProjectConfig(
            display_name="P",
            path="/tmp",
            discord_channel_id="1",
        )


def test_missing_display_name_raises():
    with pytest.raises((ValidationError, TypeError)):
        ProjectConfig(
            name="p",
            path="/tmp",
            discord_channel_id="1",
        )


def test_missing_discord_channel_id_raises():
    with pytest.raises((ValidationError, TypeError)):
        ProjectConfig(
            name="p",
            display_name="P",
            path="/tmp",
        )


def test_nonexistent_path_raises():
    with pytest.raises(ValidationError, match="does not exist"):
        ProjectConfig(
            name="p",
            display_name="P",
            path="/this/path/definitely/does/not/exist/herald/test",
            discord_channel_id="1",
        )


def test_path_that_is_a_file_raises(tmp_path):
    f = tmp_path / "notadir.txt"
    f.write_text("hello")
    with pytest.raises(ValidationError, match="not a directory"):
        ProjectConfig(
            name="p",
            display_name="P",
            path=str(f),
            discord_channel_id="1",
        )


def test_git_config_overrides(tmp_path):
    config = ProjectConfig(
        name="p",
        display_name="P",
        path=str(tmp_path),
        discord_channel_id="1",
        git={"auto_commit": False, "push_requires_approval": False, "branch_prefix": "ci/"},
    )
    assert config.git.auto_commit is False
    assert config.git.push_requires_approval is False
    assert config.git.branch_prefix == "ci/"


def test_deploy_config_overrides(tmp_path):
    config = ProjectConfig(
        name="p",
        display_name="P",
        path=str(tmp_path),
        discord_channel_id="1",
        deploy={"compose_path": "/srv/myproject/compose.yaml", "auto_deploy_on_push": True},
    )
    assert config.deploy.compose_path == "/srv/myproject/compose.yaml"
    assert config.deploy.auto_deploy_on_push is True


def test_schedule_entries_parse(tmp_path):
    config = ProjectConfig(
        name="p",
        display_name="P",
        path=str(tmp_path),
        discord_channel_id="1",
        schedule=[
            {"cron": "0 8 * * *", "task": "Read SOUL.md"},
            {"cron": "0 9 * * 1", "task": "Write blog post"},
        ],
    )
    assert len(config.schedule) == 2
    assert config.schedule[0].cron == "0 8 * * *"
    assert config.schedule[1].task == "Write blog post"


# ---------------------------------------------------------------------------
# load_projects()
# ---------------------------------------------------------------------------

def test_load_projects_returns_dict(tmp_path):
    write_yaml(tmp_path, "alpha", minimal_yaml(tmp_path, "alpha"))
    projects = load_projects(tmp_path)
    assert "alpha" in projects
    assert isinstance(projects["alpha"], ProjectConfig)


def test_load_multiple_projects(tmp_path):
    # Create two separate project directories so path validation passes
    path_a = tmp_path / "repo_a"
    path_a.mkdir()
    path_b = tmp_path / "repo_b"
    path_b.mkdir()

    yaml_dir = tmp_path / "projects"
    yaml_dir.mkdir()

    write_yaml(yaml_dir, "alpha", f"""\
        name: alpha
        display_name: Alpha
        path: {path_a}
        discord_channel_id: "111"
    """)
    write_yaml(yaml_dir, "beta", f"""\
        name: beta
        display_name: Beta
        path: {path_b}
        discord_channel_id: "222"
    """)

    projects = load_projects(yaml_dir)
    assert set(projects.keys()) == {"alpha", "beta"}


def test_load_projects_skips_example_yaml(tmp_path):
    """example.yaml in the projects dir should still load if it has valid content,
    but in practice operators won't have a real path for it — this just ensures
    the loader doesn't special-case the filename."""
    # We test that it loads fine with a real path
    write_yaml(tmp_path, "example", minimal_yaml(tmp_path, "example"))
    projects = load_projects(tmp_path)
    assert "example" in projects


def test_duplicate_project_name_raises(tmp_path):
    path_a = tmp_path / "repo_a"
    path_a.mkdir()
    yaml_dir = tmp_path / "projects"
    yaml_dir.mkdir()

    # Two files, same project name
    write_yaml(yaml_dir, "first", f"""\
        name: same
        display_name: First
        path: {path_a}
        discord_channel_id: "1"
    """)
    write_yaml(yaml_dir, "second", f"""\
        name: same
        display_name: Second
        path: {path_a}
        discord_channel_id: "2"
    """)

    with pytest.raises(ValueError, match="Duplicate project name"):
        load_projects(yaml_dir)


def test_missing_projects_dir_raises(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        load_projects(nonexistent)


def test_empty_projects_dir_returns_empty_dict(tmp_path):
    projects = load_projects(tmp_path)
    assert projects == {}


def test_invalid_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(": this is not valid: yaml: [")
    with pytest.raises(Exception):  # yaml.YAMLError or ValidationError
        load_projects(tmp_path)
