# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""One-shot inventory helpers for known remote VPS hosts."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from frappeops.services.agents.enrollment import create_enrollment_token


def ensure_ss_vps_live(*, create_token: bool = True) -> dict[str, Any]:
	"""Register live ss.frappe.my VPS (178.18.246.67). Local ss.frappe.my stays separate/protected."""
	ip = "178.18.246.67"
	server_name = "ss-vps-live"
	name = frappe.db.get_value("Server", {"ip_address": ip}, "name") or frappe.db.get_value(
		"Server", {"server_name": server_name}, "name"
	)
	org = frappe.db.get_value("Organization", {}, "name")
	payload = {
		"server_name": server_name,
		"hostname": "ss.frappe.my",
		"ip_address": ip,
		"server_type": "VPS",
		"status": "Unknown",
		"enabled": 1,
		"is_local": 0,
		"notes": (
			"Live VPS for production ss.frappe.my @ 178.18.246.67. "
			"Local site ss.frappe.my on the control host is a protected test copy."
		),
	}
	if org:
		payload["organization"] = org

	if name:
		doc = frappe.get_doc("Server", name)
		for key, value in payload.items():
			if hasattr(doc, key):
				setattr(doc, key, value)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Server", **payload})
		doc.insert(ignore_permissions=True)
		name = doc.name

	frappe.db.commit()
	out: dict[str, Any] = {
		"ok": True,
		"message": _("Live VPS server inventoried"),
		"server": name,
		"server_name": server_name,
		"ip_address": ip,
		"hostname": "ss.frappe.my",
	}
	if create_token:
		tok = create_enrollment_token(name, agent_name="ss-vps-agent")
		out["enrollment"] = {
			"agent": tok.get("agent"),
			"enrollment_token": tok.get("enrollment_token"),
			"expires_at": tok.get("expires_at"),
			"enroll_endpoint": tok.get("enroll_endpoint"),
			"message": tok.get("message"),
		}
	return out
