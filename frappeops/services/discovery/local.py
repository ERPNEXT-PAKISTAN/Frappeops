# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Read-only local host discovery for FrappeOps (Phase 4 foundation)."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
from pathlib import Path
from typing import Any

import frappe
from frappe import _

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_dict
from frappeops.utils.bench_cmd import get_bench_executable, bench_env


def _run(cmd: list[str], timeout: int = 15) -> str:
	try:
		if cmd and cmd[0] == "bench":
			cmd = [get_bench_executable(), *cmd[1:]]
		out = subprocess.check_output(
			cmd, stderr=subprocess.STDOUT, timeout=timeout, text=True, env=bench_env()
		)
		return out.strip()
	except Exception:
		return ""


def discover_local_host() -> dict[str, Any]:
	"""Collect non-secret facts about the current machine and bench."""
	bench_path = Path(frappe.utils.get_bench_path())
	hostname = socket.gethostname()
	uname = platform.uname()

	sites = []
	sites_dir = bench_path / "sites"
	if sites_dir.exists():
		for child in sorted(sites_dir.iterdir()):
			if child.is_dir() and (child / "site_config.json").exists():
				cfg = {}
				try:
					raw = json.loads((child / "site_config.json").read_text())
					cfg = {
						"site_name": child.name,
						"developer_mode": raw.get("developer_mode"),
						"maintenance_mode": raw.get("maintenance_mode"),
						"db_type": raw.get("db_type"),
						"installed_apps": raw.get("installed_apps"),
					}
				except Exception:
					cfg = {"site_name": child.name}
				sites.append(cfg)

	apps = []
	apps_dir = bench_path / "apps"
	if apps_dir.exists():
		for child in sorted(apps_dir.iterdir()):
			if child.is_dir() and not child.name.startswith("."):
				apps.append(child.name)

	common = {}
	common_path = sites_dir / "common_site_config.json"
	if common_path.exists():
		try:
			raw = json.loads(common_path.read_text())
			common = {
				k: raw.get(k)
				for k in (
					"default_site",
					"webserver_port",
					"socketio_port",
					"gunicorn_workers",
					"background_workers",
					"redis_cache",
					"redis_queue",
					"maintenance_mode",
					"pause_scheduler",
				)
				if k in raw
			}
		except Exception:
			common = {}

	disk = _run(["df", "-h", str(bench_path)])
	mem = _run(["free", "-h"])

	return redact_dict(
		{
			"hostname": hostname,
			"fqdn": socket.getfqdn(),
			"os": f"{uname.system} {uname.release}",
			"architecture": uname.machine,
			"python_version": platform.python_version(),
			"bench_path": str(bench_path),
			"bench_version": _run(["bench", "--version"]) or None,
			"common_site_config": common,
			"sites": sites,
			"apps": apps,
			"disk": disk,
			"memory": mem,
		}
	)


@frappe.whitelist()
def import_local_server(organization: str | None = None) -> dict[str, Any]:
	"""Create/update Server + Bench + Site records from local discovery (read-only host scan)."""
	if frappe.session.user != "Administrator" and "FrappeOps Administrator" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	data = discover_local_host()
	organization = organization or frappe.db.get_single_value("FrappeOps Settings", "default_organization")

	server_name = data.get("hostname") or "local-server"
	existing = frappe.db.get_value("Server", {"hostname": server_name, "is_local": 1}, "name")
	if existing:
		server = frappe.get_doc("Server", existing)
	else:
		server = frappe.get_doc(
			{
				"doctype": "Server",
				"server_name": server_name,
				"organization": organization,
				"hostname": server_name,
				"server_type": "Local",
				"environment": "Development",
				"is_local": 1,
				"status": "Online",
				"enabled": 1,
				"operating_system": data.get("os"),
				"architecture": data.get("architecture"),
				"agent_status": "Not Installed",
				"notes": "Imported by local discovery (read-only).",
			}
		)
		server.insert(ignore_permissions=True)

	server.operating_system = data.get("os")
	server.architecture = data.get("architecture")
	server.status = "Online"
	server.save(ignore_permissions=True)

	bench_path = data.get("bench_path")
	bench_name = Path(bench_path).name if bench_path else "frappe-bench"
	existing_bench = frappe.db.get_value("Bench", {"bench_path": bench_path}, "name")
	if existing_bench:
		bench = frappe.get_doc("Bench", existing_bench)
	else:
		bench = frappe.get_doc(
			{
				"doctype": "Bench",
				"bench_name": bench_name,
				"server": server.name,
				"organization": organization,
				"bench_path": bench_path,
				"environment": "Development",
				"status": "Unknown",
				"python_version": data.get("python_version"),
				"bench_version": data.get("bench_version"),
				"webserver_port": (data.get("common_site_config") or {}).get("webserver_port"),
				"socketio_port": (data.get("common_site_config") or {}).get("socketio_port"),
			}
		)
		bench.insert(ignore_permissions=True)

	imported_sites = []
	for site_info in data.get("sites") or []:
		site_name = site_info.get("site_name")
		if not site_name:
			continue
		existing_site = frappe.db.get_value("Site", {"site_name": site_name, "bench": bench.name}, "name")
		is_control = site_name == "frappeops.local"
		is_protected = site_name != "frappeops.local"
		apps = site_info.get("installed_apps") or []
		payload = {
			"site_name": site_name,
			"server": server.name,
			"bench": bench.name,
			"organization": organization,
			"site_path": str(Path(bench_path) / "sites" / site_name),
			"environment": "Control Plane" if is_control else "Production",
			"status": "Unknown",
			"developer_mode": 1 if site_info.get("developer_mode") else 0,
			"maintenance_mode": 1 if site_info.get("maintenance_mode") else 0,
			"database_type": site_info.get("db_type") or "mariadb",
			"installed_apps": ", ".join(apps) if isinstance(apps, list) else str(apps),
			"is_protected": 1 if is_protected else 0,
			"is_control_plane": 1 if is_control else 0,
			"notes": "Imported by local discovery. Protected sites must not be targeted by destructive ops.",
		}
		if existing_site:
			site_doc = frappe.get_doc("Site", existing_site)
			site_doc.update(payload)
			site_doc.save(ignore_permissions=True)
		else:
			site_doc = frappe.get_doc({"doctype": "Site", **payload})
			site_doc.insert(ignore_permissions=True)
		imported_sites.append(site_doc.name)

		# Managed apps for this site/bench (idempotent by app+bench)
		if isinstance(apps, list):
			for app_name in apps:
				exists = frappe.db.exists("Managed App", {"app_name": app_name, "bench": bench.name})
				if exists:
					continue
				frappe.get_doc(
					{
						"doctype": "Managed App",
						"app_name": app_name,
						"bench": bench.name,
						"server": server.name,
						"source": "Bench",
						"installed_state": "Present",
					}
				).insert(ignore_permissions=True)

	write_audit(
		"local_discovery.import",
		resource_type="Server",
		resource_name=server.name,
		status="Success",
		message="Imported local server/bench/sites (read-only discovery).",
		after={"server": server.name, "bench": bench.name, "sites": imported_sites},
		parameters={"organization": organization},
	)

	return {
		"server": server.name,
		"bench": bench.name,
		"sites": imported_sites,
		"apps_discovered": data.get("apps"),
		"discovery": data,
	}
