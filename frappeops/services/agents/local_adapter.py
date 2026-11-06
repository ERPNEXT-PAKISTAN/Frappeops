# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Local agent adapter — enroll + heartbeat on this host without a separate daemon."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from frappeops.services.agents.collector import collect_host_facts
from frappeops.services.agents.enrollment import create_enrollment_token, enroll_with_token
from frappeops.services.agents.heartbeat import execute_scoped, record_heartbeat
from frappeops.services.agents.protocol import AGENT_VERSION, DEFAULT_SCOPES


def install_local_agent(server: str | None = None) -> dict[str, Any]:
	"""Create token, enroll local adapter, send first heartbeat (control-plane host only)."""
	if not server:
		server = frappe.db.get_value("Server", {"is_local": 1}, "name")
	if not server:
		frappe.throw(_("No local server record. Run Scan / Discover first."))

	server_doc = frappe.get_doc("Server", server)
	if not server_doc.is_local:
		frappe.throw(_("install_local_agent only works for the local server. Use enrollment token for remotes."))

	token_result = create_enrollment_token(server, scopes=DEFAULT_SCOPES, agent_name=f"{server_doc.server_name}-local")
	token = token_result["enrollment_token"]
	facts = collect_host_facts(server_doc.bench_path if hasattr(server_doc, "bench_path") else None)

	enrolled = enroll_with_token(
		token,
		hostname=facts.get("hostname"),
		agent_version=AGENT_VERSION,
		facts=facts,
	)
	# Keep API key only in this response path for operator; also run heartbeat in-process
	api_key = enrolled["api_key"]
	hb = record_heartbeat(api_key, facts)

	# Store api key hash already done; optionally cache key in site cache for local runner (not DB)
	frappe.cache.set_value(
		f"frappeops:local_agent_key:{server}",
		api_key,
		expires_in_sec=60 * 60 * 24 * 30,
	)

	return {
		"ok": True,
		"message": _("Local agent enrolled and online"),
		"agent": enrolled["agent"],
		"server": server,
		"api_key": api_key,
		"heartbeat": hb,
		"scopes": enrolled.get("scopes"),
		"note": _("API key shown once. Local adapter also cached for control-plane heartbeat jobs."),
	}


def local_heartbeat(server: str | None = None) -> dict[str, Any]:
	if not server:
		server = frappe.db.get_value("Server", {"is_local": 1}, "name")
	api_key = frappe.cache.get_value(f"frappeops:local_agent_key:{server}")
	if not api_key:
		# Fall back: reinstall path message
		return {
			"ok": False,
			"message": _("No cached local agent key. Run Install Local Agent again."),
		}
	facts = collect_host_facts()
	return record_heartbeat(api_key, facts)


def local_discover(server: str | None = None) -> dict[str, Any]:
	if not server:
		server = frappe.db.get_value("Server", {"is_local": 1}, "name")
	api_key = frappe.cache.get_value(f"frappeops:local_agent_key:{server}")
	if not api_key:
		return {"ok": False, "message": _("No cached local agent key. Run Install Local Agent first.")}
	return execute_scoped(api_key, "discover", {"facts": collect_host_facts()})
