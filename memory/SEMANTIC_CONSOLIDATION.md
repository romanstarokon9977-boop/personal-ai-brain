# P3.2 — Semantic memory candidate discovery

## Scope

P3.2 adds an embedding-based candidate discovery engine alongside the P3.1
lexical detector. It does not replace P3.1 and does not change the consolidation
apply path.

## API

`memory.semantic_consolidation.find_semantic_consolidation_candidates(entries, embed_texts, min_similarity=0.82)`

- `embed_texts` is a caller-supplied batch function: input is a list of texts,
  output is a same-length list of numeric vectors.
- Cosine similarity is used to rank semantic proximity.
- Complete-link grouping requires every pair in a group to meet the threshold.
- Category, explicit number/date, and negation conflicts are excluded.
- Invalid provider output or provider failure raises an explicit error; it is
  never silently treated as an empty candidate list.
- The result contains full source snapshots and is compatible with the existing
  P3.1 review/apply flow.

## Memory Core

`memory_core.preview_semantic_memory_consolidation(embed_texts, min_similarity=0.82)`
loads the current memory and returns candidate groups without writing anything.

To apply a reviewed candidate, use the existing
`memory_core.apply_memory_consolidation(candidate, merged_text)` path. This
still requires explicit caller action and preserves the P3.1 snapshot checks,
backup, and atomic save pipeline.

## Deliberate boundary

No embedding model, provider, API key, network request, or new package is added
in this stage. Brain does not silently send private memory records to an external
service. A future provider adapter must be selected explicitly and tested
separately. Until then, callers must inject an embedding function (local or
remote) into the preview API.

This stage implements and tests the semantic engine and its integration point;
it does not claim that semantic embeddings are already generated automatically
on the device.
