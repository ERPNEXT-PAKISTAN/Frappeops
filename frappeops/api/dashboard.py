# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist()
def get_dashboard_summary() -> dict:
	"""High-level inventory counts for the FrappeOps dashboard."""
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	def count(doctype: str) -> int:
		if not frappe.db.exists("DocType", doctype):
			return 0
		return frappe.db.count(doctype)

	return {
		"servers": count("Server"),
		"benches": count("Bench"),
		"sites": count("Site"),
		"apps": count("Managed App"),
		"operations_running": frappe.db.count("Operation Job", {"status": "Running"})
		if frappe.db.exists("DocType", "Operation Job")
		else 0,
		"operations_failed": frappe.db.count("Operation Job", {"status": "Failed"})
		if frappe.db.exists("DocType", "Operation Job")
		else 0,
		"backups": count("Backup"),
		"domains": count("Domain"),
		"open_alerts": frappe.db.count("Ops Alert", {"status": "Open"})
		if frappe.db.exists("DocType", "Ops Alert")
		else 0,
		"note": "FrappeOps 0.3.0 local MVP. Protected sites stay locked for destructive ops.",
	}


def _can_read() -> bool:
	if frappe.session.user == "Administrator":
		return True
	from frappeops.core.constants import ROLES

	return bool(set(frappe.get_roles()).intersection(ROLES))
