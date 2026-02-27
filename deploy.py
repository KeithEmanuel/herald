"""
deploy.py — Docker Compose deployment for Herald-managed project containers.

Herald deploys project containers by running:
  docker compose -f <compose_path> up --build -d

The Docker CLI must be installed in the Herald container (see Dockerfile) and
/var/run/docker.sock must be mounted (see compose.yaml) so Herald can talk to
the host Docker daemon.

Projects opt into Herald-managed deployment by setting deploy.compose_path in
their project YAML. Without it, this module is never called.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

# Timeout for docker compose up --build -d. Image builds can be slow on first run.
DEPLOY_TIMEOUT_SECONDS = 300  # 5 minutes


async def deploy_project(compose_path: str) -> str:
    """
    Run `docker compose -f <compose_path> up --build -d`.

    stdout and stderr are merged into a single stream — docker compose writes
    build progress to stderr, which is the interesting part.

    Returns output as a string. Never raises — errors are embedded in the return
    value so the queue worker can forward them to Discord without crashing.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", compose_path, "up", "--build", "-d",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge: build progress goes to stderr
        )

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=DEPLOY_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"[TIMEOUT] Deploy exceeded {DEPLOY_TIMEOUT_SECONDS}s and was killed."

        output = stdout.decode(errors="replace").strip()

        if proc.returncode != 0:
            return f"[ERROR — exit code {proc.returncode}]\n{output}"

        return output or "Deploy complete — containers are up."

    except FileNotFoundError:
        return (
            "[ERROR] `docker` command not found. "
            "Is Docker CLI installed in the Herald container? "
            "Check the Dockerfile and ensure /var/run/docker.sock is mounted."
        )
    except Exception as e:
        return f"[ERROR] Unexpected exception during deploy: {type(e).__name__}: {e}"
