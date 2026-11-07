"""Conservative, review-first memory consolidation helpers.

Candidate discovery is read-only. Applying a candidate requires caller-supplied
merged text and an unchanged source snapshot. Original records are retained in
the consolidated record's consolidation_sources field for audit/recovery.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime


class ConsolidationError(ValueError):
    """Raised when a consolidation candidate is invalid or stale."""


_NEGATION = {"не", "нет", "никогда", "нельзя", "запрещено"}
_TOKEN_RE = re.compile(r"[а-яa-z0-9+#]+", re.IGNORECASE)
_DATE_OR_NUMBER_RE = re.compile(r"\d+(?:[./:-]\d+)*")


def _normalized(text):
    return re.sub(r"\s+", " ", str(text).lower().replace("ё", "е")).strip()


def _tokens(text):
    return set(_TOKEN_RE.findall(_normalized(text)))


def _compatible(left, right):
    if left.get("category", "facts") != right.get("category", "facts"):
        return False
    left_text, right_text = left.get("text", ""), right.get("text", "")
    if not isinstance(left_text, str) or not isinstance(right_text, str):
        return False
    # Different explicit numbers/dates may encode distinct facts.
    if set(_DATE_OR_NUMBER_RE.findall(left_text)) != set(_DATE_OR_NUMBER_RE.findall(right_text)):
        return False
    left_tokens, right_tokens = _tokens(left_text), _tokens(right_text)
    if bool(left_tokens & _NEGATION) != bool(right_tokens & _NEGATION):
        return False
    return True


def _similarity(left_text, right_text):
    left, right = _tokens(left_text), _tokens(right_text)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def find_consolidation_candidates(entries, min_similarity=0.72):
    """Return conservative candidate groups without modifying entries."""
    if not isinstance(entries, list):
        raise ConsolidationError("INVALID_ENTRIES")
    if not 0.0 <= float(min_similarity) <= 1.0:
        raise ConsolidationError("INVALID_SIMILARITY_THRESHOLD")

    valid = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        if not isinstance(entry.get("text"), str) or not entry["text"].strip():
            continue
        valid.append(copy.deepcopy(entry))

    used = set()
    groups = []
    for index, seed in enumerate(valid):
        if seed["id"] in used:
            continue
        cluster = [seed]
        scores = []
        for other in valid[index + 1:]:
            if other["id"] in used or not _compatible(seed, other):
                continue
            left_norm = _normalized(seed["text"])
            right_norm = _normalized(other["text"])
            score = 1.0 if left_norm == right_norm else _similarity(seed["text"], other["text"])
            shared = _tokens(seed["text"]) & _tokens(other["text"])
            if score >= min_similarity and (score == 1.0 or len(shared) >= 3):
                cluster.append(other)
                scores.append(score)
        if len(cluster) < 2:
            continue
        ids = [item["id"] for item in cluster]
        if len(ids) != len(set(ids)):
            continue
        used.update(ids)
        groups.append({
            "entry_ids": ids,
            "similarity": min(scores) if scores else 1.0,
            "entries": cluster,
        })
    return groups


def apply_consolidation(entries, candidate, merged_text):
    """Build a new list; never mutate inputs and reject stale source snapshots."""
    if not isinstance(entries, list) or not isinstance(candidate, dict):
        raise ConsolidationError("INVALID_CONSOLIDATION_INPUT")
    if not isinstance(merged_text, str) or not merged_text.strip():
        raise ConsolidationError("EMPTY_MERGED_TEXT")

    source_snapshot = candidate.get("entries")
    source_ids = candidate.get("entry_ids")
    if not isinstance(source_snapshot, list) or len(source_snapshot) < 2:
        raise ConsolidationError("INVALID_CANDIDATE")
    if not isinstance(source_ids, list) or len(source_ids) != len(source_snapshot):
        raise ConsolidationError("INVALID_CANDIDATE_IDS")
    if len(set(source_ids)) != len(source_ids):
        raise ConsolidationError("DUPLICATE_SOURCE_IDS")
    snapshot_ids = [item.get("id") for item in source_snapshot if isinstance(item, dict)]
    if snapshot_ids != source_ids:
        raise ConsolidationError("CANDIDATE_SOURCE_ID_MISMATCH")
    if len(snapshot_ids) != len(source_snapshot):
        raise ConsolidationError("INVALID_SOURCE_SNAPSHOT")
    if any(not isinstance(item, dict) for item in entries):
        raise ConsolidationError("INVALID_CURRENT_ENTRY")

    current_by_id = {item.get("id"): item for item in entries if isinstance(item, dict)}
    for expected in source_snapshot:
        current = current_by_id.get(expected.get("id"))
        if current != expected:
            raise ConsolidationError("STALE_CONSOLIDATION_CANDIDATE")

    canonical = copy.deepcopy(source_snapshot[0])
    topics = []
    for item in source_snapshot:
        for topic in item.get("topics", []) if isinstance(item.get("topics", []), list) else []:
            if topic not in topics:
                topics.append(topic)

    canonical["text"] = merged_text.strip()
    canonical["importance"] = max(
        (item.get("importance", 5) for item in source_snapshot
         if isinstance(item.get("importance", 5), (int, float))),
        default=5,
    )
    canonical["topics"] = topics
    canonical["source"] = "consolidated"
    canonical["consolidated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Keep full original records, not just IDs, so no source detail is discarded.
    canonical["consolidation_sources"] = copy.deepcopy(source_snapshot)

    output = []
    inserted = False
    source_id_set = set(source_ids)
    for item in entries:
        if item.get("id") in source_id_set:
            if not inserted:
                output.append(canonical)
                inserted = True
            continue
        output.append(copy.deepcopy(item))
    if not inserted:
        raise ConsolidationError("SOURCE_ENTRIES_NOT_FOUND")
    return output
