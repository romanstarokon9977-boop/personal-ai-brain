#!/usr/bin/env python3
"""Read-only update inspection for Personal AI Brain.

This stage never fetches, checks out, merges, writes, installs, or rolls back.
It verifies repository identity, reports local Git state, compares origin/main,
and checks CI evidence for the exact remote commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "romanstarokon9977-boop/personal-ai-brain"
DEFAULT_BRANCH = "main"
API_BASE = "https://api.github.com"
USER_AGENT = "Personal-AI-Brain-Update-Manager/1.1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


class UpdateManagerError(RuntimeError):
    """Raised when required local repository information is unavailable."""


def run_git(args: list[str], cwd: str | Path | None = None) -> str:
    """Run a Git inspection command; never expose stderr or credential-bearing URLs."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd is not None else None,
            check=False, capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateManagerError(f"Git command timed out: git {args[0]}") from exc
    except OSError as exc:
        raise UpdateManagerError("Git executable is unavailable") from exc
    if completed.returncode != 0:
        raise UpdateManagerError(f"Git command failed: git {' '.join(args)}")
    return completed.stdout.strip()


def normalize_github_remote(remote_url: str) -> str:
    """Return owner/repo for standard GitHub HTTPS or SSH remote URLs."""
    value = remote_url.strip()
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?", value, re.I)
    if not match:
        raise UpdateManagerError("origin is not a supported github.com HTTPS/SSH URL")
    owner_repo = match.group(1)
    if any(part in ("", ".", "..") for part in owner_repo.split("/")):
        raise UpdateManagerError("origin repository URL is invalid")
    return owner_repo.lower()


def github_get(path: str, timeout: int = 15) -> dict[str, Any]:
    """Read GitHub API data using GH_TOKEN/GITHUB_TOKEN, gh auth, or public access."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token and shutil.which("gh"):
        try:
            completed = subprocess.run(
                ["gh", "api", path.lstrip("/")], check=False,
                capture_output=True, text=True, timeout=timeout,
            )
            if completed.returncode != 0:
                return {"_error": "GitHub CLI request failed; check gh auth status and token permissions"}
            payload = json.loads(completed.stdout)
            return payload if isinstance(payload, dict) else {"_error": "Unexpected GitHub API response type"}
        except subprocess.TimeoutExpired:
            return {"_error": "GitHub CLI request timed out"}
        except (json.JSONDecodeError, OSError):
            return {"_error": "GitHub CLI unavailable or returned invalid data"}

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API_BASE + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {"_error": "Unexpected GitHub API response type"}
    except urllib.error.HTTPError as exc:
        descriptions = {
            401: "GitHub API HTTP 401: authentication failed",
            403: "GitHub API HTTP 403: access denied or rate limit reached",
            404: "GitHub API HTTP 404: resource unavailable or repository not accessible",
        }
        return {"_error": descriptions.get(exc.code, f"GitHub API HTTP {exc.code}")}
    except urllib.error.URLError:
        return {"_error": "GitHub API network connection failed"}
    except (TimeoutError, json.JSONDecodeError, OSError):
        return {"_error": "GitHub API timed out or returned invalid data"}


def parse_porcelain_status(output: str) -> list[tuple[str, str]]:
    """Return (status, path) entries without reading or exposing file contents."""
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) >= 4:
            entries.append((line[:2], line[3:]))
    return entries


def parse_ls_remote(output: str) -> str:
    """Extract the full SHA for refs/heads/main from git ls-remote output."""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{DEFAULT_BRANCH}" and _SHA_RE.fullmatch(parts[0]):
            return parts[0].lower()
    raise UpdateManagerError("Could not resolve a valid origin/main SHA")


def classify_ci_run(run: dict[str, Any]) -> str:
    """Normalize GitHub Actions run status/conclusion without treating pending as success."""
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status != "completed":
        return str(status or "unknown")
    return str(conclusion or "unknown")


def collect_report(
    cwd: str | Path | None = None,
    repository: str = DEFAULT_REPOSITORY,
    git_runner=run_git,
    api_reader=github_get,
) -> dict[str, Any]:
    """Collect a read-only report. Any identity or evidence uncertainty fails closed."""
    if not re.fullmatch(r"[^/]+/[^/]+", repository):
        raise UpdateManagerError("Repository must be specified as owner/name")

    root = git_runner(["rev-parse", "--show-toplevel"], cwd)
    local_sha = git_runner(["rev-parse", "HEAD"], cwd).lower()
    if not _SHA_RE.fullmatch(local_sha):
        raise UpdateManagerError("Local HEAD is not a valid commit SHA")
    branch = git_runner(["branch", "--show-current"], cwd) or "(detached HEAD)"
    status_output = git_runner(["status", "--porcelain=v1", "--untracked-files=all"], cwd)
    dirty_entries = parse_porcelain_status(status_output)

    remote_url = git_runner(["remote", "get-url", "origin"], cwd)
    actual_repository = normalize_github_remote(remote_url)
    if actual_repository != repository.lower():
        raise UpdateManagerError(
            f"Repository identity mismatch: expected {repository}, origin points to {actual_repository}"
        )

    remote_output = git_runner(
        ["ls-remote", "--exit-code", "origin", f"refs/heads/{DEFAULT_BRANCH}"], cwd
    )
    remote_sha = parse_ls_remote(remote_output)

    report: dict[str, Any] = {
        "repository": repository, "root": root, "branch": branch,
        "local_sha": local_sha, "remote_sha": remote_sha,
        "dirty_entries": dirty_entries, "comparison": None, "ci": None,
    }

    if local_sha == remote_sha:
        report["comparison"] = {
            "status": "identical", "ahead_by": 0, "behind_by": 0,
            "commits": [], "files": [],
        }
    else:
        compare_path = (
            f"/repos/{repository}/compare/"
            f"{urllib.parse.quote(local_sha, safe='')}...{urllib.parse.quote(remote_sha, safe='')}"
        )
        comparison = api_reader(compare_path)
        if not isinstance(comparison, dict) or "_error" in comparison:
            reason = comparison.get("_error", "Unexpected comparison response") if isinstance(comparison, dict) else "Unexpected comparison response"
            report["comparison"] = {"status": "unavailable", "reason": reason}
        else:
            report["comparison"] = {
                "status": comparison.get("status", "unknown"),
                "ahead_by": comparison.get("ahead_by"),
                "behind_by": comparison.get("behind_by"),
                "commits": [
                    {"sha": (item.get("sha") or "")[:12],
                     "message": ((item.get("commit") or {}).get("message") or "").splitlines()[0]}
                    for item in comparison.get("commits", []) if isinstance(item, dict)
                ],
                "files": [
                    {"path": item.get("filename", ""), "status": item.get("status", "unknown"),
                     "additions": item.get("additions", 0), "deletions": item.get("deletions", 0)}
                    for item in comparison.get("files", []) if isinstance(item, dict)
                ],
            }

    ci_path = (
        f"/repos/{repository}/actions/workflows/python-ci.yml/runs?"
        f"head_sha={urllib.parse.quote(remote_sha, safe='')}&per_page=10"
    )
    ci_data = api_reader(ci_path)
    if not isinstance(ci_data, dict) or "_error" in ci_data:
        reason = ci_data.get("_error", "Unexpected Actions response") if isinstance(ci_data, dict) else "Unexpected Actions response"
        report["ci"] = {"state": "unknown", "reason": reason}
    elif not isinstance(ci_data.get("workflow_runs", []), list):
        report["ci"] = {"state": "unknown", "reason": "Malformed Actions response: workflow_runs is not a list"}
    else:
        matching_runs = [
            item for item in ci_data.get("workflow_runs", [])
            if isinstance(item, dict) and item.get("head_sha") == remote_sha
        ]
        if not matching_runs:
            report["ci"] = {
                "state": "not_verified",
                "reason": "No workflow run found for the exact origin/main commit",
            }
        else:
            latest = matching_runs[0]
            report["ci"] = {
                "state": classify_ci_run(latest), "run_id": latest.get("id"),
                "html_url": latest.get("html_url"), "event": latest.get("event"),
                "head_sha": latest.get("head_sha"),
            }

    return report


def format_report(report: dict[str, Any]) -> str:
    """Format report without printing environment variables, tokens, or file contents."""
    lines = [
        "PERSONAL AI BRAIN — UPDATE CHECK (READ-ONLY)",
        f"Repository: {report['repository']}",
        f"Local root: {report['root']}",
        f"Local branch: {report['branch']}",
        f"Local HEAD: {report['local_sha']}",
        f"GitHub origin/main: {report['remote_sha']}",
    ]
    dirty = report["dirty_entries"]
    lines.append(f"Working tree: {'DIRTY' if dirty else 'CLEAN'} ({len(dirty)} entries)")
    for status, path in dirty:
        lines.append(f"  LOCAL {status} {path}")

    comparison = report.get("comparison") or {}
    lines.append(f"Remote comparison: {comparison.get('status', 'unknown')}")
    if comparison.get("reason"):
        lines.append(f"  Reason: {comparison['reason']}")
    if comparison.get("ahead_by") is not None:
        lines.append(f"  Commits: ahead_by={comparison['ahead_by']}, behind_by={comparison.get('behind_by')}")
    for commit in comparison.get("commits", []):
        lines.append(f"  COMMIT {commit['sha']} {commit['message']}")
    for item in comparison.get("files", []):
        lines.append(f"  FILE {item['status']} {item['path']} (+{item['additions']}/-{item['deletions']})")

    ci = report.get("ci") or {}
    lines.append(f"CI for exact origin/main commit: {ci.get('state', 'unknown')}")
    if ci.get("reason"):
        lines.append(f"  Reason: {ci['reason']}")
    if ci.get("run_id") is not None:
        lines.append(f"  Run ID: {ci['run_id']}")
        lines.append(f"  Event: {ci.get('event', 'unknown')}")
        lines.append(f"  Run: {ci.get('html_url', '')}")

    lines.extend([
        "", "SAFETY: read-only inspection only; no fetch, checkout, merge, reset, stash, file write, install, or rollback.",
        "A report never authorizes an update.",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Personal AI Brain update check")
    parser.add_argument("command", choices=("check",), help="inspect remote version, local Git state, and exact-commit CI")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        report = collect_report(repository=args.repo)
    except UpdateManagerError as exc:
        print(f"UPDATE CHECK FAILED: {exc}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
