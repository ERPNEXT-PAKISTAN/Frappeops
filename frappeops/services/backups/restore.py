# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Backup restore / rollback — always confirmed; never on protected sites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text
from frappeops.services.deployments.pipeline import assert_deployable_site
from frappeops.utils.bench_cmd import run_bench


def restore_backup(
	backup: str,
	*,
	site: str | None = None,
	confirm: bool = False,
	typed_confirmation: str | None = None,
	take_pre_backup: bool = True,
) -> dict[str, Any]:
	"""Restore a Backup onto a Site. DB restore is destructive — requires confirm + typed site name."""
	if not confirm:
		return {
			"ok": False,
			"needs_confirm": True,
			"message": _(
				"Restore is destructive. Set confirm=1 and typed_confirmation=<site_name> to proceed."
			),
		}

	backup_doc = frappe.get_doc("Backup", backup)
	site_name = site or backup_doc.site
	if not site_name:
		return {"ok": False, "message": _("Site is required")}

	site_doc = frappe.get_doc("Site", site_name)
	assert_deployable_site(site_doc)

	if (typed_confirmation or "").strip() != site_doc.site_name:
		return {
			"ok": False,
			"message": _("Typed confirmation must exactly match site name: {0}").format(site_doc.site_name),
		}

	if backup_doc.status not in ("Success", "Verified"):
		return {"ok": False, "message": _("Backup status must be Success/Verified (got {0})").format(backup_doc.status)}

	files = _resolve_backup_files(backup_doc)
	if not files.get("database"):
		return {
			"ok": False,
			"message": _("Could not locate database.sql.gz for this backup"),
			"storage_location": backup_doc.storage_location,
		}

	restore_doc = frappe.get_doc(
		{
			"doctype": "Restore Job",
			"backup": backup_doc.name,
			"site": site_doc.name,
			"status": "Running",
			"risk_level": "Critical",
			"notes": _("Restoring {0} → {1}").format(backup_doc.name, site_doc.site_name),
		}
	)
	restore_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	pre_backup_name = None
	if take_pre_backup:
		from frappeops.services.operations.runner import _site_backup

		pre = _site_backup(site_doc.name)
		if pre.get("ok"):
			pre_backup_name = pre.get("backup")
			restore_doc.notes = (restore_doc.notes or "") + f"\nPre-restore backup: {pre_backup_name}"
			restore_doc.save(ignore_permissions=True)
		else:
			restore_doc.status = "Failed"
			restore_doc.notes = (restore_doc.notes or "") + "\nPre-restore backup failed; aborting."
			restore_doc.save(ignore_permissions=True)
			return {
				"ok": False,
				"message": _("Aborted: could not take pre-restore backup"),
				"restore_job": restore_doc.name,
				"pre_backup_result": pre,
			}

	args = ["--site", site_doc.site_name, "restore", files["database"], "--force"]
	if files.get("public"):
		args += ["--with-public-files", files["public"]]
	if files.get("private"):
		args += ["--with-private-files", files["private"]]

	proc = run_bench(args, timeout=1800, check=False)
	ok = proc.returncode == 0
	restore_doc.status = "Success" if ok else "Failed"
	restore_doc.notes = (restore_doc.notes or "") + "\n" + redact_text((proc.stdout or "")[-1500:])
	restore_doc.save(ignore_permissions=True)

	write_audit(
		"backup.restore",
		resource_type="site",
		resource_name=site_doc.name,
		status="Success" if ok else "Failed",
		message=_("Restore {0}").format(backup_doc.name),
		operation_job=None,
		parameters={
			"backup": backup_doc.name,
			"restore_job": restore_doc.name,
			"pre_backup": pre_backup_name,
		},
		after={"rc": proc.returncode},
	)

	return {
		"ok": ok,
		"message": _("Restore completed") if ok else _("Restore failed"),
		"restore_job": restore_doc.name,
		"pre_backup": pre_backup_name,
		"output": redact_text((proc.stdout or "")[-2000:]),
		"warning": _(
			"Database restore overwrites site data. There is no automatic undo beyond the pre-restore backup."
		),
	}


def rollback_deployment(deployment: str, *, confirm: bool = False, typed_confirmation: str | None = None) -> dict[str, Any]:
	"""Honest rollback = restore Deployment.pre_backup onto the deployment site."""
	dep = frappe.get_doc("Deployment", deployment)
	if not dep.pre_backup:
		return {"ok": False, "message": _("Deployment has no pre_backup to restore")}
	if not dep.site:
		return {"ok": False, "message": _("Deployment has no site")}

	site_doc = frappe.get_doc("Site", dep.site)
	result = restore_backup(
		dep.pre_backup,
		site=dep.site,
		confirm=confirm,
		typed_confirmation=typed_confirmation or (site_doc.site_name if confirm else None),
		take_pre_backup=True,
	)
	if result.get("ok"):
		dep.status = "Rolled Back"
		dep.notes = (dep.notes or "") + f"\nRolled back via {result.get('restore_job')} at {now_datetime()}"
		dep.save(ignore_permissions=True)
	return {**result, "deployment": dep.name}


def _resolve_backup_files(backup_doc) -> dict[str, str | None]:
	"""Map Backup.storage_location to sql.gz / public / private tarballs."""
	loc = Path(backup_doc.storage_location or "")
	directory = loc.parent if loc.suffixes else loc
	if not directory.exists() and loc.exists():
		directory = loc.parent

	db = None
	public = None
	private = None

	if loc.exists() and loc.name.endswith(".sql.gz"):
		db = str(loc)
		stem_prefix = loc.name.replace("-database.sql.gz", "")
		for p in directory.glob(stem_prefix + "*"):
			name = p.name
			if name.endswith("-files.tar") and "private" not in name:
				public = str(p)
			elif name.endswith("-private-files.tar"):
				private = str(p)
	elif directory.exists():
		sqls = sorted(directory.glob("*-database.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
		if sqls:
			db = str(sqls[0])
			stem_prefix = sqls[0].name.replace("-database.sql.gz", "")
			pub = directory / f"{stem_prefix}-files.tar"
			priv = directory / f"{stem_prefix}-private-files.tar"
			if pub.exists():
				public = str(pub)
			if priv.exists():
				private = str(priv)

	return {"database": db, "public": public, "private": private}
