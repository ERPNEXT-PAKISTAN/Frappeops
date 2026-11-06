# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Audit helpers."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappeops.core.redaction import redact_dict


def write_audit(
	action: str,
	*,
	resource_type: str | None = None,
	resource_name: str | None = None,
	status: str = "Info",
	message: str | None = None,
	operation_job: str | None = None,
	before: dict | None = None,
	after: dict | None = None,
	parameters: dict | None = None,
) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Audit Log",
			"actor": frappe.session.user,
			"action": action,
			"resource_type": resource_type,
			"resource_name": resource_name,
			"status": status,
			"message": message,
			"operation_job": operation_job,
			"ip_address": getattr(frappe.local, "request_ip", None),
			"before_json": json.dumps(redact_dict(before or {}), indent=2) if before else None,
			"after_json": json.dumps(redact_dict(after or {}), indent=2) if after else None,
			"parameters_json": json.dumps(redact_dict(parameters or {}), indent=2) if parameters else None,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name
