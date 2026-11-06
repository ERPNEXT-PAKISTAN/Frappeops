"""Secret redaction utilities for logs, audits, and API output."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY_PARTS = (
	"password",
	"passwd",
	"secret",
	"token",
	"api_key",
	"apikey",
	"private_key",
	"authorization",
	"access_key",
	"encryption_key",
	"db_password",
	"mysql_root",
	"ssh_key",
)

_PATTERNS = [
	re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
	re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

REDACTED = "***REDACTED***"


def is_sensitive_key(key: str) -> bool:
	k = (key or "").lower()
	return any(part in k for part in _SENSITIVE_KEY_PARTS)


def redact_text(text: str | None) -> str:
	if not text:
		return ""
	out = text
	for pattern in _PATTERNS:
		out = pattern.sub(REDACTED, out)
	return out


def redact_value(key: str, value: Any) -> Any:
	if is_sensitive_key(key):
		return REDACTED
	if isinstance(value, str):
		return redact_text(value)
	if isinstance(value, dict):
		return redact_dict(value)
	if isinstance(value, list):
		return [redact_value(key, v) for v in value]
	return value


def redact_dict(data: dict | None) -> dict:
	if not data:
		return {}
	return {k: redact_value(str(k), v) for k, v in data.items()}
