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
in `projects/*.yaml` (gitignored). Adding a new project = drop a YAML, never touch code.

**Heraldic tincture naming convention:** Agent souls are named after heraldic tinctures.
Sable (black/ink) = Enchiridion's agent. Argent (silver) = Herald's agent. Future agents
extend the pattern. Chosen by Sable on 2026-02-27 — not assigned, earned.

---

## Long-Term Memories

*Key decisions, patterns, lessons, gotchas. Stable for weeks/months.*

**Tech stack:** Python 3.12 + discord.py + APScheduler (AsyncIOScheduler) + pydantic +
pyyaml + python-dotenv. No web server — long-running asyncio process.

**Architecture modules:**
- `bot.py` — Discord bot, commands, routing, push-approval reactions, deploy commands
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

**Deployment architecture (decided 2026-02-27):** Herald lives independently at
`/mnt/lvm-nvme/herald/` — NOT inside the main docker stack. It manages project containers
via the Docker socket. Projects get their own compose stacks at
`/mnt/lvm-nvme/herald/deployments/<projectname>/compose.yaml`. Each project owns its own
postgres if needed (no shared db). Caddy routing is configured manually per project.
All project containers join the `caddy_net` external Docker network.
GitHub pushes are release-only — normal deploys go straight to the home server.
Kubernetes was explicitly ruled out — single-server, Docker Compose is correct scale.

**Docker Compose volumes (Herald's own compose):**
- `herald_data` → `/app/data` (activity logs, runtime state) — MUST be a named volume
- `herald_claude_memory` → `/root/.claude` (agent auto-memory)
- `herald_claude_config` → `/root/.config/claude` (Claude Code auth)
- `/var/run/docker.sock` bind-mounted → Herald uses Docker CLI to deploy project containers
- `/mnt/lvm-nvme/herald/deployments` bind-mounted at same path (Docker daemon resolves
  compose file paths from the host, so container path must match host path)

**Cron stagger:** Projects staggered +15 minutes per project index in the YAML load order.
Project 0 = base time, project 1 = base+15min, etc.

**Doc structure:** `herald/docs/spec.md` (full feature spec), `herald/docs/agent-pattern.md`
(reusable agent design pattern), `herald/docs/roadmap.md` (this project's roadmap).
`herald/templates/` — starter kit: SOUL.md, MEMORY.md, CLAUDE.md, humans/template.md.

---

## Short-Term Memories

*Current sprint context. Roll up to long-term after ~2 weeks or phase end.*

**Core built (2026-02-27):** bot, serial queue, APScheduler, git approval flow, activity
tracking (`activity.py`), soul check on `on_ready`. All wired together and functional.

**Agent design pattern formalized:** `herald/docs/agent-pattern.md` + `herald/templates/`.
Enchiridion and Herald both updated to use the pattern (MEMORY.md tiered, end-of-session block
in CLAUDE.md, humans/ directory gitignored with template committed).

**Moved to standalone repo (2026-02-27):** Herald now lives at `/home/keith/Repos/herald/`
(its own repo, extracted from `enchiridion/herald/`). Not yet on GitHub — that's next.
Two projects registered: enchiridion (daily 8am), chortle (no schedule yet, needs SOUL.md).

**Still needs wiring post-move:**
- Project YAML `path:` fields and `deploy.compose_path` fields need real values once Herald
  is deployed to `/mnt/lvm-nvme/herald/`.
- Herald's own `compose.yaml` needs updating: fix `build.context` (currently `../../herald`,
  should be `.`), add `herald_data` named volume, add Docker socket mount, add deployments
  bind-mount. (Compose file shown to Keith as a sketch; not yet written to disk.)
- GitHub repo creation — Herald isn't public yet.
- Create `caddy_net` external network on the host before first deploy.

**Deploy feature shipped (2026-02-27):** `deploy.py`, `DeployConfig` in `config.py`,
`!deploy <project>` command, `auto_deploy_on_push` flag wired into post-👍 flow.
`AgentTask` extended with optional `run_fn` and `record_activity=False` for non-agent tasks.
Dockerfile updated with Docker CLI + Compose plugin.

**What's still ahead:** Discord embed formatting (currently plain text), soul creation flow
(bot detects missing SOUL.md and *offers* to create one — currently only warns), formal test
suite, blog aggregation flow, Herald's own compose.yaml needs the deploy-related additions,
write a project deploy template compose (docs/deploy-template.yaml).

---

## Humans

*How to work with each person registered as an operator or contributor.*

**Keith (operator, enchiridion + chortle):**
- 13 years backend: SQL, C#, Python, AI/ML. Frontend is not his comfort zone.
- Two kids, ~10hr days. Time is scarce. Get to the point. Don't re-explain known context.
- Direct. Hates filler. Likes jokes.
- The real reason for Enchiridion: wants to play D&D with his kids with less planning friction.
- Works in automation professionally. Thinks clearly about agentic systems — can handle technical honesty.
- Communication preference: summaries first, details on request.
