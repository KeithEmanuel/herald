FROM python:3.12-slim

WORKDIR /app

# Install system dependencies in one layer:
#   - Node.js (22.x via NodeSource) — required for Claude Code CLI
#   - git — agent runs commit to local branches
#   - Docker CLI + Compose plugin — Herald uses these to build/deploy project containers
#     via the socket bind mount (see compose.yaml). CLI only — no daemon in this image.
#     Works with both Docker (/var/run/docker.sock) and Podman rootless (via
#     HERALD_DOCKER_SOCKET in .env — Podman provides a Docker-compatible API).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally.
# This is the core agent runtime — all project agents run via `claude -p <task> --print`.
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies first (layer cache — deps change less often than code)
COPY pyproject.toml .
RUN pip install --no-cache-dir "."

# Copy Herald source code
COPY . .

# The projects/ directory and repo bind-mounts are injected via compose.yaml volumes.
# Nothing in the image needs to know about specific project paths at build time.

CMD ["python", "__main__.py"]
