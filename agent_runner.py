"""
agent_runner.py — Wraps the Claude Code CLI for non-interactive agent runs.

Invokes: cd <project_path> && claude -p "<task>" --print

The agent runs with full access to Claude Code's tools (Read, Write, Edit, Bash, etc.)
and reads the project's CLAUDE.md for context automatically.

stdout is the agent's output (the final response).
stderr is Claude Code's diagnostic/tool-use logging (captured separately).
"""

import asyncio
import os


# Default timeout for a single agent run. Long tasks (e.g. code generation) can take
# several minutes. 10 minutes is generous but bounded.
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("HERALD_AGENT_TIMEOUT", "600"))

# The Claude Code CLI binary name. Override via env if it's not on PATH.
CLAUDE_BIN = os.environ.get("HERALD_CLAUDE_BIN", "claude")

# Discord has a 2000-char message limit. We truncate output to leave room for formatting.
DISCORD_MAX_CHARS = 1900


async def run_agent(project_path: str, task: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """
    Run the Claude Code CLI non-interactively in project_path with the given task.

    Returns the agent's output as a string. Never raises — errors are embedded in the
    return value so the caller can forward them to Discord without crashing the queue.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN,
            "-p", task,
            "--print",
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Pass through the current environment so ANTHROPIC_API_KEY reaches Claude Code.
            env=os.environ.copy(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain pipes to avoid ResourceWarning
            return f"[TIMEOUT] Agent run exceeded {timeout}s and was killed."

        output = stdout.decode(errors="replace").strip()
        error = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            # Include both stdout (partial output) and stderr (error detail)
            parts = [f"[ERROR — exit code {proc.returncode}]"]
            if error:
                parts.append(error)
            if output:
                parts.append(output)
            return "\n\n".join(parts)

        return output or "[No output — agent returned nothing]"

    except FileNotFoundError:
        return (
            f"[ERROR] Claude Code CLI not found at '{CLAUDE_BIN}'. "
            "Is it installed and on PATH?"
        )
    except Exception as e:
        return f"[ERROR] Unexpected exception running agent: {type(e).__name__}: {e}"


def truncate_for_discord(text: str, max_chars: int = DISCORD_MAX_CHARS) -> str:
    """
    Truncate text to fit Discord's 2000-char message limit.

    Appends a truncation notice if the text was cut.
    """
    if len(text) <= max_chars:
        return text
    cutoff = max_chars - 50
    return text[:cutoff] + f"\n\n… [truncated — {len(text) - cutoff} chars omitted]"


# Patterns that indicate the Anthropic API refused the request due to usage/rate limits.
# The claude CLI embeds these in stderr or stdout when it can't start a run.
_USAGE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "credit balance",
    "quota exceeded",
    "overloaded_error",
    "too many requests",
)


def is_usage_limit_error(output: str) -> bool:
    """
    Return True if the agent output looks like a usage/rate limit refusal.

    Used by callers to decide whether to post an error message or skip quietly.
    Scheduled tasks skip silently on limit errors; interactive runs still report them.
    """
    lowered = output.lower()
    return any(pattern in lowered for pattern in _USAGE_LIMIT_PATTERNS)
