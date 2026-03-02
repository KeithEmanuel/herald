"""
tests/test_autonomy.py — Tests for the autonomous development module.

No Discord or Claude Code required. All tests use local file I/O with tmp_path.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from herald import autonomy
from herald.autonomy import (
    DEFAULT_TASK,
    has_roadmap_items,
    record_run,
    get_weekly_stats,
    should_run_autonomous,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_project(tmp_path: Path, enabled: bool = True, **autonomous_kwargs):
    """Build a minimal ProjectConfig-like object with AutonomousConfig."""
    from herald.config import AutonomousConfig, ProjectConfig

    # Ensure .herald/SOUL.md exists by default (most tests want checks to pass it)
    (tmp_path / ".herald").mkdir(exist_ok=True)
    soul = tmp_path / ".herald" / "SOUL.md"
    if not soul.exists():
        soul.write_text("# Soul")

    # Ensure at least one roadmap file with an unchecked item by default
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir(exist_ok=True)
    if not roadmap.exists():
        roadmap.write_text("- [ ] something to do\n")

    autonomous = AutonomousConfig(enabled=enabled, **autonomous_kwargs)
    return ProjectConfig(
        name="testproject",
        display_name="Test Project",
        path=str(tmp_path),
        discord_channel_id="123",
        autonomous=autonomous,
    )


def current_week_key() -> str:
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ---------------------------------------------------------------------------
# has_roadmap_items
# ---------------------------------------------------------------------------

def test_has_roadmap_items_with_unchecked_item(tmp_path):
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir()
    roadmap.write_text("- [x] done\n- [ ] still todo\n")
    assert has_roadmap_items(str(tmp_path), ["docs/roadmap.md"]) is True


def test_has_roadmap_items_all_items_checked(tmp_path):
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir()
    roadmap.write_text("- [x] done\n- [x] also done\n")
    assert has_roadmap_items(str(tmp_path), ["docs/roadmap.md"]) is False


def test_has_roadmap_items_no_roadmap_file(tmp_path):
    assert has_roadmap_items(str(tmp_path), ["docs/roadmap.md"]) is False


def test_has_roadmap_items_uses_fallback_path(tmp_path):
    # Primary path missing; fallback has items
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] fallback item\n")
    assert has_roadmap_items(str(tmp_path), ["docs/roadmap.md", "TODO.md"]) is True


def test_has_roadmap_items_first_match_wins(tmp_path):
    # First file has no unchecked items; second does — should still return True
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir()
    roadmap.write_text("- [x] all checked\n")
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] unchecked\n")
    # Both paths in list — first match with unchecked wins
    assert has_roadmap_items(str(tmp_path), ["docs/roadmap.md", "TODO.md"]) is True


def test_has_roadmap_items_empty_file(tmp_path):
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("")
    assert has_roadmap_items(str(tmp_path), ["ROADMAP.md"]) is False


# ---------------------------------------------------------------------------
# record_run / _load_and_normalize
# ---------------------------------------------------------------------------

def test_record_run_creates_file_if_missing(tmp_path):
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 120.0)

    assert data_file.exists()
    data = json.loads(data_file.read_text())
    assert "myproject" in data
    assert data["myproject"]["autonomous_minutes"] == pytest.approx(2.0)
    assert data["myproject"]["runs_this_week"] == 1
    assert data["myproject"]["runs_today"] == 1


def test_record_run_accumulates_weekly_minutes(tmp_path):
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 300.0)   # 5 min
        record_run("myproject", 600.0)   # 10 min

    data = json.loads(data_file.read_text())
    assert data["myproject"]["autonomous_minutes"] == pytest.approx(15.0)
    assert data["myproject"]["runs_this_week"] == 2


def test_record_run_resets_on_new_iso_week(tmp_path):
    data_file = tmp_path / "autonomy.json"
    # Seed with last week's data
    last_week_iso = datetime.now(timezone.utc) - timedelta(weeks=1)
    iso = last_week_iso.isocalendar()
    old_week_key = f"{iso.year}-W{iso.week:02d}"

    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps({
        "myproject": {
            "week_key": old_week_key,
            "autonomous_minutes": 999.0,
            "runs_this_week": 99,
            "runs_today": 5,
            "today_date": "2000-01-01",
            "last_run_ts": None,
        }
    }))

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 60.0)

    data = json.loads(data_file.read_text())
    assert data["myproject"]["week_key"] == current_week_key()
    # Old week's minutes should be gone
    assert data["myproject"]["autonomous_minutes"] == pytest.approx(1.0)
    assert data["myproject"]["runs_this_week"] == 1


def test_record_run_resets_runs_today_on_new_date(tmp_path):
    data_file = tmp_path / "autonomy.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps({
        "myproject": {
            "week_key": current_week_key(),
            "autonomous_minutes": 10.0,
            "runs_this_week": 2,
            "runs_today": 2,
            "today_date": "2000-01-01",  # stale date
            "last_run_ts": None,
        }
    }))

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 60.0)

    data = json.loads(data_file.read_text())
    # runs_today should reset to 1 (not 3)
    assert data["myproject"]["runs_today"] == 1
    # runs_this_week should continue accumulating
    assert data["myproject"]["runs_this_week"] == 3


# ---------------------------------------------------------------------------
# get_weekly_stats
# ---------------------------------------------------------------------------

def test_get_weekly_stats_empty_project(tmp_path):
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        stats = get_weekly_stats("newproject")

    assert stats["autonomous_minutes"] == 0.0
    assert stats["runs_this_week"] == 0
    assert stats["runs_today"] == 0
    assert stats["last_run_ts"] is None


def test_get_weekly_stats_populated(tmp_path):
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("proj", 180.0)  # 3 min
        stats = get_weekly_stats("proj")

    assert stats["autonomous_minutes"] == pytest.approx(3.0)
    assert stats["runs_this_week"] == 1
    assert stats["last_run_ts"] is not None


# ---------------------------------------------------------------------------
# should_run_autonomous — one test per failing condition + all-pass
# ---------------------------------------------------------------------------

def test_should_run_disabled_returns_false(tmp_path):
    project = make_project(tmp_path, enabled=False)
    with patch.object(autonomy, "DATA_FILE", tmp_path / "autonomy.json"):
        ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "disabled" in reason


def test_should_run_no_soul_md_returns_false(tmp_path):
    project = make_project(tmp_path, enabled=True)
    (tmp_path / ".herald" / "SOUL.md").unlink()  # remove it

    with patch.object(autonomy, "DATA_FILE", tmp_path / "autonomy.json"):
        ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "SOUL.md" in reason


def test_should_run_no_roadmap_items_returns_false(tmp_path):
    project = make_project(tmp_path, enabled=True)
    # Overwrite the roadmap with all-checked items
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.write_text("- [x] all done\n")

    with patch.object(autonomy, "DATA_FILE", tmp_path / "autonomy.json"):
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "roadmap" in reason


def test_should_run_budget_exhausted_returns_false(tmp_path):
    data_file = tmp_path / "autonomy.json"
    project = make_project(tmp_path, enabled=True, weekly_minutes=10)

    with patch.object(autonomy, "DATA_FILE", data_file):
        # Use up the budget
        record_run("testproject", 601.0)  # 10.01 minutes > 10 minute budget
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "budget" in reason.lower() or "exhausted" in reason.lower()


def test_should_run_daily_cap_reached_returns_false(tmp_path):
    data_file = tmp_path / "autonomy.json"
    project = make_project(tmp_path, enabled=True, max_per_day=1, min_gap_hours=0)

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("testproject", 60.0)  # first run today
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "cap" in reason or "daily" in reason


def test_should_run_gap_too_short_returns_false(tmp_path):
    data_file = tmp_path / "autonomy.json"
    project = make_project(tmp_path, enabled=True, min_gap_hours=24, max_per_day=99)

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("testproject", 60.0)  # last run just now
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "gap" in reason


def test_should_run_operator_active_returns_false(tmp_path):
    project = make_project(tmp_path, enabled=True)

    with patch.object(autonomy, "DATA_FILE", tmp_path / "autonomy.json"):
        # days_since_activity < 1 means operator was active recently
        with patch("herald.autonomy.days_since_activity", return_value=0.5):
            ok, reason = should_run_autonomous(project)
    assert ok is False
    assert "operator" in reason or "active" in reason


def test_should_run_all_checks_pass_returns_true(tmp_path):
    project = make_project(tmp_path, enabled=True, min_gap_hours=0)

    with patch.object(autonomy, "DATA_FILE", tmp_path / "autonomy.json"):
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)
    assert ok is True
    assert reason == ""


def test_default_task_is_nonempty():
    """DEFAULT_TASK must be a non-empty string."""
    assert isinstance(DEFAULT_TASK, str)
    assert len(DEFAULT_TASK.strip()) > 20


# ---------------------------------------------------------------------------
# Token tracking in record_run
# ---------------------------------------------------------------------------

def test_record_run_tracks_tokens(tmp_path):
    """record_run should persist tokens in autonomous_tokens."""
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 120.0, tokens=5000)

    data = json.loads(data_file.read_text())
    assert data["myproject"]["autonomous_tokens"] == 5000


def test_record_run_accumulates_tokens(tmp_path):
    """Multiple record_run calls should accumulate autonomous_tokens."""
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 60.0, tokens=3000)
        record_run("myproject", 60.0, tokens=7000)

    data = json.loads(data_file.read_text())
    assert data["myproject"]["autonomous_tokens"] == 10_000


def test_record_run_defaults_tokens_to_zero(tmp_path):
    """record_run without tokens argument should set autonomous_tokens to 0."""
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("myproject", 120.0)  # no tokens arg

    data = json.loads(data_file.read_text())
    assert data["myproject"]["autonomous_tokens"] == 0


def test_get_weekly_stats_includes_autonomous_tokens(tmp_path):
    """get_weekly_stats must include autonomous_tokens key."""
    data_file = tmp_path / "autonomy.json"
    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("proj", 60.0, tokens=1234)
        stats = get_weekly_stats("proj")

    assert "autonomous_tokens" in stats
    assert stats["autonomous_tokens"] == 1234


# ---------------------------------------------------------------------------
# should_run_autonomous — token budget check
# ---------------------------------------------------------------------------

def test_should_run_token_budget_exhausted_returns_false(tmp_path):
    """When weekly_tokens > 0 and autonomous_tokens >= weekly_tokens, block the run."""
    from herald.config import AutonomousConfig, ProjectConfig

    data_file = tmp_path / "autonomy.json"

    # Set up a project with token budget of 1000
    (tmp_path / ".herald").mkdir(exist_ok=True)
    soul = tmp_path / ".herald" / "SOUL.md"
    soul.write_text("# Soul")
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir(exist_ok=True)
    roadmap.write_text("- [ ] something to do\n")

    project = ProjectConfig(
        name="tokproj",
        display_name="Token Project",
        path=str(tmp_path),
        discord_channel_id="1",
        autonomous=AutonomousConfig(enabled=True, weekly_tokens=1000, min_gap_hours=0),
    )

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("tokproj", 60.0, tokens=1001)  # exceeds budget
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)

    assert ok is False
    assert "token" in reason.lower() or "budget" in reason.lower()


def test_should_run_token_budget_passes_when_under_limit(tmp_path):
    """When weekly_tokens > 0 and autonomous_tokens < weekly_tokens, allow the run."""
    from herald.config import AutonomousConfig, ProjectConfig

    data_file = tmp_path / "autonomy.json"

    (tmp_path / ".herald").mkdir(exist_ok=True)
    soul = tmp_path / ".herald" / "SOUL.md"
    soul.write_text("# Soul")
    roadmap = tmp_path / "docs" / "roadmap.md"
    roadmap.parent.mkdir(exist_ok=True)
    roadmap.write_text("- [ ] something to do\n")

    project = ProjectConfig(
        name="tokproj2",
        display_name="Token Project 2",
        path=str(tmp_path),
        discord_channel_id="2",
        autonomous=AutonomousConfig(
            enabled=True, weekly_tokens=10_000, min_gap_hours=0, max_per_day=99
        ),
    )

    with patch.object(autonomy, "DATA_FILE", data_file):
        record_run("tokproj2", 60.0, tokens=100)  # well under budget
        with patch("herald.autonomy.days_since_activity", return_value=999.0):
            ok, reason = should_run_autonomous(project)

    assert ok is True
    assert reason == ""
