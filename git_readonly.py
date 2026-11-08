"""Bounded, read-only Git inspection for the Personal AI Brain repository.

This module intentionally exposes a small operation enum instead of accepting
arbitrary Git arguments or shell command strings.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

REPO_ROOT = os.path.realpath(os.path.expanduser("~/personal_ai_brain"))
MAX_OUTPUT_CHARS = 12000
COMMANDS = {
    "status": [
        "status", "--short", "--branch", "--untracked-files=normal",
    ],
    "diff": [
        "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--",
    ],
    "log": [
        "log", "--oneline", "--no-decorate", "-n", "10",
    ],
    "show": [
        "show", "--no-ext-diff", "--no-textconv", "--no-color",
        "--stat", "--oneline", "HEAD",
    ],
}


def inspect_repo(params: Any) -> dict:
    """Run one fixed Git read operation in the configured Brain repository."""
    if not isinstance(params, dict):
        return {"ok": False, "result": None, "error": "INVALID_PARAMETERS"}

    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in COMMANDS:
        return {
            "ok": False,
            "result": None,
            "error": "INVALID_OPERATION: expected status, diff, log, or show",
        }

    # Reject extra parameters: callers cannot inject paths, revisions, or flags.
    if set(params) != {"operation"}:
        return {"ok": False, "result": None, "error": "UNSUPPORTED_PARAMETERS"}

    repo_root = os.path.realpath(REPO_ROOT)
    if not os.path.isdir(repo_root):
        return {"ok": False, "result": None, "error": "REPOSITORY_DIRECTORY_MISSING"}
    if not os.path.exists(os.path.join(repo_root, ".git")):
        return {"ok": False, "result": None, "error": "GIT_METADATA_NOT_FOUND"}

    argv = [
        "git", "--no-pager", "--no-optional-locks", "-C", repo_root,
        *COMMANDS[operation],
    ]
    env = os.environ.copy()
    env.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    })

    try:
        completed = subprocess.run(
            argv,
            cwd=repo_root,
            env=env,
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": "GIT_INSPECTION_TIMEOUT"}
    except OSError as error:
        return {
            "ok": False,
            "result": None,
            "error": f"GIT_INSPECTION_OS_ERROR: {type(error).__name__}",
        }

    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        error_text = (completed.stderr or "").strip()[:1000]
        return {
            "ok": False,
            "result": output or None,
            "error": f"GIT_EXIT_{completed.returncode}: {error_text}",
        }

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n... [OUTPUT_TRUNCATED]"

    return {
        "ok": True,
        "result": output or "(no output)",
        "error": None,
        "operation": operation,
    }
