# P3.2.4 — Semantic guardrails audit and design

**Status:** READ-ONLY audit and design proposal  
**Base reviewed:** `main` at `ac9de29fffbd602cfce9502ca5e73d8325b1d60c`  
**Scope:** memory ingestion, lexical candidate discovery, embedding candidate discovery, and reviewed apply path.  
**Implementation status:** no runtime code changed; no provider integration; no memory data accessed.

## 1. Executive conclusion

The P3.2.3 benchmark does not support using cosine similarity as a duplicate decision. At threshold 0.82, the local E5 endpoint accepted 36 pairs, of which only 10 were expected matches: precision 27.78%, recall 100%, and 26 false positives. Contradictions, negations, changed numbers/dates, causally related independent facts, and topically related distinct facts were frequently accepted.

The next stage must treat embeddings as **candidate retrieval only**. A candidate must pass independent fact-compatibility checks and remain subject to explicit review before any consolidation.

## 2. Existing paths found in main

### 2.1 Memory ingestion: `memory_core.add_memory()`

The current ingestion path performs:

1. Exact normalized-text duplicate check.
2. `_find_similar_entry()` lexical overlap check.
3. If a similar entry is found, it may update the existing entry when the incoming text is longer, recording `semantic_refinement`; otherwise it returns that a similar entry already exists.
4. Only when no similar entry is found does it proceed to contradiction detection and create a new record.

The helper compares normalized token sets using:

`len(common_tokens) / max(len(new_tokens), len(existing_tokens))`

and accepts a candidate at 0.6. This is lexical overlap, not semantic embedding. The helper does not itself enforce category, number/date, polarity, subject, or predicate compatibility.

**Risk:** an incoming statement that shares enough words with an existing record can be treated as a refinement or suppressed before the contradiction path runs. This is a separate ingestion risk from P3.2 semantic preview. The audit does not establish how often it occurs in real memory; adversarial regression tests are required before any change.

### 2.2 Lexical consolidation: `memory/consolidation.py`

The P3.1 candidate detector is read-only. It checks category equality, equality of explicit number/date token sets, and a coarse negation-presence comparison, then uses token Jaccard similarity and a minimum shared-token count.

The apply path checks candidate structure, unique source IDs, exact source snapshot identity against current records, and retains full original records in `consolidation_sources`. It requires caller-supplied merged text and an explicit apply call.

**Strength:** stale snapshots are rejected and source records are retained.

**Limit:** candidate compatibility checks are heuristic and do not prove that two statements express the same proposition. The apply function protects snapshot integrity; it is not a semantic truth validator.

### 2.3 Embedding candidate discovery: `memory/semantic_consolidation.py`

The P3.2 module:

- accepts a caller-supplied batch embedder;
- validates vector count, dimensions, numeric finite values, and non-zero vectors;
- computes cosine similarities;
- uses complete-link grouping;
- excludes different categories, differing explicit number/date sets, and a coarse negation-presence mismatch;
- returns deep-copied source snapshots and does not write memory.

**Strength:** provider injection, fail-closed validation, read-only behavior, and complete-link grouping are useful boundaries to preserve.

**Limit:** complete-link prevents chaining through a weak pair, but it cannot distinguish semantic duplicates from contradictions when every pair has high cosine. The current compatibility rules do not detect many same-polarity conflicts, role changes for numbers/dates, or implicit oppositions.

### 2.4 Existing semantic tests

`test_memory_semantic_consolidation.py` covers provider errors, vector shape/value validation, category/number/negation guards, complete-link grouping, and read-only preview.

The tests do not yet establish robust behavior for a representative adversarial matrix covering:
- same-topic contradictions without explicit negation words;
- different subjects with similar predicates;
- swapped roles for identical numeric/date tokens;
- changed units, ranges, and temporal validity;
- presence/absence and modal changes expressed without the current negation vocabulary;
- causally related but independently true facts;
- ingestion behavior when lexical overlap exceeds 0.6.

The synthetic P3.2.3 benchmark is currently a separate script; its cases are not yet a regression suite for the consolidation modules.

## 3. Benchmark-derived design constraints

1. Do not tune a single cosine threshold to solve false positives. Positive and negative classes overlap substantially.
2. Optimize safety against false merges, not candidate recall alone.
3. Preserve the embedding engine only as a retrieval/ranking stage.
4. Treat similarity scores as evidence of topical/semantic proximity, never proof of proposition identity.
5. Do not automatically rewrite, suppress, supersede, or merge a memory record based only on embedding or lexical similarity.
6. Keep local/private processing as the default provider boundary; do not introduce external calls in this stage.

## 4. Proposed guarded pipeline

The following is a design proposal, not an implementation authorization.

### Stage A — Candidate retrieval

- Exact normalized match may be reported separately.
- Lexical and embedding retrieval may nominate possible candidates.
- Candidate retrieval must not mutate or suppress an incoming fact.
- Embedding output remains optional and caller-supplied.

### Stage B — Hard compatibility checks

Compare explicit structured attributes where available:

- category / memory type;
- subject or entity;
- predicate / relation;
- polarity and presence/absence;
- numeric values, units, ranges, and their semantic roles;
- dates, intervals, and temporal validity;
- modality / certainty (e.g. must, may, can, cannot);
- source and provenance where relevant.

Unknown or ambiguous attributes must not be treated as compatible by default. A failed hard check means **SEPARATE / REVIEW**, not merge.

### Stage C — Proposition relation classification

Classify the pair as one of:

- `DUPLICATE` — same proposition, different wording;
- `REFINEMENT` — same proposition with compatible added detail;
- `CONTRADICTION` — incompatible propositions;
- `RELATED_INDEPENDENT` — related topic, distinct facts;
- `UNRELATED`;
- `UNCERTAIN`.

Only `DUPLICATE` and explicitly reviewed `REFINEMENT` may proceed to a human review proposal. The classifier must expose its evidence and uncertainty; it must not directly apply a merge.

### Stage D — Review and apply

- Show source records side by side, including IDs, dates, categories, source/provenance, and relevant metadata.
- Require an explicit reviewed merged text.
- Revalidate the exact current source snapshot immediately before apply.
- Preserve all original source records and provenance.
- If any source changed, reject as stale and regenerate the proposal.

## 5. Required P3.2.4 regression matrix

Before implementation changes are proposed, create deterministic test cases for at least these classes:

| Class | Expected outcome |
|---|---|
| True paraphrase | Candidate for review |
| Structural semantic duplicate | Candidate for review |
| Explicit negation | Separate / review |
| Implicit contradiction without negation token | Separate / review |
| Different numeric value | Separate |
| Same numbers with swapped semantic roles | Separate / review |
| Different date / interval | Separate |
| Changed unit or range | Separate / review |
| Presence versus absence | Separate / review |
| Different subject, same predicate | Separate |
| Causal but independent facts | Separate |
| Topically related facts | Separate |
| Unrelated facts | Separate |
| Ambiguous / incomplete statement | Uncertain; no merge |
| Lexical ingestion overlap >= 0.6 but distinct proposition | Must not be silently suppressed or rewritten |

Measure false positives per class, not only aggregate precision/recall. A zero-false-merge policy is the target for the guarded apply path; uncertain cases must remain separate for review.

## 6. Recommended implementation sequence

1. **P3.2.4.1 — READ-ONLY behavior specification:** approve the fact attributes, pair relation labels, and fail-closed outcomes.
2. **P3.2.4.2 — Regression fixtures:** add adversarial tests for semantic candidate discovery and the independent `add_memory()` lexical ingestion path. No behavior changes in this step.
3. **P3.2.4.3 — Guard design review:** compare the proposed checks with existing P3.1/P3.2 APIs and decide the smallest isolated module boundary.
4. **P3.2.4.4 — Implementation proposal:** only after explicit approval, implement a narrow guard layer in a new module where practical. Do not rewrite `brain.py` or change the provider.
5. Re-run unit tests and the benchmark/regression suite. No live-memory integration until false-positive behavior is understood and separately approved.

## 7. Explicit non-goals and safety boundary

This audit does not:
- modify `memory_core.py`, `consolidation.py`, or `semantic_consolidation.py`;
- change the 0.82 threshold;
- connect the E5 endpoint to live memory;
- read, write, migrate, or inspect the user's canonical memory JSON;
- change ports, model servers, or provider configuration;
- authorize automatic consolidation;
- authorize merging this branch or deploying it to the device.

## 8. Decision required

Roman's approval is required before moving from this audit/design document to regression-fixture implementation or any runtime behavior change.


## 9. P3.2.4.2 regression fixtures added

The test-only follow-up adds `tests/test_p3_2_4_semantic_guardrails.py`.

- Passing controls cover a true paraphrase, explicit numeric conflict, and explicit negation.
- Known unsafe cases are marked with Python `unittest.expectedFailure`: implicit opposite values, different entities, swapped numeric roles, changed units, presence/absence without a negation token, causally related independent facts, topically related distinct facts, and lexical-ingestion overlap that would rewrite a distinct numeric fact.
- These expected failures are intentional characterization markers: the suite remains green while exposing known gaps. They are not evidence that the guardrails are already implemented.
- Runtime modules are unchanged. No production behavior is altered by this stage.

Run from the repository root:

```bash
python -m unittest -v tests.test_p3_2_4_semantic_guardrails
```

The expected-failure count should remain visible in the test output. When a corresponding guard is implemented in a later approved stage, remove its `expectedFailure` marker and require a normal passing assertion.
