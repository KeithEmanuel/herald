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

**Package structure:** All Python source lives in `herald/` package (proper Python package
for distribution). Entry point: `python -m herald` or `herald` console script. All imports
are relative within the package (`from .activity import ...`). Root `.py` files are gone.

**Architecture modules** (all under `herald/`):
- `bot.py` — Discord bot, commands, routing, push-approval reactions, deploy commands,
  webhook posting for per-agent Discord identity
- `task_queue.py` — Serial FIFO queue; `AgentTask` supports optional `run_fn` override,
  `record_activity` flag, `duration_seconds`, `tokens_used`, `model`, `max_turns`
  (set by worker after run). Worker handles both `str` and `tuple[str, int]` returns.
- `scheduler.py` — Cron jobs per project, staggered +15min by project index; also registers
  daily autonomy-check jobs for projects with `autonomous.enabled = true`
- `agent_runner.py` — Wraps `claude -p "<task>" --print --dangerously-skip-permissions
  --output-format json [--model] [--max-turns]` in project dir; returns `tuple[str, int]`
  (text, total_tokens). `_parse_json_output()` extracts text from Claude Code's JSON stream.
- `deploy.py` — `deploy_project(compose_path)` — runs `docker compose up --build -d`
- `git_ops.py` — `get_unpushed_agent_branches()`, `push_branch()`, `delete_branch()`
- `config.py` — Pydantic models for projects/*.yaml; includes `DeployConfig`, `AutonomousConfig`
- `activity.py` — `record_activity()`, `days_since_activity()`, `accountability_message()`
  — respects `HERALD_DATA_DIR` env var (defaults to `data/`)
- `autonomy.py` — Pre-flight checklist, weekly budget tracking, roadmap detection;
  `data/autonomy.json` persists autonomous run stats (ISO-week auto-reset). Tracks both
  `autonomous_minutes` (wall-clock) and `autonomous_tokens` (API tokens). Budget mode:
  `weekly_tokens > 0` uses token count, else `weekly_minutes`. `record_run()` accepts
  optional `tokens` kwarg. Respects `HERALD_DATA_DIR` env var.

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

**Status (2026-03-01):** Core built and functional. Autonomous development mode implemented
and tested (54/54 tests passing). Repo is at /mnt/lvm-nvme/herald/repos/herald/ — all
changes on server, not yet committed or pushed.

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

**Changes this session (2026-03-01, first session):**
- Autonomous development mode: `autonomy.py` (new), `config.py` (`AutonomousConfig`),
  `scheduler.py` (daily autonomy-check jobs), `bot.py` (`!autonomy` command),
  `task_queue.py` (`duration_seconds` on `AgentTask`), `projects/example.yaml` (docs),
  `docs/spec.md` + `docs/roadmap.md` (updated), 21 new tests in `tests/test_autonomy.py`,
  5 new tests in `tests/test_config.py`, 1 new test in `tests/test_queue.py`
- Key design: autonomous runs use `record_activity=False` (accountability clock stays honest);
  budget in wall-clock minutes/week; 7-check pre-flight (all local, no API calls)

**Changes this session (2026-03-01, third session):**
- `--dangerously-skip-permissions` added to agent_runner (was missing — bug; agents could hang)
- `--output-format json` added: Claude Code now returns structured JSON with token counts
- `run_agent()` signature: `(path, task, timeout, model=None, max_turns=None) -> tuple[str, int]`
- `AgentTask` gains: `tokens_used`, `model`, `max_turns` fields
- `ProjectConfig` gains: `model: str = ""`, `max_turns: int = 0`
- `AutonomousConfig` gains: `weekly_tokens: int = 0` (when > 0, token budget replaces minutes)
- `autonomy.py`: `record_run()` now tracks tokens; pre-flight uses token budget if set
- `scheduler.py`, `bot.py`: pass model/max_turns through to AgentTask
- `_autonomy_status` updated: shows token budget when `weekly_tokens > 0`
- 16 new tests added; 70/70 passing
- `docs/roadmap.md`: new "Long-Term Possibilities" section (MCP, hooks, skills, ruamel.yaml, etc.)

**Changes this session (2026-03-01, second session):**
- Full Python package restructure: all source files moved from repo root to `herald/` package
- All imports updated to relative (`from .activity import ...`); root `.py` files deleted
- `pyproject.toml` updated: `[project.scripts]` entry, `[tool.pytest.ini_options]`,
  `[tool.ruff.lint]`, proper `packages.find` with `include = ["herald*"]`
- `Dockerfile` CMD updated to `python -m herald`
- `HERALD_DATA_DIR` env var support added to `activity.py`, `autonomy.py`, `bot.py`
- `tests/conftest.py` simplified (removed `sys.path` hack — package install handles it)
- All test imports and `patch()` paths updated to `herald.X`
- `scripts/preflight.py` updated to `from herald.config import load_projects`
- `humans/keith.md` created (skeleton — Keith to fill in accountability preferences)
- 54/54 tests passing

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
- Working directly on server at /mnt/lvm-nvme/herald/repos/herald/
- Changes not yet committed. Private repos: use SSH URLs with `!addproject`.
- `.venv` needs setup: `sudo apt install -y python3.13-venv && python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"`

---

## Humans

*How to work with each person registered as an operator or contributor.*

*Empty until first deployment. The agent fills this in as it learns its operator.*
