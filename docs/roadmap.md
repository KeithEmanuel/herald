# Herald — Roadmap

> Herald's priorities, by phase. Updated when status changes.
> See `spec.md` for detailed feature descriptions.

---

## Completed

- [x] Discord bot (discord.py), commands: `!run`, `!status`, `!projects`
- [x] Serial asyncio task queue — one agent at a time globally
- [x] APScheduler cron jobs per project, staggered +15min by index
- [x] Claude Code CLI wrapper (`agent_runner.py`)
- [x] Git push-approval flow (agent commits → Discord proposal → 👍/👎)
- [x] Activity tracking (`activity.py`, `data/activity.json`)
- [x] Accountability checker — 14d nudge / 21d direct / 28d roast (daily 9am cron)
- [x] SOUL.md soul check on startup — warns if project is missing one
- [x] Docker Compose deployment with named volumes for data + agent memory
- [x] Agent design pattern formalized (`docs/agent-pattern.md` + `templates/`)
- [x] MEMORY.md tiered memory system (Core / Long-Term / Short-Term / Humans)
- [x] Deploy feature — `deploy.py`, `!deploy` command, `auto_deploy_on_push` flag
- [x] `AgentTask.run_fn` override + `record_activity=False` for non-agent queue tasks
- [x] Dockerfile — Docker CLI + Compose plugin baked in
- [x] `compose.yaml` rewritten for standalone deployment (fixed build context, herald_data volume, Docker socket, deployments bind-mount)
- [x] Move to own repo — extracted from `enchiridion/herald/`, standalone at `/home/keith/Repos/herald/` (2026-02-27)

---

## Phase 1.5 — Polish and Identity (near-term)

These complete the core experience before going public.

- [ ] **Webhook support** — per-agent Discord identity (name + avatar) via webhook.
      `!addproject` creates channel + webhook automatically (requires `Manage Webhooks` +
      `Manage Channels` permissions). Webhook URLs stored in `data/webhooks.json`.
      Agent output posts via webhook; system messages use the bot.

- [ ] **`!addproject <name> <path> [cron]`** — register a new project from Discord.
      Creates the Discord channel, webhook, and `projects/<name>.yaml`. No YAML hand-editing.

- [ ] **Hot-reload config** — `!reload` command re-reads all YAMLs and updates the scheduler
      at runtime. No restart required when adding or editing projects.

- [ ] **`!schedule <project> <cron>`** — set or update a project's cron schedule from Discord.

- [ ] **Herald manages itself** — `projects/herald.yaml` registers Herald as its own project
      (Argent channel = Herald's Discord channel). Argent can run on Herald's codebase.
      `auto_deploy_on_push: true` so Argent can ship Herald's own updates.

- [ ] **Soul creation flow** — bot currently warns when a project lacks `SOUL.md`; should post
      a proposal and actually generate one via a bootstrapping agent run.

- [ ] **Discord embed formatting** — push proposals and run summaries should use Discord embeds
      (fields, colors, timestamp) rather than plain text code blocks.

- [ ] **Test suite** — `tests/test_queue.py` (serial invariant, task ordering),
      `tests/test_config.py` (YAML validation, error cases), `tests/test_git_ops.py`

- [ ] **Blog aggregation** — agents write `blog/YYYY-MM-DD-*.md` in their project repos;
      Herald aggregates and posts a weekly digest to a Herald-level Discord channel.

- [ ] **Argent chat** — non-`!command` messages in the `#argent` channel get a conversational
      response from Herald. Herald knows its own state (queue, projects, activity) and can
      trigger commands on your behalf. Pluggable backend via `HERALD_CHAT_BACKEND` env var:
      `claude-cli` (default, uses subscription), `anthropic` (API key, Haiku), or `ollama`
      (local, free). Ollama runs as an optional sidecar in `compose.yaml`.

---

## Phase 2 — Multi-Operator

Herald is single-operator today. These open it up.

- [ ] **Per-operator permission scoping** — restrict which Discord users can trigger which
      projects (currently any server member can `!run`)
- [ ] **Multi-guild support** — run Herald in multiple Discord servers with separate
      project sets per guild
- [ ] **`!pause` / `!resume` commands** — let operator suspend a project's cron schedule
      without editing the YAML
- [ ] **Queue introspection** — `!queue` command shows what's pending and what's running

---

## Phase 3 — Public Release

- [x] **Move to own repo** — extracted from `enchiridion/herald/` (2026-02-27)
- [ ] **Push to GitHub** — public repo, MIT license, README for strangers
- [ ] **Docker Hub image** — published image so operators can `docker compose up` without
      building from source
- [ ] **MkDocs or Docusaurus docs site** — operator guide, project config reference,
      pattern kit docs
- [ ] **Projects registry** (optional) — public list of Herald deployments / agents,
      if operators want to be listed

---

## Deferred / Unlikely

Things considered and explicitly set aside.

- **Linear / project management integration** — GitHub Projects is sufficient. Linear adds
  overhead and cost. If operator wants it, they can wire it in themselves.
- **Web dashboard** — Discord is the interface. A web UI would duplicate it for no gain in
  Phase 1-2. Revisit if Herald scales to many projects.
- **Parallel agent execution** — deliberately off the table. The serial invariant is a
  feature, not a limitation.
- **Kubernetes** — single server, Docker Compose is the correct scale. Explicitly ruled out.
- **Multiple Discord bot clients** — one bot token + webhooks achieves per-agent identity
  without running N persistent WebSocket connections.
