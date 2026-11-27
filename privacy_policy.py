"""Data classification and fail-closed secret-transfer guardrails.

Classification is metadata-only. This module never reads configuration files,
environment variables, persisted memory, or credentials.
"""
from __future__ import annotations

import re
from typing import Iterator

PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
PERSONAL = "PERSONAL"
SECRET = "SECRET"
USER_INPUT = "USER_INPUT"

_PRIVATE_NAMES = {
    "memory",
    "chat_recall",
    "skill_guidance",
    "user_profile",
    "personal_memory",
    "private_context",
}
_SECRET_NAMES = {"secret", "secrets", "credentials", "api_credentials"}

_PRIVATE_MARKERS = (
    "Контекст профиля и среды",
    "Воспоминания из прошлых обсуждений:",
    "Ниже приведены справочные материалы выбранных навыков",
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b(?:OPENROUTER_API_KEY|GEMINI_API_KEY|TELEGRAM_BOT_TOKEN|"
        r"API_KEY|ACCESS_TOKEN|CLIENT_SECRET|PASSWORD)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9._~+/=-]{16,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}", re.IGNORECASE),
)
_MAX_SCAN_CHARS = 256_000
_MAX_SCAN_DEPTH = 8


def private_context_allowed(layer: str) -> bool:
    """Only an explicitly named LOCAL route may receive private context."""
    return isinstance(layer, str) and layer == "LOCAL"


def _strings(value, depth: int = 0) -> Iterator[str]:
    if depth > _MAX_SCAN_DEPTH:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child, depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child, depth + 1)


def contains_secret_data(value) -> bool:
    """Detect common credential formats in bounded text/message structures."""
    scanned = 0
    for text in _strings(value):
        remaining = _MAX_SCAN_CHARS - scanned
        if remaining <= 0:
            # Fail closed when the scan budget is exceeded.
            return True
        chunk = text[:remaining]
        scanned += len(chunk)
        if any(pattern.search(chunk) for pattern in _SECRET_PATTERNS):
            return True
    return False


def redact_secrets(value: str) -> str:
    """Redact recognized credential patterns before diagnostics or logs."""
    if not isinstance(value, str):
        return ""
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result[:_MAX_SCAN_CHARS]


def classify_message(message: dict) -> str:
    """Classify a message by trusted structural metadata and known markers."""
    if not isinstance(message, dict):
        return INTERNAL
    if contains_secret_data(message):
        return SECRET
    role = message.get("role")
    name = message.get("name")
    if isinstance(name, str) and name in _SECRET_NAMES:
        return SECRET
    if isinstance(name, str) and name in _PRIVATE_NAMES:
        return PERSONAL
    content = message.get("content", "")
    if role == "system" and isinstance(content, str) and any(
        marker in content for marker in _PRIVATE_MARKERS
    ):
        return PERSONAL
    if role == "user":
        return USER_INPUT
    return INTERNAL


def filter_external_messages(messages: list[dict]) -> list[dict]:
    """Remove personal/secret messages and add a non-sensitive boundary notice."""
    source = list(messages) if isinstance(messages, list) else []
    filtered = [
        message for message in source
        if classify_message(message) not in {PERSONAL, SECRET}
    ]
    removed = len(filtered) != len(source)
    if removed and not any(
        isinstance(message, dict)
        and message.get("role") == "system"
        and message.get("name") == "privacy_boundary"
        for message in filtered
    ):
        filtered.append({
            "role": "system",
            "name": "privacy_boundary",
            "content": (
                "Private memory, prior chat history, user-authored skills or "
                "credential-bearing content were withheld from this external route."
            ),
        })
    return filtered
