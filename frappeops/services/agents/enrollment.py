# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Enrollment, revoke, and credential lifecycle for Server Agents."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text
from frappeops.services.agents.protocol import (
	DEFAULT_SCOPES,
	ENROLLMENT_TTL_MINUTES,
	hash_secret,
	new_token,
	parse_scopes,
	scopes_to_text,
)


def create_enrollment_token(
	server: str,
	*,
	scopes: list[str] | None = None,
	agent_name: str | None = None,
) -> dict[str, Any]:
	"""Operator action: create Pending Server Agent + one-time enrollment token (shown once)."""
	_require_admin()
	server_doc = frappe.get_doc("Server", server)
	if not server_doc.is_local:
		settings = frappe.get_single("FrappeOps Settings")
		if not getattr(settings, "enable_remote_agents", 0):
			frappe.throw(_("Enable Remote Agents in FrappeOps Settings before enrolling a remote VPS."))
	scopes = parse_scopes(scopes or DEFAULT_SCOPES)
	token = new_token(24)
	token_hash = hash_secret(token)
	expires = add_to_date(now_datetime(), minutes=ENROLLMENT_TTL_MINUTES)

	name = agent_name or f"{server_doc.server_name or server_doc.name}-agent"
	# Revoke prior pending tokens for this server
	for row in frappe.get_all(
		"Server Agent",
		filters={"server": server_doc.name, "status": "Pending"},
		pluck="name",
	):
		frappe.db.set_value(
			"Server Agent",
			row,
			{"status": "Revoked", "revoked": 1, "enrollment_token_hash": ""},
		)

	agent = frappe.get_doc(
		{
			"doctype": "Server Agent",
			"agent_name": name,
			"server": server_doc.name,
			"status": "Pending",
			"enrollment_token_hint": token[:4] + "…" + token[-4:],
			"enrollment_token_hash": token_hash,
			"enrollment_expires_at": expires,
			"permission_scope": scopes_to_text(scopes),
			"revoked": 0,
		}
	)
	agent.insert(ignore_permissions=True)

	server_doc.agent_status = "Not Installed"
	server_doc.save(ignore_permissions=True)

	write_audit(
		"agent.create_token",
		resource_type="server",
		resource_name=server_doc.name,
		status="Success",
		message=_("Enrollment token created for {0}").format(server_doc.name),
		parameters={"agent": agent.name, "hint": agent.enrollment_token_hint},
	)

	return {
		"ok": True,
		"message": _("Enrollment token created (copy now — shown once)"),
		"agent": agent.name,
		"server": server_doc.name,
		"enrollment_token": token,
		"expires_at": str(expires),
		"scopes": scopes,
		"enroll_endpoint": "/api/method/frappeops.api.agent.enroll",
	}


def enroll_with_token(
	token: str,
	*,
	hostname: str | None = None,
	agent_version: str | None = None,
	facts: dict | None = None,
) -> dict[str, Any]:
	"""Agent → control plane: exchange one-time token for API key."""
	if not token:
		frappe.throw(_("Enrollment token required"), frappe.AuthenticationError)

	token_hash = hash_secret(token)
	agent_name = frappe.db.get_value(
		"Server Agent",
		{"enrollment_token_hash": token_hash, "status": "Pending", "revoked": 0},
		"name",
	)
	if not agent_name:
		frappe.throw(_("Invalid or used enrollment token"), frappe.AuthenticationError)

	agent = frappe.get_doc("Server Agent", agent_name)
	if agent.enrollment_expires_at and agent.enrollment_expires_at < now_datetime():
		agent.status = "Revoked"
		agent.revoked = 1
		agent.enrollment_token_hash = ""
		agent.save(ignore_permissions=True)
		frappe.throw(_("Enrollment token expired"), frappe.AuthenticationError)

	api_key = new_token(32)
	agent.api_key_hash = hash_secret(api_key)
	agent.api_key_secret = api_key  # encrypted Password for outbound poll
	agent.enrollment_token_hash = ""
	agent.status = "Enrolled"
	agent.agent_version = agent_version or agent.agent_version
	agent.last_heartbeat = now_datetime()
	if hostname:
		agent.notes = redact_text(((agent.notes or "") + f"\nenrolled hostname={hostname}")[-500:])
	agent.save(ignore_permissions=True)

	server = frappe.get_doc("Server", agent.server)
	server.agent_status = "Online"
	server.agent_version = agent.agent_version
	server.last_heartbeat = agent.last_heartbeat
	if hostname and not server.hostname:
		server.hostname = hostname
	server.save(ignore_permissions=True)

	write_audit(
		"agent.enroll",
		resource_type="server",
		resource_name=server.name,
		status="Success",
		message=_("Agent enrolled"),
		parameters={"agent": agent.name, "hostname": hostname},
		after={"facts_keys": list((facts or {}).keys())},
	)

	return {
		"ok": True,
		"message": _("Enrolled"),
		"agent": agent.name,
		"server": server.name,
		"api_key": api_key,
		"scopes": parse_scopes(agent.permission_scope),
	}


def revoke_agent(agent: str) -> dict[str, Any]:
	_require_admin()
	doc = frappe.get_doc("Server Agent", agent)
	doc.status = "Revoked"
	doc.revoked = 1
	doc.api_key_hash = ""
	doc.api_key_secret = ""
	doc.enrollment_token_hash = ""
	doc.poll_enabled = 0
	doc.save(ignore_permissions=True)

	server = frappe.get_doc("Server", doc.server)
	# If no other online agents, mark server agent offline
	others = frappe.get_all(
		"Server Agent",
		filters={"server": server.name, "status": ["in", ["Online", "Enrolled"]], "name": ["!=", doc.name]},
		limit=1,
	)
	if not others:
		server.agent_status = "Offline"
		server.save(ignore_permissions=True)

	write_audit(
		"agent.revoke",
		resource_type="server",
		resource_name=server.name,
		status="Success",
		message=_("Agent revoked"),
		parameters={"agent": doc.name},
	)
	return {"ok": True, "message": _("Agent {0} revoked").format(doc.name), "agent": doc.name}


def get_agent_by_api_key(api_key: str):
	if not api_key:
		return None
	name = frappe.db.get_value(
		"Server Agent",
		{"api_key_hash": hash_secret(api_key), "revoked": 0},
		"name",
	)
	if not name:
		return None
	doc = frappe.get_doc("Server Agent", name)
	if doc.status == "Revoked":
		return None
	return doc


def _require_admin():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "FrappeOps Administrator", "FrappeOps Operator"}):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
