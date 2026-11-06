# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Versioned operator API surface (v1)."""

from __future__ import annotations

import frappe
from frappe import _

import frappeops
from frappeops.api.dashboard import get_dashboard_summary
from frappeops.services.operations.runner import run_action


@frappe.whitelist()
def status() -> dict:
	"""Control-plane health snapshot for CLI/integrations."""
	_require_read()
	summary = get_dashboard_summary()
	open_alerts = frappe.db.count("Ops Alert", {"status": "Open"}) if frappe.db.exists("DocType", "Ops Alert") else 0
	return {
		"ok": True,
		"app": "frappeops",
		"version": getattr(frappeops, "__version__", "0.1.0"),
		"api": "v1",
		"summary": summary,
		"open_alerts": open_alerts,
	}


@frappe.whitelist()
def run(action_key: str, target_type: str | None = None, target_name: str | None = None, params: str | None = None):
	"""Proxy to allowlisted operations runner."""
	return run_action(action_key, target_type, target_name, params)


@frappe.whitelist()
def alerts(status: str = "Open", limit: int = 20) -> list:
	_require_read()
	if not frappe.db.exists("DocType", "Ops Alert"):
		return []
	return frappe.get_all(
		"Ops Alert",
		filters={"status": status} if status else {},
		fields=["name", "title", "severity", "status", "alert_type", "server", "site", "last_seen", "message"],
		order_by="modified desc",
		limit_page_length=min(int(limit or 20), 100),
	)


def _require_read():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not roles.intersection(
		{
			"System Manager",
			"FrappeOps Administrator",
			"FrappeOps Operator",
			"FrappeOps Developer",
			"FrappeOps Auditor",
			"FrappeOps Viewer",
		}
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
