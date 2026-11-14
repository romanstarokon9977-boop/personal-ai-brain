"""Explicit runtime entry points for quality feedback and the solution library."""
from __future__ import annotations

import os

from .core import analyze_quality_events
from .store import ImprovementEventStore, SolutionLibrary


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
