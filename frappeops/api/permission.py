# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Permission helpers for FrappeOps Desk app visibility."""

from __future__ import annotations

import frappe

from frappeops.core.constants import ROLES


def has_app_permission() -> bool:
	if frappe.session.user == "Administrator":
		return True
	roles = set(frappe.get_roles())
	return bool(roles.intersection(ROLES))
