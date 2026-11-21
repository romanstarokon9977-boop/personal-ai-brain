# Phase 4 — Skills, Tool Catalog, Tool Proposals, MCP Catalog and Error Handling

Current implementation baseline: `main` at `2d924da3de0a0b3c408e0b197014c89591c68738` (2026-11-20).

This document supersedes the outdated integration statements in the original Phase 4 audit.

## 4.1 Dynamic skills — runtime prompt integration present

- `skills_manager.py` loads bounded JSON skill descriptors and validates their schema, size, categories, triggers and instruction length.
- `brain.py` selects skills for each user request, renders a bounded reference context and appends it to the model messages under the `skill_guidance` name.
- The rendered text is explicitly marked as untrusted reference data. It cannot authorize tools, override higher-priority instructions or change permissions.
- Selection is literal-trigger based, capped at three skills. This is a deterministic first version, not semantic skill retrieval.
- Runtime integration coverage exists in `test_phase4_runtime_integration.py`.

## 4.2 Tool catalog — native runtime exposure present

- `tool_registry.py` remains the source of registered tool definitions and model-facing schemas.
- `autonomy_controller.py` remains authoritative for AUTO / CONFIRM / BLOCK decisions.
- `tool_catalog.py` provides a read-only inventory including the effective authorization decision.
- The catalog is exposed through the native tool dispatch path and covered by runtime integration tests.
- Catalog metadata does not grant permissions; path checks, module state, validation and verification remain separate controls.

## 4.3 Tool proposals — proposal-only lifecycle

- `tool_proposals.py`, `tool_proposal_manager.py` and `tool_proposal_commands.py` validate and persist proposals and can produce inert code drafts.
- A proposal is not executable code. Proposal creation does not write implementation files, import code, register a tool or enable a module.
- Review, implementation, tests and explicit activation remain separate gated steps.

## 4.4 MCP external services — catalog only, not a general connector runtime

- `mcp_bridge.py` currently supplies the local stdio MCP integration used by the application.
- `mcp_server_catalog.py` validates declarative server metadata and keeps registrations disabled.
- The catalog does not start arbitrary servers, establish OAuth/API credential flows, store secrets or implement service-specific adapters.
- Therefore, general-purpose external service integration is NOT complete. Each new service requires a separately reviewed adapter, credential boundary, consent flow, lifecycle handling and tests.

## 4.5 Tool error handling

- `tool_error_handler.py` provides a separately testable error taxonomy and advisory recovery guidance.
- Retry decisions remain constrained by `execution_engine.py` and its explicit read-only allowlist. Unknown and side-effecting tools must not be retried automatically.

## Security and autonomy boundaries

- Skills are untrusted reference content, not executable code or authorization.
- Tool proposals remain inert until separately reviewed and implemented.
- MCP catalog registration does not start processes or grant network access.
- Self-improvement diagnostics and solution candidates do not authorize self-modification.
- User confirmation and the existing autonomy policy remain authoritative.

## Validation

- `test_phase4_infrastructure.py` covers isolated infrastructure contracts.
- `test_phase4_runtime_integration.py` covers live prompt selection, native tool exposure/dispatch and inert proposal behavior.
- CI compiles project/test modules, runs isolated unittest modules and runs full unittest discovery.
- The latest main CI run at this baseline is recorded in `docs/PRODUCT_READINESS.md`.
- CI does not prove runtime compatibility on POCO F6; device-specific checks remain a separate release gate.
