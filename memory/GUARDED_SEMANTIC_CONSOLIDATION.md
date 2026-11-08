# P3.2 — Guarded semantic memory consolidation

## Audit result

The repository already contains three relevant pieces:

- P3.1 lexical candidate discovery and an explicit apply path that checks exact source snapshots, backs up the store, writes atomically, and retains full source records in `consolidation_sources`.
- P3.2 embedding candidate discovery using caller-supplied batch embeddings and complete-link grouping.
- A pure semantic compatibility guard using explicit `FactFrame` data.

The missing integration was that embedding candidates were not required to pass the independent fact guard. The fact guard also has no built-in natural-language extractor, and the local embedding provider remains a separately injected dependency.

## Implementation

`memory.guarded_semantic_consolidation.find_guarded_semantic_consolidation_candidates()` combines the existing candidate retriever with the existing guard:

1. Only active records are considered; archived and superseded records are excluded.
2. Embeddings nominate candidate groups but do not establish proposition identity.
3. A caller-supplied fact-frame provider receives deep-copied candidate records and returns a mapping from record ID to structured fact frame.
4. Every pair in a group must receive `CANDIDATE_FOR_REVIEW` from `analyze_fact_pair()`. Any contradiction, uncertainty, or missing frame excludes the entire group.
5. Accepted candidates retain the P3.1 source snapshots and include pairwise guard evidence.

The Memory Core exposes this through
`preview_guarded_semantic_memory_consolidation(embed_texts, extract_fact_frames, min_similarity=0.82)`.

## Apply and preservation

Candidate discovery is read-only. It does not call the apply API, update records, delete records, or persist provider output.

After human review, the existing explicit
`memory_core.apply_memory_consolidation(candidate, merged_text)`
path remains the only apply mechanism. It revalidates exact source snapshots, uses the existing backup and atomic-save pipeline, and preserves complete source records and provenance in `consolidation_sources`.

## Provider boundary

No provider, model, API key, network call, or package dependency is added. Both callbacks are explicit caller dependencies. The caller must keep private memory processing local unless remote processing is separately authorized. Provider failure is explicit; it is never interpreted as an empty successful result.

This PR does not claim that fact frames are automatically extracted from arbitrary natural-language memory or that a local embedding provider is wired into Brain. Those remain separate integrations requiring their own device validation.

## Validation

The new tests cover paraphrase review candidates, numeric and subject conflicts, missing frames, inactive-record filtering, provider failures, input immutability, read-only preview, and compatibility with the existing protected apply path using temporary test data only.
