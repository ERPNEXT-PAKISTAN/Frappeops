# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Agent security helpers: hashing, scopes, offline threshold."""

from __future__ import annotations

import hashlib
import secrets

# Default scopes for a newly enrolled agent (no arbitrary shell).
DEFAULT_SCOPES = [
	"discover",
	"health",
	"list_sites",
	"backup_site",
	"heartbeat",
]

# Commands the agent API may execute (allowlist only).
SCOPED_COMMANDS = {
	"discover": {"scope": "discover", "risk": "Low"},
	"health": {"scope": "health", "risk": "Low"},
	"list_sites": {"scope": "list_sites", "risk": "Low"},
	"backup_site": {"scope": "backup_site", "risk": "Medium"},
	"heartbeat": {"scope": "heartbeat", "risk": "Low"},
}

AGENT_VERSION = "0.2.0"
HEARTBEAT_OFFLINE_MINUTES = 10
ENROLLMENT_TTL_MINUTES = 60


def hash_secret(value: str) -> str:
	return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def new_token(nbytes: int = 24) -> str:
	return secrets.token_urlsafe(nbytes)


def parse_scopes(raw) -> list[str]:
	if not raw:
		return list(DEFAULT_SCOPES)
	if isinstance(raw, list):
		return [str(x).strip() for x in raw if str(x).strip()]
	parts = []
	for chunk in str(raw).replace("\n", ",").split(","):
		chunk = chunk.strip()
		if chunk:
			parts.append(chunk)
	return parts or list(DEFAULT_SCOPES)


def scopes_to_text(scopes: list[str]) -> str:
	return ", ".join(scopes)


def has_scope(agent_scopes: list[str], required: str) -> bool:
	return required in agent_scopes or "*" in agent_scopes
