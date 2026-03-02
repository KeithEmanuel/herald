# Changelog

All notable changes to Herald are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- `project_type` field in project config (`poc`, `solo`, `open_source`, `team`, `enterprise`)
  — controls which template variant is scaffolded at `!addproject` time
- Type-specific CLAUDE.md templates: `templates/poc/` (minimal) and `templates/open_source/`
  (full docs, keepachangelog, CONTRIBUTING.md reference)
- MkDocs Material docs site with blog plugin, deployed to GitHub Pages via GitHub Actions
- `docs/index.md` home page
- Blog posts: launch post (2026-02-28) and March update (2026-03-02)

---

## [0.2.0] — 2026-03-02

### Added
- **`.herald/` directory layout** — SOUL.md, MEMORY.md, and humans/ profiles now live in
  `.herald/` in each project repo (CLAUDE.md stays at root — Claude Code requires it there)
- **Multiple agents per project** and **integration test suite** added to Phase 2 roadmap
- **Multiple coding tool backends** added to Long-Term roadmap

### Changed
- `_scaffold_project_files` creates `.herald/` directory and places MEMORY.md and humans/
  profiles inside it
- `_maybe_bootstrap_soul` checks `.herald/SOUL.md` (was `SOUL.md` at root)
- `autonomy.py` pre-flight checks `.herald/SOUL.md`
- All schedule task prompts updated: `"Read .herald/SOUL.md and .herald/MEMORY.md."`
- `.gitignore`: `humans/` → `.herald/humans/*` with `!.herald/humans/keith.md`

---

## [0.1.5] — 2026-03-01

### Added
- **Autonomous development mode** — per-project weekly minute budget; daily pre-flight check
  (SOUL.md, roadmap items, operator idle, gap, daily cap); `!autonomy` Discord command with
  `on`/`off`/`status`/`budget`/`reserve` subcommands; `data/autonomy.json` tracking with
  ISO-week and calendar-day reset logic
- **Python package restructure** — all source moved to `herald/` package; `pyproject.toml`
  with entry point, pytest config, and ruff lint
- **Test suite** — `tests/test_queue.py`, `tests/test_config.py`, `tests/test_autonomy.py`
  (70 tests total covering queue invariants, config validation, and autonomy pre-flight)
- **Claude Code CLI flags** — `--output-format json` for structured token count output;
  `--model` and `--max-turns` per-project overrides
- **File attachments in project channels** — images, logs, and text files attached to Discord
  messages are downloaded and injected into the agent task
- **`!push` / `!cancel` commands** — manually check for unpushed branches; cancel queued tasks

### Changed
- Usage limit errors (rate/quota) during scheduled tasks log a warning and skip silently;
  interactive runs still surface the error
- Autonomous runs use `record_activity=False` to keep the accountability clock honest

---

## [0.1.0] — 2026-02-28

### Added
- **Discord bot** (discord.py 2.x) with commands: `!run`, `!status`, `!projects`, `!help`
- **Serial asyncio task queue** — one agent runs at a time, globally
- **APScheduler cron jobs** per project, staggered +15 min by index
- **Claude Code CLI wrapper** — `cd <project_path> && claude -p "<task>" --print`
- **Git push-approval flow** — agent commits → Discord proposal → 👍/👎
- **Activity tracking** — `data/activity.json`, per-project last-run timestamps
- **Accountability checker** — 14d nudge / 21d direct / 28d roast (daily 9am cron)
- **SOUL.md soul check** on startup — warns if project is missing one, offers to create
- **Docker Compose deployment** with named volumes for data and agent memory
- **Agent design pattern** — `docs/agent-pattern.md` and `templates/`
- **MEMORY.md tiered memory system** — Core / Long-Term / Short-Term / Humans sections
- **Deploy feature** — `deploy.py`, `!deploy` command, `auto_deploy_on_push` flag
- **Dockerfile** — Docker CLI + Compose plugin baked in
- **Webhook support** — per-agent Discord identity (name + avatar) via webhook;
  `!addproject` creates channel + webhook automatically
- **`!addproject`** — register a new project end-to-end from Discord: clones repo,
  creates private channel, creates webhook, writes YAML, hot-reloads
- **Hot-reload config** — `!reload` re-reads all YAMLs and restarts the scheduler
- **`!schedule`** — set or update a project's cron schedule from Discord
- **Herald manages itself** — `projects/herald.yaml` registered via `!addproject`
- **Soul creation flow** — missing SOUL.md triggers an automatic bootstrap agent run;
  agent explores codebase, writes SOUL.md + initial MEMORY.md, posts a self-introduction
- **Conversational project channels** — plain messages trigger agent runs with recent
  channel history as context
- **HERALD_ROOT layout** — consolidated into single `HERALD_ROOT` var; Herald source
  lives in `repos/herald/` like other managed projects
- **Podman rootless support** — `HERALD_DOCKER_SOCKET` env var makes socket path
  configurable; Docker CLI in image works with Podman's Docker-compatible API
- **Caddy sidecar option** — optional Caddy service in compose.yaml;
  `caddy/Caddyfile.example` template; `herald_net` shared network
- **Security threat model** — prompt injection chain, Docker socket risk, Podman rootless
  mitigation documented in `docs/spec.md`
- **Watchdog service** — `watchdog.sh` + systemd unit; polls every 15s and restarts
  Herald if the container is down (required for self-deploy to complete)
