# P3.2.4.3 — Guarded semantic memory design

**Status:** design review; no runtime implementation in this change  
**Base:** `main` after PR #33, commit `990da1a39bace11422aa02be85e718e48dcbddb9`  
**Scope:** semantic candidate compatibility, proposition relation classification, and safe ingestion boundaries.

## 1. Decision

Embedding and lexical similarity are retrieval signals only. Neither may suppress an incoming memory, rewrite an existing record, or authorize consolidation.

The guard is a conservative, deterministic compatibility layer between candidate retrieval and review. It must fail closed: missing, ambiguous, malformed, or conflicting evidence produces `UNCERTAIN` or `SEPARATE`, never implicit compatibility.

This stage documents the design only. It does not change runtime behavior, thresholds, memory files, provider configuration, or the existing consolidation/apply API.

## 2. Threat model and invariants

The primary failure is a false merge or silent loss of a distinct fact. False negatives (two true paraphrases not grouped) are acceptable at this stage; false positives are not.

Required invariants:

1. Candidate retrieval never mutates memory and never blocks ingestion.
2. No single cosine threshold can establish proposition identity.
3. Unknown attributes are not treated as matching attributes.
4. Any hard conflict blocks a duplicate/refinement proposal.
5. A relation model or LLM may suggest a label, but cannot override deterministic hard conflicts or authorize apply.
6. Only explicit human review may create an apply request.
7. Apply must revalidate exact source snapshots and preserve complete source records and provenance.
8. No automatic merge, deletion, supersession, or rewrite is introduced.

## 3. Proposed module boundary

Introduce a new isolated module in the later implementation stage:

`memory/semantic_guardrails.py`

It must not import `brain.py`, perform I/O, call a model, access the canonical memory file, or invoke the embedding provider. It receives two validated record snapshots and optional structured fact frames from a separately controlled extractor.

Proposed public contract:

- `analyze_fact_pair(left, right, left_frame=None, right_frame=None) -> GuardDecision`
- `GuardDecision` is immutable and contains:
  - `relation`: one of the labels in section 5;
  - `decision`: `CANDIDATE_FOR_REVIEW`, `SEPARATE`, or `UNCERTAIN`;
  - `reason_codes`: stable machine-readable evidence codes;
  - `evidence`: bounded, non-mutating details sufficient for review.
- Invalid input raises a specific validation error; it must not return a permissive decision.

This API is a proposal, not an implementation commitment. Names and data shape must be reviewed against existing P3.1/P3.2 callers before coding.

## 4. Fact frame

A fact frame is structured evidence, not an inferred truth. Every field may be unknown.

| Attribute | Meaning | Examples |
|---|---|---|
| subject/entity | Who or what the statement is about | Roman, Maria, server |
| predicate/relation | The asserted relation or property | uses, lives_in, available |
| polarity/state | Affirmed, negated, present, absent | enabled / disabled |
| value | Explicit quantity or categorical value | 8, 256, available |
| unit | Unit attached to a value | GB, TB, days |
| semantic role | What the value measures | RAM, storage, timeout |
| interval | Validity time or date range | since date, until date |
| modality | Strength/possibility/obligation | must, may, can, cannot |
| provenance | Source and origin metadata | user, system, imported |

Do not equate different surface forms without an explicit normalization rule. For example, GB and TB require a unit-aware conversion policy; a bare number must not be compared to a number with an unknown unit. Distinct subjects, roles, incompatible values, incompatible intervals, or opposite states are hard conflicts when reliably extracted.

If extraction cannot distinguish subject from object, or cannot assign a numeric role, the corresponding attribute remains unknown. Unknown is not a wildcard.

## 5. Pair relation taxonomy

Exactly one relation label is returned:

| Relation | Definition | Outcome |
|---|---|---|
| `DUPLICATE` | Same subject, predicate, state, value/role, modality, and compatible time; wording differs | Candidate for review |
| `REFINEMENT` | Same proposition with compatible additional detail and no changed assertion | Candidate for review, explicit review required |
| `CONTRADICTION` | At least one reliable hard attribute conflicts | Separate |
| `RELATED_INDEPENDENT` | Shared topic or causal connection, but distinct propositions | Separate |
| `UNRELATED` | No meaningful proposition relationship | Separate |
| `UNCERTAIN` | Evidence is incomplete, ambiguous, or extractor disagreement exists | Uncertain; no merge |

A relation classifier must not label a pair `DUPLICATE` or `REFINEMENT` when any reliable hard conflict exists.

## 6. Hard-check order

The later implementation should evaluate checks in this order and report all applicable reason codes:

1. Record and frame validity; reject malformed values.
2. Category compatibility.
3. Subject/entity identity.
4. Predicate/relation identity.
5. Polarity and state, including lexical opposites and presence/absence.
6. Numeric value, unit, range, and semantic role.
7. Date/interval and temporal validity.
8. Modality and certainty.
9. Provenance/source constraints where required by the caller.

A reliable mismatch yields `CONTRADICTION` or `RELATED_INDEPENDENT` and `SEPARATE`. An unknown or ambiguous field yields `UNCERTAIN` unless the remaining evidence proves a hard conflict. Similarity scores may rank candidates but are not inputs to hard-check compatibility.

## 7. Ingestion protection is a separate boundary

The current `memory_core.add_memory()` lexical-overlap path is independent of semantic preview. The audit identified that a lexical match can update or suppress an incoming statement before contradiction detection.

The later ingestion change must ensure:

- Exact normalized duplicates may be reported as duplicates under the existing explicit policy.
- Lexical/embedding matches only attach candidate references for review.
- A similarity match alone never returns a "already exists" result that discards the incoming fact.
- A similarity match alone never rewrites an existing record.
- If the guard returns `UNCERTAIN`, preserve the incoming fact as a separate record or route it to an explicit review queue; never suppress it.
- Any change to ingestion semantics requires dedicated tests around `add_memory()` and a separately reviewed migration/compatibility impact assessment.

This design does not choose the final persistence behavior for review queues; that decision belongs to the implementation proposal.

## 8. Review/apply boundary

Only `DUPLICATE` and `REFINEMENT` can create a review proposal. A proposal must show both full source records, IDs, timestamps, category, source/provenance, extracted attributes, reason codes, and uncertainty.

The reviewer supplies the merged text explicitly. Immediately before apply:

- reload current records;
- compare each full record to the proposal snapshot;
- reject stale or missing sources;
- preserve complete original records and provenance;
- require the existing explicit apply operation;
- do not silently retry against changed records.

No guard decision directly calls the apply operation.

## 9. Required implementation and regression plan

The next implementation proposal must split work into independently reviewable changes:

**A. Pure guard module**
- deterministic hard checks;
- immutable decision result;
- no filesystem/network/model imports;
- fail-closed behavior for unknowns and malformed frames.

**B. Adversarial regression coverage**
- implicit opposite states (available/unavailable);
- different subjects with identical predicates;
- swapped numeric roles;
- unit changes and incompatible ranges;
- presence/absence and enabled/disabled;
- date/interval changes;
- modality changes;
- causal but independent facts;
- topically related distinct facts;
- ambiguous/incomplete frames;
- positive paraphrase/refinement controls.

**C. Ingestion isolation**
- reproduce the current lexical-overlap rewrite/suppression case;
- require the new incoming fact to remain preserved;
- assert existing record text and provenance remain unchanged;
- test through a temporary memory file only.

**D. Review/apply safety**
- stale snapshot rejection;
- no apply call from candidate discovery;
- complete source provenance retained;
- no write on `UNCERTAIN`, `CONTRADICTION`, or `RELATED_INDEPENDENT`.

For every adversarial class, assert the relation, decision, and reason codes. Keep zero false-merge behavior as the safety objective. Do not remove existing `expectedFailure` markers until the corresponding behavior is implemented and the test passes as a normal assertion.

## 10. Validation gates and non-goals

This design-only PR must not modify runtime modules. CI should run the existing Python 3.11 suite, including:
- `test_p3_2_4_semantic_guardrails`;
- `test_memory_semantic_consolidation`;
- `test_memory_consolidation`;
- the existing memory lifecycle and protection suites.

No threshold tuning, E5 integration, canonical memory access, automatic consolidation, changes to `brain.py`, changes to security permissions, or live-device deployment are part of this stage.

## 11. Decision required before implementation

Approval of this document authorizes only the design boundary described here. The next PR that adds `memory/semantic_guardrails.py` or changes `memory_core.add_memory()` must be a separate implementation proposal with its own diff, regression suite, CI evidence, and explicit review before merge.
