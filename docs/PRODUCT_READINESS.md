# Personal AI Brain — Product Readiness Register

Baseline audited: `main` at `2d924da3de0a0b3c408e0b197014c89591c68738`  
Audit date: 2026-11-21  
Target runtime: Android / Termux on POCO F6; Python 3.11 CI baseline.

## Executive result

**Status: NOT RELEASE-READY — integration and device-validation gates remain.**

The repository contains a substantial working application: model routing, local chat-model support, memory, tools/MCP, planning, task execution, verification, context management and guarded self-improvement. The existence of these modules is not equivalent to a fully integrated, independently validated product.

This register separates code that is present and covered by repository tests from capabilities that still require implementation or on-device proof. Do not describe the project as fully autonomous, fully private or production-ready until all release gates below pass.

## Verified architecture inventory

| Domain | Current repository evidence | Readiness |
|---|---|---|
| Model routing | OpenRouter-compatible routing, model stats, fallback/cooldown logic; latest main CI covers router tests | Implemented; live provider reliability remains external |
| Local chat inference | llama.cpp chat services configured on ports 8085 and 8088 | Code present; target-device smoke test required |
| Memory Core | Persistent fact memory, extraction queue, lifecycle, backup/restore and read-only audit modules | Implemented; recovery drill on device required |
| Semantic memory | Candidate retrieval, fact frames, semantic guardrails, explicit guarded preview/apply boundary and local CLI preview command `память семантика` | Manual preview integrated; automatic provider lifecycle and device validation absent |
| Embeddings | Loopback-only local provider and synthetic contract/integration tests | Adapter implemented; device service unverified |
| Planning and execution | Planner, Task Manager, execution engine, autonomy controller and verifier | API/Gemini agent path present; local model tool-calling is disabled, so strictly local agent execution is incomplete |
| Skills | Validated descriptors selected and injected into model context as untrusted reference data | Runtime integration present; literal matching only |
| Native tools | Registry, tool catalog, bounded execution and permission checks | Implemented; full permission matrix audit required |
| MCP | Local stdio bridge plus disabled declarative server catalog | General external-service runtime incomplete |
| Self-improvement | Feedback persistence, quality report, improvement proposals and solution candidates | Controlled proposal workflow; no autonomous code deployment |
| Android/Termux | Platform-specific paths and process management in code | CI cannot prove device compatibility or stability |

## Critical release gates

### G1 — Reproducible installation and startup
- **Documentation and dependency manifest added in the current candidate:** `README.md`, `docs/TERMUX_INSTALL.md` and `requirements.txt` now describe the Termux prerequisites, setup and launch path.
- Clean installation, upgrade, restart and recovery still require a device acceptance run on POCO F6.
- Verify fresh install, upgrade, restart and recovery without relying on hidden local state.
- Verify model files and local llama.cpp binary prerequisites with actionable diagnostics.
- Confirm startup does not silently start unwanted services or overwrite user data.

### G2 — Memory durability and privacy
- Exercise save, recall, update, archive, delete, backup and restore using temporary synthetic stores.
- Prove that backup restoration preserves record IDs, provenance and active/archive states.
- **External model privacy gate implemented in this candidate:** dynamic memory, prior chat recall and user-authored skill descriptors are loaded/appended only for an explicit LOCAL route. A second boundary at `controller_execute()` strips these blocks whenever a route is non-local. A failed LOCAL route cannot silently fall back to API/Gemini; only another LOCAL route may be retried, and any AUTO cloud lock selected during route discovery is cleared. Unknown and external routes fail closed and receive a non-sensitive notice that private context is unavailable. The local semantic preview is a CLI operation and does not return memory text to a remote model.
- The active request and ordinary in-session conversation history are still part of the request when an external model is selected. This gate protects the separate persisted memory, cross-chat recall and user-authored skill context; it cannot prevent the user from submitting content to a chosen provider.
- Verify memory and prompts are never sent to embedding services outside loopback.
- Verify logs and diagnostics do not expose API keys, personal memory content or other secrets.
- Define and test behavior when memory file is missing, malformed, partially written or inaccessible.

### G3 — End-to-end task execution
- Test the complete path: request → task classification → plan → permission decision → tool execution → postcondition verification → user-facing result.\n- Explicitly document and test that LOCAL mode currently disables model tool-calling; do not represent it as a fully offline agent until a bounded local tool path passes POCO F6 acceptance.
- Cover denied, confirmation-required, timeout, malformed tool result, partial completion and rollback cases.
- Prove side-effecting tools are never automatically retried after uncertain outcomes.

### G4 — Model routing and failure recovery
- Test empty choices, empty content, tool-call-only responses, malformed JSON, HTTP 429/5xx, timeout and provider disconnect.
- Verify cooldowns, fallback deduplication, manual model locks and state persistence.
- Ensure failed providers do not corrupt task state or memory.

### G5 — MCP and external services
- Keep unconfigured external servers disabled.
- For every future adapter, require explicit user consent, least-privilege scopes, secret isolation, process/network lifecycle controls, timeout handling and revocation tests.
- Do not mark the general external integration layer complete based only on the declarative catalog.

### G6 — Self-improvement safety
- Keep observation, proposal, review, implementation, tests and activation as distinct states.
- Require a reviewed patch and passing tests before any implementation can be activated.
- Never permit model-generated code to self-register or self-enable tools without the explicit authorization path.
- Test persistence and restart recovery of improvement events and proposals.

### G7 — POCO F6 device acceptance
- Run the clean-start and restart suite on the actual device.
- Verify local model startup, memory location, loopback ports, RAM headroom, CPU load, thermal behavior and long-session stability.
- Validate the dedicated embedding server separately from chat models.
- Confirm no personal data leaves the device except requests explicitly sent to the configured language-model provider.

## CI baseline

At the audited main commit:
- GitHub Actions run #784 for commit `2d924da3de0a0b3c408e0b197014c89591c68738` completed with conclusion `success`.
- Workflow: `.github/workflows/python-ci.yml`.
- CI compiles the enumerated project/test modules, runs isolated unittest modules and runs `python -m unittest discover -v`.
- CI uses Python 3.11 and a dummy OpenRouter key; it does not validate real API credentials, network availability, local GGUF files or Android process behavior.

A green CI run is necessary, not sufficient, for release.

Current candidate branch `work/product-readiness-audit-20261121` was also checked by GitHub Actions run #792 for commit `89c2d1f083ffa69e24e5bad411c4da09c1ce4076`; compilation, isolated unittest modules and full unittest discovery completed successfully. This is repository CI evidence only, not device validation.

## Definition of done

The product may be called release-ready only when:
1. Every critical gate G1–G7 has recorded evidence.
2. All repository tests and CI checks pass on the release candidate commit.
3. No unresolved critical/high severity security or data-integrity defect remains.
4. The device acceptance suite passes on POCO F6.
5. Installation, configuration, backup/recovery and operator documentation match the actual implementation.
6. The final PR is reviewed and explicitly approved by Roman.

## Working protocol

- `main` remains authoritative.
- Work only in a dedicated branch and submit a PR against `main`.
- Keep changes narrow, evidence-based and test-backed.
- Never merge the PR without Roman's separate instruction.
- Report verified facts, blockers and unverified assumptions separately.
