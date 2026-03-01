"""
autonomy.py — Autonomous development mode for Herald.

When enabled on a project, Herald checks daily whether the operator has been
inactive. If all pre-flight checks pass, an agent run is queued to pick one
unchecked roadmap item and implement it. The existing push-approval flow
handles review — nothing ships without a 👍.

Two budget modes (configured in ProjectConfig.autonomous):
  - weekly_minutes (default): wall-clock minutes per ISO week. Simple proxy.
  - weekly_tokens (if > 0): actual API token count (input + output) per ISO week.
    More precise — comes from --output-format json. Takes precedence if set.

Autonomous runs deliberately do NOT update activity.json so they don't interfere
with the accountability tracker (which measures operator engagement, not agent work).
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .activity import days_since_activity

if TYPE_CHECKING:
    from .config import ProjectConfig

log = logging.getLogger(__name__)

# Persisted via Docker volume. Override via HERALD_DATA_DIR env var.
DATA_FILE = Path(os.environ.get("HERALD_DATA_DIR", "data")) / "autonomy.json"

# Default task prompt used when project.autonomous.task is empty.
# Designed to produce one scoped, completable unit of work per session.
DEFAULT_TASK = """\
Read SOUL.md, MEMORY.md, and the project roadmap. Pick ONE unchecked item \
from the roadmap that is actionable and completable in a single session. \
Implement it. Commit your work with a clear message. \
End your response with a short summary: what you built and how to test it. \
Scope tightly — finish one thing completely rather than starting several.\
"""


# ---------------------------------------------------------------------------
# Roadmap detection
# ---------------------------------------------------------------------------

def has_roadmap_items(project_path: str, roadmap_paths: list[str]) -> bool:
    """
    Return True if any roadmap file contains an unchecked item (- [ ]).

    Tries each path in order; returns True on the first match found.
    Returns False if no files exist or all items are checked.
    """
    for rel_path in roadmap_paths:
        full = Path(project_path) / rel_path
        if full.exists():
            try:
                if "- [ ]" in full.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                log.warning("Could not read roadmap file: %s", full)
    return False


# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------

def _load_all() -> dict:
    """Load autonomy.json. Returns empty dict on missing or corrupt file."""
    try:
        return json.loads(DATA_FILE.read_text())
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read %s: %s — starting fresh", DATA_FILE, exc)
        return {}


def _save_all(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _current_week_key() -> str:
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _load_and_normalize(project_name: str) -> dict:
    """
    Load the project's autonomy entry and reset counters if the week or day has rolled over.

    Never raises. Returns a dict with all expected keys populated.
    """
    all_data = _load_all()
    entry = all_data.get(project_name, {})

    week_key = _current_week_key()
    today = date.today().isoformat()

    # Reset weekly counters on ISO week rollover
    if entry.get("week_key") != week_key:
        entry["week_key"] = week_key
        entry["autonomous_minutes"] = 0.0
        entry["autonomous_tokens"] = 0
        entry["runs_this_week"] = 0
        # Also reset daily counters when resetting the week
        entry["runs_today"] = 0
        entry["today_date"] = today

    # Reset daily counter on calendar day rollover (within the same week)
    if entry.get("today_date") != today:
        entry["runs_today"] = 0
        entry["today_date"] = today

    # Ensure all keys exist with safe defaults
    entry.setdefault("autonomous_minutes", 0.0)
    entry.setdefault("autonomous_tokens", 0)
    entry.setdefault("runs_this_week", 0)
    entry.setdefault("runs_today", 0)
    entry.setdefault("last_run_ts", None)

    return entry


def record_run(project_name: str, duration_seconds: float, tokens: int = 0) -> None:
    """
    Record a completed autonomous run. Updates time/token counters and run counts.

    Called from the scheduler's on_complete callback after the agent finishes.

    Args:
        project_name: Project identifier (matches projects/*.yaml name field).
        duration_seconds: Wall-clock seconds the agent ran. Always tracked.
        tokens: API tokens consumed (input + output). 0 if not available.
    """
    all_data = _load_all()
    entry = _load_and_normalize(project_name)

    entry["autonomous_minutes"] = entry["autonomous_minutes"] + duration_seconds / 60.0
    entry["autonomous_tokens"] = entry["autonomous_tokens"] + tokens
    entry["runs_this_week"] = entry["runs_this_week"] + 1
    entry["runs_today"] = entry["runs_today"] + 1
    entry["last_run_ts"] = datetime.now(timezone.utc).isoformat()

    all_data[project_name] = entry
    _save_all(all_data)
    log.info(
        "Autonomous run recorded for '%s': %.1fs, %d tokens (%.1f min / %d tok total this week)",
        project_name,
        duration_seconds,
        tokens,
        entry["autonomous_minutes"],
        entry["autonomous_tokens"],
    )


def get_weekly_stats(project_name: str) -> dict:
    """Return the normalized autonomy entry for display in !autonomy status."""
    return _load_and_normalize(project_name)


# ---------------------------------------------------------------------------
# Pre-flight checklist
# ---------------------------------------------------------------------------

def should_run_autonomous(project: "ProjectConfig") -> tuple[bool, str]:
    """
    Run the pre-flight checklist for an autonomous agent run.

    All checks are local (no API calls). Returns (True, "") if the run should
    proceed, or (False, reason) explaining why it was skipped.

    Checks in order:
    1. autonomous.enabled
    2. SOUL.md exists (project is bootstrapped)
    3. Roadmap has unchecked items
    4. Weekly budget not exhausted (token budget if weekly_tokens > 0, else minutes)
    5. Daily run cap not reached
    6. Min gap between runs satisfied
    7. Operator has NOT been active in the last 24h
       (autonomous runs use record_activity=False, so activity.json only
       reflects operator-initiated runs — this check is meaningful)
    """
    cfg = project.autonomous

    if not cfg.enabled:
        return False, "autonomous mode disabled"

    soul_path = Path(project.path) / "SOUL.md"
    if not soul_path.exists():
        return False, "project has no SOUL.md (run soul bootstrap first)"

    if not has_roadmap_items(project.path, cfg.roadmap_paths):
        return False, "no unchecked roadmap items found"

    data = _load_and_normalize(project.name)

    # Token budget takes precedence over minutes budget when weekly_tokens > 0.
    if cfg.weekly_tokens > 0:
        used_tokens = data["autonomous_tokens"]
        if used_tokens >= cfg.weekly_tokens:
            return False, (
                f"weekly token budget exhausted "
                f"({used_tokens:,} / {cfg.weekly_tokens:,} tokens)"
            )
    else:
        if data["autonomous_minutes"] >= cfg.weekly_minutes:
            return False, (
                f"weekly budget exhausted "
                f"({data['autonomous_minutes']:.0f}m / {cfg.weekly_minutes}m)"
            )

    if data["runs_today"] >= cfg.max_per_day:
        return False, f"daily run cap reached ({cfg.max_per_day}/day)"

    last_ts = data.get("last_run_ts")
    if last_ts:
        last_dt = datetime.fromisoformat(last_ts)
        gap_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
        if gap_hours < cfg.min_gap_hours:
            return False, (
                f"gap too short ({gap_hours:.1f}h < {cfg.min_gap_hours}h required)"
            )

    # Back off if the operator was active in the last 24h.
    days_idle = days_since_activity(project.name)
    if days_idle < 1.0:
        return False, "operator active in last 24h — backing off"

    return True, ""
