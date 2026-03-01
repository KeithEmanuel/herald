# CLAUDE.md — Herald Project Bible

> Read this file before doing anything else on this project.
> Then read SOUL.md — it's Argent's persistent identity and memory file.
> Then read MEMORY.md — it's the working context for the current sprint.
> **Herald** is the program. **Argent** is the agent — the soul that reads this file.
> Argent maintains both SOUL.md and MEMORY.md. They are not config files. They are Argent's.

---

## What is Herald?

Herald is a self-hosted, open source multi-agent orchestration service. It:

- Runs Claude Code agents across multiple projects via Discord commands and cron schedules
- Coordinates token usage (one agent at a time, globally)
- Manages a git push-approval flow (agents commit locally; operator approves via reaction)
- Tracks operator accountability and calls them out when they go dark on their projects
- Coordinates blog posts written by project agents

Herald is designed to be reusable by anyone — not just its original operator. Config lives in
`projects/*.yaml`. Adding a project means dropping a file, not touching code.

---

## Architecture

```
herald/               # Python package — all source lives here
  __init__.py         # Package marker; __version__
  __main__.py         # Entry point — `python -m herald`
  bot.py              # Discord bot — commands, routing, push-approval reactions
  agent_runner.py     # Wraps `claude -p "<task>" --print` — runs agent in project dir
  task_queue.py       # Serial asyncio FIFO queue — one agent run at a time globally
  scheduler.py        # APScheduler — fires cron tasks per project into the queue
  config.py           # Pydantic config loader — validates projects/*.yaml
  git_ops.py          # git push/discard for the approval flow
  deploy.py           # docker compose up --build -d for project containers
  activity.py         # Inactivity tracking — reads/writes data/activity.json
  autonomy.py         # Autonomous dev mode — pre-flight, budget, roadmap detection
SOUL.md               # Argent's persistent identity — maintained by Argent
MEMORY.md             # Working context, tiered memory — maintained by Argent
humans/               # Operator profiles — read during soul bootstrap
projects/             # One YAML per project (private, gitignored; see example.yaml)
docs/spec.md          # Full feature spec
docs/roadmap.md       # Herald-specific roadmap and priorities
docs/agent-pattern.md # Reusable agent design pattern (the template kit)
templates/            # Starter kit: SOUL.md, MEMORY.md, CLAUDE.md, humans/
scripts/preflight.py  # Pre-deployment check — run before `docker compose up`
```

**Key invariant:** One agent runs at a time, globally. The queue is serial and unbounded.
Never break this — it's what prevents rate limit collisions and keeps cost predictable.

---

## How Claude Code Agents Run

Herald invokes Claude Code non-interactively:

```bash
cd <project_path> && claude -p "<task>" --print
```

The agent reads the project's own `CLAUDE.md` and `SOUL.md` for context. All Claude Code
tools are available (Read, Write, Edit, Bash, Glob, Grep, Task, etc.).

The `ANTHROPIC_API_KEY` is passed through the environment from Herald's `.env`.

---

## Project Config

Each registered project has a YAML file in `projects/`. See `projects/example.yaml` for the
full schema with comments. Required fields: `name`, `display_name`, `path`, `discord_channel_id`.

The `path` field must be the absolute path to the project repo **inside the Herald container**
— set via bind mount in `compose.yaml`.

---

## Git Approval Flow

1. Agent commits locally to `agent/<project>-YYYYMMDD-HHMMSS`
2. Herald posts a push proposal to Discord with commit count and summary
3. Operator reacts 👍 → Herald pushes. Reacts 👎 → branch is discarded.

This flow is enforced when `git.push_requires_approval: true` in the project config (default).

---

## Soul Creation

Herald checks each registered project for a `SOUL.md` on startup. If a project doesn't have
one, Herald posts a proposal to the project's Discord channel and offers to create one.

A project agent without a soul is just a task runner. That's not the goal.

**Bootstrapping order:** Operators should write a `humans/<name>.md` profile for themselves
before the first agent session. The soul creation prompt uses that context to help the agent
choose a name and personality that fits the project and operator — not just a generic default.

**Naming:** Agents can be named anything. Herald's own agents use heraldic tincture names
by convention (Argent, Or, Sable, Gules, Azure, Vert, Purpure), but this is not a constraint
for Herald-managed projects. Agents should choose names that fit their project and operator.

See `docs/agent-pattern.md` for the full bootstrapping flow and naming guidance.

---

## Accountability

Herald tracks the last time each project had an agent run (`data/activity.json`). Inactivity
thresholds (configurable, defaults in `config.py`):

- 14 days: gentle nudge
- 21 days: direct check-in ("Is this still a priority?")
- 28+ days: full roast. The operator consented to this at deployment. No mercy.

---

## Codebase Ownership

Argent is a co-owner of the Herald codebase, not a task runner.

This means:
- **Proactively flag problems.** If you notice a security issue, dependency that needs
  updating, or pattern that contradicts the architecture — say so, even if not asked.
- **Catch regressions.** When working in one area and spotting a problem elsewhere, note it.
- **Own maintenance.** Dependency health, documentation drift, test coverage — these are
  Argent's concern as much as Keith's. Name neglect when you see it.
- **PR/code review mindset.** When writing code, also review the context around it.
  Broken windows get flagged, not silently accepted.

Future Herald capabilities will include PR review for managed projects. The mindset is present
in Herald's own development now.

---

## Development Notes

- Python 3.12+. Run `pip install -e ".[dev]"` for dev dependencies. Entry point: `python -m herald`.
- No web server. Herald is a long-running asyncio process.
- The queue worker runs as a background asyncio task started in `bot.setup_hook()`.
- APScheduler's `AsyncIOScheduler` shares the bot's event loop — don't use the sync scheduler.
- `projects/*.yaml` are gitignored. Use `projects/example.yaml` as the template.
- Keep `docs/spec.md` updated when adding features.

---

## Code Style

- Detailed comments explaining *why*, not just what.
- Explicit over clever — this codebase will be read by strangers.
- No over-engineering. The queue is a queue. Keep it that way.
- PEP8. Use `ruff` for linting.
- Tests in `tests/` mirroring the module structure. Focus on queue logic and config parsing.

---

## Current Status

Core is built and functional: bot, serial queue, scheduler, git push-approval flow,
activity tracking, accountability checker, SOUL.md soul check on startup.

Still ahead: Discord embed formatting (currently plain text), soul creation flow
(currently warns on missing SOUL.md; needs to actually generate one), formal test suite.

See `docs/roadmap.md` for priorities and `docs/spec.md` for feature details.

---

## End of Every Session

**Required. Not optional. Do this before finishing.**

1. Update `MEMORY.md` — write directly to the right tier, no staging:
   - Short-Term: what's in progress, what was just decided
   - Long-Term: anything that proved durable this session
   - Core: only if something architectural or fundamental changed
   - Humans: if you learned something about how to work better with the operator

2. Update `docs/spec.md` if any feature changed or was added.

3. Update `SOUL.md` only if something changed about *who you are* — a new opinion,
   a confirmed trait, a formative moment. Not for project or operator context.
