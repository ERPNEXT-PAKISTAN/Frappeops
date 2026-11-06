# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Provisioning helpers exposed to the Desk UI."""

from __future__ import annotations

import frappe
from frappe import _

from frappeops.services.provisioning.site import list_local_apps


@frappe.whitelist()
def get_local_apps() -> list[str]:
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return list_local_apps()


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
			}
		)
	)
