# Roadmap audit — sections 7–9

Audit baseline: `main` commit `37f4c3920a061820a884644eaf3f4c8ad1803c35`  
Audit date: 2026-11-27  
Target runtime: POCO F6 / Android / Termux

This register distinguishes code presence, automated coverage and device acceptance. A module existing in the repository does not mean the complete user-facing capability is finished.

## 7. Reliability and security

| Item | Current evidence | Status | Remaining work |
|---|---|---|---|
| 7.1 Encrypted backups and off-device copy | `memory/backup_restore.py` creates atomic JSON snapshots with SHA-256 sidecars; restore verifies before replacement and preserves a valid current snapshot | Partial | Add authenticated encryption using a maintained crypto library; key provisioning/recovery; user-approved export to independent storage; restore drill on POCO F6 |
| 7.2 Integrity control | Memory snapshot checksum/schema checks; `module_manager.py` validates its own state; atomic writes/checkpoints exist in memory and task storage | Partial | Add a read-only integrity inventory for critical files/config/stores; detect missing, malformed and unexpected changes; define trusted baseline and recovery policy |
| 7.3 Confidentiality | Local memory/chat recall/skills are restricted to explicit LOCAL routes; external dispatch strips private context; embedding adapter is loopback-only; install docs keep API keys in environment variables | Partial | Formal data classification and storage boundaries; secret scanning/redaction tests across logs, diagnostics, exports and Git; explicit consent for every external transfer |
| 7.4 Action journal | This branch adds a local append-only JSONL journal for model-requested tool calls: tool, policy decision, permission source, coarse outcome and duration; no arguments or payloads | Foundation implemented in this PR | Extend coverage to CLI operations, task lifecycle, memory mutations, module changes, MCP lifecycle and update/recovery events; add rotation and tamper-evidence |
| 7.5 Disaster recovery | Atomic memory restore with pre-restore snapshot; Task Manager checkpoint/restart recovery; module state has guarded recovery | Partial | Define coordinated backup set for memory/tasks/config/module state; verify compatibility/version; run failure-injection and POCO F6 restore drills without overwriting newer user data |

## 8. User interface and interaction

| Item | Current evidence | Status | Remaining work |
|---|---|---|---|
| 8.1 Unified dashboard | CLI startup/status commands and separate subsystem diagnostics | Not implemented as a unified panel | Mobile-first dashboard with health, models, memory, tasks, tools and processes |
| 8.2 Task controls | Planner and Task Manager persist plans/checkpoints; CLI supports listing, inspection, progress, pause/interruption and explicit continuation | Partial | Unified priority editing, approval queue, cancellation and safe stop controls |
| 8.3 Memory visualization | CLI memory display/status, provenance fields and read-only audit exist | Partial | Searchable memory view with source/provenance, lifecycle state, history and proposed changes |
| 8.4 Operating modes | AUTO/LOCAL/provider routing and task-aware planning exist | Partial | Explicit user-facing chat, research, programming, learning and autonomous-execution profiles with mode-specific permissions |
| 8.5 Mobile optimization | Primary runtime is terminal-based and documented for Termux | Partial | Touch-friendly UI, small-screen layout, accessibility and device acceptance |

## 9. Future direction

| Item | Current evidence | Status | Remaining work |
|---|---|---|---|
| 9.1 Modular ecosystem | Tool Registry, Module Manager, skills descriptors and disabled MCP server catalog | Foundation implemented | Versioned module contract, dependency/capability manifests, lifecycle hooks and compatibility tests |
| 9.2 Portability | Memory is in shared storage; task/config/state files are separate; memory restore exists | Partial | Versioned encrypted export/import bundle for settings, memory and task history; path remapping and migration tests on a second device |
| 9.3 Local/cloud intelligence | LOCAL and external provider routes exist; local chat services are supported | Partial | Policy-based routing by task/privacy/cost/latency; explicit consent; local tool execution remains disabled and must not be advertised as complete |
| 9.4 Provider independence | OpenRouter-compatible routing, Gemini path and local llama.cpp services exist | Partial | Stable provider adapter contract, normalized errors/capabilities and conformance tests independent of provider-specific logic |
| 9.5 Standalone product | README, Termux installation guide, CI and product-readiness register exist | Early foundation | Reproducible installer/update/uninstall, secure onboarding, backup migration, user documentation, support and release acceptance |

## Implementation order

The work is intentionally split into reviewable PRs. Do not combine a mobile UI rewrite, cryptographic backup design and execution-policy changes into one high-risk patch.

1. **7.4 foundation (this PR):** privacy-preserving tool-action journal and tests.
2. **7.2 + 7.5:** read-only integrity inventory, coordinated recovery design and failure-injection tests.
3. **7.1 + 7.3:** authenticated backup encryption, key lifecycle, off-device export consent and secret-boundary audit. No home-grown cryptography; use a maintained authenticated-encryption implementation.
4. **8.2 + 8.3:** task and memory control/read APIs with provenance and permission boundaries.
5. **8.1 + 8.4 + 8.5:** mobile-first dashboard and explicit operating profiles.
6. **9.1–9.4:** stable module/provider contracts, migration/export format and conformance tests.
7. **9.5:** installer, operator documentation, release packaging and full device acceptance.

## Acceptance rules

- `main` is authoritative; work stays on a dedicated branch and PR.
- Never store user memory, prompts, tool arguments, tool output, API keys or secrets in Git.
- Destructive or external side effects require the existing authorization path and explicit user consent.
- CI is necessary but does not replace POCO F6 runtime/recovery testing.
- No PR is merged without Roman's separate instruction.
