"""Embedding-assisted, review-first semantic memory candidate discovery.

The caller supplies a batch embedding function. This module performs no network
requests, model selection, persistence, or automatic consolidation.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Callable, Sequence


class SemanticConsolidationError(ValueError):
    """Raised when semantic candidate discovery cannot be performed safely."""


_NEGATION = {"не", "нет", "никогда", "нельзя", "запрещено", "без"}
_NUMBER_OR_DATE = re.compile(r"\d+(?:[./:-]\d+)*")
_MAX_ENTRIES = 500
_MAX_TEXT_LENGTH = 2000


def _compatible(left: dict, right: dict) -> bool:
    if left.get("category", "facts") != right.get("category", "facts"):
        return False
    left_text = left.get("text", "")
    right_text = right.get("text", "")
    if not isinstance(left_text, str) or not isinstance(right_text, str):
        return False
    if set(_NUMBER_OR_DATE.findall(left_text)) != set(_NUMBER_OR_DATE.findall(right_text)):
        return False
    left_negated = bool(set(left_text.lower().split()) & _NEGATION)
    right_negated = bool(set(right_text.lower().split()) & _NEGATION)
    return left_negated == right_negated


def _validated_vector(value, expected_dimension=None):
    if not isinstance(value, (list, tuple)) or not value:
        raise SemanticConsolidationError("INVALID_EMBEDDING_VECTOR")
    vector = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SemanticConsolidationError("NON_NUMERIC_EMBEDDING_VALUE")
        number = float(item)
        if not math.isfinite(number):
            raise SemanticConsolidationError("NON_FINITE_EMBEDDING_VALUE")
        vector.append(number)
    if expected_dimension is not None and len(vector) != expected_dimension:
        raise SemanticConsolidationError("EMBEDDING_DIMENSION_MISMATCH")
    if not any(vector):
        raise SemanticConsolidationError("ZERO_NORM_EMBEDDING")
    return vector


def _cosine_similarity(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        raise SemanticConsolidationError("ZERO_NORM_EMBEDDING")
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def find_semantic_consolidation_candidates(
    entries: list,
    embed_texts: Callable[[list[str]], Sequence[Sequence[float]]],
    min_similarity: float = 0.82,
) -> list[dict]:
    """Return semantic candidate groups using caller-provided batch embeddings.

    Groups use complete-link clustering: every pair inside a group must meet
    the threshold. This reduces unsafe chaining through a weakly related seed.
    The returned entries are deep-copied snapshots compatible with P3.1 apply.
    """
    if not isinstance(entries, list):
        raise SemanticConsolidationError("INVALID_ENTRIES")
    if not callable(embed_texts):
        raise SemanticConsolidationError("EMBEDDING_PROVIDER_REQUIRED")
    if isinstance(min_similarity, bool) or not isinstance(min_similarity, (int, float)):
        raise SemanticConsolidationError("INVALID_SIMILARITY_THRESHOLD")
    if not 0.75 <= float(min_similarity) <= 1.0:
        raise SemanticConsolidationError("SIMILARITY_THRESHOLD_OUT_OF_SAFE_RANGE")

    valid = []
    seen_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        text = entry.get("text")
        if not isinstance(identifier, str) or not identifier or not isinstance(text, str) or not text.strip():
            continue
        if len(text) > _MAX_TEXT_LENGTH:
            continue
        if identifier in seen_ids:
            raise SemanticConsolidationError("DUPLICATE_ENTRY_ID")
        seen_ids.add(identifier)
        valid.append(copy.deepcopy(entry))

    if len(valid) < 2:
        return []
    if len(valid) > _MAX_ENTRIES:
        raise SemanticConsolidationError("ENTRY_LIMIT_EXCEEDED")

    texts = [item["text"] for item in valid]
    try:
        raw_vectors = embed_texts(texts)
    except Exception as exc:
        raise SemanticConsolidationError("EMBEDDING_PROVIDER_FAILED") from exc
    if not isinstance(raw_vectors, (list, tuple)) or len(raw_vectors) != len(valid):
        raise SemanticConsolidationError("EMBEDDING_COUNT_MISMATCH")

    vectors = []
    dimension = None
    for raw in raw_vectors:
        vector = _validated_vector(raw, dimension)
        if dimension is None:
            dimension = len(vector)
        vectors.append(vector)

    similarities = {}
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            similarities[(i, j)] = _cosine_similarity(vectors[i], vectors[j])

    used = set()
    groups = []
    threshold = float(min_similarity)
    for seed_index, seed in enumerate(valid):
        if seed_index in used:
            continue
        cluster_indices = [seed_index]
        for candidate_index in range(seed_index + 1, len(valid)):
            if candidate_index in used:
                continue
            candidate = valid[candidate_index]
            if not _compatible(seed, candidate):
                continue
            if all(
                _compatible(valid[member_index], candidate)
                and similarities[tuple(sorted((member_index, candidate_index)))] >= threshold
                for member_index in cluster_indices
            ):
                cluster_indices.append(candidate_index)

        if len(cluster_indices) < 2:
            continue
        pair_scores = [
            similarities[tuple(sorted((left, right)))]
            for pos, left in enumerate(cluster_indices)
            for right in cluster_indices[pos + 1:]
        ]
        cluster = [copy.deepcopy(valid[index]) for index in cluster_indices]
        groups.append({
            "entry_ids": [item["id"] for item in cluster],
            "similarity": min(pair_scores),
            "match_type": "semantic_embedding",
            "entries": cluster,
        })
        used.update(cluster_indices)

    return groups
