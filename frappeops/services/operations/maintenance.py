# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Maintenance helpers for Operation Jobs."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime


def fail_stale_operation_jobs(hours: int = 2) -> dict[str, Any]:
	"""Mark long-running jobs Failed so locks and dashboard counts recover."""
	cutoff = add_to_date(now_datetime(), hours=-hours)
	names = frappe.get_all(
		"Operation Job",
		filters={"status": ["in", ["Running", "Queued", "Planning"]], "modified": ["<", cutoff]},
		pluck="name",
		limit_page_length=200,
	)
	for name in names:
		frappe.db.set_value(
			"Operation Job",
			name,
			{
				"status": "Failed",
				"error": _("Marked failed: stale job (no finish within {0}h)").format(hours),
				"progress": 100,
				"finished_at": now_datetime(),
			},
		)
	return {"ok": True, "failed": names, "count": len(names)}
