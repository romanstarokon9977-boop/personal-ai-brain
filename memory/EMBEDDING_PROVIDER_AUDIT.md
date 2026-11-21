# P3.2.1 — Local embedding provider: implementation and device-validation status

Last reconciled with `main` at `2d924da3de0a0b3c408e0b197014c89591c68738` (2026-11-20).

## Purpose and privacy boundary

Semantic memory candidate discovery can use embeddings locally so that personal memory text need not be sent to an external embedding API. The adapter is designed for a dedicated loopback llama.cpp embedding server. It does not provide a remote fallback and does not start or stop servers.

## Current repository implementation

The previously proposed adapter now exists as `memory/local_embedding_provider.py`.

It:
- accepts only HTTP loopback hostnames (`127.0.0.1`, `localhost`, `::1`);
- disables environment proxies and refuses HTTP redirects;
- posts batches to `/v1/embeddings`;
- applies the `query: ` prefix to supplied text for the multilingual-e5 retrieval model;
- validates response count, unique indexes, vector dimensions, numeric values, finite values and non-zero vectors;
- raises explicit `LocalEmbeddingError` failures and has no external fallback.

Contract coverage exists in `test_local_embedding_provider.py`; provider integration and read-only preview coverage exists in `test_p3_2_4_9_provider_integration.py`.

The guarded semantic preview is exposed by Memory Core as `preview_guarded_semantic_memory_consolidation(embed_texts, extract_fact_frames, min_similarity=0.82)`. It is a preview operation: it does not apply merges or mutate memory. Applying a reviewed candidate still requires the existing explicit `apply_memory_consolidation(candidate, merged_text)` path, which revalidates source snapshots and preserves provenance.

## What is not yet proven

- The provider is not automatically wired into Brain's normal startup or memory-retrieval lifecycle.
- The dedicated embedding server on port 8090 has not been verified on POCO F6 in this GitHub-only work.
- The candidate GGUF model file, provenance, checksum, model compatibility, memory footprint, thermal behavior, latency and Russian semantic quality have not been measured on the device.
- Existing Qwen chat servers on ports 8085 and 8088 must remain separate; their chat endpoint is not evidence of embedding support.

## Device validation gate

Before enabling automatic use:
1. Record the installed llama.cpp version/commit and confirm embedding support.
2. Verify the selected GGUF artifact, provenance, license and SHA-256.
3. Start a separate embedding-only server on loopback; do not alter Qwen chat services.
4. Check `/health`, `/v1/models` and `POST /v1/embeddings` using synthetic text only.
5. Verify vector count, dimension, finite values and non-zero norm.
6. Measure Russian paraphrase, negation and numeric-conflict cases against a fixed synthetic benchmark.
7. Measure cold/warm latency, peak RAM and thermal behavior on POCO F6.
8. Verify the user's memory file checksum is unchanged throughout testing.

No personal memory records should be used for initial device tests without explicit approval.

## Current status

| Item | Status |
|---|---|
| Loopback-only provider implementation | Implemented |
| Provider contract tests | Present in CI |
| Guarded read-only semantic preview | Implemented |\n| Local CLI preview command (`память семантика`) | Implemented; requires a separately started loopback embedding service |
| Explicit reviewed apply path | Implemented |
| Automatic Brain lifecycle integration | Not implemented |
| Dedicated server validation on POCO F6 | Not verified |
| Device performance and semantic benchmark | Not verified |
| External embedding API fallback | Not present |

This distinction is mandatory: implemented adapter and passing synthetic tests do not establish that the local embedding service is operational on the target phone.
