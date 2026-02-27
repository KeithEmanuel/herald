"""
activity.py — Activity tracking for Herald's accountability feature.

Records the last time each project had an agent run. Herald's scheduler checks this
daily and posts nudges (or roasts) for projects that have gone quiet.

Data is stored in data/activity.json — a simple JSON file persisted via Docker volume.
Nothing fancy: agent runs are infrequent enough that file I/O is not a bottleneck.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Persisted via Docker volume — see compose.yaml
DATA_DIR = Path("data")
ACTIVITY_FILE = DATA_DIR / "activity.json"

# Inactivity thresholds (days) and their corresponding tone
NUDGE_DAYS = 14    # gentle check-in
DIRECT_DAYS = 21   # direct question: "is this still a priority?"
ROAST_DAYS = 28    # full roast. the operator consented.


def record_activity(project_name: str) -> None:
    """Record that project_name had an agent run right now."""
    DATA_DIR.mkdir(exist_ok=True)
    data = _load()
    data[project_name] = datetime.now(timezone.utc).isoformat()
    ACTIVITY_FILE.write_text(json.dumps(data, indent=2))
    log.debug("Recorded activity for project '%s'", project_name)


def get_last_activity(project_name: str) -> datetime | None:
    """Return the UTC datetime of the last agent run, or None if never run."""
    data = _load()
    ts = data.get(project_name)
    if ts is None:
        return None
    return datetime.fromisoformat(ts)


def days_since_activity(project_name: str) -> float:
    """Return days since last agent run. Returns inf if the project has never run."""
    last = get_last_activity(project_name)
    if last is None:
        return float("inf")
    delta = datetime.now(timezone.utc) - last
    return delta.total_seconds() / 86400


def accountability_message(project_name: str, days: float) -> str | None:
    """
    Return an accountability message for a project that's been inactive for `days` days.
    Returns None if the project is within the acceptable range (< NUDGE_DAYS).

    The tone escalates from gentle to direct to full roast.
    """
    days_int = int(days) if days != float("inf") else "∞"

    if days >= ROAST_DAYS:
        return (
            f"🔥 **{project_name}** — {days_int} days with no activity. "
            f"At this point we're not even in a slow phase, we're in a coma. "
            f"What happened? Be honest. I'm not going anywhere."
        )
    elif days >= DIRECT_DAYS:
        return (
            f"⚠️ **{project_name}** — {days_int} days with no activity. "
            f"Is this still a priority? If the answer is no, that's fine — "
            f"but say so and we can update the roadmap."
        )
    elif days >= NUDGE_DAYS:
        return (
            f"👋 **{project_name}** — quiet for {days_int} days. "
            f"Everything okay? No pressure, just checking in."
        )
    return None


def _load() -> dict:
    """Load the activity JSON file. Returns empty dict if it doesn't exist or is corrupt."""
    if ACTIVITY_FILE.exists():
        try:
            return json.loads(ACTIVITY_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("activity.json is corrupt — resetting to empty")
    return {}
