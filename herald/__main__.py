"""
__main__.py — Herald entry point.

Run with:  python -m herald
           (from repo root, or anywhere after `pip install -e .`)

Loads environment variables from .env if present, then starts the Discord bot.
The bot's setup_hook starts the queue worker and scheduler before the bot connects.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before anything else so env vars are available to all modules
load_dotenv()

# Configure logging — INFO for Herald, WARNING for noisy libraries
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Suppress discord.py's verbose gateway/heartbeat logs
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

log = logging.getLogger("herald")


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN is not set. Set it in .env or the environment.")
        sys.exit(1)

    # Projects directory — default to ./projects relative to the repo root (parent of herald/)
    projects_dir_str = os.environ.get(
        "HERALD_PROJECTS_DIR",
        str(Path(__file__).parent.parent / "projects")
    )
    projects_dir = Path(projects_dir_str)

    if not projects_dir.exists():
        log.error("Projects directory not found: %s", projects_dir)
        sys.exit(1)

    # Import here so env vars are loaded before module-level constants are evaluated
    from .bot import HeraldBot

    # Optional: restrict push approvals to a specific Discord user ID
    operator_id_str = os.environ.get("HERALD_OPERATOR_ID")
    operator_id = int(operator_id_str) if operator_id_str else None
    if operator_id is None:
        log.warning(
            "HERALD_OPERATOR_ID is not set — any server member can approve push proposals. "
            "Set it in .env to restrict approvals to the operator."
        )

    # HERALD_ROOT is the deployment root — used to find repos/ for !addproject cloning.
    # In the container, HERALD_ROOT is passed via compose.yaml environment, matching the
    # host path (same-path invariant: repos are mounted at the same absolute path on both sides).
    herald_root_str = os.environ.get("HERALD_ROOT")
    herald_root = Path(herald_root_str) if herald_root_str else None
    if herald_root is None:
        log.warning(
            "HERALD_ROOT is not set — !addproject will guess repos/ location from projects/ parent. "
            "Set HERALD_ROOT in .env to ensure correct path."
        )

    log.info("Starting Herald — projects dir: %s, herald root: %s", projects_dir, herald_root or "(unset)")
    bot = HeraldBot(projects_dir, herald_root=herald_root, operator_id=operator_id)

    # bot.run() starts the event loop and blocks until the bot disconnects
    bot.run(token)


if __name__ == "__main__":
    main()
