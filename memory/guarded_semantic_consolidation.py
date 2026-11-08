"""Fail-closed semantic candidate filtering for review-first memory consolidation.

Embeddings retrieve possible matches. Structured fact frames must independently
confirm every pair before a group is exposed as a consolidation candidate.
This module performs no persistence, network access, or automatic apply.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from itertools import combinations

from memory.semantic_consolidation import (
    SemanticConsolidationError,
    find_semantic_consolidation_candidates,
)
from memory.semantic_guardrails import (
    SemanticGuardError,
    analyze_fact_pair,
)


class GuardedSemanticConsolidationError(ValueError):
    """Raised when semantic candidate validation cannot run safely."""


def find_guarded_semantic_consolidation_candidates(
    entries,
    embed_texts,
    extract_fact_frames,
    min_similarity=0.82,
):
    """Return only embedding groups whose every pair passes the fact guard.

    extract_fact_frames receives deep-copied candidate records and must return
    a mapping of record ID to FactFrame (or a compatible mapping). Missing
    frames fail closed by excluding that group. Provider failures and malformed
    output raise an explicit error; they are never treated as an empty success.

    Returned candidates retain the P3.1 shape and full source snapshots, with
    additional guard evidence. They can be passed to the existing explicit
    review/apply path. This function never mutates entries or applies a merge.
    """
    if not isinstance(entries, list):
        raise GuardedSemanticConsolidationError("INVALID_ENTRIES")
    if not callable(extract_fact_frames):
        raise GuardedSemanticConsolidationError("FACT_FRAME_PROVIDER_REQUIRED")

    # Archived and superseded records are historical evidence, not active
    # consolidation targets. Legacy records without status remain active.
    active = [
        copy.deepcopy(item)
        for item in entries
        if isinstance(item, dict)
        and item.get("status", "active") == "active"
        and not item.get("superseded_by")
    ]
    if len(active) < 2:
        return []

    try:
        raw_candidates = find_semantic_consolidation_candidates(
            active,
            embed_texts=embed_texts,
            min_similarity=min_similarity,
        )
    except SemanticConsolidationError as exc:
        raise GuardedSemanticConsolidationError(str(exc)) from exc

    if not raw_candidates:
        return []

    candidate_ids = {
        entry_id
        for candidate in raw_candidates
        for entry_id in candidate.get("entry_ids", [])
    }
    candidate_records = [
        item for item in active if item.get("id") in candidate_ids
    ]
    try:
        frames = extract_fact_frames(copy.deepcopy(candidate_records))
    except Exception as exc:
        raise GuardedSemanticConsolidationError(
            "FACT_FRAME_PROVIDER_FAILED"
        ) from exc

    if not isinstance(frames, Mapping):
        raise GuardedSemanticConsolidationError("INVALID_FACT_FRAME_RESULT")
    if any(not isinstance(key, str) for key in frames):
        raise GuardedSemanticConsolidationError("INVALID_FACT_FRAME_ID")
    if set(frames) - candidate_ids:
        raise GuardedSemanticConsolidationError("UNKNOWN_FACT_FRAME_ID")

    accepted = []
    for candidate in raw_candidates:
        source_entries = candidate["entries"]
        pair_decisions = []
        group_passes = True

        for left, right in combinations(source_entries, 2):
            try:
                decision = analyze_fact_pair(
                    left,
                    right,
                    frames.get(left["id"]),
                    frames.get(right["id"]),
                )
            except SemanticGuardError as exc:
                raise GuardedSemanticConsolidationError(
                    "INVALID_FACT_FRAME"
                ) from exc

            pair_decisions.append({
                "left_id": left["id"],
                "right_id": right["id"],
                "relation": decision.relation,
                "decision": decision.decision,
                "reason_codes": list(decision.reason_codes),
                "evidence": list(decision.evidence),
            })
            if decision.decision != "CANDIDATE_FOR_REVIEW":
                group_passes = False

        # Complete-link embedding retrieval is not sufficient by itself:
        # every pair must independently pass the proposition compatibility guard.
        if not group_passes:
            continue

        reviewed_candidate = copy.deepcopy(candidate)
        reviewed_candidate["candidate_policy"] = "guarded_semantic_review_only"
        reviewed_candidate["guard_decisions"] = pair_decisions
        accepted.append(reviewed_candidate)

    return accepted
