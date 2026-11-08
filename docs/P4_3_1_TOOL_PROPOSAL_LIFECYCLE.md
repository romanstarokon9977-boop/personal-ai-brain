# P4.3.1 — Persistent Tool Proposal Lifecycle

## Scope

This change adds an isolated proposal metadata manager. It does not connect the manager to Brain commands or the runtime Tool Bridge.

## API

- `ToolProposalManager(store_path, registry)`: requires an explicit JSON file path and a readable registry.
- `create(proposal)`: validates and persists a `PROPOSED` record.
- `list_proposals(status=None)`: lists copies of records, optionally filtered by `PROPOSED`, `APPROVED`, or `REJECTED`.
- `get(proposal_id)`: retrieves a copy by ID.
- `review(proposal_id, "APPROVED" | "REJECTED", note="")`: records a review transition from `PROPOSED` only.

## Safety invariants

- Store path is explicit; the manager does not choose a default path or create parent directories.
- Writes use a same-directory temporary file, fsync, atomic replace, and mode 0600 where supported.
- Invalid, oversized, corrupt, or unsupported stores fail closed.
- Proposal names cannot collide with registered tool names or any prior proposal name.
- Required permissions must match an existing registered tool name or capability.
- Proposal risk cannot be lower than the risk of any requested permission.
- Known forbidden capabilities are rejected.
- Approval/rejection changes metadata only. `implementation_applied` remains false and `activation_allowed` remains false.
- There is no code generation, source-file write, import, ToolRegistry mutation, module activation, or runtime dispatch in this manager.

## Approval boundary

The caller must obtain explicit human confirmation before calling `review`. This module records the decision but does not authenticate the reviewer or provide an interactive approval UI. `APPROVED` means the proposal passed a human review checkpoint; it is **not** permission to implement, register, or activate the tool.

## Deferred work

Runtime commands, user identity/authentication, implementation workflow, acceptance-test execution, registration, and activation are intentionally out of scope. They require a separate design and approval.
