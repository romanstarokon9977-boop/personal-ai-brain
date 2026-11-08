# P3.2 — Guarded semantic memory consolidation

## Audit result

The repository already contains three relevant pieces:

- P3.1 lexical candidate discovery and an explicit apply path that checks exact source snapshots, backs up the store, writes atomically, and retains full source records in `consolidation_sources`.
- P3.2 embedding candidate discovery using caller-supplied batch embeddings and complete-link grouping.
- A pure semantic compatibility guard using explicit `FactFrame` data.

The missing integration was that embedding candidates were not required to pass the independent fact guard. The repository now includes a conservative deterministic RU/EN FactFrame extractor for a narrow set of atomic patterns, plus a loopback-only llama.cpp embedding adapter. Unsupported or compound statements remain unframed and fail closed.

## Implementation

`memory.guarded_semantic_consolidation.find_guarded_semantic_consolidation_candidates()` combines the existing candidate retriever with the existing guard:

1. Only active records are considered; archived and superseded records are excluded.
2. Embeddings nominate candidate groups but do not establish proposition identity.
3. The caller-supplied fact-frame provider receives deep-copied candidate records and returns a mapping from record ID to structured fact frame. The built-in extractor returns None for unsupported or ambiguous statements.
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

The local embedding adapter targets a dedicated llama.cpp /v1/embeddings server, accepts loopback URLs only, defaults to 127.0.0.1:8090, validates response shape and 384-dimensional vectors, and has no remote fallback. Providers are explicitly injected; no server is started automatically.

This PR does not claim that fact frames are automatically extracted from arbitrary natural-language memory or that a local embedding provider is wired into Brain. Those remain separate integrations requiring their own device validation.

## Validation

The new tests cover paraphrase review candidates, numeric and subject conflicts, missing frames, inactive-record filtering, provider failures, input immutability, read-only preview, and compatibility with the existing protected apply path using temporary test data only.


## Ingestion and adversarial protection

add_memory() now suppresses only exact normalized-text duplicates. Lexical overlap cannot suppress an incoming fact or rewrite an existing record. Contradiction superseding remains unchanged and source records are retained.

Former expected-failure cases now run as ordinary guarded-preview tests. The narrow extractor supports selected location, numeric-role, availability, backup-state, and study-topic patterns. Unsupported causal/compound statements, multi-value statements, missing provenance, and ambiguous text yield no frame and cannot become candidates.

## Device validation gate

The adapter is implemented and contract-tested, but the dedicated embedding server/model has not yet been validated on POCO F6. Before enabling live use, run the synthetic device checks in memory/EMBEDDING_PROVIDER_AUDIT.md against a separate llama.cpp embedding server on loopback port 8090. Existing Qwen chat services are not changed. CI uses only synthetic temporary memory.
