from __future__ import annotations

import re


REDACTED = "***REDACTED***"
SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*)"
        r"([^\s]+)"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]


def redact_secrets(text: str | None) -> str | None:
    if text is None:
        return None
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redacted_assignment, redacted)
    return redacted


def _redacted_assignment(match: re.Match[str]) -> str:
    if match.lastindex == 2:
        return f"{match.group(1)}{REDACTED}"
    return REDACTED
