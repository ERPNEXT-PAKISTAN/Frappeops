# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Backup retention — scan and optional purge; never silent delete."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text


def default_retention_days() -> int:
	try:
		days = frappe.db.get_single_value("FrappeOps Settings", "backup_retention_days")
		return int(days or 30)
	except Exception:
		return 30


def apply_retention_dates(days: int | None = None) -> dict[str, Any]:
	"""Set retention_until on Success backups missing it."""
	days = days or default_retention_days()
	updated = 0
	for row in frappe.get_all(
		"Backup",
		filters={"status": ["in", ["Success", "Verified"]], "retention_until": ["is", "not set"]},
		fields=["name", "taken_at", "creation"],
		limit_page_length=500,
	):
		base = getdate(row.taken_at or row.creation)
		frappe.db.set_value("Backup", row.name, "retention_until", add_days(base, days))
		updated += 1
	return {"ok": True, "updated": updated, "retention_days": days}


def scan_expired() -> dict[str, Any]:
	"""List backups past retention_until — does not delete."""
	apply_retention_dates()
	today = getdate(nowdate())
	rows = frappe.get_all(
		"Backup",
		filters={
			"status": ["in", ["Success", "Verified", "Expired"]],
			"retention_until": ["<", today],
		},
		fields=["name", "backup_name", "site", "size_mb", "taken_at", "retention_until", "storage_location", "status"],
		order_by="retention_until asc",
		limit_page_length=200,
	)
	# Mark Expired status without deleting files
	for row in rows:
		if row.status != "Expired":
			frappe.db.set_value("Backup", row.name, "status", "Expired")
	return {
		"ok": True,
		"message": _("Found {0} expired backup(s). Purge requires explicit confirm.").format(len(rows)),
		"expired": rows,
		"count": len(rows),
	}


def purge_expired(*, confirm: bool = False, typed_confirmation: str | None = None) -> dict[str, Any]:
	"""Delete expired backup files + mark records. Requires settings allow + confirm + typed PURGE."""
	if not frappe.db.get_single_value("FrappeOps Settings", "allow_backup_purge"):
		return {
			"ok": False,
			"message": _("Backup purge is disabled. Enable Allow Backup Purge in FrappeOps Settings."),
		}
	if not confirm or (typed_confirmation or "").strip().upper() != "PURGE":
		return {
			"ok": False,
			"needs_confirm": True,
			"message": _("Set confirm=1 and typed_confirmation=PURGE to delete expired backup files."),
		}

	scan = scan_expired()
	deleted = []
	errors = []
	for row in scan.get("expired") or []:
		# Never purge backups tied to protected sites
		if row.site and frappe.db.get_value("Site", row.site, "is_protected"):
			errors.append({"backup": row.name, "error": "protected site — skipped"})
			continue
		path = Path(row.storage_location or "")
		try:
			removed = _remove_backup_artifacts(path)
			frappe.db.set_value(
				"Backup",
				row.name,
				{
					"status": "Expired",
					"notes": redact_text(f"Purged files at {now_datetime()}: {removed}"),
					"storage_location": "",
				},
			)
			deleted.append({"backup": row.name, "removed": removed})
		except Exception as exc:
			errors.append({"backup": row.name, "error": redact_text(str(exc))})

	write_audit(
		"backup.purge_expired",
		resource_type="backup",
		resource_name="expired",
		status="Success" if deleted else "Failed",
		message=_("Purged {0} backup(s)").format(len(deleted)),
		after={"deleted": len(deleted), "errors": len(errors)},
	)
	return {
		"ok": True,
		"message": _("Purged {0} expired backup(s)").format(len(deleted)),
		"deleted": deleted,
		"errors": errors,
	}


def _remove_backup_artifacts(primary: Path) -> list[str]:
	removed = []
	if not primary or str(primary) == ".":
		return removed
	candidates = []
	if primary.exists() and primary.is_file():
		candidates.append(primary)
		stem = primary.name.replace("-database.sql.gz", "")
		for p in primary.parent.glob(stem + "*"):
			if p not in candidates:
				candidates.append(p)
	for p in candidates:
		if p.is_file() and ("backups" in str(p) or p.suffix in {".gz", ".tar", ".json"}):
			os.remove(p)
			removed.append(str(p))
	return removed
