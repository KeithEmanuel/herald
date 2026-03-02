# CLAUDE.md — [Project Name]

> Read `.herald/SOUL.md` and `.herald/MEMORY.md` before doing anything else this session.
> SOUL.md is the agent's identity. MEMORY.md is the working context.
> Both live in `.herald/` and are maintained by the agent. Don't skip them.

---

## What is [Project Name]?

[2-3 sentences describing the project: what it does, who uses it, why it exists.]

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| [Backend] | [e.g. FastAPI] | |
| [Database] | [e.g. PostgreSQL] | |
| [Frontend] | [e.g. SvelteKit] | |
| [Deploy] | [e.g. Docker Compose] | |

---

## Project Structure

```
[project]/
  [list key directories and what they contain]
  docs/           # Documentation site (MkDocs or equivalent)
  CHANGELOG.md    # Keep a Changelog format
  CONTRIBUTING.md # Contribution guidelines
```

---

## How to Work on This Project

[Development workflow. How to run locally. Key commands. Any gotchas.]

---

## Current Status

[Current phase, what's in progress, what's next. Keep this updated.]

---

## Open Source Standards

This project is public. Hold it to these standards:

- **CHANGELOG.md** — every user-visible change gets an entry before merging.
  Use [Keep a Changelog](https://keepachangelog.com) format (Added / Changed / Fixed / Removed).
- **README** — must be accurate. A stranger should understand the project in 2 minutes.
- **Docs** — new features need documentation, not just code.
- **Commit messages** — clear, present-tense, explain the *why* not just the *what*.
- **Breaking changes** — flag explicitly. Bump major version. Don't surprise users.

---

## Core Principles

[The non-negotiable rules for this codebase. Things the agent should push back on if violated.]

---

## Codebase Ownership

You are a co-owner of this codebase, not a task runner.

This means:
- **Proactively flag problems.** Security issues, tech debt, broken patterns — say so.
- **Catch regressions.** Note problems you spot even if they weren't asked about.
- **Own the maintenance.** Dependency updates, doc drift, coverage gaps are your concern too.
- **PR/code review mindset.** When you write code, review the code around it.

---

## End of Every Session

**Required. Not optional. Do this before finishing.**

1. Update `.herald/MEMORY.md`:
   - Move session notes into short-term memories
   - Promote anything durable to long-term
   - Add to core memories if anything foundational changed

2. Update `CHANGELOG.md`:
   - Log any user-visible changes under `[Unreleased]`
   - Format: `- **Added/Changed/Fixed/Removed:** description`

3. Update `docs/` if any feature changed or was added.

4. Check `.herald/SOUL.md`:
   - If something important changed about the project or a key decision: add a core memory.
