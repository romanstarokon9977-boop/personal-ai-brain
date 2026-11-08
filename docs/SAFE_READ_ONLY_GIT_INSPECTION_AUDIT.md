# Shell authorization audit and bounded Git inspection

## Audited baseline

The audit was performed against the repository snapshot at commit
`d2c387a7832289218b53649706b8c753f0be1a62`.

### Confirmed authorization path

- `tool_registry.py` registers `shell` as a native tool with
  `RiskLevel.CRITICAL`.
- `autonomy_controller.py` only auto-approves explicitly named read-only
  tools and the fixed `run_tests` runner. All other registered tools,
  including `shell`, return `CONFIRM`.
- `brain.py` has a second shell gate. `_classify_shell_call()` rejects
  shell operators and only auto-approves a narrow command list or selected
  file reads.
- `tool_shell()` has a separate first-token allowlist:
  `ls`, `pwd`, `echo`, `df`, `free`, `ps`, and `wc`.
  It does not include Git. Therefore, even if the autonomy gate were bypassed,
  `git status` would be rejected as `COMMAND_NOT_ALLOWED`.
- `tool_run_tests()` already uses a fixed filename whitelist, targeted/full
  scope validation, argument-vector execution, and a 180-second timeout.
  `autonomy_controller.py` already auto-approves this registered native
  tool as `LOW_RISK_BOUNDED_TEST_RUN`. The whitelist is bounded, but each
  test's side effects still depend on that test's implementation; this audit
  does not claim every listed test is side-effect-free.

### Goal verification finding

`goal_verifier.verify_goal_result()` returns `FAIL` when the tool result
is not successful (`ok is not True`). For successful tools without a
specific deterministic postcondition, it returns `UNCERTAIN`, not `FAIL`.
The `GOAL_VERIFICATION_FAILED` wrapper is added by `brain.py` only when
the verifier status is `FAIL`. Therefore, an approval interruption alone
does not establish the cause of that status; the actual tool result and
verifier reasons must be inspected. A shell rejection such as
`COMMAND_NOT_ALLOWED` can produce a failed tool result and then a verifier
failure.

## Implemented boundary

This PR adds `git_inspect`, a dedicated native tool. It does not lower the
risk of `shell` and does not add `git` to the shell command allowlist.

The new tool accepts exactly one parameter, `operation`, with four values:

- `status`
- `diff`
- `log`
- `show`

It uses fixed argument vectors, `shell=False`, a fixed repository root,
10-second timeout, bounded output, disabled Git optional locks, no pager,
no external diff, and no textconv. Caller-supplied revisions, paths, flags,
and extra parameters are rejected. The tool is registered as LOW risk and
included in the explicit read-only autonomy allowlist.

## Explicitly out of scope

- Arbitrary shell execution and shell command parsing.
- Git write operations (add, commit, checkout, reset, clean, push, pull, fetch).
- Caller-supplied Git paths, revisions, config, or flags.
- Changes to the existing test-runner whitelist or its authorization policy.
- Any runtime test against the user's live repository or device state.

## Validation

The new unit tests mock subprocess execution and use temporary directories.
They do not invoke Git, touch the live repository, or modify user data.
