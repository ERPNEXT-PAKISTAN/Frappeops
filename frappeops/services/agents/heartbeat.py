# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Heartbeat + scoped agent command handling."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_dict, redact_text
from frappeops.services.agents.collector import collect_host_facts
from frappeops.services.agents.enrollment import get_agent_by_api_key
from frappeops.services.agents.protocol import (
	HEARTBEAT_OFFLINE_MINUTES,
	SCOPED_COMMANDS,
	has_scope,
	parse_scopes,
)


def record_heartbeat(api_key: str, facts: dict | None = None) -> dict[str, Any]:
	agent = get_agent_by_api_key(api_key)
	if not agent:
		frappe.throw(_("Invalid agent credentials"), frappe.AuthenticationError)

	facts = facts or collect_host_facts()
	agent.status = "Online"
	agent.last_heartbeat = now_datetime()
	agent.agent_version = facts.get("agent_version") or agent.agent_version
	agent.save(ignore_permissions=True)

	server = frappe.get_doc("Server", agent.server)
	server.agent_status = "Online"
	server.agent_version = agent.agent_version
	server.last_heartbeat = agent.last_heartbeat
	if facts.get("disk_used_percent") is not None:
		server.disk_used_percent = facts.get("disk_used_percent")
	if facts.get("disk_total_gb") is not None:
		server.disk_gb = facts.get("disk_total_gb")
	if facts.get("hostname"):
		server.hostname = facts.get("hostname")
	if facts.get("os") and hasattr(server, "operating_system"):
		server.operating_system = str(facts.get("os"))[:140]
	if facts.get("architecture") and hasattr(server, "architecture"):
		server.architecture = str(facts.get("architecture"))[:64]
	if facts.get("cpu_cores") is not None and hasattr(server, "cpu_cores"):
		server.cpu_cores = int(facts.get("cpu_cores") or 0)
	if facts.get("ram_gb") is not None and hasattr(server, "ram_gb"):
		server.ram_gb = float(facts.get("ram_gb") or 0)
	if facts.get("public_ip") and not server.ip_address:
		server.ip_address = facts.get("public_ip")
	server.status = "Online"
	server.save(ignore_permissions=True)

	# Lightweight Server Health row from agent facts
	status = "Healthy"
	disk_p = float(facts.get("disk_used_percent") or 0)
	ram_p = float(facts.get("ram_percent") or 0)
	cpu_p = float(facts.get("cpu_percent") or 0)
	if disk_p >= 90 or ram_p >= 95:
		status = "Critical"
	elif disk_p >= 80 or ram_p >= 85:
		status = "Warning"

	health = frappe.get_doc(
		{
			"doctype": "Server Health",
			"server": server.name,
			"status": status,
			"checked_at": now_datetime(),
			"cpu_percent": cpu_p,
			"ram_percent": ram_p,
			"disk_percent": disk_p,
			"load_average": ",".join(str(x) for x in (facts.get("load_average") or [])),
			"details_json": json.dumps(redact_dict(facts), indent=2, default=str),
		}
	)
	health.insert(ignore_permissions=True)
	server.last_health_check = now_datetime()
	server.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Heartbeat accepted"),
		"agent": agent.name,
		"server": server.name,
		"health": health.name,
		"status": status,
	}


def execute_scoped(api_key: str, command: str, params: dict | None = None) -> dict[str, Any]:
	"""Allowlisted agent commands only — never arbitrary shell."""
	agent = get_agent_by_api_key(api_key)
	if not agent:
		frappe.throw(_("Invalid agent credentials"), frappe.AuthenticationError)

	meta = SCOPED_COMMANDS.get(command)
	if not meta:
		return {"ok": False, "message": _("Unknown or disallowed command: {0}").format(command)}

	scopes = parse_scopes(agent.permission_scope)
	if not has_scope(scopes, meta["scope"]):
		return {"ok": False, "message": _("Scope denied: {0}").format(meta["scope"])}

	params = params or {}
	if command == "heartbeat":
		return record_heartbeat(api_key, params.get("facts"))
	if command == "discover":
		return _cmd_discover(agent, params)
	if command == "health":
		return record_heartbeat(api_key, params.get("facts") or collect_host_facts())
	if command == "list_sites":
		facts = collect_host_facts()
		return {"ok": True, "sites": facts.get("sites") or [], "bench_path": facts.get("bench_path")}
	if command == "backup_site":
		return _cmd_backup(agent, params)

	return {"ok": False, "message": _("Not implemented")}


def mark_stale_agents_offline() -> dict[str, Any]:
	"""Scheduler: agents without recent heartbeat → Offline."""
	cutoff = add_to_date(now_datetime(), minutes=-HEARTBEAT_OFFLINE_MINUTES)
	updated = []
	for row in frappe.get_all(
		"Server Agent",
		filters={"status": "Online", "revoked": 0},
		fields=["name", "server", "last_heartbeat"],
	):
		if not row.last_heartbeat or row.last_heartbeat < cutoff:
			frappe.db.set_value("Server Agent", row.name, "status", "Offline")
			frappe.db.set_value("Server", row.server, "agent_status", "Offline")
			updated.append(row.name)
	return {"ok": True, "marked_offline": updated}


def _cmd_discover(agent, params: dict) -> dict[str, Any]:
	facts = params.get("facts") or collect_host_facts()
	# Reuse local import when agent is on this control-plane host
	server = frappe.get_doc("Server", agent.server)
	imported = None
	if server.is_local:
		from frappeops.services.discovery.local import import_local_server

		imported = import_local_server()
	write_audit(
		"agent.discover",
		resource_type="server",
		resource_name=agent.server,
		status="Success",
		message=_("Agent discovery"),
		parameters={"agent": agent.name},
		after=redact_dict({"site_count": facts.get("site_count"), "app_count": facts.get("app_count")}),
	)
	return {
		"ok": True,
		"message": _("Discovery complete"),
		"facts": redact_dict(facts),
		"imported": imported,
	}


def _cmd_backup(agent, params: dict) -> dict[str, Any]:
	site_name = (params.get("site_name") or "").strip()
	if not site_name:
		return {"ok": False, "message": _("site_name required")}

	# Only backup sites that belong to this server inventory
	site = frappe.db.get_value(
		"Site",
		{"site_name": site_name, "server": agent.server},
		["name", "is_protected"],
		as_dict=True,
	)
	if not site:
		return {"ok": False, "message": _("Site not found on this server inventory")}

	# Backup allowed on protected (safe); other mutating ops blocked elsewhere
	from frappeops.services.operations.runner import _site_backup

	return _site_backup(site.name)
