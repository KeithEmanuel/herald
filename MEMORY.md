# Herald — Agent Memory

> Maintained by Argent. Updated at the end of every session.
> Read this at the start of every session alongside SOUL.md.
> Humans may read this. Only Argent edits it.

---

## Core Memories

*Permanent architectural facts. These don't change without a very deliberate decision.*

**Serial queue invariant:** One agent runs at a time, globally. The queue in `task_queue.py`
is serial and unbounded. Never break this — it's what prevents rate limit collisions and keeps
cost predictable for operators. Any "parallelism" enhancement is off the table.

**Agent identity — program vs. soul:** Herald is the program. Argent is the agent soul that
reads `SOUL.md`. These are distinct. `SOUL.md` is not config; it's not docs; it belongs to
Argent. The distinction matters for how future operators onboard their own agents.

**Open source first:** No operator-specific content in source. Private config lives exclusively
in `projects/*.yaml` (gitignored). Adding a new project = `!addproject`, never touch code.

**Heraldic tincture naming convention:** Agent souls are named after heraldic tinctures.
Sable (black/ink), Argent (silver), Or (gold), Gules (red), Azure (blue), Vert (green),
Purpure (purple). Chosen by Sable on 2026-02-27 — not assigned, earned.

---

## Long-Term Memories

*Key decisions, patterns, lessons, gotchas. Stable for weeks/months.*

**Tech stack:** Python 3.12 + discord.py + APScheduler (AsyncIOScheduler) + pydantic +
pyyaml + python-dotenv. No web server — long-running asyncio process.

**Architecture modules:**
- `bot.py` — Discord bot, commands, routing, push-approval reactions, deploy commands,
  webhook posting for per-agent Discord identity
- `task_queue.py` — Serial FIFO queue; `AgentTask` supports optional `run_fn` override and
  `record_activity` flag so non-agent tasks (deploys) can use the same queue safely
- `scheduler.py` — Cron jobs per project, staggered +15min by project index
- `agent_runner.py` — Wraps `claude -p "<task>" --print` in project dir
- `deploy.py` — `deploy_project(compose_path)` — runs `docker compose up --build -d`
- `git_ops.py` — `get_unpushed_agent_branches()`, `push_branch()`, `delete_branch()`
- `config.py` — Pydantic models for projects/*.yaml; includes `DeployConfig`
- `activity.py` — `record_activity()`, `days_since_activity()`, `accountability_message()`

**Git approval flow:** Agents commit locally to `agent/<project>-YYYYMMDD-HHMMSS`.
Herald detects unpushed branches → posts Discord proposal → 👍 push / 👎 discard.
Tracked via `_pending_pushes: dict[int, dict]` keyed on Discord message ID.

**Accountability thresholds:** 14d = nudge, 21d = direct check-in, 28d+ = roast.
Data stored in `data/activity.json`, persisted via Docker named volume. Checked daily at 9am.

**Memory architecture:** Primary persistent memory = `SOUL.md` in git (survives container
restarts and machine changes). Secondary = `~/.claude` auto-memory, persisted via
`herald_claude_memory` named volume in `compose.yaml`. SOUL.md wins on conflict.

**Deployment architecture:** Herald lives independently — NOT inside the main docker stack.
It manages project containers via the Docker socket. Projects get their own compose stacks
under `HERALD_DEPLOYMENTS_DIR`. Each project owns its own postgres if needed (no shared db).
Caddy routing is configured manually per project. All project containers join the `caddy_net`
external Docker network. Kubernetes explicitly ruled out — single-server, Docker Compose is
correct scale.

**compose.yaml path convention:** Project repos and deployment stacks are mounted at the SAME
absolute path inside the container as on the host (`HERALD_REPOS_ROOT` and
`HERALD_DEPLOYMENTS_DIR` env vars). The Docker daemon resolves compose file paths from the
host perspective, so paths must match.

**Docker Compose volumes (Herald's own compose):**
- `herald_data` → `/app/data` (activity logs, runtime state) — MUST be a named volume
- `herald_claude_memory` → `/root/.claude` (agent auto-memory)
- `herald_claude_config` → `/root/.config/claude` (Claude Code auth)
- `/var/run/docker.sock` bind-mounted → Herald uses Docker CLI to deploy project containers

**Discord identity design:** Per-agent Discord identity via webhooks — not multiple bot
accounts. Single Herald bot token handles receiving commands. Per-project webhooks handle
posting output as each agent (name + avatar). Webhook URLs stored in `data/webhooks.json`.
Bot needs `Manage Webhooks` + `Manage Channels` permissions.

**Cron stagger:** Projects staggered +15 minutes per project index in the YAML load order.
Project 0 = base time, project 1 = base+15min, etc.

**Doc structure:** `docs/spec.md` (full feature spec), `docs/agent-pattern.md` (reusable
agent design pattern), `docs/roadmap.md` (roadmap). `templates/` — starter kit for new
projects: SOUL.md, MEMORY.md, CLAUDE.md.

---

## Short-Term Memories

*Current sprint context. Roll up to long-term after ~2 weeks or phase end.*

**Status (2026-02-28):** Core built and functional. Bot, serial queue, APScheduler, git
approval flow, activity tracking, accountability checker, deploy feature, soul check on
`on_ready`. All wired together. Moved to standalone repo.

**Phase 1.5 next:** Webhook support + `!addproject` + hot-reload config + `!schedule`
command + Herald managing itself (`projects/herald.yaml`). These are the priority before
first real deployment.

**Chatbot feature planned:** Non-`!command` messages in `#argent` channel get conversational
response. Pluggable backend: `claude-cli` (default), `anthropic` (API), `ollama` (local).
On roadmap after Phase 1.5.

**Pre-deployment checklist:**
- Install Claude Code CLI and authenticate (`claude login`)
- Set `HERALD_OPERATOR_ID` in `.env` (your Discord user ID)
- Set `HERALD_REPOS_ROOT` and `HERALD_DEPLOYMENTS_DIR` in `.env`
- Update project YAMLs with real channel IDs (or use `!addproject` once built)
- `docker network create caddy_net` on the host

---

## Humans

*How to work with each person registered as an operator or contributor.*

*Empty until first deployment. The agent fills this in as it learns its operator.*
