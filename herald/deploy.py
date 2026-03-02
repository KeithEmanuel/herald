"""
deploy.py — Container compose deployment for Herald-managed project containers.

Herald deploys project containers in two steps:
  1. <HERALD_COMPOSE_CMD> -f <compose_path> build        — build new image
  2. <HERALD_COMPOSE_CMD> -f <compose_path> up -d --no-build  — start containers

The two-step split matters for self-deployment (!deploy herald). When Herald
deploys itself, step 2 kills Herald's process before the new container can start.
Step 1 completes cleanly so the new image is ready. A host-side watchdog
(watchdog.sh + systemd) then detects Herald is down and runs `podman compose up -d`
which picks up the newly built image and starts it.

HERALD_COMPOSE_CMD controls which compose implementation is used:
  - "docker compose"  (default) — Docker CLI with compose plugin
  - "podman compose"             — Podman with compose plugin

When using Podman rootless, keep HERALD_COMPOSE_CMD as "docker compose" — the
Docker CLI in the Herald image talks to the Podman socket mounted at
/var/run/docker.sock via Podman's Docker-compatible API.

Projects opt into Herald-managed deployment by setting deploy.compose_path in
their project YAML. Without it, this module is never called.
"""

import asyncio
import logging
import os
import shlex

log = logging.getLogger(__name__)

# Which compose command to use. Split on whitespace so both "docker compose"
# and "podman compose" work as multi-word commands.
_COMPOSE_CMD = shlex.split(os.environ.get("HERALD_COMPOSE_CMD", "docker compose"))

# Timeout for the build step. Image builds can be slow on first run.
BUILD_TIMEOUT_SECONDS = 300  # 5 minutes
# Timeout for the up step (image is already built — this should be fast).
UP_TIMEOUT_SECONDS = 60


async def _run_compose(cmd: list[str], timeout: int) -> str:
    """Run a compose command and return merged stdout+stderr. Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge: build progress goes to stderr
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"[TIMEOUT] Command exceeded {timeout}s and was killed."

        output = stdout.decode(errors="replace").strip()
        if proc.returncode != 0:
            return f"[ERROR — exit code {proc.returncode}]\n{output}"
        return output

    except FileNotFoundError:
        cmd_str = " ".join(_COMPOSE_CMD)
        return (
            f"[ERROR] `{cmd_str}` not found. "
            f"Set HERALD_COMPOSE_CMD in .env (e.g. 'docker compose'). "
            f"Also ensure HERALD_DOCKER_SOCKET is set in .env."
        )
    except Exception as e:
        return f"[ERROR] Unexpected exception: {type(e).__name__}: {e}"


async def deploy_project(compose_path: str) -> str:
    """
    Build and start containers for the given compose file.

    Step 1: build — runs `compose build` to create the new image. Herald stays
    alive through this. The build output is returned if step 2 fails.

    Step 2: up — runs `compose up -d --no-build` to start containers. For
    self-deploys (deploying Herald itself), this kills Herald's process before
    the new container starts. The host-side watchdog handles the recovery.

    Returns output as a string. Never raises.
    """
    build_cmd = [*_COMPOSE_CMD, "-f", compose_path, "build"]
    build_output = await _run_compose(build_cmd, BUILD_TIMEOUT_SECONDS)

    if build_output.startswith(("[ERROR", "[TIMEOUT")):
        return build_output

    # Step 2: recreate and start containers with the newly built image.
    # For self-deploys, this kills Herald — the watchdog restarts it.
    up_cmd = [*_COMPOSE_CMD, "-f", compose_path, "up", "-d", "--no-build"]
    up_output = await _run_compose(up_cmd, UP_TIMEOUT_SECONDS)

    if up_output.startswith(("[ERROR", "[TIMEOUT")):
        return f"Build OK. Start failed:\n{up_output}"

    return up_output or "Deploy complete — containers are up."
