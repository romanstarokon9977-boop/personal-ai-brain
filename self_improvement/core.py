"""Read-only diagnostics and deterministic analysis for Brain self-improvement."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


def collect_diagnostics(project_root: str | None = None, registry: Any = None) -> dict:
    """Collect a bounded, read-only health snapshot from existing Brain modules.

    Missing or unavailable information is reported as UNKNOWN, never promoted
    to a failure. This function does not inspect arbitrary files or secrets.
    """
    from self_inspection import collect as inspect_project
    import module_manager

    inspection = inspect_project(project_root)
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "UNKNOWN",
        "checks": {},
        "findings": [],
        "mutations_performed": False,
    }
    if not isinstance(inspection, dict) or inspection.get("ok") is not True:
        result["findings"].append({
            "code": "SELF_INSPECTION_UNAVAILABLE",
            "severity": "UNKNOWN",
            "evidence": "Existing self_inspection.collect did not return a successful report.",
        })
    else:
        payload = inspection.get("result") or {}
        files = payload.get("files") if isinstance(payload, dict) else {}
        files = files if isinstance(files, dict) else {}
        for path, info in files.items():
            if not isinstance(info, dict):
                continue
            exists = info.get("exists")
            readable = info.get("readable")
            state = "OK" if exists is True and readable is True else (
                "ERROR" if exists is False and info.get("error") == "NOT_FOUND" else "UNKNOWN"
            )
            result["checks"]["file:" + str(path)] = state
            if state != "OK":
                result["findings"].append({
                    "code": "INSPECTED_FILE_" + state,
                    "severity": state,
                    "evidence": str(path)[:240],
                })
        git = payload.get("git") if isinstance(payload, dict) else {}
        if isinstance(git, dict):
            result["checks"]["git"] = "OK" if git.get("available") is True else "UNKNOWN"
        diagnostics = payload.get("diagnostics") if isinstance(payload, dict) else {}
        if isinstance(diagnostics, dict):
            for item in (diagnostics.get("warnings") or [])[:50]:
                result["findings"].append({
                    "code": "INSPECTION_WARNING",
                    "severity": "WARNING",
                    "evidence": str(item)[:240],
                })
            for item in (diagnostics.get("inconclusive") or [])[:50]:
                result["findings"].append({
                    "code": "INSPECTION_INCONCLUSIVE",
                    "severity": "UNKNOWN",
                    "evidence": str(item)[:240],
                })

    try:
        state = module_manager.state_health()
        result["checks"]["module_manager_state"] = (
            "OK" if state in {"ok", "first_run"} else "ERROR" if state in {"corrupt", "unreadable"} else "UNKNOWN"
        )
    except Exception:
        result["checks"]["module_manager_state"] = "UNKNOWN"

    if registry is not None:
        try:
            definitions = registry.all_tools()
            result["checks"]["registered_tools"] = "OK"
            result["metrics"] = {"registered_tools": len(definitions) if isinstance(definitions, list) else 0}
        except Exception:
            result["checks"]["registered_tools"] = "UNKNOWN"

    states = list(result["checks"].values())
    if states and all(value == "OK" for value in states) and not result["findings"]:
        result["status"] = "HEALTHY"
    elif any(value == "ERROR" for value in states) or any(
        item.get("severity") == "ERROR" for item in result["findings"]
    ):
        result["status"] = "DEGRADED"
    elif states:
        result["status"] = "WARNING"
    return result


def analyze_quality_events(events: list[dict], repeat_threshold: int = 2) -> dict:
    """Aggregate explicitly supplied, sanitized quality events.

    No conversation text is inferred or collected. Events need a stable
    category and outcome; uncertainty and user preference remain distinct.
    """
    if not isinstance(events, list):
        raise ValueError("INVALID_EVENTS")
    if isinstance(repeat_threshold, bool) or not isinstance(repeat_threshold, int) or not 2 <= repeat_threshold <= 100:
        raise ValueError("INVALID_REPEAT_THRESHOLD")
    counts: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    for event in events[:5000]:
        if not isinstance(event, dict):
            continue
        category = event.get("category")
        outcome = event.get("outcome")
        if not isinstance(category, str) or not category.strip() or len(category) > 80:
            continue
        if outcome not in {"pass", "fail", "uncertain", "user_preference"}:
            continue
        outcomes[outcome] += 1
        if outcome == "fail":
            counts[category.strip().upper()] += 1
    recurring = [
        {"category": category, "count": count}
        for category, count in sorted(counts.items())
        if count >= repeat_threshold
    ]
    return {
        "schema_version": 1,
        "events_analyzed": min(len(events), 5000),
        "outcomes": dict(outcomes),
        "recurring_failures": recurring,
        "repeat_threshold": repeat_threshold,
        "automatic_root_cause_claims": False,
    }


def build_improvement_proposal(finding: dict, title: str, rationale: str,
                               affected_modules: list[str], tests: list[str],
                               risk: str = "LOW") -> dict:
    """Create an inert technical proposal; never writes or applies code."""
    if not isinstance(finding, dict) or not isinstance(title, str) or not title.strip():
        raise ValueError("INVALID_PROPOSAL_INPUT")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("INVALID_PROPOSAL_RATIONALE")
    if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise ValueError("INVALID_RISK")
    for field, value in (("affected_modules", affected_modules), ("tests", tests)):
        if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError("INVALID_" + field.upper())
    return {
        "schema_version": 1,
        "title": title.strip()[:160],
        "rationale": rationale.strip()[:2000],
        "finding": {
            "code": str(finding.get("code", "UNSPECIFIED"))[:100],
            "severity": str(finding.get("severity", "UNKNOWN"))[:20],
            "evidence": str(finding.get("evidence", ""))[:1000],
        },
        "affected_modules": list(dict.fromkeys(x[:160] for x in affected_modules))[:30],
        "tests": list(dict.fromkeys(x[:240] for x in tests))[:50],
        "risk": risk,
        "status": "PROPOSED",
        "approval_required": True,
        "implementation_applied": False,
        "activation_allowed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
