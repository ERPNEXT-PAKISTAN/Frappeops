# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Easy home/portal APIs for the FrappeOps UI."""

from __future__ import annotations

import frappe
from frappe import _

from frappeops.services.operations.registry import ACTIONS


@frappe.whitelist()
def get_home() -> dict:
	"""Return a UI-ready control-center snapshot."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	servers = frappe.get_all(
		"Server",
		fields=[
			"name",
			"server_name",
			"status",
			"hostname",
			"ip_address",
			"provider",
			"region",
			"server_type",
			"is_local",
			"is_protected",
			"environment",
			"agent_status",
			"agent_version",
			"disk_used_percent",
			"disk_gb",
			"ram_gb",
			"cpu_cores",
			"last_heartbeat",
			"last_health_check",
		],
		order_by="creation asc",
		limit_page_length=50,
	)
	benches = frappe.get_all(
		"Bench",
		fields=[
			"name",
			"bench_name",
			"server",
			"status",
			"bench_path",
			"frappe_version",
			"environment",
			"scheduler_state",
			"worker_count",
			"last_health_check",
		],
		order_by="creation asc",
		limit_page_length=100,
	)
	sites = frappe.get_all(
		"Site",
		fields=[
			"name",
			"site_name",
			"server",
			"bench",
			"status",
			"environment",
			"is_protected",
			"is_control_plane",
			"installed_apps",
			"primary_domain",
			"maintenance_mode",
			"developer_mode",
			"ssl_state",
			"last_health_check",
		],
		order_by="creation asc",
		limit_page_length=200,
	)
	apps = frappe.get_all(
		"Managed App",
		fields=["name", "app_name", "bench", "server", "version", "branch", "installed_state", "source"],
		order_by="app_name asc",
		limit_page_length=300,
	)
	services = frappe.get_all(
		"Service",
		fields=["name", "service_name", "server", "service_type", "status", "managed_by"],
		order_by="service_name asc",
		limit_page_length=100,
	)
	jobs = frappe.get_all(
		"Operation Job",
		fields=["name", "operation_type", "status", "risk_level", "creation", "site", "server", "bench"],
		order_by="creation desc",
		limit_page_length=8,
	)
	alerts = []
	if frappe.db.exists("DocType", "Ops Alert"):
		alerts = frappe.get_all(
			"Ops Alert",
			filters={"status": ["in", ["Open", "Acknowledged"]]},
			fields=["name", "title", "severity", "status", "alert_type", "last_seen", "message"],
			order_by="modified desc",
			limit_page_length=8,
		)

	agents = []
	if frappe.db.exists("DocType", "Server Agent"):
		agents = frappe.get_all(
			"Server Agent",
			filters={"revoked": 0},
			fields=[
				"name",
				"agent_name",
				"server",
				"status",
				"listen_url",
				"poll_enabled",
				"last_poll_at",
				"last_poll_status",
				"last_heartbeat",
				"agent_version",
			],
			order_by="modified desc",
			limit_page_length=20,
		)

	domains = []
	if frappe.db.exists("DocType", "Domain"):
		domains = frappe.get_all(
			"Domain",
			fields=[
				"name",
				"domain_name",
				"site",
				"nginx_status",
				"dns_status",
				"ssl_status",
				"apply_status",
			],
			order_by="modified desc",
			limit_page_length=20,
		)

	latest_server_health = {}
	for row in frappe.get_all(
		"Server Health",
		fields=[
			"name",
			"server",
			"status",
			"checked_at",
			"cpu_percent",
			"disk_percent",
			"ram_percent",
			"load_average",
		],
		order_by="creation desc",
		limit_page_length=50,
	):
		latest_server_health.setdefault(row.server, row)

	catalog = []
	if frappe.db.exists("DocType", "App Catalog Item"):
		catalog = frappe.get_all(
			"App Catalog Item",
			filters={"enabled": 1},
			fields=[
				"name",
				"app_name",
				"title",
				"git_url",
				"default_branch",
				"category",
				"featured",
				"description",
			],
			order_by="featured desc, title asc",
			limit_page_length=50,
		)

	destinations = []
	if frappe.db.exists("DocType", "Backup Destination"):
		destinations = frappe.get_all(
			"Backup Destination",
			filters={"enabled": 1},
			fields=["name", "destination_name", "provider", "is_default", "prefix"],
			order_by="is_default desc, name asc",
			limit_page_length=20,
		)

	latest_site_health = {}
	for row in frappe.get_all(
		"Site Health",
		fields=["name", "site", "status", "checked_at", "http_status", "database_ok"],
		order_by="creation desc",
		limit_page_length=100,
	):
		latest_site_health.setdefault(row.site, row)

	tree = []
	for server in servers:
		server_benches = []
		for bench in [b for b in benches if b.server == server.name]:
			bench_sites = []
			for s in [x for x in sites if x.bench == bench.name]:
				sh = latest_site_health.get(s.name)
				bench_sites.append(
					{
						**s,
						"health": sh,
						"app_count": len([a for a in (s.installed_apps or "").split(",") if a.strip()]),
					}
				)
			bench_apps = [a for a in apps if a.bench == bench.name]
			server_benches.append({**bench, "sites": bench_sites, "apps": bench_apps})
		tree.append(
			{
				**server,
				"benches": server_benches,
				"services": [svc for svc in services if svc.server == server.name],
				"health": latest_server_health.get(server.name),
			}
		)

	from frappeops.api.dashboard import get_dashboard_summary

	summary = get_dashboard_summary()
	summary.update(
		{
			"healthy_sites": len([s for s in sites if (s.status or "").lower() == "healthy"]),
			"warning_sites": len([s for s in sites if (s.status or "").lower() == "warning"]),
			"critical_sites": len([s for s in sites if (s.status or "").lower() in ("critical", "offline")]),
			"protected_sites": len([s for s in sites if s.is_protected]),
			"services": len(services),
		}
	)

	return {
		"summary": summary,
		"tree": tree,
		"apps": apps,
		"catalog": catalog,
		"backup_destinations": destinations,
		"jobs": jobs,
		"alerts": alerts,
		"agents": agents,
		"domains": domains,
		"actions": ACTIONS,
		"indicators": {
			"servers_online": len([s for s in servers if (s.status or "").lower() == "online"]),
			"servers_total": len(servers),
			"sites_total": len(sites),
			"apps_total": len(apps),
			"catalog_total": len(catalog),
			"open_alerts": summary.get("open_alerts") or len(alerts),
			"agents_online": len([a for a in agents if (a.status or "").lower() == "online"]),
			"agents_total": len(agents),
			"domains_total": len(domains),
			"jobs_running": summary.get("operations_running") or 0,
			"jobs_failed": summary.get("operations_failed") or 0,
		},
		"quick_links": [
			{"label": _("Overview"), "route": "/app/frappeops-overview", "desc": _("Easy home")},
			{"label": _("Site Control"), "route": "/app/frappeops-site", "desc": _("Site status & actions")},
			{"label": _("Server Control"), "route": "/app/frappeops-server", "desc": _("VPS status & agents")},
			{"label": _("Install Apps"), "route": "/app/frappeops-apps", "desc": _("Marketplace → install on a site")},
			{"label": _("Servers (raw)"), "route": "/app/server", "desc": _("Advanced DocType")},
			{"label": _("Sites (raw)"), "route": "/app/site", "desc": _("Advanced DocType")},
			{"label": _("Commands / Jobs"), "route": "/app/operation-job", "desc": _("Operation history")},
			{"label": _("Services"), "route": "/app/service", "desc": _("Nginx, Redis, DB…")},
			{"label": _("Backups"), "route": "/app/backup", "desc": _("Backup history")},
			{"label": _("Backup Destinations"), "route": "/app/backup-destination", "desc": _("S3 / Drive / Dropbox")},
			{"label": _("Domains"), "route": "/app/domain", "desc": _("Nginx drafts & DNS")},
			{"label": _("SSL Certificates"), "route": "/app/ssl-certificate", "desc": _("Cert inventory")},
			{"label": _("Agents"), "route": "/app/server-agent", "desc": _("Enrollment, poll, heartbeats")},
			{"label": _("Deployments"), "route": "/app/deployment", "desc": _("Pipeline history")},
			{"label": _("Restore Jobs"), "route": "/app/restore-job", "desc": _("DR / rollback")},
			{"label": _("Ops Alerts"), "route": "/app/ops-alert", "desc": _("Threshold alerts")},
			{"label": _("AI Tasks"), "route": "/app/ai-task", "desc": _("Plan → approve → execute")},
			{"label": _("AI Providers"), "route": "/app/ai-provider", "desc": _("Ollama / OpenAI-compatible")},
			{"label": _("Audit"), "route": "/app/audit-log", "desc": _("Who did what")},
			{"label": _("Settings"), "route": "/app/frappeops-settings", "desc": _("Safety & defaults")},
		],
		"safety": {
			"destructive_ops_enabled": False,
			"message": _(
				"Safe mode is ON. Protected sites (like production ERPNext) block cache clear and other risky actions."
			),
		},
	}


def _can_read() -> bool:
	if frappe.session.user == "Administrator":
		return True
	from frappeops.core.constants import ROLES

	return bool(set(frappe.get_roles()).intersection(ROLES))
