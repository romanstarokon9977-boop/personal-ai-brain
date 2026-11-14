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

- `self_improvement.core.collect_diagnostics`: composes existing read-only diagnostics, Golden-reference integrity, Git worktree counts and module-manager health. Golden drift is WARNING, corrupted reference data is ERROR, and missing evidence is UNKNOWN rather than a failure.
- `analyze_quality_events`: groups quality events and distinguishes failures, uncertainty, passes and user preferences. It does not infer root cause.
- `record_answer_feedback`: explicit feedback tool; records only category, outcome and optional evidence code. The native tool is MEDIUM-risk and requires user confirmation.
- `build_quality_report`: summarizes explicitly recorded feedback events; no conversation transcript is retained.
- `build_improvement_proposal`: creates an inert technical proposal with evidence, affected modules, tests, risk and approval flags.
- `ImprovementEventStore`: persists bounded metadata in the directory containing the Brain memory file, using private atomic writes.
- `SolutionLibrary`: exposed through the confirmation-gated `solution_library` tool. It stores reusable algorithm descriptions, not executable code or permissions. CANDIDATE can become VERIFIED only with a caller-supplied passing test-run reference; this is an attestation, not cryptographic CI verification.

## Safety boundaries

- No self-modifying code, dynamic imports, generated-code execution or automatic deployment.
- No permissions are granted by diagnostics, proposals or library records.
- No automatic conversation capture. Callers must explicitly submit sanitized event metadata.
- Stores are bounded, atomically replaced and created with mode 0600.
- Parent directories are never created implicitly.
- A proposal remains inert; approval and implementation are separate decisions.
- A solution record is knowledge, not executable code.

## Integration status and next steps

The read-only diagnostic report is exposed as the native `self_improvement_report`
tool under the exact LOW-risk read-only authorization allowlist. It does not invoke
MCP, write state, or collect conversation history.

Quality feedback is recorded only when the user explicitly asks Brain to save it and
confirms the MEDIUM-risk tool call. Runtime verification outcomes are not yet
automatically captured; this is deliberately separate from subjective answer
feedback so uncertainty and user preference are not mislabeled as failures.

## Validation

GitHub Actions must compile the package and run `test_self_improvement.py`.
Device validation on POCO F6 remains required after merge and is not represented
by GitHub CI.
