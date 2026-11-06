# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Domain / nginx APIs for Desk UI."""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist()
def list_domains() -> list[dict]:
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_all(
		"Domain",
		fields=[
			"name",
			"domain_name",
			"site",
			"nginx_status",
			"dns_status",
			"ssl_status",
			"apply_status",
			"protocol",
		],
		order_by="modified desc",
		limit_page_length=200,
	)


@frappe.whitelist()
def get_domain(domain: str) -> dict:
	if not _can_read():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc = frappe.get_doc("Domain", domain)
	site = frappe.get_doc("Site", doc.site) if doc.site else None
	return {
		"domain": doc.as_dict(),
		"site": {
			"name": site.name,
			"site_name": site.site_name,
			"is_protected": site.is_protected,
		}
		if site
		else None,
	}


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
