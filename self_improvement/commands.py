"""Explicit runtime entry points for quality feedback and the solution library."""
from __future__ import annotations

import os

from .core import analyze_quality_events, build_improvement_proposal
from .store import ImprovementEventStore, SolutionLibrary, ImprovementProposalStore


def _data_path(memory_file: str, filename: str) -> str:
    if not isinstance(memory_file, str) or not memory_file.strip():
        raise ValueError("MEMORY_PATH_UNAVAILABLE")
    parent = os.path.dirname(os.path.abspath(os.path.expanduser(memory_file)))
    if not os.path.isdir(parent):
        raise ValueError("BRAIN_DATA_DIRECTORY_UNAVAILABLE")
    return os.path.join(parent, filename)


def record_answer_feedback(memory_file: str, category: str, outcome: str,
                           evidence_code: str = "") -> dict:
    """Persist only an explicit, sanitized user-feedback event."""
    if category not in {"ACCURACY", "COMPLETENESS", "RELEVANCE", "REASONING", "STYLE", "OTHER"}:
        raise ValueError("INVALID_FEEDBACK_CATEGORY")
    store = ImprovementEventStore(_data_path(memory_file, "self_improvement_events.json"))
    return store.add(category, outcome, "user_feedback", evidence_code)


def build_quality_report(memory_file: str) -> dict:
    store = ImprovementEventStore(_data_path(memory_file, "self_improvement_events.json"))
    return analyze_quality_events(store.list_events())


def manage_solution_library(memory_file: str, operation: str, params: dict) -> dict:
    """Manage inert solution knowledge; every mutation is confirmation-gated upstream."""
    if not isinstance(params, dict):
        raise ValueError("INVALID_SOLUTION_LIBRARY_PARAMS")
    library = SolutionLibrary(_data_path(memory_file, "verified_solutions.json"))
    if operation == "list":
        status = params.get("status")
        return {"solutions": library.list_solutions(status)}
    if operation == "add_candidate":
        return library.add_candidate(
            params.get("name"), params.get("problem"), params.get("algorithm"),
            params.get("conditions", []), params.get("limitations", []),
        )
    if operation == "verify":
        return library.verify(params.get("solution_id"), {
            "test_run": params.get("test_run"),
            "passed": params.get("passed"),
        })
    if operation in {"deprecate", "reject"}:
        return library.set_status(
            params.get("solution_id"),
            "DEPRECATED" if operation == "deprecate" else "REJECTED",
        )
    raise ValueError("INVALID_SOLUTION_LIBRARY_OPERATION")


def manage_module_improvements(memory_file: str, operation: str, params: dict) -> dict:
    """Create/list/review architecture proposals; never generates or applies code."""
    if not isinstance(params, dict):
        raise ValueError("INVALID_IMPROVEMENT_PARAMS")
    store = ImprovementProposalStore(_data_path(memory_file, "module_improvement_proposals.json"))
    if operation == "list":
        return {"proposals": store.list_proposals(params.get("review_status"))}
    if operation == "create":
        proposal = build_improvement_proposal(
            params.get("finding", {}),
            params.get("title"),
            params.get("rationale"),
            params.get("affected_modules"),
            params.get("tests"),
            params.get("risk", "LOW"),
        )
        return store.create(proposal)
    if operation in {"approve", "reject"}:
        return store.review(
            params.get("reference"),
            "APPROVED" if operation == "approve" else "REJECTED",
        )
    raise ValueError("INVALID_MODULE_IMPROVEMENT_OPERATION")
