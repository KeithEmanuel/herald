# Herald — Spec

## What is Herald?

Herald is a self-hosted, open source multi-agent orchestration service. It runs Claude Code
agents for multiple projects, coordinates token usage, bridges async communication via Discord,
holds the owner accountable for making progress, and publishes blog posts about what the agents
are doing.

Each project gets an agent. Herald coordinates them all.

Herald is a standalone open source project — designed to be useful to anyone running Claude Code
agents on a home server, not just the person who built it.

---

## User Stories

**As the operator (project owner), I want to:**
- Message a Discord channel and have the relevant project agent respond
- Get a daily status note from each project agent without opening a terminal
- Have agents commit work to a branch and ask me before pushing
- Add a new project via a Discord command — no YAML hand-editing required
- Be called out (gently, then less gently) when I haven't touched a project in too long
- Read weekly/monthly blog posts written by my agents about their work
- Deploy project containers from Discord without SSHing into the server

**As a project agent, I want to:**
- Receive tasks via Discord and execute them in the project repo
- Run scheduled reflection and maintenance tasks
- Commit changes to a feature branch and request owner approval to push
- Write blog posts about project progress and lessons learned
- Coordinate with other agents (read-only: see what other projects are doing)
- Appear in Discord with my own name and avatar, not as the generic Herald bot

**As a self-hoster (open source user), I want to:**
- Deploy Herald with a single `docker compose up` and a `.env` file
- Register projects via a Discord command — or by dropping a YAML file
- Understand the config schema without reading source code
- Trust that Herald won't push code without my approval

---

## Architecture

Herald is a **long-running asyncio daemon** — not a collection of scripts. One process runs
continuously, holding a persistent WebSocket to Discord and an APScheduler on the same event loop.

```
Discord WebSocket (discord.py)
    ↓ commands / reactions
    ↓ posts output via webhook (per-agent identity) or bot (system messages)
APScheduler cron
    ↓ fires tasks on schedule
Serial FIFO Queue (task_queue.py)
    ↓ one item at a time — no parallelism, ever
Agent Runner            Deploy Runner
`claude -p "<task>"     `docker compose
 --print`                up --build -d`
```

```
herald/
  __main__.py     # Entry point — loads env, starts bot + event loop
  bot.py          # Discord bot — commands, reactions, webhook posting, approval flow
  agent_runner.py # Wraps claude CLI — runs agent subprocess, returns output
  task_queue.py   # Serial asyncio FIFO queue — one task at a time globally
  scheduler.py    # APScheduler — cron tasks per project, staggered by index
  config.py       # Pydantic config loader — validates projects/*.yaml
  git_ops.py      # Git push/discard helpers for approval flow
  deploy.py       # docker compose up --build -d for project containers
  activity.py     # Reads/writes data/activity.json — inactivity tracking
  SOUL.md         # Argent's persistent identity (maintained by Argent)
  MEMORY.md       # Working context, tiered memory (maintained by Argent)
  projects/       # One YAML per registered project (private — gitignored)
    example.yaml  # Template / docs-by-example
  templates/      # Starter kit: SOUL.md, MEMORY.md, CLAUDE.md, humans/
  docs/
    spec.md           # This file
    roadmap.md        # Herald priorities by phase
    agent-pattern.md  # Reusable agent identity pattern
  Dockerfile
  compose.yaml    # Standalone Herald service (not nested in main docker stack)
  pyproject.toml
  .env.example
```

**Key invariant:** One agent runs at a time, globally. The queue is serial and unbounded.
Never break this — it's what prevents rate limit collisions and keeps cost predictable.

---

## Project Config Schema

```yaml
# projects/example.yaml — copy and fill in for each project
name: myproject
display_name: "My Project"
path: /srv/herald/repos/myproject  # absolute path — under HERALD_ROOT/repos/
discord_channel_id: "123456789" # right-click channel in Discord → Copy Channel ID

# Optional: per-agent Discord identity via webhook
# Herald creates this automatically on first run if the bot has Manage Webhooks permission.
# Store the generated URL here (or let Herald manage it in data/webhooks.json).
agent_avatar: argent.png        # path relative to project repo root

git:
  auto_commit: true               # agents may commit locally
  push_requires_approval: true    # must get 👍 in Discord before git push
  branch_prefix: "agent/"         # all agent commits go to agent/* branches

schedule:
  - cron: "0 8 * * *"            # 8am daily (staggered +15min per project index)
    task: >
      Read SOUL.md and MEMORY.md. Write a brief journal entry noting
      project status, any open questions, and anything that looks inconsistent
      or needs attention. Update MEMORY.md if anything is worth remembering.
      Keep it under 200 words.

  - cron: "0 9 * * 1"            # 9am every Monday — optional blog post
    task: >
      Write a short blog post (300-500 words) about the past week's work.
      What shipped, what didn't, what you learned, what surprised you.
      Save it as blog/YYYY-MM-DD-weekly.md (create the blog/ dir if it doesn't exist).
      Commit it to the current agent branch.

deploy:
  compose_path: null              # e.g. /srv/herald/deployments/myproject/compose.yaml
  auto_deploy_on_push: false      # if true, deploys automatically after a 👍 push
```

---

## Discord Interface

### Commands

| Command | Description |
|---|---|
| `!run <project> <task>` | Trigger a one-off agent run |
| `!deploy <project>` | Deploy the project's Docker container |
| `!status` | Show queue depth and currently running job |
| `!projects` | List registered projects and their last-active time |
| `!addproject <name> <path> [cron]` | Register a new project (creates YAML + channel + webhook) |
| `!schedule <project> <cron>` | Set or update a project's cron schedule |
| `!reload` | Hot-reload all project configs without restarting Herald |

### Git Approval Flow

1. Agent commits locally to `agent/projectname-YYYYMMDD-HHMMSS`
2. Herald posts to project channel: "Ready to push — 2 commits. [summary]"
3. Operator reacts 👍 → Herald pushes (and auto-deploys if configured). Reacts 👎 → branch discarded.

### Output Formatting

- Short output (< 1900 chars): posted as a plain message with code block
- Long output: attached as a text file
- Structured results (future): Discord embeds with title/description/fields

---

## Agent Identity in Discord

Each project agent appears in Discord with its own name and avatar, not as the generic Herald bot.
This is implemented via **Discord webhooks** — one per project channel.

**Why webhooks, not multiple bot accounts:**
- Running N Discord clients (one per agent) would require N tokens and N persistent connections
- Webhooks let Herald post as any identity from a single bot connection
- The Herald bot still handles *receiving* commands; webhooks handle *posting* agent output

**Setup flow (automated):**
1. Bot requires `Manage Webhooks` + `Manage Channels` permissions
2. On `!addproject`, Herald creates the project channel, then creates a webhook in it
3. Herald reads the project's `agent_avatar` file (PNG) and sets it as the webhook avatar
4. Webhook URL is stored in `data/webhooks.json` (persisted via Docker named volume)
5. All agent output posts go through the webhook; system messages come from the bot

**Manual setup:** If you prefer, you can create the webhook in Discord (channel settings →
Integrations → Webhooks) and paste the URL into `data/webhooks.json` yourself.

---

## Accountability Feature

Herald tracks the last time each project had an agent run. If a project goes quiet:

| Days inactive | Action |
|---|---|
| 14 | Gentle nudge in the project channel |
| 21 | More direct check-in: "Is this still a priority?" |
| 28+ | Full roast. No mercy. The owner gave consent. |

The activity log is stored in `data/activity.json`, persisted via Docker named volume.
Herald's scheduler checks it daily at 9am.

---

## Blog Feature

Each project agent can be scheduled to write blog posts. Herald collects them.

**Agent side:** The scheduled task prompt asks the agent to write a post and commit it to
`blog/YYYY-MM-DD-title.md` in the project repo.

**Herald side (future):** A `blog_output` config option per project can specify:
- `repo`: commit the post to a separate blog repo
- `file`: just leave it in the project repo (default)
- `webhook`: POST to a Ghost/WordPress/Buttondown API (future)

Blog posts are committed to agent branches and go through the normal push-approval flow —
the owner sees them in Discord before they're pushed.

---

## Token Coordination

Simple serial queue: only one agent runs at a time across all projects. Cron tasks
for different projects are staggered by 15 minutes. If two tasks queue simultaneously,
they run back-to-back. This prevents rate limit collisions and makes cost predictable.

Future: per-project token budgets if this becomes a problem.

---

## Claude Integration

Herald invokes Claude Code CLI non-interactively:

```bash
cd <project_path> && claude -p "<task>" --print
```

Claude Code reads the project's `CLAUDE.md` for context (which references `SOUL.md` and
`MEMORY.md`). All Claude Code tools (Read, Write, Edit, Bash, Glob, Grep, Task) are available.

**Authentication:** Subscription auth via `~/.claude/` (OAuth, not API key). Credentials
persist via the `herald_claude_config` Docker named volume. Authenticate once interactively
inside the container; all subsequent runs use the stored credentials.

Requires Node.js + Claude Code CLI in the Herald Docker image.

---

## Deployment

Herald runs as an **independent service** — not nested inside your main docker stack.
It manages project containers via the Docker socket.

```
HERALD_ROOT/                # e.g. /srv/herald — set in .env
  compose.yaml              # Herald's own service definition (this is NOT in the git repo)
  .env                      # DISCORD_TOKEN, ANTHROPIC_API_KEY, HERALD_ROOT
  projects/                 # Private YAML configs (managed by Herald, not in git)
  repos/                    # All project source repos live here
    herald/                 # Git clone of Herald itself (what agents edit)
    myproject/              # Other project repos
  deployments/              # Project docker compose stacks managed by Herald
    myproject/
      compose.yaml
```

**Setup:** `compose.yaml` is not cloned from the Herald repo — you create it at `HERALD_ROOT/`
using the template in `repos/herald/compose.yaml`. It points `build: context: ./repos/herald`
so Docker builds the Herald image from the cloned source.

**Docker socket:** Herald bind-mounts `/var/run/docker.sock` to run `docker compose up --build -d`
for project containers. This grants Herald full control over host Docker — it's intentional.

**Path invariant:** `repos/` and `deployments/` must be bind-mounted at the same absolute path
inside the Herald container as on the host. The Docker daemon resolves compose file paths from
the host perspective, so `HERALD_ROOT/deployments/myproject/compose.yaml` must appear at that
exact path inside the container. This is why `HERALD_ROOT` must be an absolute path.

**Caddy routing:** Each project container joins the `caddy_net` external Docker network.
Caddy routing is configured manually per project (not automated by Herald).

**Named volumes:**
- `herald_data` → `/app/data` — activity logs, webhook URLs, runtime state
- `herald_claude_config` → `/root/.config/claude` — Claude Code auth (subscription OAuth)
- `herald_claude_memory` → `/root/.claude` — Claude Code auto-memory

---

## Adding a New Project

**Via Discord (recommended):**
```
!addproject chortle /srv/herald/repos/chortle
```
Herald creates the channel, webhook, and YAML. Hot-reloads config. Done.

**Via YAML (manual):**
1. Copy `projects/example.yaml` → `projects/chortle.yaml`
2. Fill in `name`, `display_name`, `path`, `discord_channel_id`
3. Run `!reload` in Discord (or restart Herald)

---

## Open Source Design Principles

Herald is designed to be deployed by anyone, not just the original author.

- **No hardcoded owner-specific config** in the codebase. Projects, paths, and channel IDs live
  in `projects/*.yaml` (private, gitignored in user deployments).
- **`projects/example.yaml`** serves as the primary documentation for the config schema.
- **Single `docker compose up` deployment** — no manual setup steps beyond `.env`.
- **`!addproject` for onboarding** — drop a new project in without touching files or restarting.
- **SOUL.md is the agent's own file** — not part of the public API, but included because it's
  what makes Herald interesting. Users can give their Herald its own identity.

---

## What's Out of Scope (for now)

- Agent ↔ agent direct communication (they share a Discord server — that's enough for now)
- Web UI for Herald
- Per-project token budgets
- Google Assistant integration (that's Chortle's problem)
- Discord embed formatting (current output is plaintext code blocks — good enough for now)
- Blog webhook output (file commits are fine for Phase 1)
- Kubernetes (single server, Docker Compose is the correct scale)
