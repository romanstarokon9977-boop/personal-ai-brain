# Personal AI Brain — Self-Improvement

## Purpose

Deliver the Section 6 capabilities as one controlled subsystem:

- 6.1 Self-diagnostics
- 6.2 Answer-quality analysis
- 6.3 Controlled module improvement
- 6.4 Verified solution library

## Audit baseline

The implementation branch is based on `main` commit
`25a924bfc3c1d5f78a7efc60dc2a23bf61d5515c` (2026-11-14).

Existing components found during the read-only audit:

| Component | Existing responsibility | Limitation relevant to Section 6 |
|---|---|---|
| `self_inspection.py` | File hashes, Golden references, Git state | Fixed inspected-file list; not a complete capability/dependency inventory |
| `verifier.py` | Static code checks and tool-result contract validation | Does not maintain longitudinal answer-quality history |
| `tool_error_handler.py` | Error classification and advisory recovery guidance | Does not aggregate recurring errors over time |
| `module_manager.py` | Persistent enabled/disabled state | Not a diagnostic or improvement planner |
| `tool_catalog.py` | Read-only registry inventory and authorization view | Does not propose or implement architectural changes |
| `tool_proposal_manager.py` | Inert lifecycle for proposed tools | Specific to tool proposals, not general module improvements |

No dedicated verified engineering-solution library was found in the audited source paths.

## New package

- `self_improvement.core.collect_diagnostics`: composes existing read-only diagnostics and module-manager health. Missing evidence is UNKNOWN, not a failure.
- `analyze_quality_events`: groups explicitly supplied quality events and distinguishes failures, uncertainty, passes and user preferences. It does not infer root cause.
- `build_improvement_proposal`: creates an inert technical proposal with evidence, affected modules, tests, risk and approval flags.
- `ImprovementEventStore`: persists only explicitly supplied, bounded metadata; it does not scrape conversations.
- `SolutionLibrary`: stores reusable algorithm descriptions. CANDIDATE can become VERIFIED only with an explicit passing test-run reference.

## Safety boundaries

- No self-modifying code, dynamic imports, generated-code execution or automatic deployment.
- No permissions are granted by diagnostics, proposals or library records.
- No automatic conversation capture. Callers must explicitly submit sanitized event metadata.
- Stores are bounded, atomically replaced and created with mode 0600.
- Parent directories are never created implicitly.
- A proposal remains inert; approval and implementation are separate decisions.
- A solution record is knowledge, not executable code.

## Integration status and next steps

This PR establishes tested, standalone infrastructure. Runtime event instrumentation,
user-facing commands, registry exposure and end-to-end workflow integration are
intentionally separate follow-up work after review of this foundation. No claim is
made that answer-quality events are automatically captured yet.

## Validation

GitHub Actions must compile the package and run `test_self_improvement.py`.
Device validation on POCO F6 remains required after merge and is not represented
by GitHub CI.
