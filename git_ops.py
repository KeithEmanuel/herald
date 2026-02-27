"""
git_ops.py — Git operations for Herald's push-approval flow.

After each agent run, Herald checks whether the agent created any new commits
on an `agent/*` branch that haven't been pushed yet. If so, it posts a push
proposal to Discord and waits for the operator's 👍 or 👎 reaction.

All operations are synchronous subprocess calls — they run quickly and don't
need to be async. The queue worker awaits them implicitly via run_in_executor
if needed, but for now direct subprocess is fine since git ops are fast.
"""

import logging
import subprocess

log = logging.getLogger(__name__)


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command in cwd, capturing output. Never raises on non-zero exit."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def get_unpushed_agent_branches(repo_path: str, branch_prefix: str) -> list[dict]:
    """
    Find local branches matching branch_prefix that have unpushed commits.

    Returns a list of dicts: [{"branch": str, "commits": [str, ...]}]
    Each commit is a one-line summary (hash + message).
    """
    # List all local branches
    result = _run_git(["branch", "--format=%(refname:short)"], cwd=repo_path)
    if result.returncode != 0:
        log.warning("git branch failed in %s: %s", repo_path, result.stderr)
        return []

    agent_branches = [
        b.strip()
        for b in result.stdout.splitlines()
        if b.strip().startswith(branch_prefix)
    ]

    if not agent_branches:
        return []

    unpushed = []
    for branch in agent_branches:
        commits = _get_unpushed_commits(repo_path, branch)
        if commits:
            unpushed.append({"branch": branch, "commits": commits})

    return unpushed


def _get_unpushed_commits(repo_path: str, branch: str) -> list[str]:
    """
    Return one-line commit summaries for commits on branch not yet pushed to origin.

    Falls back to comparing against main/master if the remote branch doesn't exist.
    """
    # First try: compare against the remote tracking branch
    result = _run_git(
        ["log", f"origin/{branch}..{branch}", "--oneline"],
        cwd=repo_path,
    )

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()

    # If origin/{branch} doesn't exist (never pushed), compare against main
    for base in ("main", "master"):
        result = _run_git(
            ["log", f"{base}..{branch}", "--oneline"],
            cwd=repo_path,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()

    return []


def push_branch(repo_path: str, branch: str) -> tuple[bool, str]:
    """
    Push branch to origin. Returns (success: bool, message: str).
    """
    result = _run_git(["push", "origin", branch], cwd=repo_path)
    if result.returncode == 0:
        msg = result.stdout.strip() or f"Branch `{branch}` pushed successfully."
        log.info("Pushed %s in %s", branch, repo_path)
        return True, msg
    else:
        log.error("Failed to push %s: %s", branch, result.stderr)
        return False, result.stderr.strip() or "Push failed (no output from git)."


def delete_branch(repo_path: str, branch: str) -> tuple[bool, str]:
    """
    Delete a local branch (discard agent work). Returns (success: bool, message: str).
    """
    result = _run_git(["branch", "-D", branch], cwd=repo_path)
    if result.returncode == 0:
        log.info("Deleted branch %s in %s", branch, repo_path)
        return True, f"Branch `{branch}` discarded."
    else:
        log.error("Failed to delete %s: %s", branch, result.stderr)
        return False, result.stderr.strip() or "Delete failed (no output from git)."
