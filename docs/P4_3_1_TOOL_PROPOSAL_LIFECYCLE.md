# P4.3.1 — Persistent Tool Proposal Lifecycle

## Scope

This document describes the persistent proposal metadata manager and its direct-terminal review and implementation-preparation request commands. The manager remains isolated from runtime tool registration and execution.

## API

- `ToolProposalManager(store_path, registry)`: requires an explicit JSON file path and a readable registry.
- `create(proposal)`: validates and persists a `PROPOSED` record.
- `list_proposals(status=None)`: lists copies of records, optionally filtered by `PROPOSED`, `APPROVED`, `REJECTED`, or `IMPLEMENTATION_REQUESTED`.
- `get(proposal_id)`: retrieves a copy by ID.
- `review(proposal_id, "APPROVED" | "REJECTED", note="")`: records a review transition from `PROPOSED` only.
- `request_implementation(proposal_id, note="")`: records a separate implementation-preparation request from `APPROVED` only; this is not implementation permission.

## Safety invariants

- Store path is explicit; the manager does not choose a default path or create parent directories.
- Writes use a same-directory temporary file, fsync, atomic replace, and mode 0600 where supported.
- Invalid, oversized, corrupt, or unsupported stores fail closed.
- Proposal names cannot collide with registered tool names or any prior proposal name.
- Required permissions may be an empty list for a purely computational proposal that operates only on supplied input and needs no external/system access. Every non-empty permission must match an existing registered tool name or capability; unknown, blank, or invalidly typed entries are rejected.
- The model-facing `propose_tool` contract explicitly instructs the model to use `[]` when a proposal only processes supplied arguments in memory and does not access files, Brain memory, network, device, database, or other external/system resources. `filesystem.read`/`read_file` must not be added merely because the input is text.
- Proposal risk cannot be lower than the risk of any requested permission. An empty permission list has no permission-derived risk floor; the proposal's own risk classification and human confirmation gate still apply.
- Known forbidden capabilities are rejected.
- Approval/rejection changes metadata only. `implementation_applied` remains false and `activation_allowed` remains false.
- A separate `IMPLEMENTATION_REQUESTED` state is reachable only from `APPROVED`. The direct terminal command is `предложение подготовить <ID>` and requires the exact second confirmation phrase `ПОДГОТОВИТЬ РЕАЛИЗАЦИЮ <ID>`.
- The implementation request records a timestamp and optional note only. It does not change proposal permissions or the inert flags.
- There is no code generation, source-file write, import, acceptance-test execution, ToolRegistry mutation, module activation, or runtime dispatch in this manager.

## Approval boundary

The direct terminal caller must obtain an exact second confirmation before calling `review` or `request_implementation`. These commands are not model-callable. The manager records metadata but does not authenticate the reviewer. `APPROVED` means the proposal passed a human review checkpoint; it is **not** permission to implement, register, or activate the tool. `IMPLEMENTATION_REQUESTED` records a separate human request to prepare a future implementation; it still does not apply code, run tests, register, or activate the tool.

## Deferred work

Actual implementation drafting, source-file writes, acceptance-test execution, registration, and activation remain out of scope. Each requires a separate bounded design, explicit authorization, and independent verification.
