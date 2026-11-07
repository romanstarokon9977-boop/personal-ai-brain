# P3.2.3 — Read-only local embedding benchmark

## Purpose

Measure whether the local `multilingual-e5-small` embedding endpoint can retrieve semantic-consolidation candidates without confusing duplicates with merely related or contradictory facts.

This is an offline-first, synthetic benchmark. It does not import Brain modules, inspect the canonical memory file, connect to Memory Core, or write benchmark output to disk.

## Scope

- 40 Russian-language text pairs (80 texts), five pairs in each of eight classes.
- True matches: paraphrases and structurally different semantic duplicates (10 pairs).
- Expected separate: contradictions, negations/presence-absence, changed numbers/dates, causally related independent facts, topically related distinct facts, and unrelated texts (30 pairs).
- Two embedding requests over the same ordered text batch to estimate repeatability.
- Cosine similarity, vector dimension, finite-value checks, L2 norms, latency, precision/recall/F1, category-level errors.
- Best-effort device snapshot: available RAM, benchmark process peak RSS, and readable thermal-zone values.

## Run on POCO F6 / Termux

Prerequisite: the dedicated local embedding server is already running on loopback port 8090. Do not stop or reconfigure the existing Brain/model servers on ports 8085 or 8088.

From the repository root:

```bash
python tools/embedding_benchmark_p3_2_3.py
```

Optional arguments:

```bash
python tools/embedding_benchmark_p3_2_3.py --url http://127.0.0.1:8090/v1/embeddings --model multilingual-e5-small --threshold 0.82 --timeout 60
```

The script uses only Python standard-library modules. It sends two batched HTTP requests to the explicitly configured local endpoint. It prints results to stdout and keeps all synthetic data and vectors in process memory.

## Interpretation

- `TP`: expected duplicate pair accepted as a candidate.
- `FP`: expected separate pair incorrectly accepted. This is the critical risk for memory consolidation.
- `FN`: true paraphrase/duplicate pair missed.
- `TN`: expected separate pair correctly rejected.
- `precision`: proportion of accepted pairs that are expected matches.
- `recall`: proportion of expected matches that are accepted.
- `vector stability`: cosine similarity between each text's vector from request 1 and request 2.
- `threshold=0.82` is a benchmark starting point, not a validated production threshold. Results must be reviewed across all categories; a single aggregate score is insufficient.

Causal and topical classes are deliberately labelled `SEPARATE`: semantic relatedness is not evidence that two records express the same fact.

## Measurement limitations

- The benchmark measures endpoint request latency, not model cold-start time.
- Peak RSS belongs to the benchmark Python process, not necessarily the embedding server process.
- Available RAM and thermal-zone readings are best-effort snapshots. Android may restrict thermal sysfs access; a missing value is not a zero temperature.
- A before/after temperature snapshot cannot establish sustained heating. For a meaningful thermal assessment, record device temperature and throttling externally during a longer repeated run.
- Synthetic pairs are a controlled diagnostic set, not a representative sample of the user's real memory.

## Safety boundary

This benchmark is strictly read-only with respect to the repository's application data and memory:

- no imports from `brain.py`, `memory_core.py`, or consolidation code;
- no reads or writes of `brain_memory.json`;
- no writes of result files or model files;
- no changes to ports 8085/8088;
- no automatic threshold tuning, memory merge, or provider integration.

The script is a measurement tool only. Its output does not authorize connecting embeddings to live memory consolidation.
