"""
agent_runner.py — Wraps the Claude Code CLI for non-interactive agent runs.

Invokes:
  cd <project_path> && claude -p "<task>" --print --dangerously-skip-permissions \
      --output-format json [--model <model>] [--max-turns <n>]

--dangerously-skip-permissions is required for non-interactive runs. Without it,
Claude Code will pause at permission prompts and hang indefinitely.

--output-format json gives us structured output including actual token counts
(input + output tokens from the Anthropic API). The CLI outputs newline-delimited
JSON; we parse the final "result" record to extract text and usage.

stdout is the agent's output (JSON lines).
stderr is Claude Code's diagnostic/tool-use logging (captured separately).
"""

import asyncio
import json
import logging
import os

log = logging.getLogger(__name__)

# Default timeout for a single agent run. Long tasks (e.g. code generation) can take
# several minutes. 10 minutes is generous but bounded.
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("HERALD_AGENT_TIMEOUT", "600"))

# The Claude Code CLI binary name. Override via env if it's not on PATH.
CLAUDE_BIN = os.environ.get("HERALD_CLAUDE_BIN", "claude")

# Discord has a 2000-char message limit. We truncate output to leave room for formatting.
DISCORD_MAX_CHARS = 1900


def _parse_json_output(raw: str) -> tuple[str, int]:
    """
    Parse --output-format json output from the Claude Code CLI.

    The CLI emits newline-delimited JSON. Each line is a separate JSON object.
    The final line with type="result" contains the agent's answer and token usage.

    Returns (result_text, total_tokens). Falls back gracefully if the format is
    unexpected (returns raw text and 0 tokens) — e.g. when claude itself errors out
    and emits plain text instead of JSON.
    """
    result_text = raw.strip()
    total_tokens = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") == "result":
            result_text = obj.get("result", raw.strip())
            usage = obj.get("usage", {})
            total_tokens = (
                usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0)
            )
            break

    return result_text, total_tokens


async def run_agent(
    project_path: str,
    task: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    model: str | None = None,
    max_turns: int | None = None,
) -> tuple[str, int]:
    """
    Run the Claude Code CLI non-interactively in project_path with the given task.

    Returns (output_text, total_tokens). Never raises — errors are embedded in the
    return value so the caller can forward them to Discord without crashing the queue.

    Args:
        project_path: Absolute path to the project directory.
        task: The prompt passed to the agent via -p.
        timeout: Seconds before the process is killed (default: HERALD_AGENT_TIMEOUT).
        model: Optional Claude model override (e.g. "claude-opus-4-5"). Uses the
               Claude Code default if not set.
        max_turns: Optional cap on agentic iterations. Prevents runaway tasks that
                   would otherwise loop indefinitely. None = Claude Code default.
    """
    cmd = [
        CLAUDE_BIN,
        "-p", task,
        "--print",
        "--dangerously-skip-permissions",   # required for non-interactive runs
        "--output-format", "json",           # structured output with token counts
    ]
    if model:
        cmd += ["--model", model]
    if max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
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
            return f"[TIMEOUT] Agent run exceeded {timeout}s and was killed.", 0

        raw_output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            # Include both stdout (partial output) and stderr (error detail)
            parts = [f"[ERROR — exit code {proc.returncode}]"]
            if error:
                parts.append(error)
            if raw_output.strip():
                parts.append(raw_output.strip())
            return "\n\n".join(parts), 0

        if not raw_output.strip():
            return "[No output — agent returned nothing]", 0

        return _parse_json_output(raw_output)

    except FileNotFoundError:
        return (
            f"[ERROR] Claude Code CLI not found at '{CLAUDE_BIN}'. "
            "Is it installed and on PATH?"
        ), 0
    except Exception as e:
        return f"[ERROR] Unexpected exception running agent: {type(e).__name__}: {e}", 0


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
