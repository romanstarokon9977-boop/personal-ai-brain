# Read-only memory audit

The `memory_audit` native tool reports aggregate lifecycle metadata for the
canonical runtime store at:

`/storage/emulated/0/Documents/AI_Brain/brain_memory.json`

## Security boundary

- The model-facing tool accepts no arguments and cannot select another path.
- The implementation opens the fixed file with `O_RDONLY` and uses
  `O_NOFOLLOW` when the platform provides it.
- Only regular files up to 8 MiB are accepted.
- It does not create a missing file, create backups, migrate data, archive
  entries, or invoke restore operations.
- It deliberately does not import `memory.memory_core`: `_load_raw()`
  calls `_ensure_file()`, which can create the canonical store, while
  `load_memory()` can apply retention archival.
- The response contains counts and policy labels only. It never returns
  entry text, identifiers, source values, provenance contents, or history
  contents.

## Report fields

- Total records and memory version.
- Effective permanent / long-term / temporary classification, including
  legacy classification rules.
- Records missing an explicit `memory_type`.
- Presence counts for lifecycle/provenance metadata.
- Active, archived, superseded, and other status counts.
- Count of expired temporary records that remain active and are awaiting
  the next normal Memory Core load/retention pass.
- The configured retention policy and the code-level load-time archival
  behavior.

This is an aggregate diagnostic, not a repair or migration command.
