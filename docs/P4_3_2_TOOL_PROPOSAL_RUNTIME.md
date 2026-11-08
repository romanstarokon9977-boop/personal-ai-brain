# P4.3.2 — Runtime integration for persistent tool proposals

## Commands
- `предложения` — list saved proposal IDs, status, name, risk and purpose.
- `предложение <ID>` — inspect one proposal and its constraints/tests.
- `предложение одобрить <ID>` — approve metadata after exact confirmation `ОДОБРИТЬ <ID>`.
- `предложение отклонить <ID>` — reject metadata after exact confirmation `ОТКЛОНИТЬ <ID>`.

Full UUID hex IDs are required; prefix matching is not supported.

## Runtime and safety
- The manager uses `tool_proposals.json` beside the existing `MEMORY_FILE`.
- The manager does not create parent directories. If the store cannot be initialized or written, proposal creation fails closed.
- Model-requested `propose_tool` still passes the existing autonomy confirmation gate before persistence.
- Review commands are parsed only from direct terminal input and are not model-callable tools.
- Approval/rejection requires a second exact phrase containing the full ID. Incorrect or interrupted confirmation leaves the record unchanged.
- Review changes metadata only. `implementation_applied` and `activation_allowed` remain false.
- No source writes, imports, ToolRegistry mutation, module activation, or runtime dispatch are performed.

CI compiles touched modules and runs proposal command tests plus Phase 4 runtime integration tests. Local Termux verification remains a separate user-side step after merge/update.
