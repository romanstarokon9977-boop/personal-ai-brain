# Phase 4 — Skills, Tool Catalog, Tool Proposals, MCP Integrations and Error Handling

Audit baseline: `main` at `3f9e2671dd164b28e1ad1f3e8d950594a0ba8bd4`.

## Audit findings

### 4.1 Dynamic Skills
- No dedicated skills directory/loader or runtime skill-selection module existed in the audited tree.
- Existing `context_manager.py` manages conversation context, not reusable task-specific skill packages.
- Gap: validated skill metadata, bounded discovery/selection and safe rendering.
- Added: `skills_manager.py` and four data-only skill descriptors. Content is never executed. Selection is literal-trigger based and capped at three skills.
- Integration status: library and descriptors are available; automatic injection into the live model prompt is intentionally not wired in this change because it requires a separately reviewed change to the large `brain.py` request/context pipeline.

### 4.2 Tool Catalog
- `tool_registry.py` is already the source of registered tool definitions and model-facing schemas.
- `autonomy_controller.py` is the authoritative AUTO/CONFIRM/BLOCK policy. Registry metadata alone does not grant permission.
- Gap: a single inspection/report view combining tool metadata with the actual authorization decision.
- Added: read-only `tool_catalog.py`. It derives authorization from the existing policy and does not mutate the registry.

### 4.3 Creating New Tools
- `module_manager.py` manages enabled/disabled state; it does not generate, validate or install new tool code.
- Existing `self_inspection.py` is diagnostic, not a code deployment mechanism.
- Added: `tool_proposals.py` to validate requirements and produce a proposal plus inert Python stub text. No file is written, code imported, tool registered or module enabled. Explicit review, tests and approval remain mandatory.

### 4.4 External Services
- `mcp_bridge.py` currently implements a local stdio MCP client with a fixed filesystem server executable and allowed directory.
- No general external-server manifest/consent catalog was present in the audited root.
- Added: declarative `mcp_server_catalog.py`. It validates metadata and records servers as disabled/not started. It does not spawn processes, open network connections or handle credentials.
- Actual server lifecycle, secret storage, OAuth/API credentials and service-specific adapters remain a separate integration stage.

### 4.5 Tool Error Handling
- `brain.py` contains a broad string-based `classify_error`; `execution_engine.py` separately permits only bounded retries for a fixed set of read-only tools.
- Gap: consistent tool-error taxonomy and recovery guidance as a separately testable component.
- Added: `tool_error_handler.py`. It classifies common failure classes and only marks a small explicit read-only allowlist retryable. Recovery is advisory; no automatic retry or permission change is performed.

## Safety and integration boundaries
- No edits to `brain.py`, `tool_registry.py`, `mcp_bridge.py`, autonomy policy, shell allowlist, secrets, runtime configuration or existing permissions.
- No automatic skill execution, code deployment, MCP process startup, network access or credential handling.
- This PR delivers tested standalone infrastructure and descriptors. Live prompt wiring, tool-registry metadata enrichment and actual external service adapters are explicitly deferred to separately scoped integration PRs after review.

## Validation
- Added isolated unit tests in `test_phase4_infrastructure.py`.
- CI is extended to compile and run the new test module.
- GitHub Actions results must be green before merge. Runtime activation on POCO F6 is not claimed by CI and must be tested separately after merge.
