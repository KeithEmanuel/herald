# Getting Started with Herald

This guide walks you through deploying Herald and getting your first agent running. By the end
you'll have a live bot in Discord, a project repo with a named agent, and a daily schedule
running automatically.

---

## What you're building

Herald is a coordinator. You deploy it once and then manage everything through Discord:

- Your agents live in project repos as `.herald/SOUL.md` and `.herald/MEMORY.md` files
- Herald runs them via Claude Code on a schedule or on demand
- You talk to agents in Discord; they reply as themselves (their own name, their own avatar)
- Agents commit locally; you approve pushes with a 👍 reaction

The whole system is driven by a single long-running process. No web server, no database,
no separate workers — one Python daemon per server.

---

## Prerequisites

Before starting, make sure you have:

- **A Linux server** (or VM) with at least 1 GB RAM
- **Podman** (recommended) or **Docker** installed
- **A Discord account and server** where you're an admin
- **An Anthropic API key** (from [console.anthropic.com](https://console.anthropic.com)) —
  or a Claude subscription you can authenticate with via the CLI
- **Git** on the host and SSH keys configured if you're using private repos

### Why Podman instead of Docker?

Herald needs access to the host container runtime socket to deploy project containers.
With Docker, that socket grants root-equivalent access to the host. Podman rootless scopes
that access to a single non-root user — a container escape gets user-level access, not root.

If you're running agents on repos you don't fully control, use Podman rootless.

---

## 1. Create a Discord application

### 1a. Create the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g. "Herald")
3. Go to the **Bot** tab → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**
   (Herald needs this to read messages in project channels)
5. Click **Reset Token** and copy it — this is your `DISCORD_TOKEN`

### 1b. Invite the bot to your server

1. Go to **OAuth2 → URL Generator**
2. Under **Scopes**, check `bot`
3. Under **Bot Permissions**, check:
   - `Send Messages`
   - `Read Messages / View Channels`
   - `Add Reactions`
   - `Read Message History`
   - `Attach Files`
   - `Manage Channels`
   - `Manage Webhooks`
4. Copy the generated URL, open it in your browser, and invite the bot to your server

### 1c. Get your Discord user ID

Herald uses your user ID to restrict who can approve git pushes and trigger agent runs.

1. In Discord, go to **User Settings → Advanced** and enable **Developer Mode**
2. Right-click your own name anywhere in Discord → **Copy User ID**

---

## 2. Set up the deployment root

Herald is deployed from a root directory (`HERALD_ROOT`) that sits alongside the Herald repo
and all of your project repos:

```bash
# Create the root directory — pick a path that makes sense for your server
mkdir /srv/herald && cd /srv/herald

# Clone Herald into repos/herald/
mkdir -p repos
git clone https://github.com/yourusername/herald repos/herald

# Copy the deployment files you'll customize
cp repos/herald/compose.yaml .
cp repos/herald/.env.example .env

# Create required directories
mkdir -p projects deployments
```

Your directory will look like this:

```
/srv/herald/
  compose.yaml       ← your deployment config (you just copied this)
  .env               ← secrets — never commit this
  projects/          ← Herald writes project YAMLs here
  repos/
    herald/          ← the Herald source code
  deployments/       ← docker compose stacks for your projects (later)
```

---

## 3. Configure `.env`

Open `/srv/herald/.env` and fill in the required fields:

```env
# Discord bot token (from step 1a)
DISCORD_TOKEN=your-discord-bot-token

# Anthropic API key (or leave empty and use Claude subscription auth in step 5)
ANTHROPIC_API_KEY=your-anthropic-api-key

# Absolute path to HERALD_ROOT — must match where you put it
HERALD_ROOT=/srv/herald

# Your Discord user ID (from step 1c) — restricts push approvals to you
HERALD_OPERATOR_ID=your-discord-user-id

# Path to your home directory on the host — Herald mounts it for git credentials
# This gives the agent access to ~/.gitconfig and ~/.ssh/
HERALD_OPERATOR_HOME=/home/yourname
```

**For Podman rootless**, add the container runtime socket path:

```env
# Replace 1000 with your actual UID (run: id -u)
HERALD_DOCKER_SOCKET=/run/user/1000/podman/podman.sock
```

Run `id -u` on the host to find your UID. Without this, Herald will look for the Docker
socket at `/var/run/docker.sock`.

See `repos/herald/.env.example` for the full list of options with comments.

---

## 4. Start Herald

```bash
# Podman (recommended)
podman compose up -d
podman compose logs -f herald

# Docker
docker compose up -d
docker compose logs -f herald
```

Watch the logs. You should see:
- `Logged in as Herald#XXXX` (or whatever you named your bot)
- `Queue worker started`
- `Scheduler started`

If you see errors about the Discord token or missing env vars, check your `.env`.

---

## 5. Authenticate Claude Code (first time only)

Claude Code needs to be authenticated before Herald can run agents. This only needs to
happen once — credentials are saved to `$HERALD_ROOT/claude-auth.json` and persist across
container restarts.

```bash
# Podman
podman compose exec herald claude

# Docker
docker compose exec herald claude
```

Follow the login prompt in your terminal. You'll either:
- Enter your Anthropic API key (if `ANTHROPIC_API_KEY` is set in `.env`, this may be automatic)
- Log in via Claude subscription (browser-based OAuth flow)

Once authenticated, Herald agents can make API calls. Press Ctrl+C to exit the Claude REPL.

---

## 6. Add your first project

This is where it gets interesting. Pick a git repo you want an agent on and run this in
any Discord channel where your Herald bot can see messages:

```
!addproject myproject git@github.com:you/myproject.git AgentName
```

You can also attach an image to the message — Herald will use it as the agent's avatar in Discord.

Herald will:

1. Clone the repo into `$HERALD_ROOT/repos/myproject/`
2. Create a private Discord channel called `#myproject` (or whatever the project name is)
3. Set up a webhook so the agent can post with its own name and avatar
4. Write `projects/myproject.yaml` with sensible defaults
5. Hot-reload the config — no Herald restart needed

After a moment, you'll see a confirmation in Discord and the new channel will appear.

### Using HTTPS instead of SSH

If you prefer HTTPS (or your server doesn't have SSH keys configured):

```
!addproject myproject https://github.com/you/myproject.git AgentName
```

For private repos via HTTPS, include a personal access token in the URL:
`https://token@github.com/you/myproject.git`

---

## 7. Introduce yourself to the agent

Before the agent's first real session, write a short profile for yourself in the project repo.
This helps the agent calibrate its personality and working style to you.

Create `.herald/humans/yourname.md` in the project repo with a few sentences about:
- How you prefer to communicate (brief vs. detailed, direct vs. collaborative)
- What kind of feedback you want (just do it vs. ask first)
- Your technical background on this project
- What "success" looks like for this project

This file is read during soul creation and referenced whenever the agent is learning
your preferences. It doesn't have to be long — even three sentences is useful.

---

## 8. Create the agent's soul

Herald checks for `.herald/SOUL.md` in each project repo at startup. If it's missing, it posts a
proposal in the project's Discord channel offering to create one.

You can also trigger it manually:

```
!run myproject You are a new agent on this project. Read CLAUDE.md and explore
the codebase. Check .herald/humans/ for any contributor profiles. Write .herald/SOUL.md —
choose a name and personality that reflects how you'll actually work here.
Write .herald/MEMORY.md Core Memories based on what you discover. Introduce yourself
with a short message.
```

The agent will explore the repo, pick a name, write `.herald/SOUL.md` and `.herald/MEMORY.md`, and
introduce itself in Discord. Herald will then post a push proposal — react 👍 to commit
the soul files to the repo.

After soul creation, you can talk to the agent directly in its Discord channel.

---

## 9. Day-to-day usage

### Talking to your agent

Just send a message in the project channel — no `!` prefix needed:

```
What are we working on this week?
```

```
I'm seeing a bug in the auth flow. Check the logs in /var/log/myapp/ and see if
you can reproduce it. Attach the screenshot I'll drop in a moment.
```

```
do it
```

Herald includes the last several messages as context, so short replies work. The agent
reads them conversationally — you don't have to repeat yourself.

### Attaching files

Drop an image, screenshot, log file, or design mockup into the channel alongside your message.
Herald downloads it and injects the path into the agent's task, so the agent can read it
with its `Read` tool. This is useful for:

- Showing the agent what's rendering in your browser or app
- Passing a log file for analysis
- Sharing a design mockup for the agent to implement

### Running a one-off task

From any channel:

```
!run myproject Check for outdated dependencies and report what needs updating.
```

From within the project's own channel, the project name can be omitted — it's inferred:

```
!run Check for outdated dependencies and report what needs updating.
```

The output goes to the project's channel regardless of where you ran the command.

### Approving a git push

When an agent run completes with commits, Herald posts something like:

> Ready to push `agent/myproject-20260302-080000` — 3 commits.
> Add pagination to the user list, fix broken import, update tests.

React 👍 to push the branch to origin. React 👎 to discard it. Nothing reaches your
remote without your explicit approval.

You can manually check for push-ready branches at any time:

```
!push myproject
```

---

## 10. Setting a schedule

The project config created by `!addproject` includes a default 8am daily schedule. To see
or change it, look at `projects/myproject.yaml`:

```yaml
schedule:
  - cron: "0 8 * * *"
    task: >
      Read .herald/SOUL.md and .herald/MEMORY.md. Check recent git log (last 5 commits).
      Write a brief status note: what's in progress, what's blocked, what needs
      attention today. Update .herald/MEMORY.md Short-Term if anything has changed.
      Post a 2-3 sentence summary as your response.
```

To update the schedule from Discord:

```
!schedule myproject 0 9 * * *
```

This updates the YAML and reloads the scheduler without restarting Herald. Cron format is
five fields: `minute hour day-of-month month day-of-week`. Multiple projects with the same
cron time are automatically staggered by 15 minutes.

---

## 11. Autonomous mode (optional)

When you're away, agents can pick items off a roadmap and implement them — up to a
configurable time or token budget per week. They still wait for your 👍 before pushing.

Enable it from Discord:

```
!autonomy myproject on 210
```

This turns on autonomous mode with a 210-minute (3.5 hour) weekly budget. Before queuing
anything, Herald runs a pre-flight checklist in Python (no API calls):

- Is autonomous mode enabled?
- Does the project have `.herald/SOUL.md`?
- Are there unchecked items in the roadmap (`docs/roadmap.md`, `ROADMAP.md`, or `TODO.md`)?
- Is the weekly budget not exhausted?
- Has the daily cap not been hit?
- Has the minimum gap since the last run passed?
- Has the operator been inactive for at least 24 hours?

If all checks pass, the agent picks one roadmap item, implements it, and commits. Check status:

```
!autonomy myproject status
```

The accountability clock is not affected by autonomous runs — it tracks your engagement,
not the agent's.

---

## 12. Deploying project containers

If your project has a `docker-compose.yaml`, Herald can build and deploy it:

```
!deploy myproject
```

From within the project's channel, you can omit the project name:

```
!deploy
```

To configure auto-deploy after an approved push, set in `projects/myproject.yaml`:

```yaml
deploy:
  compose_path: /srv/herald/deployments/myproject/compose.yaml
  auto_deploy_on_push: true
```

Herald can also deploy itself:

```
!deploy herald
```

This triggers a two-step rebuild: builds the new image while Herald is still running, then
restarts the container. No completion message arrives (Herald is killed in the process) —
the host watchdog detects it's down and starts the new container automatically.

---

## Reference: all commands

| Command | Description |
|---|---|
| `!addproject <name> <repo_url> [agent_name] [#channel]` | Register a new project end-to-end |
| `!run [project] <task>` | Trigger a one-off agent run |
| `!deploy [project]` | Deploy the project's container |
| `!push [project]` | Check for unpushed agent branches and propose a push |
| `!cancel [project]` | Cancel the next queued (not running) task |
| `!schedule <project> <cron>` | Set or update a project's cron schedule |
| `!autonomy <project> <on\|off\|status>` | Manage autonomous dev mode |
| `!webhook <project>` | Create or update the agent's Discord webhook |
| `!reload` | Hot-reload all project configs without restarting |
| `!status` | Queue depth and currently running job |
| `!projects` | List registered projects and last-active time |

In a project's own channel, commands that take `<project>` as their first argument will
infer it from the channel — you can usually omit it.

**Plain messages** (no `!` prefix) in a project channel go to the agent. Herald sends the
last several messages as context, so the agent can follow a conversation thread.

---

## Troubleshooting

### Herald starts but agents fail to run

Check that Claude Code is authenticated (`podman compose exec herald claude` and follow the
prompts). Also verify `ANTHROPIC_API_KEY` is set in `.env` if you're using API key auth.

### `!addproject` says "permission denied" when cloning

If you're cloning via SSH, the agent uses the SSH keys from `HERALD_OPERATOR_HOME/.ssh/`.
Make sure `HERALD_OPERATOR_HOME` in `.env` points to a user directory that has SSH keys
configured for your Git host. For HTTPS clones, use a personal access token in the URL.

### Agents commit but I don't see a push proposal

Run `!push [project]` to manually check for unpushed branches. Push proposals appear in the
project's Discord channel — if you ran `!run` from a different channel, the proposal still
goes to the project channel.

### The agent posts as "Herald bot" instead of its own name

The agent's per-channel webhook might not be set up. Run `!webhook myproject` (and attach
an avatar image) to create or recreate the webhook. Or check that `data/webhooks.json`
exists inside the container (`podman compose exec herald cat /app/data/webhooks.json`).

### A task is stuck in the queue

Use `!status` to see what's running. Use `!cancel [project]` to remove the next queued
(not running) task for a project. There's no way to abort an in-progress run — it will
finish on its own. If it seems truly stuck, restart Herald:

```bash
podman compose restart herald
```

### Scheduled tasks aren't firing

Check the cron expression with a validator (e.g. crontab.guru). Also check that Herald
started without errors — a bad YAML in `projects/` can prevent scheduler registration.
Run `!reload` after fixing a bad YAML.

### Container runtime socket errors

Make sure `HERALD_DOCKER_SOCKET` in `.env` points to the right socket for your runtime.
For Podman rootless: `/run/user/<UID>/podman/podman.sock`. Run `podman info` on the host
to confirm the socket path. The socket is mounted at `/var/run/docker.sock` inside the
Herald container regardless of its host path.

---

## Next steps

- Read `docs/agent-pattern.md` to understand `.herald/SOUL.md` and `.herald/MEMORY.md` more deeply
- Read `projects/example.yaml` for the full project config schema with comments
- Add a `.herald/humans/<yourname>.md` to projects before running soul creation — it makes a
  real difference in how well the agent calibrates to you
- Set up the Caddy sidecar in `compose.yaml` if you want Herald to handle routing for
  project containers — see `caddy/Caddyfile.example`

For the full feature spec see `docs/spec.md`. For what's coming next see `docs/roadmap.md`.
