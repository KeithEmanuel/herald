# Herald Agent Pattern — Starter Templates

Copy these files to bootstrap a new project with the Herald agent pattern.

## Minimum setup (solo dev, greenfield)

```bash
cp templates/SOUL.md     your-project/SOUL.md
cp templates/CLAUDE.md   your-project/CLAUDE.md
cp templates/MEMORY.md   your-project/MEMORY.md
cp -r templates/humans/  your-project/humans/
```

Add to `your-project/.gitignore`:
```
humans/
!humans/template.md
```

Then open Claude Code in your project and say:
> "Read CLAUDE.md. Then read SOUL.md and fill in your identity — name yourself, describe
> your role on this project, and note anything you can already infer about the codebase.
> You'll update it over time."

That's it. The agent writes its own soul on first session and maintains everything from there.

## Files

| File | Purpose | In git? |
|---|---|---|
| `CLAUDE.md` | Project context + agent instructions | Yes |
| `SOUL.md` | Agent identity and core memories | Yes |
| `MEMORY.md` | Tiered working memory (core/long/short/session) | Yes |
| `humans/template.md` | Schema for contributor profiles | Yes |
| `humans/<name>.md` | Per-contributor context (create on first use) | No (gitignored) |

## Full pattern documentation

See `docs/agent-pattern.md` for the complete spec including optional files,
enterprise additions, changelog attribution format, and Herald integration.
