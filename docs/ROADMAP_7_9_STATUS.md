# Roadmap audit — sections 7–9

Audit baseline: `main` commit `37f4c3920a061820a884644eaf3f4c8ad1803c35`  
Audit date: 2026-11-27  
Target runtime: POCO F6 / Android / Termux

This is the master checklist. The implementation PRs below are separate and remain unmerged until explicitly approved. A green CI is not device acceptance.

## 7. Reliability and security

| Item | Work prepared | Current status | Still required |
|---|---|---|---|
| 7.1 Protected backups | PR #91: AES-256-GCM encrypted portable export of memory, tasks and module state; hidden passphrase; verify and decrypt-to-staging commands | Partial | Existing automatic local snapshots remain plaintext; no Android keystore/key recovery; independent off-phone copy must be transferred manually; perform restore drill |
| 7.2 Integrity control | PR #90: read-only inventory for memory, task store, module state and backup checksums/schema | Partial | Trusted baseline for critical code/config; detect unexpected code/config changes; verify more stores and run device failure tests |
| 7.3 Confidentiality | PR #92: PUBLIC/INTERNAL/PERSONAL/SECRET/USER_INPUT classification, private-context filtering, credential-pattern scan, external-dispatch block and CPA/MCP error redaction | Partial | Pattern scanning is not exhaustive; extend coverage to all logs, exports and connectors; formal external-transfer consent and repository secret scanning |
| 7.4 Action journal | PR #89: append-only metadata-only journal for model tool calls, task lifecycle writes and memory-store writes | Foundation | Cover module changes, MCP lifecycle, updates, backup/restore, all CLI actions; add rotation, integrity chaining and export controls |
| 7.5 Disaster recovery | PR #90: integrity/recovery inspection; PR #91: authenticated decryption into a new staging directory; existing memory/task checkpoint recovery | Partial | Coordinated transactional restore across memory/tasks/module state; rollback after interrupted restore; version compatibility and POCO F6 recovery drill |

## 8. User interface and interaction

| Item | Work prepared | Current status | Still required |
|---|---|---|---|
| 8.1 Unified dashboard | PR #95: compact read-only Termux panel for model, memory, tasks, tools, candidates and background processes | First CLI panel | Graphical dashboard, refresh controls and unified approval queue |
| 8.2 Task management | PR #93: critical/high/normal/low priorities, priority ordering, history and safe legacy defaults; existing interrupt/continue/confirmation flows | Partial | Edit plans and deadlines; consolidated approvals; cancellation semantics and task stop verification |
| 8.3 Memory visualization | PR #94: single-record provenance card, source/confidence/dates/change metadata; existing candidate review and explicit confirmation | Partial | Searchable lifecycle UI, proposed-change diff/approval screen, archive/expiry controls |
| 8.4 Operating modes | PR #96: conversation, research, programming, learning and autonomous modes with enforced tool allowlists | Foundation | Persist per-chat profiles; refine task/privacy/cost routing; device tests for every mode and tool class |
| 8.5 Mobile optimization | PR #95: compact small-screen dashboard; current primary interface remains Termux CLI | Partial | Touch-first graphical UI, accessibility, responsive layout and Poco F6 acceptance |

## 9. Future direction

| Item | Work prepared | Current status | Still required |
|---|---|---|---|
| 9.1 Modular ecosystem | PR #97: strict versioned manifest, capability/permission/risk validation, dependency order and cycle detection | Contract foundation | Loader sandbox, signed packages, lifecycle hooks, install/uninstall and compatibility tests |
| 9.2 Portability | PR #91: encrypted bundle for memory, task history and optional module state; authenticated verify and staging decrypt | Partial | Settings/history completeness, path remapping, migration, second-device import and restore tests |
| 9.3 Local/cloud intelligence | Existing LOCAL and external routes, local llama.cpp services and local-only private-context boundary | Existing foundation | Explicit task/privacy/cost/latency routing policy; no silent cloud fallback for sensitive tasks; local tool execution remains separately guarded |
| 9.4 Provider independence | Existing OpenRouter-compatible, Gemini and llama.cpp paths | Partial | Stable provider adapter interface, normalized capabilities/errors, conformance suite and provider-switch tests |
| 9.5 Standalone product | README, Termux install guide, product-readiness docs, CI and safety tests | Early foundation | Reproducible install/update/uninstall, onboarding, configuration migration, release packaging, support docs and multi-device acceptance |

## PR implementation map

- #89 — action journal and task/memory mutation audit
- #90 — integrity inventory and recovery inspection
- #91 — authenticated encrypted backup export, verification and staging decryption
- #92 — data classification and secret-transfer guardrails
- #93 — task priority controls
- #94 — memory provenance cards
- #95 — compact mobile dashboard
- #96 — explicit operating modes and enforced tool allowlists
- #97 — versioned module manifest contract

All PRs are review candidates, not merged functionality. Review and merge in dependency order; after each merge, refresh/rebase the remaining branches and rerun CI.

## Remaining implementation sequence

1. Review and merge the prepared PRs only after all required checks pass.
2. Perform POCO F6 acceptance: encrypted export, wrong-password/tamper rejection, staging decrypt, memory provenance, task priority, dashboard and all modes.
3. Implement coordinated transactional recovery with rollback and interrupted-restore recovery.
4. Extend audit coverage to module/MCP/update/backup/CLI lifecycle events and add bounded rotation/tamper evidence.
5. Finish policy-based local/cloud routing and provider adapter conformance.
6. Build the touch-first mobile interface and approval queue.
7. Complete module sandbox/lifecycle, portable import/migration and release installer/uninstaller.

## Acceptance and safety rules

- GitHub `main` is authoritative. Each implementation stays on a dedicated branch and PR.
- Never commit memory, prompts, tool arguments/results, credentials, local exports or private logs.
- No module entrypoint executes merely because its manifest validates.
- No operating mode bypasses the existing authorization/confirmation policy.
- No encrypted restore overwrites live stores without a separate reviewed transaction and explicit user confirmation.
- CI is necessary but does not replace runtime, backup, recovery and privacy acceptance on the POCO F6.
- Do not mark a roadmap item complete until code, automated tests, device acceptance and recovery evidence all exist.
