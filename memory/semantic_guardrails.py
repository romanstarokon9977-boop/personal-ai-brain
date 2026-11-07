"""Deterministic, fail-closed semantic compatibility checks for memory facts.

This module is deliberately pure: no I/O, model calls, embeddings, persistence,
or memory mutation. Similarity-based retrieval cannot authorize consolidation.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
import re
from typing import Any, Mapping


class SemanticGuardError(ValueError):
    """Raised when a record or structured fact frame is malformed."""


@dataclass(frozen=True)
class FactFrame:
    """Explicitly extracted proposition attributes; None means unknown."""

    subject: str | None = None
    predicate: str | None = None
    polarity: str | None = None
    state: str | None = None
    value: str | int | float | None = None
    unit: str | None = None
    semantic_role: str | None = None
    interval_start: str | None = None
    interval_end: str | None = None
    modality: str | None = None
    details: str = ""
    provenance: str | None = None


@dataclass(frozen=True)
class GuardDecision:
    """Immutable, review-only result of analyzing a pair of memory records."""

    relation: str
    decision: str
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]


_FRAME_FIELDS = {item.name for item in fields(FactFrame)}
_PROPOSITION_FIELDS = (
    "subject", "predicate", "polarity", "state", "value", "unit",
    "semantic_role", "interval_start", "interval_end", "modality", "details",
)
_REQUIRED_FIELDS = ("subject", "predicate")
_MAX_TEXT_LENGTH = 2000
_MAX_FIELD_LENGTH = 500
_TOKEN_RE = re.compile(r"\s+")


def _normalized_text(value: str) -> str:
    return _TOKEN_RE.sub(" ", value.casefold().replace("ё", "е")).strip()


def _validate_record(record: Mapping[str, Any], side: str) -> tuple[str, str]:
    if not isinstance(record, Mapping):
        raise SemanticGuardError(f"INVALID_{side.upper()}_RECORD")
    text = record.get("text")
    category = record.get("category", "facts")
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_TEXT_LENGTH:
        raise SemanticGuardError(f"INVALID_{side.upper()}_TEXT")
    if not isinstance(category, str) or not category.strip() or len(category) > 100:
        raise SemanticGuardError(f"INVALID_{side.upper()}_CATEGORY")
    return text, category.strip().casefold()


def _coerce_frame(frame: FactFrame | Mapping[str, Any] | None, side: str) -> FactFrame | None:
    if frame is None:
        return None
    if isinstance(frame, FactFrame):
        values = {name: getattr(frame, name) for name in _FRAME_FIELDS}
    elif isinstance(frame, Mapping):
        unknown = set(frame) - _FRAME_FIELDS
        if unknown:
            raise SemanticGuardError(f"UNKNOWN_{side.upper()}_FRAME_FIELDS")
        values = dict(frame)
    else:
        raise SemanticGuardError(f"INVALID_{side.upper()}_FRAME")

    for name, value in tuple(values.items()):
        if value is None:
            continue
        if name == "details":
            if not isinstance(value, str) or len(value) > _MAX_FIELD_LENGTH:
                raise SemanticGuardError(f"INVALID_{side.upper()}_DETAILS")
            values[name] = value.strip().casefold()
            continue
        if name == "value":
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise SemanticGuardError(f"INVALID_{side.upper()}_VALUE")
            if isinstance(value, float) and (value != value or abs(value) == float("inf")):
                raise SemanticGuardError(f"INVALID_{side.upper()}_VALUE")
            if isinstance(value, str) and (not value.strip() or len(value) > _MAX_FIELD_LENGTH):
                raise SemanticGuardError(f"INVALID_{side.upper()}_VALUE")
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_FIELD_LENGTH:
            raise SemanticGuardError(f"INVALID_{side.upper()}_{name.upper()}")
        values[name] = value.strip() if name == "provenance" else value.strip().casefold()

    try:
        return FactFrame(**values)
    except TypeError as exc:
        raise SemanticGuardError(f"INVALID_{side.upper()}_FRAME") from exc


def _decision(relation: str, decision: str, codes: list[str], evidence: list[str]) -> GuardDecision:
    return GuardDecision(
        relation=relation,
        decision=decision,
        reason_codes=tuple(dict.fromkeys(codes)),
        evidence=tuple(dict.fromkeys(evidence)),
    )


def _parse_iso(value: str) -> date | datetime | None:
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value)
    except ValueError:
        return None


def _interval_relation(left: FactFrame, right: FactFrame) -> str | None:
    values = (left.interval_start, left.interval_end, right.interval_start, right.interval_end)
    if not any(values):
        return None
    if not all(values):
        return "INTERVAL_INCOMPLETE"
    ls, le, rs, re = (_parse_iso(item) for item in values)
    if None in (ls, le, rs, re):
        return "INTERVAL_UNPARSEABLE"
    try:
        if ls > le or rs > re:
            return "INTERVAL_INVALID_RANGE"
        if le < rs or re < ls:
            return "INTERVAL_DISJOINT"
    except TypeError:
        return "INTERVAL_INCOMPARABLE"
    return None


def analyze_fact_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    left_frame: FactFrame | Mapping[str, Any] | None = None,
    right_frame: FactFrame | Mapping[str, Any] | None = None,
) -> GuardDecision:
    """Classify two records without mutation; unknown evidence fails closed.

    DUPLICATE and REFINEMENT return CANDIDATE_FOR_REVIEW only. This function
    never merges, deletes, rewrites, or persists records.
    """
    left_text, left_category = _validate_record(left, "left")
    right_text, right_category = _validate_record(right, "right")
    lf = _coerce_frame(left_frame, "left")
    rf = _coerce_frame(right_frame, "right")

    if left_category != right_category:
        return _decision("RELATED_INDEPENDENT", "SEPARATE", ["CATEGORY_MISMATCH"], [])
    if lf is None and rf is None:
        if _normalized_text(left_text) == _normalized_text(right_text):
            return _decision("DUPLICATE", "CANDIDATE_FOR_REVIEW", ["EXACT_NORMALIZED_TEXT"], [])
        return _decision("UNCERTAIN", "UNCERTAIN", ["STRUCTURED_FRAMES_REQUIRED"], [])
    if lf is None or rf is None:
        return _decision("UNCERTAIN", "UNCERTAIN", ["FRAME_MISSING"], [])

    codes: list[str] = []
    evidence: list[str] = []

    for name in ("subject", "predicate"):
        a, b = getattr(lf, name), getattr(rf, name)
        if a is not None and b is not None and a != b:
            return _decision(
                "RELATED_INDEPENDENT", "SEPARATE", [f"{name.upper()}_MISMATCH"],
                [f"{name}: values differ"],
            )

    for name in ("polarity", "state"):
        a, b = getattr(lf, name), getattr(rf, name)
        if a is not None and b is not None and a != b:
            return _decision(
                "CONTRADICTION", "SEPARATE", [f"{name.upper()}_CONFLICT"],
                [f"{name}: values differ"],
            )

    for name in ("value", "unit", "semantic_role"):
        a, b = getattr(lf, name), getattr(rf, name)
        if a is not None and b is not None and a != b:
            return _decision(
                "CONTRADICTION", "SEPARATE", [f"{name.upper()}_CONFLICT"],
                [f"{name}: values differ"],
            )

    interval_code = _interval_relation(lf, rf)
    if interval_code == "INTERVAL_DISJOINT":
        return _decision(
            "RELATED_INDEPENDENT", "SEPARATE", [interval_code],
            ["validity intervals do not overlap"],
        )
    if interval_code:
        codes.append(interval_code)

    if lf.modality is not None and rf.modality is not None and lf.modality != rf.modality:
        codes.append("MODALITY_MISMATCH")
        evidence.append("modality differs; compatibility is not established")

    missing = [
        name for name in _REQUIRED_FIELDS
        if getattr(lf, name) is None or getattr(rf, name) is None
    ]
    if missing:
        codes.append("REQUIRED_FRAME_FIELD_UNKNOWN")
        evidence.extend(f"unknown required field: {name}" for name in missing)

    unknown = [
        name for name in _PROPOSITION_FIELDS
        if getattr(lf, name) is None or getattr(rf, name) is None
    ]
    if unknown:
        codes.append("PROPOSITION_EVIDENCE_INCOMPLETE")
        evidence.extend(f"unknown or unpaired field: {name}" for name in unknown)

    if lf.provenance is None or rf.provenance is None:
        codes.append("PROVENANCE_UNKNOWN")
        evidence.append("source provenance is incomplete")
    elif lf.provenance != rf.provenance:
        codes.append("PROVENANCE_DIFFERENCE")
        evidence.append("source provenance differs; retain both provenance records")

    if codes:
        return _decision("UNCERTAIN", "UNCERTAIN", codes, evidence)

    left_values = {name: getattr(lf, name) for name in _PROPOSITION_FIELDS}
    right_values = {name: getattr(rf, name) for name in _PROPOSITION_FIELDS}
    left_known = {key: value for key, value in left_values.items() if value is not None}
    right_known = {key: value for key, value in right_values.items() if value is not None}

    if left_known == right_known:
        return _decision("DUPLICATE", "CANDIDATE_FOR_REVIEW", ["FRAME_MATCH"], evidence)

    left_core = {key: value for key, value in left_known.items() if key != "details"}
    right_core = {key: value for key, value in right_known.items() if key != "details"}
    if left_core == right_core and lf.details != rf.details:
        shorter, longer = sorted((lf.details, rf.details), key=len)
        if not shorter or shorter in longer:
            return _decision(
                "REFINEMENT", "CANDIDATE_FOR_REVIEW",
                ["COMPATIBLE_ADDITIONAL_DETAIL"], evidence,
            )

    return _decision("UNCERTAIN", "UNCERTAIN", ["COMPATIBILITY_NOT_PROVEN"], evidence)
