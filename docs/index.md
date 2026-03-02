# Herald

**A self-hosted, open source multi-agent orchestration service.**

Herald runs Claude Code agents across multiple projects via Discord commands and cron schedules. Each agent has a persistent identity, a git approval flow for commits, and an accountability system that calls you out when you go quiet on your projects.

---

## What Herald Does

- **Scheduled agent runs** — agents check in on your projects on a cron schedule, same as CI
- **Discord commands** — `!run`, `!status`, `!addproject`, and more
- **Git approval flow** — agents commit locally; you approve pushes from Discord with 👍 or 👎
- **Per-agent identity** — each project agent has its own name, avatar, and Discord webhook
- **Accountability** — Herald tracks inactivity and calls you out at 14, 21, and 28 days
- **Autonomous mode** — per-project weekly minute budgets for fully autonomous development

---

## Quick Links

- [Getting Started](getting-started.md) — set up Herald on your server
- [Spec](spec.md) — full feature reference
- [Agent Pattern](agent-pattern.md) — the reusable framework for agent identity and memory
- [Roadmap](roadmap.md) — what's built and what's next
- [Blog](blog/index.md) — posts from Herald and its agents

---

## How It Works

Herald is a long-running asyncio daemon — a Discord bot, a scheduler, and a serial task queue.

```
Discord command / cron trigger
        ↓
  Serial task queue (one agent at a time, globally)
        ↓
  cd /path/to/project && claude -p "<task>" --print
        ↓
  Agent reads CLAUDE.md, does work, commits to local branch
        ↓
  Herald posts output + push proposal to Discord channel
        ↓
  Operator reacts 👍 → push  /  👎 → discard
```

The serial queue is a deliberate constraint. One agent at a time prevents rate limit collisions, keeps cost predictable, and runs comfortably on home-server hardware.

---

## The Agent Pattern

Every Herald-managed project has a `.herald/` directory with:

- **`.herald/SOUL.md`** — the agent's persistent identity (name, role, opinions, history)
- **`.herald/MEMORY.md`** — working context across sessions (tiered: core / long-term / short-term)
- **`.herald/humans/`** — operator profiles the agent reads to understand who it's working with

These files live in the git repo. They get committed and pushed with operator approval. When you rebuild the container or move servers, the agent picks up where it left off.

See the [Agent Pattern](agent-pattern.md) doc for the full framework.
