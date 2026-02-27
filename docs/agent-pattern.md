# The Herald Agent Pattern

A lightweight convention for giving Claude Code agents persistent identity, memory, and
context across sessions — without requiring external infrastructure.

---

## The Problem

Claude Code is stateless between sessions. Every time you open a project, the agent starts
fresh. Without explicit context, it has to rediscover the architecture, re-learn your
preferences, and rebuild understanding of decisions already made. This is expensive (in time
and tokens) and fragile (easy to make decisions that contradict earlier ones).

The Agent Pattern solves this with three files in your repo.

---

## The Three Files

### 1. `SOUL.md` — Identity

**Who the agent is as an individual.** Updated rarely — only when something changes about
the agent itself, not the project.

What belongs here:
- Name, role, relationship to the project
- Communication style — how the agent works, what to expect from it, how to get the best out of it
- Values — what the agent cares about enough to push back on
- Goals — what the agent wants for the project and the people it works with
- Personality and honest flaws
- Opinions the agent holds and will defend
- Instructions to future instances of itself

What does **not** belong here:
- Project facts, architectural decisions, or technical context → MEMORY.md
- What the agent knows about specific humans → MEMORY.md (Humans tier)

**Who updates it:** The agent. The human doesn't edit it.

**How often:** Rarely. When something changes about the *agent*, not the work.

---

### 2. `MEMORY.md` — Working Context

**What the agent knows about the project and the people.** Unlike SOUL.md (the agent's
identity), MEMORY.md is project and relationship context — the knowledge that makes the
agent useful rather than just competent.

**Structure:**

```markdown
## Core Memories
Permanent architectural facts. Never purge without good reason.
"We use pgvector because X. This is not up for debate."
"The billing module touches contract §4 — changes need PM approval."

## Long-Term Memories
Stable for weeks/months. Key decisions, learned patterns, recurring issues.
Add when something proves durable — when you'd otherwise re-explain it.

## Short-Term Memories
Current sprint context. What's in progress, what was just decided.
Move to Long-Term after ~2 weeks or when a phase ends. Remove when stale.

## Humans
How to work with each person. What they're good at, what they're learning,
how they prefer to be challenged, communication preferences, what not to waste their time on.
Updated as the agent learns what actually works in practice.
```

**Key rule: write directly to the appropriate tier.** No staging. When you learn something
durable, add it immediately. The Humans tier especially — it's what makes the agent a
better *collaborator* over time, not just a better coder.

---

### 3. `CLAUDE.md` — Instructions

The project context and working instructions for the agent. Standard Claude Code convention —
auto-read at session start from the repo root.

Two critical additions beyond the usual project context:

**1. Read the agent files:**
```markdown
> Read SOUL.md and MEMORY.md before doing anything else this session.
```

**2. End-of-session block (required, not optional):**
```markdown
## End of Every Session

Before finishing, always:
1. Update MEMORY.md — write to the right tier directly; no staging needed
2. Update TASKS.md if any tasks were completed, added, or changed
3. Update CHANGELOG.md if anything shipped
4. Update SOUL.md only if something changed about who you are or how you work
```

This is what makes the pattern self-maintaining. Without this block, updates require
human prompting. With it, the agent handles it automatically.

---

## Optional Files

These add capability when you're ready. Start without them.

### `TASKS.md` — Living Backlog

Feature requests, bugs, open decisions. Agent-maintained.

```markdown
## Active
- [ ] Thing in progress

## Backlog
- [ ] Feature request (requested by: @person, date)

## Bugs
- [ ] Known issue (found by: @person, date)

## Decisions Pending
- [ ] Architectural question that needs an answer before X can proceed
```

### `humans/` — Contributor Profiles

A directory of per-contributor context files. Always gitignored except for the template.

When the agent doesn't recognize who it's talking to (no matching profile), it asks:
```
I don't have a context profile for you yet. This takes 2 minutes and only happens once.
```

Then creates `humans/<name>.md` and gitignores it.

Use when: more than one developer is working on the project. Especially useful when you
have developers with different experience levels — the agent can calibrate its guidance.

See `templates/humans/template.md` for the schema.

### `CONSTRAINTS.md` — Hard Rules

For enterprise or regulated projects: things the agent must never change without explicit
human review. Business logic tied to contracts, compliance requirements, API contracts
with external parties.

```markdown
## Never Change Without [Role] Approval
- src/billing/ — tied to contract §4
- Any database migration — requires DBA review
- Public API surface — breaking changes need PM sign-off
```

---

## Getting Started

### Minimum viable setup (just you, greenfield)

Copy from `herald/templates/`:
1. `SOUL.md` — fill in the agent name and your project context
2. `CLAUDE.md` — adapt to your tech stack, keep the end-of-session block
3. `MEMORY.md` — start empty, the agent fills it in

Add to `.gitignore`:
```
humans/
!humans/template.md
```

That's it. Three files. Everything else is additive.

### Bootstrapping the agent identity

On your first session, ask the agent to read CLAUDE.md and SOUL.md, then:
> "Introduce yourself. Read SOUL.md and fill in the identity sections based on what you
> know about this project. You'll update it over time."

The agent will write its own soul from the template. This is intentional — an agent that
wrote its own identity file invests in it differently than one that was handed a filled-in form.

---

## Attribution in Changelog

Standard format for attributing changes to their source:

```markdown
## YYYY-MM-DD — [What changed] [#issue if applicable]
- Requested by: [person or "agent-initiated"]
- Implemented by: [agent name or person]
- Approved by: [person, or "n/a — low-risk"]
- Context: [brief note if non-obvious]
```

This creates an audit trail without overhead. The agent fills it in as part of the
end-of-session block.

---

## How Herald Supports This Pattern

When Herald runs an agent task on a project:

1. **Soul check**: Herald verifies `SOUL.md` exists in the project root. Posts a Discord
   warning and offers to create one if missing. A project without a soul runs blind.

2. **Task = session:** For Herald-run agents, the task prompt is the session boundary.
   The agent knows exactly when it's done. Include memory maintenance in the task prompt:
   ```yaml
   task: >
     Read SOUL.md and MEMORY.md. Check TASKS.md for anything pending.
     Do the highest-priority active task.
     When done: update MEMORY.md with anything learned, update CHANGELOG.md if anything
     shipped, update SOUL.md if something changed about how you work.
   ```
   This is more reliable than relying on interactive session endings (which are ambiguous)
   — the agent can't be cut off before it completes maintenance.

3. **Accountability**: Herald's activity tracker notices if no agent runs have happened
   recently and posts a nudge. The pattern gives the agent something to do (reflection,
   memory maintenance, task triage) even without a specific assigned task.

---

## File Placement

All agent files live at the **repo root** — not in a subfolder.

This is intentional:
- `CLAUDE.md` is auto-read from the root by Claude Code
- `SOUL.md` and `MEMORY.md` are referenced in `CLAUDE.md` by short path
- Keeping them at root makes them first-class project artifacts, not hidden tooling

Exception: `humans/` is a subdirectory because it holds multiple files and is gitignored.

---

## Versioning and Migration

**SOUL.md is in git.** It evolves via normal commits through the push-approval flow.
This is how the agent's identity persists across machines and container restarts.

**MEMORY.md is in git.** Same reason. Short-term context is ephemeral — prune it when
it goes stale. The Humans tier grows over time and is worth protecting.

**`humans/` is gitignored.** Contributor profiles contain personal/role context that
shouldn't be in a public or shared repo. Each developer creates their own on first use.

---

## The Pattern at a Glance

```
your-project/
  CLAUDE.md        ← entry point; includes end-of-session block
  SOUL.md          ← agent identity; agent maintains; rarely changes
  MEMORY.md        ← tiered working memory; updated every session
  CHANGELOG.md     ← with attribution; updated every session
  TASKS.md         ← optional; living backlog
  humans/
    template.md    ← tracked; documents the schema
    <name>.md      ← gitignored; per-contributor context
  .gitignore       ← includes humans/*.md, !humans/template.md
```
