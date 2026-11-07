# Memory lifecycle: retention, provenance, recovery

## Storage compatibility

The canonical runtime memory file remains `/storage/emulated/0/Documents/AI_Brain/brain_memory.json`.
The JSON envelope remains version 2 (`{"version": 2, "entries": [...]}`); lifecycle fields are additive and legacy readers can ignore them. Legacy entries are classified lazily when updated. Reading the store does not trigger a migration or write.

## 2.4 Retention classes

| Type | Default classification | Rule |
|---|---|---|
| `permanent` | `preferences`, `brain_info`, `arch_rules`, `dev_rules` | No automatic expiry; retained until an explicit user action |
| `long_term` | Other stable facts | No automatic deletion; review marker after 365 days |
| `temporary` | Explicitly selected by the caller | Archived after 7 days; never automatically hard-deleted |

Call `add_memory(..., memory_type="temporary")` to mark temporary material. Existing API calls remain valid. Call `archive_expired_memory()` to apply the archive policy. Archived and superseded records are excluded from dynamic recall but remain in the JSON store. Retention does not delete facts.

## 2.5 Provenance

New or touched records retain the existing `source` and `confidence` fields and add:
- `created_at`: immutable creation time;
- `updated_at`: last modification time;
- `source_date`: date associated with the source statement;
- `provenance`: source, source date, and confidence snapshot;
- `change_history`: append-only before/after values, timestamp, action, and actor.

The legacy `timestamp` field continues to represent the last update for compatibility with existing sorters. Fact refinements and manual updates record history. Contradictory facts are marked `superseded` with a link to the replacement instead of being silently removed. Explicit deletion remains available as a user operation.

## 2.6 Backup and recovery

Every pre-write snapshot is validated JSON and receives a sibling `.sha256` manifest. Snapshot creation verifies the copied bytes before the memory write proceeds. Rotation keeps the newest 10 JSON snapshots by default.

Memory Core APIs:
- `create_memory_backup()` — create a verified on-demand snapshot;
- `verify_memory_backup(filename)` — verify checksum and structure;
- `restore_memory_backup(filename)` — restore a verified snapshot atomically; a valid current store is snapshotted first;
- `archive_expired_memory()` — archive expired temporary records.

The lower-level `memory.backup_restore` module accepts explicit paths and is covered by isolated tests. Restore refuses snapshots without a valid SHA-256 sidecar. Historical snapshots created before this change have no sidecar and are intentionally not treated as integrity-verified restore points.

## Safety invariants

1. Corrupt or unreadable memory is never interpreted as an empty store.
2. A failed backup aborts a normal memory write.
3. A restore candidate is checksum-verified and schema-validated before replacing the target.
4. Restore writes through a same-directory temporary file, fsyncs it, atomically replaces the target, then reads back and verifies the restored bytes.
5. Expiry archives; it does not erase.
6. Legacy JSON version 1 and 2 snapshots remain parseable, but only snapshots with a valid sidecar are eligible for restore.
