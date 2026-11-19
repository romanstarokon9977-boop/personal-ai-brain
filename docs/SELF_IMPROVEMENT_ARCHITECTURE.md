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

The initial audit found no dedicated solution library; Section 6.4 introduced `SolutionLibrary` and its confirmation-gated native tool.

## New package

- `self_improvement.core.collect_diagnostics`: composes existing read-only diagnostics, Golden-reference integrity, Git worktree counts and module-manager health. Golden drift is WARNING, corrupted reference data is ERROR, and missing evidence is UNKNOWN rather than a failure.
- `analyze_quality_events`: groups quality events and distinguishes failures, uncertainty, passes and user preferences. It does not infer root cause.
- `record_answer_feedback`: explicit feedback tool; records only category, outcome and optional evidence code. The native tool is MEDIUM-risk and requires user confirmation.
- `build_quality_report`: summarizes explicitly recorded feedback events; no conversation transcript is retained.
- `module_improvement`: confirmation-gated persistent lifecycle for architecture/module proposals: create, list, approve, reject. IDs use `M-001` format. Review never applies code or enables a module.
- `build_improvement_proposal`: creates an inert technical proposal with evidence, affected modules, tests, risk and approval flags.
- `ImprovementEventStore`: persists bounded metadata in the directory containing the Brain memory file, using private atomic writes.
- `ImprovementProposalStore`: stores inert module proposals and a separate review status; approval is not implementation authorization.
- `SolutionLibrary`: exposed through the confirmation-gated `solution_library` tool. It stores reusable algorithm descriptions, problem statements, conditions, limitations, compatibility metadata and test references—not executable code or permissions. Candidate creation, verification and status changes use a private-home inter-process lock and verify persisted writes by reading them back. Under P6.6, caller-supplied `passed` and `test_run` values are no longer accepted as proof. A candidate must be bound at creation to a 40-character source commit SHA and a declared test reference in `test_module.py::test_name` form. The verifier independently queries GitHub Actions and validates immutable repository identity, workflow ID/path, equality of the workflow definition at the tested commit and trusted `main`, exact commit SHA, push event and allowed branch, completed successful run, required Python 3.11 job, successful compile and isolated-unittest steps, module inclusion in the trusted CI loop, and presence of the declared test function at that commit. `VERIFIED` is persisted only after all checks pass. `INCONCLUSIVE` and `REJECTED` leave the candidate unchanged. Legacy candidates without a source SHA remain readable but cannot be externally verified. The evidence snapshot stores API-derived metadata, not secrets. GitHub Actions metadata is provenance evidence, not a cryptographic attestation that every test instruction executed; local JSON is not tamper-proof. Activation remains a separate authorization. Existing version-1 records remain readable. Legacy candidates without declared test references remain readable. The confirmation-gated `add_test_reference` operation can append a bounded, unique reference to a CANDIDATE; the candidate can then be verified against that exact reference.

## Safety and authorization model

- The controls listed here describe the current scope of this subsystem; they are not a claim that every future action must remain permanently disabled.
- A specific action may be authorized by Roman through the applicable explicit confirmation and permission workflow. Authorization must identify the action and its scope; it does not silently grant broader or continuing permissions.
- A confirmation does not bypass technical safeguards, platform restrictions or applicable law.
- P6.5 itself does not add self-modifying code, generated-code execution, automatic deployment, permission changes, or autonomous activation.
- No permissions are granted by diagnostics, proposals or library records.
- No automatic conversation capture. Callers must explicitly submit sanitized event metadata.
- Stores are bounded, atomically replaced and created with mode 0600.
- Parent directories are never created implicitly.
- A proposal remains inert; approval and implementation are separate decisions.
- A solution record is knowledge, not executable code. Compatibility and test references do not trigger environment checks, test execution, network access or activation.

## Integration status and next steps

The read-only diagnostic report is exposed as the native `self_improvement_report`
tool under the exact LOW-risk read-only authorization allowlist. It does not invoke
MCP, write state, or collect conversation history.

Quality feedback is recorded only when the user explicitly asks Brain to save it and
confirms the MEDIUM-risk tool call. P6.5 solution verification requires an exact declared
test reference, a passing run identifier and the upstream MEDIUM-risk confirmation gate.
The stored confirmation marker is an audit trace, not independent CI verification.
Runtime verification outcomes remain separate from subjective answer feedback so
uncertainty and user preference are not mislabeled as failures. Approved module proposals
remain inert until a separately reviewed implementation task is created and explicitly authorized.

## Validation

GitHub Actions must compile the package and run `test_self_improvement.py`.
Device validation on POCO F6 remains required after merge and is not represented
by GitHub CI.
