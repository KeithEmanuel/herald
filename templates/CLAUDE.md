# CLAUDE.md — [Project Name]

> Read SOUL.md and MEMORY.md before doing anything else this session.
> SOUL.md is the agent's identity. MEMORY.md is the working context.
> Both are maintained by the agent. Don't skip them.

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
```

---

## How to Work on This Project

[Development workflow. How to run locally. Key commands. Any gotchas.]

---

## Current Status

[Current phase, what's in progress, what's next. Keep this updated — it's the first thing
the agent checks to understand where we are.]

---

## Core Principles

[The non-negotiable rules for this codebase. Things the agent should push back on if
violated. Examples:
- "All business logic in services/, not in routes/"
- "No raw SQL — use the ORM"
- "Feature flags before A/B anything"
]

---

## Hard Constraints

*If this project has compliance, contract, or security constraints — list them here.
The agent treats these as non-negotiable and will flag any changes that touch them.*

[Remove this section if not applicable.]

---

## End of Every Session

**Required. Not optional. Do this before finishing.**

1. Update MEMORY.md:
   - Move session notes into short-term memories
   - Promote anything from short-term that has aged into long-term
   - Add to core memories if anything foundational changed

2. Update TASKS.md (if it exists):
   - Mark completed tasks done
   - Add any new requests that came up this session
   - Note who requested what

3. Update CHANGELOG.md:
   - Log any changes that shipped
   - Include: what changed, who requested it, who implemented it

4. Check SOUL.md:
   - If something important changed about the project, the relationship, or a key decision:
     add a core memory
