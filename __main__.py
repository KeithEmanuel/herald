"""
__main__.py — Herald entry point.

Run with:  python -m herald
           (from the herald/ directory, or with PYTHONPATH set to herald/)

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

    # Projects directory — default to ./projects relative to this file
    projects_dir_str = os.environ.get("HERALD_PROJECTS_DIR", str(Path(__file__).parent / "projects"))
    projects_dir = Path(projects_dir_str)

    if not projects_dir.exists():
        log.error("Projects directory not found: %s", projects_dir)
        sys.exit(1)

    # Import here so env vars are loaded before module-level constants are evaluated
    from bot import HeraldBot

    log.info("Starting Herald — projects dir: %s", projects_dir)
    bot = HeraldBot(projects_dir)

    # bot.run() starts the event loop and blocks until the bot disconnects
    bot.run(token)


if __name__ == "__main__":
    main()
