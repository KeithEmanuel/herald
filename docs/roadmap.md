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
- [x] **HERALD_ROOT layout** — consolidated HERALD_REPOS_ROOT + HERALD_DEPLOYMENTS_DIR into single `HERALD_ROOT` var; Herald source now lives in `repos/herald/` like other projects; build context updated to `./repos/herald` (2026-02-28)
- [x] **Podman rootless support** — `HERALD_DOCKER_SOCKET` env var makes socket path configurable; Docker CLI in image works transparently with Podman's Docker-compatible API; Podman promoted to recommended runtime in all docs (2026-02-28)
- [x] **Caddy sidecar option** — optional Caddy service in compose.yaml (commented out); `caddy/Caddyfile.example` template; `herald_net` shared network for Caddy ↔ project container routing (2026-02-28)
- [x] **Security threat model documented** — prompt injection chain, Docker socket risk, Podman rootless mitigation, per-project considerations (2026-02-28)

---

## Phase 1.5 — Polish and Identity (near-term)

These complete the core experience before going public.

- [x] **Webhook support** — per-agent Discord identity (name + avatar) via webhook.
      `!addproject` creates channel + webhook automatically. `!webhook <project>` to
      create/update separately. URLs stored in `data/webhooks.json`.

- [x] **`!addproject <name> <repo_url> [agent_name] [#channel]`** — register a new project
      end-to-end from Discord. Clones repo, creates private channel, creates webhook,
      writes YAML, hot-reloads. Default 8am daily schedule included automatically.

- [x] **Hot-reload config** — `!reload` re-reads all YAMLs, updates `self.projects`, rebuilds
      `_channel_to_project` map, and restarts the scheduler. No Herald restart needed.

- [x] **`!schedule <project> <cron>`** — set or update a project's cron schedule from Discord.
      Updates YAML and hot-reloads scheduler immediately.

- [x] **Herald manages itself** — `projects/herald.yaml` registered via `!addproject`. Argent
      runs on Herald's own codebase. `auto_deploy_on_push` can be enabled once
      `deploy.compose_path` is set.

- [x] **Soul creation flow** — on startup, projects missing `SOUL.md` automatically get a
      bootstrapping agent run queued. Agent explores codebase, writes SOUL.md + initial
      MEMORY.md, and posts a self-introduction. No manual intervention needed.

- [x] **Conversational project channels** — plain messages in project channels automatically
      trigger agent runs with recent channel history as context. Short replies like "yes"
      or "do the top item" work because the agent sees what it said in previous messages.

- [x] **Usage limit handling** — scheduled tasks skip silently when API rate/quota limits are
      hit (log warning only). Interactive runs still surface the error.

- [ ] **Discord embed formatting** — push proposals and run summaries should use Discord embeds
      (fields, colors, timestamp) rather than plain text code blocks.

- [ ] **Test suite** — `tests/test_queue.py` (serial invariant, task ordering),
      `tests/test_config.py` (YAML validation, error cases), `tests/test_git_ops.py`

- [ ] **Blog aggregation** — agents write `blog/YYYY-MM-DD-*.md` in their project repos;
      Herald aggregates and posts a weekly digest to a Herald-level Discord channel.

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
- [ ] **Container registry image** — published image (ghcr.io or Docker Hub) so operators
      can `podman compose up` without building from source
- [ ] **Podman rootless setup guide** — detailed walkthrough for the recommended runtime:
      dedicated `herald` user, `podman system service`, lingering, socket path
- [ ] **GitHub Pages / blog** — launch post written (`blog/2026-02-28-introducing-herald.md`);
      needs a static site to publish it (Jekyll or MkDocs)
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
