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
- **Soul creation** — Herald checks that each project has a SOUL.md and offers to create one if not

One agent runs at a time, globally. This prevents rate limit collisions and makes token costs predictable.

---

## Prerequisites

- Docker and Docker Compose
- A Discord server and bot token
- A Claude subscription (or Anthropic API key)
- Git repos for each project you want to run agents on

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/yourusername/herald.git
cd herald
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your-discord-bot-token
ANTHROPIC_API_KEY=your-anthropic-api-key   # or use Claude subscription auth
```

### 2. Start Herald

```bash
docker compose up -d
docker compose logs -f herald
```

### 3. Authenticate Claude Code (first time only)

```bash
docker compose exec herald claude
```

Follow the login prompt. Credentials persist via Docker named volume across restarts.

### 4. Add a project

In Discord:

```
!addproject myproject /path/to/repo
```

Herald creates the Discord channel, sets up the webhook with the agent's avatar, writes the
project config, and hot-reloads — no restart needed, no files to edit.

---

## Discord Setup

### Create the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g. "Herald")
3. Go to **Bot** → click **Add Bot**
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the bot token — this is your `DISCORD_TOKEN`

### Set permissions and invite

1. Go to **OAuth2 → URL Generator**
2. Scopes: `bot`
3. Bot Permissions: `Send Messages`, `Read Messages/View Channels`, `Add Reactions`,
   `Read Message History`, `Attach Files`, `Manage Channels`, `Manage Webhooks`
4. Open the generated URL and invite the bot to your server

---

## Commands

| Command | Description |
|---|---|
| `!addproject <name> <path> [cron]` | Register a new project — creates channel, webhook, config |
| `!run <project> <task>` | Trigger a one-off agent run |
| `!deploy <project>` | Deploy the project's Docker container |
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

Agents can do real work — commits, refactors, file edits — without ever pushing to your
remote without your explicit approval.

---

## Project Config

Projects are registered via `!addproject` or by dropping a YAML in `projects/`. See
`projects/example.yaml` for the full schema with comments. Key fields:

```yaml
name: myproject
display_name: "My Project"
path: /repos/myproject             # absolute path inside the Herald container
discord_channel_id: "123456789"
agent_avatar: argent.png           # PNG in the project repo root

git:
  push_requires_approval: true

deploy:
  compose_path: /path/to/deployments/myproject/compose.yaml
  auto_deploy_on_push: false

schedule:
  - cron: "0 8 * * *"
    task: >
      Read SOUL.md and MEMORY.md. Reflect on project status...
```

---

## Agent Identity — SOUL.md

Each project should have a `SOUL.md` at its root — a persistent identity file maintained by
the project agent. Herald checks for this on startup and offers to create one if it's missing.

**Why SOUL.md instead of relying on Claude Code's auto-memory?**
Claude Code stores auto-memory inside the container. SOUL.md lives in the project's git repo —
it survives container restarts, travels across machines, and evolves via the normal
push-approval flow. It's also readable by humans, which matters.

See `docs/agent-pattern.md` for the full agent identity pattern used by Herald and its projects.

---

## License

MIT
