"""Deterministic goal/postcondition verification for Tool Bridge.

Only verifiable file-write operations can currently return PASS. Operations
without an explicit deterministic postcondition return UNCERTAIN rather than
being treated as successful merely because the tool envelope says ok=True.
"""
import os
from typing import Any, Dict


def _result(status: str, tool_name: str, reasons: list[str]) -> Dict[str, Any]:
    return {
        "status": status,
        "verified": status == "PASS",
        "tool": tool_name if isinstance(tool_name, str) else "",
        "reasons": reasons,
    }


def extract_error_code(error: Any) -> Any:
    """Extract a stable uppercase machine code from a wrapped tool error."""
    if not isinstance(error, str):
        return None
    candidate = error.strip().rsplit(": ", 1)[-1].strip()
    if (
        candidate
        and candidate.replace("_", "").isalnum()
        and candidate.upper() == candidate
    ):
        return candidate
    return None


def _read_persisted(path: str) -> str:
    real_path = os.path.realpath(os.path.expanduser(path))
    with open(real_path, "r", encoding="utf-8") as stream:
        return stream.read()


def verify_goal_result(
    goal: str,
    tool_name: str,
    params: Dict[str, Any],
    tool_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Verify whether a successful tool call demonstrably achieved its goal.

    PASS is intentionally limited to deterministic file postconditions:
    write_file must persist the exact requested content; file_edit must have
    passed its own postcondition and the requested replacement must be present.
    Other tools return UNCERTAIN until they expose explicit verifiable
    postconditions. No language-model self-approval is treated as evidence.
    """
    if not isinstance(tool_result, dict) or tool_result.get("ok") is not True:
        reasons = ["TOOL_EXECUTION_NOT_SUCCESSFUL"]
        error_code = tool_result.get("error_code") if isinstance(tool_result, dict) else None
        if (
            isinstance(error_code, str)
            and error_code
            and error_code.replace("_", "").isalnum()
            and error_code.upper() == error_code
        ):
            reasons.append("TOOL_ERROR_CODE:" + error_code)
        return _result("FAIL", tool_name, reasons)

    if not isinstance(goal, str) or not goal.strip():
        return _result("UNCERTAIN", tool_name, ["USER_GOAL_UNAVAILABLE"])

    if not isinstance(params, dict):
        return _result("UNCERTAIN", tool_name, ["TOOL_PARAMETERS_UNAVAILABLE"])

    if tool_name == "write_file":
        path = params.get("path")
        expected = params.get("content")
        if not isinstance(path, str) or not path.strip() or not isinstance(expected, str):
            return _result("UNCERTAIN", tool_name, ["WRITE_POSTCONDITION_INPUT_MISSING"])
        try:
            actual = _read_persisted(path)
        except (OSError, UnicodeError, ValueError) as error:
            return _result("FAIL", tool_name, [f"WRITE_READBACK_FAILED:{type(error).__name__}"])
        if actual != expected:
            return _result("FAIL", tool_name, ["WRITE_CONTENT_MISMATCH"])
        return _result("PASS", tool_name, ["PERSISTED_CONTENT_EXACT_MATCH"])

    if tool_name == "file_edit":
        path = params.get("path")
        replacement = params.get("new_text")
        verifier_report = tool_result.get("verifier")
        if not isinstance(path, str) or not path.strip() or not isinstance(replacement, str):
            return _result("UNCERTAIN", tool_name, ["EDIT_POSTCONDITION_INPUT_MISSING"])
        if not isinstance(verifier_report, dict) or verifier_report.get("postcondition") != "PASS":
            return _result("FAIL", tool_name, ["FILE_EDIT_POSTCONDITION_NOT_CONFIRMED"])
        try:
            _read_persisted(path)
        except (OSError, UnicodeError, ValueError) as error:
            return _result("FAIL", tool_name, [f"EDIT_READBACK_FAILED:{type(error).__name__}"])
        # verify_file_edit already compares the complete persisted file with
        # the exact expected new_content; do not replace that proof with a
        # substring heuristic that can produce false positives.
        return _result("PASS", tool_name, ["EXACT_FILE_EDIT_POSTCONDITION_CONFIRMED"])

    if tool_name == "git_inspect":
        requested_operation = params.get("operation")
        if requested_operation != "status":
            return _result("UNCERTAIN", tool_name, ["GIT_OPERATION_POSTCONDITION_UNSUPPORTED"])

        reported_operation = tool_result.get("operation")
        if not isinstance(reported_operation, str):
            return _result("UNCERTAIN", tool_name, ["GIT_STATUS_OPERATION_UNCONFIRMED"])
        if reported_operation != requested_operation:
            return _result("FAIL", tool_name, ["GIT_OPERATION_MISMATCH"])

        output = tool_result.get("result")
        if not isinstance(output, str) or not output.strip():
            return _result("FAIL", tool_name, ["GIT_STATUS_OUTPUT_MISSING"])
        if "[OUTPUT_TRUNCATED]" in output:
            return _result("FAIL", tool_name, ["GIT_STATUS_OUTPUT_TRUNCATED"])
        first_line = output.strip().splitlines()[0]
        if not first_line.startswith("## "):
            return _result("FAIL", tool_name, ["GIT_STATUS_OUTPUT_NOT_CONFIRMED"])

        return _result("PASS", tool_name, ["GIT_STATUS_OPERATION_AND_OUTPUT_CONFIRMED"])

    return _result("UNCERTAIN", tool_name, ["NO_DETERMINISTIC_GOAL_POSTCONDITION"])
