#!/usr/bin/env python3
"""Safe, opt-in-by-policy fast-forward updater for Personal AI Brain startup.

The updater only applies the public repository's main branch when the local
checkout is clean, on main, fast-forwardable, and the exact target commit has
a successful Python 3.11 CI check. It never resets, cleans, stashes, or force
updates the worktree.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

REPOSITORY = "romanstarokon9977-boop/personal-ai-brain"
EXPECTED_REMOTE = (
    "https://github.com/romanstarokon9977-boop/personal-ai-brain.git",
    "https://github.com/romanstarokon9977-boop/personal-ai-brain",
    "git@github.com:romanstarokon9977-boop/personal-ai-brain.git",
    "ssh://git@github.com/romanstarokon9977-boop/personal-ai-brain.git",
)
CI_CHECK_NAME = "Python 3.11 checks"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


class AutoUpdateError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def _git(args: list[str], *, cwd: Path, timeout: int = 30) -> str:
    result = _run(["git", *args], cwd=cwd, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise AutoUpdateError(detail[:500])
    return (result.stdout or "").strip()


def normalize_remote(value: str) -> str:
    value = (value or "").strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    elif value.startswith("ssh://git@github.com/"):
        value = "https://github.com/" + value[len("ssh://git@github.com/"):]
    return value.rstrip("/").lower()


def is_expected_remote(value: str) -> bool:
    expected = {normalize_remote(item) for item in EXPECTED_REMOTE}
    return normalize_remote(value) in expected


def ci_is_successful(payload: dict) -> bool:
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        return False
    matching = [
        item for item in runs
        if isinstance(item, dict) and item.get("name") == CI_CHECK_NAME
    ]
    return bool(matching) and all(
        item.get("status") == "completed"
        and item.get("conclusion") == "success"
        for item in matching
    )


def _exact_commit_ci_ok(repo_root: Path, sha: str) -> bool:
    if not _SHA_RE.fullmatch(sha):
        return False
    result = _run(
        ["gh", "api", f"repos/{REPOSITORY}/commits/{sha}/check-runs"],
        cwd=repo_root,
        timeout=25,
    )
    if result.returncode:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except (TypeError, ValueError):
        return False
    return ci_is_successful(payload)


def apply_update_if_safe(repo_root: str | os.PathLike | None = None) -> dict:
    """Attempt one guarded fast-forward. Any uncertainty means no update."""
    root = Path(repo_root or Path(__file__).resolve().parent).resolve()

    try:
        top = Path(_git(["rev-parse", "--show-toplevel"], cwd=root)).resolve()
        if top != root:
            return {"status": "skipped", "reason": "not_repository_root"}

        branch = _git(["branch", "--show-current"], cwd=root)
        if branch != "main":
            return {"status": "skipped", "reason": "not_on_main"}

        remote = _git(["remote", "get-url", "origin"], cwd=root)
        if not is_expected_remote(remote):
            return {"status": "skipped", "reason": "unexpected_origin"}

        dirty = _git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
        if dirty:
            return {"status": "skipped", "reason": "working_tree_not_clean"}

        _git(["fetch", "--no-tags", "origin", "main"], cwd=root, timeout=60)
        current = _git(["rev-parse", "HEAD"], cwd=root)
        target = _git(["rev-parse", "refs/remotes/origin/main"], cwd=root)

        if not _SHA_RE.fullmatch(current) or not _SHA_RE.fullmatch(target):
            return {"status": "skipped", "reason": "invalid_commit_id"}
        if current == target:
            return {"status": "current", "commit": current}

        ancestor = _run(
            ["git", "merge-base", "--is-ancestor", current, target],
            cwd=root,
            timeout=15,
        )
        if ancestor.returncode != 0:
            return {"status": "skipped", "reason": "not_fast_forward"}

        # Do not update until the exact main commit has passed the required CI job.
        if not _exact_commit_ci_ok(root, target):
            return {"status": "skipped", "reason": "ci_not_successful"}

        backup_dir = Path.home() / "AI_Brain_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = backup_dir / f"brain_pre_update_{stamp}_{current[:8]}.bundle"
        _git(["bundle", "create", str(backup), "--all"], cwd=root, timeout=120)
        _git(["bundle", "verify", str(backup)], cwd=root, timeout=30)

        # Recheck immediately before mutation; never overwrite concurrent user work.
        dirty = _git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
        if dirty or _git(["rev-parse", "HEAD"], cwd=root) != current:
            return {"status": "skipped", "reason": "worktree_changed_during_update"}

        _git(["merge", "--ff-only", "origin/main"], cwd=root, timeout=60)
        installed = _git(["rev-parse", "HEAD"], cwd=root)
        if installed != target:
            return {
                "status": "error",
                "reason": "installed_sha_mismatch",
                "backup": str(backup),
            }
        return {
            "status": "updated",
            "from": current,
            "to": installed,
            "backup": str(backup),
        }
    except (AutoUpdateError, OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "skipped", "reason": "safe_update_check_failed", "detail": str(exc)[:300]}
