# Herald

Herald is a self-hosted multi-agent orchestration service. You give each project a Claude Code
agent with its own name, personality, and memory. Herald runs them all from a single server,
coordinates their token usage, and bridges everything through Discord.

Each project gets an agent. Herald coordinates them all.

---

## Why Herald?

The gap between "I have Claude" and "Claude is reliably working on my projects" is bigger than
it looks. Running a one-off `claude -p "..."` is easy. Getting an agent to show up every day,
remember what it was working on, commit real changes, and wait for your approval before pushing
— that's an infrastructure problem.

Herald solves it:

- **Persistent identity.** Each agent has a `SOUL.md` — a file it writes and maintains itself,
  in the project's git repo. It survives restarts, travels across machines, and evolves over time.
  After a few weeks, your agent has opinions. It knows the codebase. It knows you.

- **Conversational, not command-line.** Talk to your agents in Discord — from your phone, from
  the couch, from anywhere. Drop a screenshot into the channel; the agent reads it. Short replies
  like "do it" or "just the top item" work conversationally because Herald includes recent channel
  history as context.

- **You stay in control.** Agents commit locally and wait for your 👍 before pushing to origin.
  Nothing ships without your explicit approval — but you don't have to be at a terminal to give it.

- **It stays on you.** The accountability system tracks when you last engaged with each project.
  At 14 days of silence it nudges you. At 21 days it asks if the project is still a priority. At
  28+ days it roasts you. You consented to this at deployment. No mercy.

- **Autonomous mode.** When you're away, agents can pick items off the roadmap and implement them
  on a configurable time budget. They still need your 👍 to push. The accountability clock is
  untouched — autonomous runs don't pretend you're engaged.

- **Deploy from Discord.** Herald can build and deploy project containers via `!deploy`. It even
  deploys itself — `!deploy herald` rebuilds and restarts Herald while you watch in Discord.

---

## What Herald Does

- **Conversational channels** — drop a message in a project's Discord channel; the agent reads
  it, acts on it, and replies as itself (its own name and avatar, not "Herald bot")
- **File attachments** — attach images, screenshots, or text files to your message; the agent
  reads them with Claude Code's Read tool
- **Cron schedules** — daily check-ins, weekly blog posts, or any task you define per project
- **Push approval** — agents commit locally; you approve pushes via 👍/👎 reaction in Discord
- **Deploys** — Herald runs `docker compose up --build -d` for project containers on command
- **Accountability** — Herald notices when you go dark on a project and says something
- **Per-agent identity** — each agent posts to Discord with its own name and avatar
- **Soul creation** — Herald checks that each project has a `SOUL.md` and offers to create one
- **Autonomous mode** — configurable time budget; agents self-assign roadmap items when you're idle

One agent runs at a time, globally. This prevents rate limit collisions and makes token costs
predictable.

---

## Prerequisites

- Podman (recommended) or Docker
- A Discord server and bot token
- A Claude subscription or Anthropic API key
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
  claude-auth.json        # Claude Code credentials (created on first auth)
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
HERALD_OPERATOR_HOME=/home/yourname        # for git credentials (~/.gitconfig, ~/.ssh)
```

For Podman rootless, also set:
```env
HERALD_DOCKER_SOCKET=/run/user/1000/podman/podman.sock  # replace 1000 with your UID
```

See `repos/herald/.env.example` for all options with comments.

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

Follow the login prompt. Credentials are saved to `$HERALD_ROOT/claude-auth.json`
and bind-mounted into the container — they persist across restarts and rebuilds.

### 5. Add a project

In Discord:

```
!addproject myproject git@github.com:you/myproject.git AgentName
```

Herald clones the repo, creates a private Discord channel, sets up the agent webhook with the
agent's avatar (attach an image to the `!addproject` message), writes the project config, and
hot-reloads — no restart needed.

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
| `!addproject <name> <repo_url> [agent_name] [#channel]` | Register a new project end-to-end |
| `!run <project> <task>` | Trigger a one-off agent run |
| `!deploy [project]` | Deploy the project's container (inferred from channel if omitted) |
| `!push [project]` | Check for unpushed agent branches and propose a push |
| `!cancel [project]` | Cancel the next queued (not running) task |
| `!schedule <project> <cron>` | Set or update a project's cron schedule |
| `!autonomy <project> <on\|off\|status\|budget\|reserve>` | Manage autonomous dev mode |
| `!webhook <project>` | Create or update the agent's Discord webhook |
| `!reload` | Hot-reload all project configs without restarting |
| `!status` | Queue depth and currently running job |
| `!projects` | List registered projects and last-active time |

**Plain messages** in a project channel (no `!` prefix) go directly to the agent. Herald
includes the last several messages as context — short replies like "yes", "do it", or "start
with the third one" work as intended.

**File attachments** in project channels are downloaded and their paths injected into the task
so the agent can read them. Drop a screenshot, a log file, or a design mockup.

---

## Git Push Approval Flow

When an agent run completes, Herald checks for unpushed `agent/*` branches:

1. Herald posts: "Ready to push `agent/myproject-20260224-0800` — 3 commits."
2. React 👍 → Herald pushes to origin (and auto-deploys if configured)
3. React 👎 → branch is discarded

You can also trigger a push check manually with `!push [project]`.

Agents do real work — commits, refactors, file edits — without ever pushing to your remote
without your explicit approval.

---

## Autonomous Development Mode

Each project can be configured to run autonomously when you haven't been active recently:

```yaml
# in projects/myproject.yaml
autonomous:
  enabled: true
  weekly_minutes: 210    # ~3.5 hours of wall-clock time per week
  min_gap_hours: 20      # at least 20 hours between runs
  max_per_day: 1         # one autonomous run per day max
```

Before queuing anything, Herald runs a pre-flight checklist in Python (no agent calls):
- Is autonomous mode enabled?
- Does the project have `SOUL.md`?
- Are there unchecked items in the roadmap?
- Is the weekly budget not exhausted?
- Has the daily cap not been hit?
- Is the minimum gap since the last run satisfied?
- Has the operator been inactive for at least 24 hours?

If all checks pass, the agent picks one roadmap item, implements it, and commits. The push
approval flow handles the rest. Manage it in Discord:

```
!autonomy myproject on 180     # enable with a 3-hour weekly budget
!autonomy myproject status     # show this week's stats and pre-flight result
!autonomy myproject off        # disable
```

---

## Project Config

Projects are registered via `!addproject` or by dropping a YAML in `projects/`. See
`projects/example.yaml` for the full schema. Key fields:

```yaml
name: myproject
display_name: "My Project"
path: /srv/herald/repos/myproject    # must be under HERALD_ROOT/repos/
discord_channel_id: "123456789"
agent_name: "Argent"                 # shown in Discord as the webhook username

git:
  push_requires_approval: true

deploy:
  compose_path: /srv/herald/deployments/myproject/compose.yaml
  auto_deploy_on_push: false

schedule:
  - cron: "0 8 * * *"
    task: >
      Read SOUL.md and MEMORY.md. Reflect on project status...

autonomous:
  enabled: false
  weekly_minutes: 210
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

Write a `humans/<yourname>.md` profile in your project before the first soul bootstrap — the
agent uses it to pick a name and personality that fits the project and operator.

See `docs/agent-pattern.md` for the full agent identity pattern.

---

## Security

Herald requires access to the container runtime socket. **Use Podman rootless** if possible —
it limits a container escape to user-level access rather than root. See `docs/spec.md` for
the full threat model and Podman setup instructions.

**Permissions:** Herald runs Claude Code as root inside the container. Tool use permissions are
granted via `permissions.allow` in Claude Code's settings (seeded by `docker-entrypoint.sh` on
startup) — the `--dangerously-skip-permissions` CLI flag is intentionally not used because the
Claude Code CLI blocks it for root users.

---

## License

MIT
