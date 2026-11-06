# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Easy control-page APIs (status + actions, not raw DocType dumps)."""

from __future__ import annotations

from pathlib import Path

import frappe
from frappe import _

from frappeops.services.agents.remote_status import get_server_status
from frappeops.services.apps.marketplace import list_catalog
from frappeops.services.operations.registry import ACTIONS
from frappeops.services.provisioning.site import list_local_apps


def _can_read() -> bool:
	if frappe.session.user == "Administrator":
		return True
	from frappeops.core.constants import ROLES

	return bool(set(frappe.get_roles()).intersection(ROLES))


@frappe.whitelist()
def list_servers() -> list[dict]:
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_all(
		"Server",
		fields=[
			"name",
			"server_name",
			"status",
			"hostname",
			"ip_address",
			"is_local",
			"provider",
			"agent_status",
			"disk_used_percent",
		],
		order_by="is_local desc, creation asc",
		limit_page_length=100,
	)


@frappe.whitelist()
def get_server(server: str) -> dict:
	"""Server control snapshot: status, agents, sites, actions."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not server or not frappe.db.exists("Server", server):
		frappe.throw(_("Server is required"))

	status = get_server_status(server)
	doc = frappe.get_doc("Server", server)
	sites = frappe.get_all(
		"Site",
		filters={"server": server},
		fields=["name", "site_name", "status", "is_protected", "installed_apps", "environment"],
		order_by="creation asc",
		limit_page_length=100,
	)
	benches = frappe.get_all(
		"Bench",
		filters={"server": server},
		fields=["name", "bench_name", "status", "bench_path", "frappe_version"],
		order_by="creation asc",
		limit_page_length=20,
	)
	agents = frappe.get_all(
		"Server Agent",
		filters={"server": server, "revoked": 0},
		fields=[
			"name",
			"agent_name",
			"status",
			"listen_url",
			"poll_enabled",
			"last_heartbeat",
			"last_poll_status",
		],
		order_by="modified desc",
		limit_page_length=20,
	)
	jobs = frappe.get_all(
		"Operation Job",
		filters={"server": server},
		fields=["name", "operation_type", "status", "risk_level", "creation"],
		order_by="creation desc",
		limit_page_length=10,
	)

	actions = []
	for action in ACTIONS:
		if action.get("target") not in ("server", "agent"):
			continue
		# Keep the most useful operator actions on this page
		if action["key"] not in {
			"server.health",
			"server.discover",
			"server.status",
			"server.register_vps",
			"agent.create_token",
			"agent.install_script",
			"agent.heartbeat",
			"agent.poll",
			"agent.install_local",
			"agent.start_listener",
			"monitor.poll",
		}:
			continue
		actions.append(action)

	return {
		"server": {
			"name": doc.name,
			"server_name": doc.server_name,
			"status": doc.status,
			"hostname": doc.hostname,
			"ip_address": doc.ip_address,
			"is_local": doc.is_local,
			"provider": getattr(doc, "provider", None),
			"region": getattr(doc, "region", None),
			"server_type": doc.server_type,
			"agent_status": doc.agent_status,
			"agent_version": doc.agent_version,
			"disk_used_percent": doc.disk_used_percent,
			"disk_gb": doc.disk_gb,
			"ram_gb": getattr(doc, "ram_gb", None),
			"cpu_cores": getattr(doc, "cpu_cores", None),
			"last_heartbeat": doc.last_heartbeat,
			"last_health_check": doc.last_health_check,
		},
		"status": status.get("status"),
		"sites": sites,
		"benches": benches,
		"agents": agents,
		"jobs": jobs,
		"actions": actions,
	}


@frappe.whitelist()
def get_apps_hub(site: str | None = None) -> dict:
	"""Marketplace + on-disk apps + optional target site for install wizard."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	sites = frappe.get_all(
		"Site",
		fields=[
			"name",
			"site_name",
			"status",
			"is_protected",
			"is_control_plane",
			"installed_apps",
			"environment",
		],
		order_by="creation asc",
		limit_page_length=200,
	)
	catalog = list_catalog().get("apps") or []
	on_disk = list_local_apps()

	selected = None
	if site and frappe.db.exists("Site", site):
		selected = frappe.get_doc("Site", site)
	else:
		# Prefer test/customer sites over control plane / protected
		for s in sites:
			if not s.is_protected and not s.is_control_plane:
				selected = frappe.get_doc("Site", s.name)
				break
		if not selected:
			for s in sites:
				if not s.is_protected:
					selected = frappe.get_doc("Site", s.name)
					break
		if not selected and sites:
			selected = frappe.get_doc("Site", sites[0].name)

	installed = []
	if selected:
		installed = [a.strip() for a in (selected.installed_apps or "").split(",") if a.strip()]

	# Enrich catalog with install state for selected site
	for row in catalog:
		row["on_disk"] = row.get("app_name") in on_disk
		row["installed_on_site"] = row.get("app_name") in installed

	disk_rows = []
	for app in on_disk:
		disk_rows.append(
			{
				"app_name": app,
				"on_disk": True,
				"installed_on_site": app in installed,
				"source": "Bench",
			}
		)

	return {
		"sites": sites,
		"selected_site": {
			"name": selected.name,
			"site_name": selected.site_name,
			"is_protected": selected.is_protected,
			"is_control_plane": selected.is_control_plane,
			"installed_apps": installed,
			"status": selected.status,
		}
		if selected
		else None,
		"catalog": catalog,
		"on_disk": disk_rows,
		"can_install": bool(selected and not selected.is_protected),
	}


@frappe.whitelist()
def nav_summary() -> dict:
	"""Compact counts for overview tiles."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return {
		"servers": frappe.db.count("Server"),
		"sites": frappe.db.count("Site"),
		"apps_on_disk": len(list_local_apps()),
		"catalog": frappe.db.count("App Catalog Item", {"enabled": 1})
		if frappe.db.exists("DocType", "App Catalog Item")
		else 0,
		"agents_online": frappe.db.count("Server Agent", {"status": "Online", "revoked": 0})
		if frappe.db.exists("DocType", "Server Agent")
		else 0,
		"backups": frappe.db.count("Backup"),
		"open_alerts": frappe.db.count("Ops Alert", {"status": ["in", ["Open", "Acknowledged"]]})
		if frappe.db.exists("DocType", "Ops Alert")
		else 0,
	}
