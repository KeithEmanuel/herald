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
- Add a new project by dropping a config file, not rewriting code
- Be called out (gently, then less gently) when I haven't touched a project in too long
- Read weekly/monthly blog posts written by my agents about their work

**As a project agent, I want to:**
- Receive tasks via Discord and execute them in the project repo
- Run scheduled reflection and maintenance tasks
- Commit changes to a feature branch and request owner approval to push
- Write blog posts about project progress and lessons learned
- Coordinate with other agents (read-only: see what other projects are doing)

**As a self-hoster (open source user), I want to:**
- Deploy Herald with a single `docker compose up` and a `.env` file
- Register projects by dropping a YAML file — no code changes
- Understand the config schema without reading source code
- Trust that Herald won't push code without my approval

---

## Architecture

```
herald/
  __main__.py     # Entry point — loads env, starts bot
  bot.py          # Discord bot — commands, routing, git approval flow
  agent_runner.py # Wraps claude CLI — runs agent in project context, returns output
  task_queue.py   # Serial asyncio queue — one agent run at a time globally
  scheduler.py    # APScheduler — fires cron tasks per project config
  config.py       # Pydantic config loader — reads projects/*.yaml
  git_ops.py      # Git push/discard helpers for approval flow
  SOUL.md         # Herald's persistent identity and memory (maintained by Herald)
  projects/       # One YAML file per registered project (private — gitignored in user forks)
    example.yaml  # Template / docs-by-example
  docs/
    spec.md       # This file
  Dockerfile
  compose.yaml    # Designed to drop into docker/<service>/ on server
  pyproject.toml
  .env.example
```

---

## Project Config Schema

```yaml
# projects/example.yaml — copy and fill in for each project
name: myproject
display_name: "My Project (AgentName)"
path: /repos/myproject          # absolute path in the Herald container (bind-mounted)
discord_channel_id: "123456789" # right-click channel in Discord → Copy Channel ID

git:
  auto_commit: true               # agents may commit locally
  push_requires_approval: true    # must get 👍 in Discord before git push
  branch_prefix: "agent/"         # all agent commits go to agent/* branches

schedule:
  - cron: "0 8 * * *"            # 8am daily (staggered +15min per project index)
    task: >
      Read SOUL.md and memory/MEMORY.md. Write a brief journal entry noting
      project status, any open questions, and anything that looks inconsistent
      or needs attention. Update SOUL.md Core Memories if anything is worth
      remembering. Keep it under 200 words.

  - cron: "0 9 * * 1"            # 9am every Monday — optional blog post
    task: >
      Write a short blog post (300-500 words) about the past week's work.
      What shipped, what didn't, what you learned, what surprised you.
      Save it as blog/YYYY-MM-DD-weekly.md (create the blog/ dir if it doesn't exist).
      Commit it to the current agent branch.

# Optional: accountability config (Herald-level feature, not per-project)
# accountability:
#   inactivity_days: 14          # warn after this many days without a run
#   roast_after_days: 21         # escalate to roast mode
```

---

## Discord Interface

| Command | Description |
|---|---|
| `!run <project> <task>` | Trigger a one-off agent run |
| `!status` | Show queue depth and currently running job |
| `!projects` | List registered projects |
| Agent messages auto-post to project channel | Cron results, commit proposals, blog posts, etc. |

**Git approval flow:**
1. Agent commits locally to `agent/projectname-YYYYMMDD-HHMMSS`
2. Herald posts to Discord: "Ready to push `agent/projectname-...` — 2 commits."
3. Owner reacts 👍 → Herald pushes. Owner reacts 👎 → branch is discarded.

**Output formatting:**
- Short output (< 1900 chars): posted as a plain message with code block
- Long output: attached as a text file
- Structured results (future): Discord embeds with title/description/fields

---

## Accountability Feature

Herald tracks the last time each project had an agent run. If a project goes quiet:

| Days inactive | Action |
|---|---|
| 14 | Gentle nudge in the project channel |
| 21 | More direct check-in: "Is this still a priority?" |
| 28+ | Full roast. No mercy. The owner gave consent. |

The activity log is stored in a lightweight JSON file (`data/activity.json`) persisted via Docker volume.

**Implementation:** stored as a thin JSON log; Herald's scheduler checks it daily and fires nudge
tasks to the Herald bot's own channel (or the project channel, configurable).

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

Claude Code reads the project's CLAUDE.md for context (including SOUL.md reference).
All of Claude Code's tools (Read, Write, Edit, Bash, Glob, Grep) are available to the agent.
Authentication via `ANTHROPIC_API_KEY` environment variable.

Requires Node.js + Claude Code CLI in the Herald Docker image.

---

## Deployment (Server Pattern)

Server pattern: `docker/<service>/compose.yaml` with bind mounts for data.

```
docker/herald/
  compose.yaml         # references the herald image
  .env                 # DISCORD_TOKEN, ANTHROPIC_API_KEY, etc.
  projects/            # project config files (bind-mounted in, NOT in public repo)
    enchiridion.yaml
    chortle.yaml
```

Project repos are bind-mounted into the Herald container as read-write volumes.

---

## Open Source Design Principles

Herald is designed to be deployed by anyone, not just the original author.

- **No hardcoded owner-specific config** in the codebase. Projects, paths, and channel IDs live
  in `projects/*.yaml` (private, gitignored in user deployments).
- **`projects/example.yaml`** serves as the primary documentation for the config schema.
- **Single `docker compose up` deployment** — no manual setup steps beyond `.env`.
- **SOUL.md is the agent's own file** — not part of the public API, but included because it's
  what makes Herald interesting. Users can give their Herald its own identity.

---

## What's Out of Scope (for now)

- Agent ↔ agent direct communication (they share a Discord server — that's enough)
- Web UI for Herald
- Per-project token budgets
- Google Assistant integration (that's Chortle's problem)
- Discord embed formatting (current output is plaintext code blocks — good enough for now)
- Blog webhook output (file commits are fine for Phase 1)
