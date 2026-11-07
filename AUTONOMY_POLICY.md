# Personal AI Brain — Autonomy Policy 1.5

## Decision classes

| Decision | Runtime behavior |
|---|---|
| `AUTO` | Execute without an interactive prompt, but only for an exact allowlisted read-only tool whose registry risk is `LOW` and whose capability is explicitly read-only. |
| `CONFIRM` | Show the tool name, risk, and sanitized argument preview. Execute only after an affirmative user response. A refusal or unavailable input denies the call. |
| `BLOCK` | Do not execute. Unknown tools, malformed requests or metadata, and forbidden capabilities fail closed. |

## Automatic execution

The exact read-only allowlist is maintained in `autonomy_controller.py`. It includes file reads, listing/search/metadata operations, and read-only self-inspection. Membership alone is insufficient: the registry risk must also be `LOW` and the capability must be in the read-only capability allowlist.

## Confirmation required

Every registered tool not proven read-only requires confirmation, including:
- filesystem writes, edits, directory creation, moves;
- network access;
- shell commands (which remain subject to the existing shell command classifier and secret-file denylist);
- device notifications, speech, briefing configuration, and test execution;
- dry-run CPA preview generation.

A `LOW` risk label does not bypass confirmation for stateful or side-effecting tools.

## Blocked

Unknown tools, invalid requests, invalid risk metadata, and explicitly forbidden capabilities are blocked. The registry's existing path security checks, module-disable checks, shell restrictions, and tool-result verification remain additional independent controls.

## Scope

The policy applies to model-requested tool calls in the active API Tool Bridge path, including parsed XML fallback calls. The current LOCAL model route disables tools before execution and therefore cannot invoke tools; any future activation of LOCAL tool calling must use this same gate. Explicit user-issued Brain commands remain explicit user actions and retain their existing command-specific validation. Multi-step execution uses the same decision function; it does not define a separate risk policy.

## Safety invariants

1. Missing registry metadata never grants permission.
2. No tool is automatically approved solely because its risk label is `LOW`.
3. User denial is remembered for the remainder of the current Tool Bridge request.
4. The policy classifies authorization; it does not replace path validation, shell validation, module state, or post-execution verification.
