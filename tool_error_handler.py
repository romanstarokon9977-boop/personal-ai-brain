"""Conservative tool-error classification and recovery guidance."""
from __future__ import annotations

from typing import Any

# Recovery is advisory. Only a small explicit set of read-only tools can retry.
_SAFE_READ_ONLY_TOOLS = frozenset({
    "read_file", "directory_list", "file_search", "read_pdf", "read_docx",
    "directory_tree", "get_file_info", "read_multiple_files",
    "list_allowed_directories", "read_text_file", "list_directory", "search_files",
    "directory_tree", "get_file_info", "read_multiple_files",
})

_RULES = (
    ("RATE_LIMIT", ("429", "RATE_LIMIT", "TOO MANY REQUESTS"), "WAIT_THEN_RETRY_READ_ONLY"),
    ("TIMEOUT", ("TIMEOUT", "TIMED OUT"), "RETRY_READ_ONLY_ONCE"),
    ("NETWORK", ("CONNECTIONERROR", "CONNECTION_ERROR", "CONNECTION REFUSED", "CONNECTION RESET", "NETWORK IS UNREACHABLE"), "CHECK_CONNECTIVITY"),
    ("AUTHORIZATION", ("PERMISSION DENIED", "UNAUTHORIZED", "FORBIDDEN", "NOT ALLOWED"), "STOP_AND_REVIEW_PERMISSIONS"),
    ("NOT_FOUND", ("NOT FOUND", "ENOENT", "404"), "VERIFY_RESOURCE_IDENTIFIER"),
    ("INVALID_ARGUMENT", ("INVALID_TOOL_ARGUMENTS", "INVALID ARGUMENT", "VALIDATION ERROR"), "CORRECT_ARGUMENTS"),
    ("MCP_PROTOCOL", ("JSON-RPC", "MCP_PROTOCOL", "PROTOCOL ERROR", "MCP SERVER NOT RUNNING"), "STOP_AND_REINITIALIZE_AFTER_REVIEW"),
    ("API_SERVER", ("HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504", "INTERNAL SERVER ERROR"), "RETRY_READ_ONLY_ONCE"),
)


def classify_tool_error(error: Any, tool_name: str = "", side_effecting: bool = False) -> dict:
    message = str(error or "").strip()
    upper = message.upper()
    category, recovery = "UNKNOWN", "STOP_AND_REPORT"
    for candidate, markers, action in _RULES:
        if any(marker in upper for marker in markers):
            category, recovery = candidate, action
            break
    retryable = (
        not side_effecting
        and tool_name in _SAFE_READ_ONLY_TOOLS
        and category in {"RATE_LIMIT", "TIMEOUT", "API_SERVER"}
    )
    if not retryable and recovery.startswith("RETRY_"):
        recovery = "STOP_AND_REPORT"
    if category in {"AUTHORIZATION", "INVALID_ARGUMENT", "MCP_PROTOCOL"}:
        retryable = False
    return {
        "category": category,
        "recovery": recovery,
        "retryable": retryable,
        "requires_user_attention": not retryable,
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "ReportedError",
    }
