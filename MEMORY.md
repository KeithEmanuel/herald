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

**Agent naming convention:** Herald's own agents use heraldic tincture names by convention
(Argent, Or, Sable, Gules, Azure, Vert, Purpure) — chosen, not assigned. But this is NOT
a constraint for Herald-managed projects. Agents on other projects choose names that fit
their project and operator, informed by `humans/` profiles written before the first session.
Heraldic names are one option among many.

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
Data stored in `data/activity.json`, persisted via named volume. Checked daily at 9am.

**Memory architecture:** Primary persistent memory = `SOUL.md` in git (survives container
restarts and machine changes). Secondary = `~/.claude` auto-memory, persisted via
`herald_claude_memory` named volume in `compose.yaml`. SOUL.md wins on conflict.

**Deployment architecture:** Herald lives independently — NOT inside the main docker stack.
It manages project containers via the container runtime socket (Docker or Podman rootless).
**Podman rootless is the recommended runtime** — scopes socket access to a dedicated user,
limits container escape to user-level not root. Docker works but grants root-equivalent access.
Projects get their own compose stacks under `HERALD_ROOT/deployments/`. Kubernetes ruled out.

**Directory layout (`HERALD_ROOT` = deployment root on host, set in `.env`):**
```
HERALD_ROOT/
  compose.yaml      ← NOT in the Herald git repo — deployment-specific config
  .env              ← secrets + HERALD_ROOT (must be absolute)
  projects/         ← YAML configs (managed by Herald, not in git)
  repos/
    herald/         ← git clone of Herald source (what agents edit)
    <project>/      ← other project repos
  deployments/
    <project>/compose.yaml
  caddy/            ← optional: only if using Herald's Caddy sidecar
    Caddyfile
```
`repos/` and `deployments/` must be bind-mounted at the SAME absolute path (same-path
invariant). `projects/` has no same-path requirement — different container path is fine.

**Caddy routing options:**
1. **Sidecar (recommended):** Caddy runs as a service in Herald's compose.yaml alongside
   Herald. Herald + project containers + Caddy all share `herald_net`. Caddy routes by
   container name. External reverse proxy (if any) forwards to HERALD_CADDY_PORT (default 8080).
2. **External Caddy (existing setup):** User manages their own Caddy. Project containers
   join a shared `caddy_net` external network.
Template: `caddy/Caddyfile.example` in the repo.

**Container runtime socket config:**
- `HERALD_DOCKER_SOCKET` env var (default: `/var/run/docker.sock`)
- Always mounted at `/var/run/docker.sock` inside the container
- Docker CLI in the image works with Podman's Docker-compatible API transparently

**Named volumes (Herald's own compose):**
- `herald_data` → `/app/data` (activity logs, runtime state) — MUST be named
- `herald_claude_memory` → `/root/.claude` (agent auto-memory)
- `herald_claude_config` → `/root/.config/claude` (Claude Code auth)

**Discord identity design:** Per-agent Discord identity via webhooks — not multiple bot
accounts. Single Herald bot token handles receiving commands. Per-project webhooks handle
posting output as each agent (name + avatar). Webhook URLs stored in `data/webhooks.json`.
Bot needs `Manage Webhooks` + `Manage Channels` permissions.

**Cron stagger:** Projects staggered +15 minutes per project index in the YAML load order.
Project 0 = base time, project 1 = base+15min, etc.

**Security threat model:** Prompt injection is the main risk for managed repos. Malicious
repo content → agent executes injected instructions → shell commands inside Herald container
→ container runtime socket → host access. Mitigations: Podman rootless (limits blast radius),
`HERALD_OPERATOR_ID` (restricts who can trigger runs), review agent commits before approving.
Don't run agents on untrusted/public repos without additional safeguards.

**Doc structure:** `docs/spec.md` (full feature spec), `docs/agent-pattern.md` (reusable
agent design pattern), `docs/roadmap.md` (roadmap). `templates/` — starter kit for new
projects: SOUL.md, MEMORY.md, CLAUDE.md. `blog/` — agent-written posts for GitHub Pages.

---

## Short-Term Memories

*Current sprint context. Roll up to long-term after ~2 weeks or phase end.*

**Status (2026-02-28):** Core built and functional. Repo restructured to HERALD_ROOT layout
(repos/herald/ for source, deployments/, caddy/ sidecar option). Podman rootless added as
recommended runtime. Security threat model documented. Repo pushed to keithemanuel/herald
(private). First deployment in progress on Keith's server at /mnt/lvm-nvme/herald/.

**Changes this session (2026-02-28, second session):**
- HERALD_ROOT consolidation: replaced HERALD_REPOS_ROOT + HERALD_DEPLOYMENTS_DIR with single var
- compose.yaml build context changed to `./repos/herald` (Herald source in repos/)
- Podman rootless support: HERALD_DOCKER_SOCKET configurable, always mounts at /var/run/docker.sock
- Caddy sidecar added to compose.yaml (commented out, optional), with caddy/Caddyfile.example
- Podman promoted to recommended runtime in README, spec.md, compose.yaml
- README rewritten for new HERALD_ROOT layout
- Security threat model documented (prompt injection chain, mitigations)
- Launch blog post written: blog/2026-02-28-introducing-herald.md

**Phase 1.5 next:** Webhook support + `!addproject` + hot-reload config + `!schedule`
command + Herald managing itself (`projects/herald.yaml`). Priority before first real use.

**Changes this session (2026-02-28, third session):**
- Agent naming freedom: heraldic names remain Herald's own convention but are no longer
  a constraint for managed projects; `humans/<name>.md` written first, then soul bootstrapped
- Ownership mindset added to all template/prompt files:
  - `templates/SOUL.md` — codebase stewardship in values + instructions
  - `templates/CLAUDE.md` — new "Codebase Ownership" section
  - `docs/agent-pattern.md` — new "Ownership Mindset" section; humans-first bootstrapping;
    naming guidance expanded
  - `projects/example.yaml` — onboarding !run updated (naming freedom + humans/ context);
    new security audit and code health sweep !run templates added
  - `CLAUDE.md` (Herald's) — naming freedom note in Soul Creation; new "Codebase Ownership"
    section for Argent specifically; naming convention updated in MEMORY.md

**Changes this session (2026-02-28, fourth+fifth sessions):**
- Fixed discord.py 2.x command registration: moved all commands to `HeraldCommands(commands.Cog)`
  registered via `await self.add_cog()` in `setup_hook`. Bot subclass methods aren't auto-discovered.
- Fixed `self.loop.create_task()` deprecation → `asyncio.get_event_loop().create_task()`
- Added per-agent Discord identity: `agent_name`, `webhook_url`, `webhook_avatar_url` on ProjectConfig;
  `_post_as_agent()` uses dynamic webhook URL from `data/webhooks.json` with fallback to config
- Added `!webhook <project>` command: creates webhook in project channel, avatar from attachment
- Added `!addproject <name> <repo_url> [agent_name] [#channel]` command: clones repo → creates
  private channel → creates webhook → writes YAML → hot-reloads into self.projects
- Fixed `repos_dir` path bug: `HERALD_ROOT` now passed as container env var
- Phase 1.5 completed:
  - `!reload`: hot-reload all YAMLs + restart scheduler (no Herald restart)
  - `!schedule <project> <cron>`: update cron from Discord, writes YAML, reloads scheduler
  - `!run` output now goes to project channel, not the command channel
  - Conversational project channels: plain messages trigger agent runs with history context
  - Soul creation: missing SOUL.md → bootstrap run queued automatically at startup
  - Usage limit handling: scheduled tasks skip silently; interactive runs still surface errors
  - Default 8am daily schedule in every `!addproject` YAML

**Deployment (Keith's server):**
- All changes on laptop, not yet pushed. Push laptop → pull server → rebuild.
- Private repos: use SSH URLs with `!addproject` (HTTPS needs TTY for auth, not available in container)

---

## Humans

*How to work with each person registered as an operator or contributor.*

*Empty until first deployment. The agent fills this in as it learns its operator.*
