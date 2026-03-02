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
herald/                 # Python package — all source lives here
  __init__.py           # Package marker; __version__
  __main__.py           # Entry point — `python -m herald`
  bot.py                # Discord bot — commands, reactions, webhook posting, approval flow
  agent_runner.py       # Wraps claude CLI — runs agent subprocess, returns output
  task_queue.py         # Serial asyncio FIFO queue — one task at a time globally
  scheduler.py          # APScheduler — cron tasks per project, staggered by index
  config.py             # Pydantic config loader — validates projects/*.yaml
  git_ops.py            # Git push/discard helpers for approval flow
  deploy.py             # docker compose up --build -d for project containers
  activity.py           # Reads/writes data/activity.json — inactivity tracking
  autonomy.py           # Autonomous dev mode — pre-flight, budget tracking, roadmap detection
.herald/
  SOUL.md               # Argent's persistent identity (maintained by Argent)
  MEMORY.md             # Working context, tiered memory (maintained by Argent)
  humans/               # Operator profiles — read by agent during soul bootstrap
CLAUDE.md               # Project instructions for Claude Code
projects/               # One YAML per registered project (private — gitignored)
  example.yaml          # Template / docs-by-example
scripts/
  preflight.py          # Pre-deployment connectivity and permissions check
templates/              # Starter kit: .herald/SOUL.md, .herald/MEMORY.md, CLAUDE.md, .herald/humans/
docs/
  spec.md               # This file
  roadmap.md            # Herald priorities by phase
  agent-pattern.md      # Reusable agent identity pattern
Dockerfile
compose.yaml            # Standalone Herald service (not nested in main docker stack)
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
path: /srv/herald/repos/myproject  # absolute path inside Herald container (same as host — see path invariant)
discord_channel_id: "123456789"    # right-click channel in Discord → Copy Channel ID

# Optional: per-agent Discord identity
# When set, agent output posts appear as the agent, not the Herald bot.
# !addproject sets these automatically. !webhook creates/updates the webhook.
agent_name: "Argent"              # display name used in webhook posts
webhook_url: null                 # static fallback URL; dynamic URL stored in data/webhooks.json
webhook_avatar_url: null          # URL to an image for per-post avatar override (usually leave null)

git:
  auto_commit: true               # agents may commit locally
  push_requires_approval: true    # must get 👍 in Discord before git push
  branch_prefix: "agent/myproject" # all agent commits go to this branch prefix

schedule:
  - cron: "0 8 * * *"            # 8am daily (staggered +15min per project index)
    task: >
      Read .herald/SOUL.md and .herald/MEMORY.md. Write a brief journal entry noting
      project status, any open questions, and anything that looks inconsistent
      or needs attention. Update .herald/MEMORY.md if anything is worth remembering.
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
| `!run <project> <task>` | Trigger a one-off agent run (posts result to project channel) |
| `!deploy [project]` | Deploy the project's Docker container (inferred from channel if omitted) |
| `!push [project]` | Check for unpushed agent branches and propose a push |
| `!cancel [project]` | Cancel the next queued (not running) task for a project |
| `!status` | Show queue depth and currently running job |
| `!projects` | List registered projects and their channel |
| `!addproject <name> <repo_url> [agent_name] [#channel]` | Register a new project end-to-end |
| `!webhook <project>` | Create/update the agent's Discord webhook (attach image for avatar) |
| `!schedule <project> <cron>` | Set/update the project's cron schedule (e.g. `0 8 * * *`) |
| `!autonomy <project> <on\|off\|status\|budget\|reserve>` | Manage autonomous development mode |
| `!reload` | Hot-reload all project YAMLs and restart the scheduler |

**Direct messages:** Posting a plain (non-`!`) message in a project's Discord channel
automatically queues a task for that agent. Recent channel history is included as context,
so short replies like "yes" or "do the top item" work conversationally.

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

**Setup flow (via `!addproject`):**
1. Bot requires `Manage Webhooks` + `Manage Channels` permissions in the server
2. `!addproject <name> <repo_url> [agent_name]` clones the repo, creates a private channel,
   creates a webhook (attach an image to the command to set the agent's avatar), and writes
   the project YAML — all in one step
3. Webhook URL stored in `data/webhooks.json` (persisted via Docker named volume); never in git
4. All agent output posts go through the webhook; system messages come from the bot

**Updating the webhook:**
```
!webhook <project>     # (optionally attach a new avatar image)
```
Re-creates the webhook in the project channel. Safe to run multiple times.

**Webhook priority:** Dynamic URL from `data/webhooks.json` (set by `!webhook`/`!addproject`)
takes precedence over `webhook_url` in the project YAML. The YAML `webhook_url` field is a
static fallback for manual setups.

**Manual setup:** Create a webhook in Discord (channel settings → Integrations → Webhooks),
then either paste the URL into `projects/<name>.yaml` as `webhook_url`, or into
`data/webhooks.json` as `{"<name>": "<url>"}`.

**Private repos:** Use SSH URLs (`git@github.com:user/repo.git`) for `!addproject`, not HTTPS.
HTTPS clones require interactive credentials which aren't available inside the container.
The `~/.ssh` directory is bind-mounted into the container for this purpose.

---

## Autonomous Development Mode

When the operator hasn't been active recently, Herald can autonomously pick roadmap items,
implement them, commit locally, and post push proposals for the operator to review.
The existing `👍`/`👎` flow handles everything — nothing ships without approval.

### How it works

1. Herald registers a daily check job at 10am UTC (staggered per project) for each project
   with `autonomous.enabled = true`
2. Before queuing anything, a pre-flight checklist runs entirely in Python — no agent call:
   - `autonomous.enabled` is `true`
   - Project has `.herald/SOUL.md` (bootstrapped)
   - Roadmap file contains at least one unchecked item (`- [ ]`)
   - Weekly autonomous budget not exhausted (wall-clock minutes, resets each ISO week)
   - Today's run count < `max_per_day`
   - Minimum gap since last autonomous run is satisfied
   - Operator has NOT been active in the last 24h
3. If all checks pass, the agent runs: reads roadmap, picks ONE item, implements it, commits
4. Agent output posts to the project channel; the existing push-approval proposal appears
5. Operator reacts `👍` to push and test, or `👎` to discard

Autonomous runs use `record_activity=False` — they do not reset the accountability clock.
That clock measures operator engagement, not agent activity.

### Config schema

```yaml
autonomous:
  enabled: false            # opt in per project
  weekly_minutes: 210       # wall-clock budget per ISO week (~3.5 hours)
  reserve_minutes: 90       # informational — shown in !autonomy status
  min_gap_hours: 20         # minimum hours between runs (spread across the week)
  max_per_day: 1            # hard cap per calendar day
  roadmap_paths:            # checked in order; first file with - [ ] wins
    - docs/roadmap.md
    - ROADMAP.md
    - TODO.md
  task: ""                  # custom prompt; empty = built-in default
```

### Discord commands

| Command | Description |
|---|---|
| `!autonomy <project> on [minutes]` | Enable (optionally set weekly budget) |
| `!autonomy <project> off` | Disable |
| `!autonomy <project> status` | Show current week stats and pre-flight result |
| `!autonomy <project> budget <minutes>` | Update weekly budget |
| `!autonomy <project> reserve <minutes>` | Update informational reserve |

### Data persistence

Autonomous run stats are tracked in `data/autonomy.json` (persisted via Docker named volume):
```json
{
  "myproject": {
    "week_key": "2026-W09",
    "autonomous_minutes": 47.3,
    "runs_this_week": 2,
    "runs_today": 1,
    "today_date": "2026-03-02",
    "last_run_ts": "2026-03-02T10:00:00+00:00"
  }
}
```

Weekly counters reset automatically when the ISO week rolls over. Daily counters reset
when the calendar day changes. No manual intervention needed.

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

Claude Code reads the project's `CLAUDE.md` for context (which references `.herald/SOUL.md` and
`.herald/MEMORY.md`). All Claude Code tools (Read, Write, Edit, Bash, Glob, Grep, Task) are available.

**Authentication:** Subscription auth via `~/.claude.json` (OAuth, not API key). Credentials
are stored at `${HERALD_ROOT}/claude-auth.json` on the host, bind-mounted into the container
at `/root/.claude.json`. Authenticate once interactively (`podman compose exec herald claude`);
credentials persist across restarts and rebuilds via the bind mount — no named volume needed.

**Permissions:** Tool use (Write, Edit, Bash, etc.) is permitted via `permissions.allow` in
`/root/.claude/settings.json`, written by `docker-entrypoint.sh` on every container startup.
The `--dangerously-skip-permissions` CLI flag is NOT used — the Claude Code CLI blocks it for
root users. The settings.json approach is equivalent and isn't root-restricted.

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

**Container runtime socket:** Herald bind-mounts the container runtime socket so it can run
`docker compose up --build -d` for project containers. The Docker CLI installed in the Herald
image works with both Docker and Podman (Podman exposes a Docker-compatible API).

- **Docker (default):** `/var/run/docker.sock` — root daemon, full host Docker access
- **Podman rootless (recommended for public repos):** set `HERALD_DOCKER_SOCKET` in `.env`
  to `/run/user/<uid>/podman/podman.sock`. Requires `podman system service` running as a
  dedicated `herald` user. Container escapes are limited to user-level access, not root.

**`HERALD_COMPOSE_CMD`:** Controls which compose command Herald uses for `!deploy` (default:
`docker compose`). Do **not** set this to `podman compose` — `podman` is not installed in the
Herald container image. The Docker CLI inside the container talks to the Podman socket at
`/var/run/docker.sock` via Podman's Docker-compatible API. `docker compose` is correct for both
Docker and Podman rootless setups.

  Host setup for Podman rootless:
  ```bash
  useradd -r -s /bin/false herald
  loginctl enable-linger herald
  # As the herald user:
  systemctl --user enable --now podman.socket
  ```

**Path invariant:** `repos/` and `deployments/` must be bind-mounted at the same absolute path
inside the Herald container as on the host. The Docker daemon resolves compose file paths from
the host perspective, so `HERALD_ROOT/deployments/myproject/compose.yaml` must appear at that
exact path inside the container. This is why `HERALD_ROOT` must be an absolute path.

**Caddy routing:** Each project container joins the `caddy_net` external Docker network.
Caddy routing is configured manually per project (not automated by Herald).

**Named volumes:**
- `herald_data` → `/app/data` — activity logs, webhook URLs, runtime state
- `herald_claude_memory` → `/root/.claude` — Claude Code auto-memory and settings.json

**Bind mounts (not named volumes):**
- `${HERALD_ROOT}/claude-auth.json` → `/root/.claude.json` — Claude Code auth (subscription OAuth).
  Created on first `claude` login inside the container. Persists across rebuilds.
- `${HERALD_DOCKER_SOCKET}` → `/var/run/docker.sock` — container runtime socket

---

## Adding a New Project

**Via Discord (recommended):**

```
!addproject chortle git@github.com:you/chortle.git Pounce
```

Herald will, in one command:
1. Clone the repo to `HERALD_ROOT/repos/chortle/`
2. Create a private `#pounce` channel visible only to the operator and Herald
3. Create an agent webhook for Pounce (attach an image to the `!addproject` message to set the avatar)
4. Write `projects/chortle.yaml`
5. Hot-reload — `!run chortle <task>` works immediately, no restart needed

To use an existing channel instead of creating a new one:
```
!addproject chortle git@github.com:you/chortle.git Pounce #existing-channel
```

**SSH URLs for private repos:** Use `git@github.com:user/repo.git`, not `https://`. HTTPS clones
require interactive credentials unavailable inside the container. Public repos can use HTTPS.

**Via YAML (manual):**
1. Clone the repo manually to `HERALD_ROOT/repos/chortle/`
2. Copy `projects/example.yaml` → `projects/chortle.yaml`
3. Fill in `name`, `display_name`, `path`, `discord_channel_id`, `agent_name`
4. Restart Herald (hot-reload not available for manual YAML drops)

---

## Open Source Design Principles

Herald is designed to be deployed by anyone, not just the original author.

- **No hardcoded owner-specific config** in the codebase. Projects, paths, and channel IDs live
  in `projects/*.yaml` (private, gitignored in user deployments).
- **`projects/example.yaml`** serves as the primary documentation for the config schema.
- **Single `docker compose up` deployment** — no manual setup steps beyond `.env`.
- **`!addproject` for onboarding** — drop a new project in without touching files or restarting.
- **`.herald/SOUL.md` is the agent's own file** — not part of the public API, but included because it's
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
