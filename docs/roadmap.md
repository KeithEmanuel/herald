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
- [x] MEMORY.md tiered memory system (Core / Long-Term / Short-Term / Session Notes)

---

## Phase 1.5 — Polish (near-term)

These are small but important for usability and correctness.

- [ ] **Discord embed formatting** — currently posting plain text; should use Discord embeds
      for push proposals and run summaries (fields, colors, timestamp)
- [ ] **Soul creation flow** — bot currently *warns* when a project lacks `SOUL.md`;
      should post a proposal and actually generate one via a bootstrapping agent run
- [ ] **Test suite** — `tests/test_queue.py` (serial invariant, task ordering),
      `tests/test_config.py` (YAML validation, error cases), `tests/test_git_ops.py`
- [ ] **Blog aggregation** — agents write `blog/YYYY-MM-DD-*.md` in their project repos;
      Herald aggregates and posts a weekly digest to a Herald-level Discord channel

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

## Phase 3 — Own Repo + Public Release

Herald has its own repo now (`/home/keith/Repos/herald/`). Next: go public.

- [x] **Move to own repo** — extracted from `enchiridion/herald/`, standalone repo (2026-02-27)
- [ ] **Push to GitHub** — public repo, own CI
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
