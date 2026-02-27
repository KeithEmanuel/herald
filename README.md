# Herald

A self-hosted multi-agent orchestration service. Herald runs Claude Code agents across multiple
projects, coordinates token usage, and bridges async communication via Discord.

Each project gets an agent. Herald coordinates them all.

---

## What Herald Does

- **Discord commands** — trigger agent runs on demand: `!run myproject <task>`
- **Cron schedules** — agents run daily reflections, weekly blog posts, or anything you define
- **Push approval** — agents commit locally; you approve pushes via 👍/👎 reaction in Discord
- **Accountability** — Herald notices when you go dark on a project and says something
- **Soul creation** — Herald checks that each project has a SOUL.md and offers to create one if not

One agent runs at a time, globally. This prevents rate limit collisions and makes token costs predictable.

---

## Prerequisites

- Docker and Docker Compose
- A Discord server and bot (see [Discord Setup](#discord-setup) below)
- An Anthropic API key
- Git repos for each project you want to run agents on

---

## Quick Start

### 1. Clone Herald

```bash
git clone https://github.com/yourusername/herald.git
cd herald
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your-discord-bot-token
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 3. Add a project

```bash
cp projects/example.yaml projects/myproject.yaml
```

Edit `projects/myproject.yaml` — set `name`, `display_name`, `path`, and `discord_channel_id`.

The `path` is where the project repo will be mounted inside the Herald container (e.g. `/repos/myproject`).

### 4. Configure the compose file

Edit `compose.yaml` to add volume mounts for each project repo:

```yaml
volumes:
  - /absolute/path/to/myproject:/repos/myproject:rw
  - ~/.gitconfig:/root/.gitconfig:ro
  - ~/.ssh:/root/.ssh:ro
```

### 5. Start Herald

```bash
docker compose up -d
```

Herald will connect to Discord, load your projects, and start the scheduler. Check logs with:

```bash
docker compose logs -f herald
```

---

## Discord Setup

### Create the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g. "Herald")
3. Go to **Bot** → click **Add Bot**
4. Enable **Message Content Intent** and **Server Members Intent** under Privileged Gateway Intents
5. Copy the bot token — this is your `DISCORD_TOKEN`

### Set permissions and invite

1. Go to **OAuth2 → URL Generator**
2. Scopes: `bot`
3. Bot Permissions: `Send Messages`, `Read Messages/View Channels`, `Add Reactions`, `Read Message History`, `Attach Files`
4. Open the generated URL and invite the bot to your server

### Get channel IDs

Enable Developer Mode: **User Settings → Advanced → Developer Mode**

Right-click any channel → **Copy Channel ID**. Paste this into your project's `discord_channel_id` field.

---

## Project Config Reference

See `projects/example.yaml` for a fully-commented example. Key fields:

```yaml
name: myproject                    # used in !run commands
display_name: "My Project (Agent)" # shown in Discord messages
path: /repos/myproject             # path inside the container
discord_channel_id: "123456789"    # where Herald posts results

git:
  push_requires_approval: true     # 👍/👎 approval before any push

schedule:
  - cron: "0 8 * * *"             # daily at 8am
    task: >
      Read SOUL.md and memory/MEMORY.md. Write a brief journal entry...
```

---

## Commands

| Command | Description |
|---|---|
| `!run <project> <task>` | Trigger a one-off agent run |
| `!status` | Queue depth and currently running job |
| `!projects` | List registered projects |

---

## Git Push Approval Flow

When an agent run completes, Herald checks for unpushed `agent/*` branches:

1. Herald posts: "Ready to push `agent/myproject-20260224-0800` — 3 commits."
2. React 👍 → Herald pushes to origin
3. React 👎 → branch is discarded

This means agents can do real work — commits, refactors, file edits — without ever pushing
to your remote without your approval.

---

## Project Structure

```
herald/
  __main__.py     # entry point
  bot.py          # Discord bot, commands, push-approval reactions
  agent_runner.py # Claude Code CLI wrapper
  task_queue.py   # serial asyncio queue
  scheduler.py    # APScheduler cron tasks
  config.py       # project config loader
  git_ops.py      # git push/discard
  SOUL.md         # Herald's identity (maintained by Herald)
  CLAUDE.md       # context for Claude Code sessions on this repo
  projects/
    example.yaml  # config template
  docs/
    spec.md       # full feature spec
```

---

## Agent Memory and SOUL.md

Each project should have a `SOUL.md` at its root — a persistent identity file maintained by
the project agent. Herald checks for this on startup and offers to create one if it's missing.

**Why SOUL.md instead of relying on Claude Code's auto-memory?**
Claude Code stores auto-memory at `~/.claude/projects/...` on the host machine. In a Docker
container, this path is inside the container and can be lost on restart. SOUL.md lives in
the project's git repo — it survives container restarts, travels across machines, and evolves
via the normal push-approval flow.

---

## Deployment (Home Server Pattern)

If you're running multiple Docker services with the pattern `docker/<service>/compose.yaml`:

```
docker/
  herald/
    compose.yaml   ← reference the herald image here
    .env           ← DISCORD_TOKEN, ANTHROPIC_API_KEY
    projects/      ← your private project YAML configs (gitignored)
```

The `compose.yaml` in the Herald repo is designed to be dropped into this pattern.

---

## License

MIT
