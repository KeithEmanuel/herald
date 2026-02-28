# Herald

A self-hosted multi-agent orchestration service. Herald runs Claude Code agents across multiple
projects, coordinates token usage, and bridges async communication via Discord.

Each project gets an agent. Herald coordinates them all.

---

## What Herald Does

- **Discord commands** — trigger agent runs on demand: `!run myproject <task>`
- **Cron schedules** — agents run daily reflections, weekly blog posts, or anything you define
- **Push approval** — agents commit locally; you approve pushes via 👍/👎 reaction in Discord
- **Deploys** — Herald runs `docker compose up --build -d` for project containers on approval
- **Accountability** — Herald notices when you go dark on a project and says something
- **Per-agent identity** — each agent posts to Discord with its own name and avatar
- **Soul creation** — Herald checks that each project has a `SOUL.md` and offers to create one

One agent runs at a time, globally. This prevents rate limit collisions and makes token costs predictable.

---

## Prerequisites

- Podman (recommended) or Docker
- A Discord server and bot token
- A Claude subscription (or Anthropic API key)
- Git repos for each project you want to run agents on

**Why Podman?** Herald requires access to the host container runtime socket to deploy project
containers. With Docker, that socket grants root-equivalent access to the host. Podman rootless
scopes that access to a dedicated user — a container escape gets user-level access, not root.
This matters especially if you plan to run agents on public or third-party repos.

---

## Directory Layout

Herald is deployed from a root directory (`HERALD_ROOT`) that is **not** the Herald git repo.
The repo lives inside it, alongside your project repos:

```
HERALD_ROOT/              # e.g. /srv/herald
  compose.yaml            # your deployment config (copy from repos/herald/)
  .env                    # secrets — never committed
  projects/               # private YAML configs, managed by Herald
  repos/
    herald/               # git clone of Herald (what agents edit and redeploy)
    myproject/            # your other project repos
  deployments/            # docker compose stacks for project containers
    myproject/
      compose.yaml
  caddy/                  # optional: only if using Herald's Caddy sidecar
    Caddyfile
```

---

## Quick Start

### 1. Create the deployment root

```bash
mkdir /srv/herald && cd /srv/herald
git clone https://github.com/yourusername/herald repos/herald
cp repos/herald/compose.yaml .
cp repos/herald/.env.example .env
mkdir -p projects deployments
```

### 2. Configure `.env`

```env
DISCORD_TOKEN=your-discord-bot-token
ANTHROPIC_API_KEY=your-anthropic-api-key   # or use Claude subscription auth
HERALD_ROOT=/srv/herald                    # must be absolute
HERALD_OPERATOR_ID=your-discord-user-id   # restricts push approvals to you
```

For Podman rootless, also set:
```env
HERALD_DOCKER_SOCKET=/run/user/1000/podman/podman.sock  # replace 1000 with your UID
```

See `repos/herald/.env.example` for all options.

### 3. Start Herald

```bash
# Podman (recommended)
podman compose up -d
podman compose logs -f herald

# Docker
docker compose up -d
docker compose logs -f herald
```

### 4. Authenticate Claude Code (first time only)

```bash
podman compose exec herald claude   # or docker compose exec
```

Follow the login prompt. Credentials persist across restarts via a named volume.

### 5. Add a project

In Discord:

```
!addproject myproject /srv/herald/repos/myproject
```

Herald creates the Discord channel, sets up the webhook with the agent's avatar, writes the
project config, and hot-reloads — no restart needed, no files to edit.

---

## Discord Setup

### Create the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → give it a name (e.g. "Herald")
3. **Bot** → **Add Bot**
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the bot token → `DISCORD_TOKEN` in `.env`

### Set permissions and invite

1. **OAuth2 → URL Generator**
2. Scopes: `bot`
3. Bot Permissions: `Send Messages`, `Read Messages/View Channels`, `Add Reactions`,
   `Read Message History`, `Attach Files`, `Manage Channels`, `Manage Webhooks`
4. Open the generated URL → invite the bot to your server

---

## Commands

| Command | Description |
|---|---|
| `!addproject <name> <path> [cron]` | Register a new project — creates channel, webhook, config |
| `!run <project> <task>` | Trigger a one-off agent run |
| `!deploy <project>` | Deploy the project's container |
| `!schedule <project> <cron>` | Set or update a project's cron schedule |
| `!reload` | Hot-reload project configs without restarting |
| `!status` | Queue depth and currently running job |
| `!projects` | List registered projects and last-active time |

---

## Git Push Approval Flow

When an agent run completes, Herald checks for unpushed `agent/*` branches:

1. Herald posts: "Ready to push `agent/myproject-20260224-0800` — 3 commits."
2. React 👍 → Herald pushes to origin (and auto-deploys if configured)
3. React 👎 → branch is discarded

Agents do real work — commits, refactors, file edits — without ever pushing to your remote
without your explicit approval.

---

## Project Config

Projects are registered via `!addproject` or by dropping a YAML in `projects/`. See
`projects/example.yaml` for the full schema. Key fields:

```yaml
name: myproject
display_name: "My Project"
path: /srv/herald/repos/myproject    # must be under HERALD_ROOT/repos/
discord_channel_id: "123456789"
agent_avatar: argent.png             # PNG in the project repo root

git:
  push_requires_approval: true

deploy:
  compose_path: /srv/herald/deployments/myproject/compose.yaml
  auto_deploy_on_push: false

schedule:
  - cron: "0 8 * * *"
    task: >
      Read SOUL.md and MEMORY.md. Reflect on project status...
```

---

## Routing (Caddy)

Herald includes an optional Caddy sidecar. When enabled, Caddy runs alongside Herald and
routes traffic to project containers by name on a shared internal network. Uncomment the
`caddy` service in `compose.yaml` and create a `caddy/Caddyfile` (see `caddy/Caddyfile.example`).

If you already run Caddy externally, skip the sidecar and configure your Caddy to route
to project containers via a shared network.

---

## Agent Identity — SOUL.md

Each project should have a `SOUL.md` at its root — a persistent identity file maintained by
the project agent. Herald checks for this on startup and offers to create one if it's missing.

SOUL.md lives in the project's git repo — it survives container restarts, travels across
machines, and evolves via the normal push-approval flow. It's readable by humans.

See `docs/agent-pattern.md` for the full agent identity pattern.

---

## Security

Herald requires access to the container runtime socket. **Use Podman rootless** if possible —
it limits a container escape to user-level access rather than root. See `docs/spec.md` for
the full threat model and Podman setup instructions.

---

## License

MIT
