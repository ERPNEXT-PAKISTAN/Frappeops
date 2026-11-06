# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Public agent API (token/API-key auth) + operator helpers."""

from __future__ import annotations

import json

import frappe
from frappe import _

from frappeops.services.agents.enrollment import (
	create_enrollment_token,
	enroll_with_token,
	revoke_agent,
)
from frappeops.services.agents.heartbeat import execute_scoped, record_heartbeat
from frappeops.services.agents.local_adapter import install_local_agent, local_discover, local_heartbeat
from frappeops.services.security.rate_limit import check_rate_limit


def _parse(value):
	if value is None or value == "":
		return None
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str):
		try:
			return json.loads(value)
		except Exception:
			return value
	return value


@frappe.whitelist(allow_guest=True)
def enroll(token: str | None = None, hostname: str | None = None, agent_version: str | None = None, facts=None):
	"""One-time enrollment. Guest-allowed; auth is the enrollment token."""
	check_rate_limit(f"enroll:{frappe.local.request_ip or 'local'}", limit=20, window_seconds=60)
	return enroll_with_token(
		token or frappe.form_dict.get("token"),
		hostname=hostname,
		agent_version=agent_version,
		facts=_parse(facts),
	)


@frappe.whitelist(allow_guest=True)
def heartbeat(api_key: str | None = None, facts=None):
	check_rate_limit(f"hb:{frappe.local.request_ip or 'local'}", limit=120, window_seconds=60)
	api_key = api_key or frappe.form_dict.get("api_key") or _bearer()
	return record_heartbeat(api_key, _parse(facts))


@frappe.whitelist(allow_guest=True)
def execute(api_key: str | None = None, command: str | None = None, params=None):
	check_rate_limit(f"exec:{frappe.local.request_ip or 'local'}", limit=60, window_seconds=60)
	api_key = api_key or frappe.form_dict.get("api_key") or _bearer()
	command = command or frappe.form_dict.get("command")
	return execute_scoped(api_key, command, _parse(params) or {})


@frappe.whitelist()
def create_token(server: str, scopes: str | None = None):
	scope_list = None
	if scopes:
		scope_list = [s.strip() for s in scopes.replace("\n", ",").split(",") if s.strip()]
	return create_enrollment_token(server, scopes=scope_list)


@frappe.whitelist()
def revoke(agent: str):
	return revoke_agent(agent)


@frappe.whitelist()
def install_local(server: str | None = None):
	return install_local_agent(server)


@frappe.whitelist()
def run_local_heartbeat(server: str | None = None):
	return local_heartbeat(server)


@frappe.whitelist()
def run_local_discover(server: str | None = None):
	return local_discover(server)


def _bearer() -> str | None:
	auth = frappe.get_request_header("Authorization") or ""
	if auth.lower().startswith("bearer "):
		return auth.split(" ", 1)[1].strip()
	return None
