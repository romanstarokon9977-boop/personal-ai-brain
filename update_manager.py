#!/usr/bin/env python3
"""Read-only update inspection for Personal AI Brain.

This first-stage manager never fetches, checks out, merges, writes, or installs.
It reports local Git state, the public origin/main head, GitHub comparison data,
and CI evidence for the exact remote commit.
"""
from __future__ import annotations

import argparse
import json
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
USER_AGENT = "Personal-AI-Brain-Update-Manager/1.0"


class UpdateManagerError(RuntimeError):
    """Raised when required local repository information is unavailable."""


def run_git(args: list[str], cwd: str | Path | None = None) -> str:
    """Run a read-only Git command and return stdout."""
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        # Do not include arbitrary stderr: it may contain credential-bearing URLs.
        raise UpdateManagerError(f"Git command failed: git {' '.join(args)}")
    return completed.stdout.strip()


def github_get(path: str, timeout: int = 15) -> dict[str, Any]:
    """Read a public GitHub API endpoint without credentials or external packages."""
    request = urllib.request.Request(
        API_BASE + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {"_error": "Unexpected API response"}
    except urllib.error.HTTPError as exc:
        return {"_error": f"GitHub API HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {"_error": "GitHub API unavailable or returned invalid data"}


def parse_porcelain_status(output: str) -> list[tuple[str, str]]:
    """Return (status, path) entries without exposing file contents."""
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) >= 4:
            entries.append((line[:2], line[3:]))
    return entries


def parse_ls_remote(output: str) -> str:
    """Extract the SHA for refs/heads/main from git ls-remote output."""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{DEFAULT_BRANCH}":
            sha = parts[0]
            if len(sha) == 40 and all(ch in "0123456789abcdef" for ch in sha.lower()):
                return sha
    raise UpdateManagerError("Could not resolve origin/main")


def collect_report(
    cwd: str | Path | None = None,
    repository: str = DEFAULT_REPOSITORY,
    git_runner=run_git,
    api_reader=github_get,
) -> dict[str, Any]:
    """Collect a read-only update report. Network/API failures remain explicit."""
    root = git_runner(["rev-parse", "--show-toplevel"], cwd)
    local_sha = git_runner(["rev-parse", "HEAD"], cwd)
    branch = git_runner(["branch", "--show-current"], cwd) or "(detached HEAD)"
    status_output = git_runner(["status", "--porcelain=v1", "--untracked-files=all"], cwd)
    dirty_entries = parse_porcelain_status(status_output)

    remote_output = git_runner(
        ["ls-remote", "--exit-code", "origin", f"refs/heads/{DEFAULT_BRANCH}"],
        cwd,
    )
    remote_sha = parse_ls_remote(remote_output)

    report: dict[str, Any] = {
        "repository": repository,
        "root": root,
        "branch": branch,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "dirty_entries": dirty_entries,
        "comparison": None,
        "ci": None,
    }

    if local_sha == remote_sha:
        report["comparison"] = {
            "status": "identical",
            "ahead_by": 0,
            "behind_by": 0,
            "commits": [],
            "files": [],
        }
    else:
        compare_path = (
            f"/repos/{repository}/compare/"
            f"{urllib.parse.quote(local_sha, safe='')}...{urllib.parse.quote(remote_sha, safe='')}"
        )
        comparison = api_reader(compare_path)
        if "_error" in comparison:
            report["comparison"] = {"status": "unavailable", "reason": comparison["_error"]}
        else:
            report["comparison"] = {
                "status": comparison.get("status", "unknown"),
                "ahead_by": comparison.get("ahead_by"),
                "behind_by": comparison.get("behind_by"),
                "commits": [
                    {
                        "sha": (item.get("sha") or "")[:12],
                        "message": ((item.get("commit") or {}).get("message") or "").splitlines()[0],
                    }
                    for item in comparison.get("commits", [])
                    if isinstance(item, dict)
                ],
                "files": [
                    {
                        "path": item.get("filename", ""),
                        "status": item.get("status", "unknown"),
                        "additions": item.get("additions", 0),
                        "deletions": item.get("deletions", 0),
                    }
                    for item in comparison.get("files", [])
                    if isinstance(item, dict)
                ],
            }

    ci_path = (
        f"/repos/{repository}/actions/workflows/python-ci.yml/runs?"
        f"head_sha={urllib.parse.quote(remote_sha, safe='')}&per_page=10"
    )
    ci_data = api_reader(ci_path)
    if "_error" in ci_data:
        report["ci"] = {"state": "unknown", "reason": ci_data["_error"]}
    else:
        matching_runs = [
            run for run in ci_data.get("workflow_runs", [])
            if isinstance(run, dict) and run.get("head_sha") == remote_sha
        ]
        if not matching_runs:
            report["ci"] = {
                "state": "not_verified",
                "reason": "No workflow run found for the exact origin/main commit",
            }
        else:
            latest = matching_runs[0]
            report["ci"] = {
                "state": latest.get("conclusion") or latest.get("status") or "unknown",
                "run_id": latest.get("id"),
                "html_url": latest.get("html_url"),
                "event": latest.get("event"),
                "head_sha": latest.get("head_sha"),
            }

    return report


def format_report(report: dict[str, Any]) -> str:
    """Format a concise report; never print environment variables or file contents."""
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
        lines.append(
            f"  Commits: ahead_by={comparison['ahead_by']}, "
            f"behind_by={comparison.get('behind_by')}"
        )
    for commit in comparison.get("commits", []):
        lines.append(f"  COMMIT {commit['sha']} {commit['message']}")
    for item in comparison.get("files", []):
        lines.append(
            f"  FILE {item['status']} {item['path']} "
            f"(+{item['additions']}/-{item['deletions']})"
        )

    ci = report.get("ci") or {}
    lines.append(f"CI for exact origin/main commit: {ci.get('state', 'unknown')}")
    if ci.get("reason"):
        lines.append(f"  Reason: {ci['reason']}")
    if ci.get("run_id") is not None:
        lines.append(f"  Run ID: {ci['run_id']}")
        lines.append(f"  Event: {ci.get('event', 'unknown')}")
        lines.append(f"  Run: {ci.get('html_url', '')}")

    lines.extend([
        "",
        "SAFETY: no fetch, checkout, merge, reset, stash, file write, or installation was performed.",
        "This report does not authorize an update.",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Personal AI Brain update check"
    )
    parser.add_argument(
        "command",
        choices=("check",),
        help="check remote version, local Git state, changed files, and exact-commit CI",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPOSITORY,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    try:
        report = collect_report(repository=args.repo)
    except (UpdateManagerError, subprocess.TimeoutExpired) as exc:
        print(f"UPDATE CHECK FAILED: {exc}", file=sys.stderr)
        return 2

    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
