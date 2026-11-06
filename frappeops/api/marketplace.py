# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Marketplace whitelist APIs for Overview UI."""

from __future__ import annotations

import frappe
from frappe import _

from frappeops.services.apps.marketplace import get_app_from_git, list_catalog, seed_catalog


def _can() -> bool:
	if frappe.session.user == "Administrator":
		return True
	from frappeops.core.constants import ROLES

	return bool(set(frappe.get_roles()).intersection(ROLES))


@frappe.whitelist()
def list_apps():
	if not _can():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return list_catalog()


@frappe.whitelist()
def seed():
	if not _can():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return seed_catalog()


@frappe.whitelist()
def get_app(catalog_item: str | None = None, git_url: str | None = None, branch: str | None = None, confirm: int = 0):
	if not _can():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return get_app_from_git(
		catalog_item=catalog_item,
		git_url=git_url,
		branch=branch,
		confirm=bool(int(confirm or 0)),
	)
