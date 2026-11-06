# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Simple resource locks to prevent conflicting operations."""

from __future__ import annotations

import frappe
from frappe import _


def is_locked(resource_type: str, resource_name: str, exclude_job: str | None = None) -> str | None:
	"""Return blocking Operation Job name if resource is locked, else None."""
	filters: dict = {"status": ["in", ["Queued", "Running", "Planning", "Waiting for Approval"]]}
	if resource_type == "site":
		filters["site"] = resource_name
	elif resource_type == "bench":
		filters["bench"] = resource_name
	elif resource_type == "server":
		filters["server"] = resource_name
	else:
		return None

	if exclude_job:
		filters["name"] = ["!=", exclude_job]

	existing = frappe.get_all(
		"Operation Job",
		filters=filters,
		fields=["name", "operation_type"],
		limit=1,
	)
	if existing:
		return existing[0].name
	return None


def acquire_lock(resource_type: str, resource_name: str, operation_job: str) -> None:
	"""Raise if another running job already locks this resource."""
	blocking = is_locked(resource_type, resource_name, exclude_job=operation_job)
	if blocking:
		frappe.throw(
			_("Resource locked by operation {0}").format(blocking),
			title=_("Busy"),
		)


def assert_site_action_allowed(site_doc, action: dict) -> None:
	if site_doc.is_protected and not action.get("allowed_on_protected", False):
		frappe.throw(
			_("Refused: {0} is protected. Action {1} is not allowed.").format(
				site_doc.site_name, action.get("label") or action.get("key")
			),
			title=_("Protected Site"),
		)
