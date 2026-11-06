# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Site detail APIs for the easy Site Control page."""

from __future__ import annotations

import frappe
from frappe import _

from frappeops.services.operations.registry import ACTIONS


@frappe.whitelist()
def get_site(site: str) -> dict:
	"""Return one Site with recent health, backups, jobs, and allowed actions."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not site:
		frappe.throw(_("Site is required"))

	doc = frappe.get_doc("Site", site)
	health = frappe.get_all(
		"Site Health",
		filters={"site": doc.name},
		fields=["name", "status", "checked_at", "http_status", "database_ok", "details_json"],
		order_by="creation desc",
		limit_page_length=5,
	)
	backups = frappe.get_all(
		"Backup",
		filters={"site": doc.name},
		fields=["name", "backup_name", "status", "backup_type", "size_mb", "taken_at", "storage_location"],
		order_by="creation desc",
		limit_page_length=8,
	)
	jobs = frappe.get_all(
		"Operation Job",
		filters={"site": doc.name},
		fields=["name", "operation_type", "status", "risk_level", "creation", "finished_at"],
		order_by="creation desc",
		limit_page_length=10,
	)

	actions = []
	for action in ACTIONS:
		if action.get("target") != "site":
			continue
		blocked = bool(doc.is_protected and not action.get("allowed_on_protected", False))
		actions.append(
			{
				**action,
				"blocked": blocked,
				"block_reason": _("Protected site") if blocked else None,
			}
		)

	return {
		"site": {
			"name": doc.name,
			"site_name": doc.site_name,
			"status": doc.status,
			"environment": doc.environment,
			"server": doc.server,
			"bench": doc.bench,
			"is_protected": doc.is_protected,
			"is_control_plane": doc.is_control_plane,
			"maintenance_mode": doc.maintenance_mode,
			"developer_mode": doc.developer_mode,
			"primary_domain": doc.primary_domain,
			"ssl_state": doc.ssl_state,
			"installed_apps": doc.installed_apps,
			"last_health_check": doc.last_health_check,
		},
		"health": health,
		"backups": backups,
		"jobs": jobs,
		"actions": actions,
	}


@frappe.whitelist()
def list_sites() -> list[dict]:
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_all(
		"Site",
		fields=["name", "site_name", "status", "is_protected", "is_control_plane", "environment"],
		order_by="creation asc",
		limit_page_length=200,
	)


def _can_read() -> bool:
	if frappe.session.user == "Administrator":
		return True
	roles = set(frappe.get_roles())
	return bool(
		roles.intersection(
			{
				"System Manager",
				"FrappeOps Administrator",
				"FrappeOps Operator",
				"FrappeOps Developer",
				"FrappeOps Auditor",
				"FrappeOps Viewer",
			}
		)
	)
