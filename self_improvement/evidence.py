"""Independent GitHub Actions evidence validation for P6.6.

The caller's test result is a claim, never proof. This module retrieves the
workflow, run, and job metadata from GitHub and fails closed on uncertainty.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Callable
from urllib.parse import quote

from update_manager import github_get

EXPECTED_REPOSITORY_ID = 1381206490
WORKFLOW_PATH = ".github/workflows/python-ci.yml"
EXPECTED_JOB_NAME = "Python 3.11 checks"
_ALLOWED_BRANCH_PREFIXES = ("ci/", "work/", "development/", "feature/", "feat/", "fix/")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_TEST_REF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.py::(test_[A-Za-z0-9_]+)$")


def _get(api_reader: Callable[[str], dict[str, Any]], path: str) -> dict[str, Any]:
    try:
        value = api_reader(path)
    except Exception:
        return {"_error": "GitHub API request failed"}
    return value if isinstance(value, dict) else {"_error": "Malformed GitHub API response"}


def _content_sha(api_reader: Callable[[str], dict[str, Any]], repository: str,
                 ref: str) -> tuple[str | None, str | None]:
    path = f"/repos/{repository}/contents/{quote(WORKFLOW_PATH, safe='/')}?ref={quote(ref, safe='')}"
    data = _get(api_reader, path)
    if "_error" in data:
        return None, str(data["_error"])
    if data.get("type") != "file" or data.get("path") != WORKFLOW_PATH:
        return None, "Trusted workflow file is unavailable"
    return data.get("sha"), None


def validate_github_actions_evidence(
    repository: str,
    commit_sha: str,
    test_reference: str,
    run_id: int | None = None,
    api_reader: Callable[[str], dict[str, Any]] = github_get,
) -> dict[str, Any]:
    """Compare Brain's claim with independently fetched, exact-commit CI facts."""
    base = {
        "provider": "github_actions",
        "repository": repository,
        "claimed_commit_sha": commit_sha if isinstance(commit_sha, str) else None,
        "test_reference": test_reference if isinstance(test_reference, str) else None,
    }
    if not isinstance(repository, str) or repository.lower() != "romanstarokon9977-boop/personal-ai-brain":
        return {**base, "decision": "REJECTED", "reason": "UNTRUSTED_REPOSITORY"}
    if not isinstance(commit_sha, str) or not _SHA_RE.fullmatch(commit_sha):
        return {**base, "decision": "INCONCLUSIVE", "reason": "COMMIT_SHA_REQUIRED"}
    if not isinstance(test_reference, str):
        return {**base, "decision": "INCONCLUSIVE", "reason": "TEST_REFERENCE_REQUIRED"}
    match = _TEST_REF_RE.fullmatch(test_reference)
    if not match:
        return {**base, "decision": "INCONCLUSIVE", "reason": "TEST_REFERENCE_NOT_MAPPED_TO_CI_TEST"}
    test_module = match.group(1) + ".py"

    repo_data = _get(api_reader, f"/repos/{repository}")
    if "_error" in repo_data:
        return {**base, "decision": "INCONCLUSIVE", "reason": "REPOSITORY_LOOKUP_UNAVAILABLE"}
    if repo_data.get("id") != EXPECTED_REPOSITORY_ID or repo_data.get("full_name", "").lower() != repository.lower():
        return {**base, "decision": "REJECTED", "reason": "REPOSITORY_IDENTITY_MISMATCH"}

    workflow = _get(api_reader, f"/repos/{repository}/actions/workflows/{WORKFLOW_PATH}")
    if "_error" in workflow:
        return {**base, "decision": "INCONCLUSIVE", "reason": "WORKFLOW_LOOKUP_UNAVAILABLE"}
    if workflow.get("path") != WORKFLOW_PATH or not isinstance(workflow.get("id"), int):
        return {**base, "decision": "REJECTED", "reason": "WORKFLOW_IDENTITY_MISMATCH"}

    trusted_sha, trusted_error = _content_sha(api_reader, repository, "main")
    target_sha, target_error = _content_sha(api_reader, repository, commit_sha)
    if trusted_error or target_error:
        return {**base, "decision": "INCONCLUSIVE", "reason": "WORKFLOW_CONTENT_UNAVAILABLE"}
    if not trusted_sha or trusted_sha != target_sha:
        return {**base, "decision": "REJECTED", "reason": "WORKFLOW_DEFINITION_DIFFERS_FROM_TRUSTED_MAIN"}

    workflow_runs = _get(
        api_reader,
        f"/repos/{repository}/actions/workflows/{workflow['id']}/runs?head_sha={quote(commit_sha, safe='')}&per_page=100",
    )
    if "_error" in workflow_runs or not isinstance(workflow_runs.get("workflow_runs"), list):
        return {**base, "decision": "INCONCLUSIVE", "reason": "WORKFLOW_RUNS_UNAVAILABLE"}
    candidates = [
        item for item in workflow_runs["workflow_runs"]
        if isinstance(item, dict)
        and item.get("workflow_id") == workflow["id"]
        and item.get("head_sha") == commit_sha
    ]
    if run_id is not None:
        candidates = [item for item in candidates if item.get("id") == run_id]
    if not candidates:
        return {**base, "decision": "INCONCLUSIVE", "reason": "NO_EXACT_COMMIT_RUN"}
    run = candidates[0]

    event = run.get("event")
    branch = run.get("head_branch")
    if event != "push" or not isinstance(branch, str) or not branch.startswith(_ALLOWED_BRANCH_PREFIXES):
        return {**base, "decision": "REJECTED", "reason": "UNTRUSTED_RUN_EVENT_OR_BRANCH",
                "run_id": run.get("id"), "event": event, "branch": branch}
    if run.get("status") != "completed":
        return {**base, "decision": "INCONCLUSIVE", "reason": "CI_RUN_NOT_COMPLETED",
                "run_id": run.get("id"), "status": run.get("status")}
    if run.get("conclusion") != "success":
        return {**base, "decision": "REJECTED", "reason": "CI_RUN_FAILED",
                "run_id": run.get("id"), "conclusion": run.get("conclusion")}

    jobs_data = _get(api_reader, f"/repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100")
    if "_error" in jobs_data or not isinstance(jobs_data.get("jobs"), list):
        return {**base, "decision": "INCONCLUSIVE", "reason": "CI_JOBS_UNAVAILABLE",
                "run_id": run.get("id")}
    jobs = [job for job in jobs_data["jobs"] if isinstance(job, dict)]
    required_job = next((job for job in jobs if job.get("name") == EXPECTED_JOB_NAME), None)
    if required_job is None:
        return {**base, "decision": "INCONCLUSIVE", "reason": "REQUIRED_CI_JOB_MISSING",
                "run_id": run.get("id")}
    if required_job.get("status") != "completed":
        return {**base, "decision": "INCONCLUSIVE", "reason": "REQUIRED_CI_JOB_NOT_COMPLETED",
                "run_id": run.get("id")}
    if required_job.get("conclusion") != "success":
        return {**base, "decision": "REJECTED", "reason": "REQUIRED_CI_JOB_FAILED",
                "run_id": run.get("id"), "job_conclusion": required_job.get("conclusion")}

    # The trusted workflow must explicitly include this module in its unittest loop.
    # Fetch its source at the verified commit and ensure the module is actually listed.
    workflow_file = _get(
        api_reader,
        f"/repos/{repository}/contents/{quote(WORKFLOW_PATH, safe='/')}?ref={quote(commit_sha, safe='')}",
    )
    try:
        workflow_text = base64.b64decode(workflow_file.get("content", "")).decode("utf-8")
    except Exception:
        workflow_text = ""
    if test_module not in workflow_text or 'python -m unittest -v "${test_module}"' not in workflow_text:
        return {**base, "decision": "INCONCLUSIVE", "reason": "TEST_MODULE_NOT_CONFIRMED_IN_TRUSTED_CI"}

    return {
        **base,
        "decision": "VERIFIED",
        "reason": "EXACT_COMMIT_AND_REQUIRED_CI_JOB_PASSED",
        "repository_id": repo_data["id"],
        "workflow_id": workflow["id"],
        "workflow_path": WORKFLOW_PATH,
        "workflow_definition_sha": target_sha,
        "run_id": run["id"],
        "run_attempt": run.get("run_attempt"),
        "run_url": run.get("html_url"),
        "event": event,
        "branch": branch,
        "commit_sha": run["head_sha"],
        "run_status": run["status"],
        "run_conclusion": run["conclusion"],
        "job_id": required_job.get("id"),
        "job_name": required_job.get("name"),
        "job_status": required_job.get("status"),
        "job_conclusion": required_job.get("conclusion"),
        "completed_at": run.get("updated_at"),
        "assurance": "GitHub Actions run and required job metadata validated; not a cryptographic test attestation",
    }
