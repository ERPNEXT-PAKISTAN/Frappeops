# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Site deployment pipeline: backup → migrate → (optional build) → health."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text
from frappeops.utils.bench_cmd import run_bench


def assert_deployable_site(site_doc) -> None:
	if site_doc.is_protected:
		frappe.throw(
			_("Refused: deployments are blocked on protected site {0}.").format(site_doc.site_name),
			title=_("Protected Site"),
		)
	name = (site_doc.site_name or "").lower()
	if name == "ss.frappe.my":
		frappe.throw(_("Refused: ss.frappe.my cannot be a deployment target."))


def run_site_pipeline(
	site: str,
	*,
	confirm: bool = False,
	run_migrate: bool = True,
	run_build: bool = False,
	apps_to_build: str | None = None,
	deployment_name: str | None = None,
) -> dict[str, Any]:
	"""Execute allowlisted deploy steps and record Deployment + Deployment Job rows."""
	if not confirm:
		return {
			"ok": False,
			"needs_confirm": True,
			"message": _("Set confirm=1 after reviewing the target site. Pipeline: backup → migrate → health."),
		}

	site_doc = frappe.get_doc("Site", site)
	assert_deployable_site(site_doc)

	dep = frappe.get_doc(
		{
			"doctype": "Deployment",
			"deployment_name": deployment_name
			or f"deploy-{site_doc.site_name}-{now_datetime().strftime('%Y%m%d-%H%M%S')}",
			"status": "Running",
			"server": site_doc.server,
			"bench": site_doc.bench,
			"site": site_doc.name,
			"target_environment": site_doc.environment or "Unknown",
			"started_at": now_datetime(),
			"notes": "Wave E pipeline: backup → migrate → health",
		}
	)
	dep.insert(ignore_permissions=True)

	steps_log = []
	ok = True
	final_message = _("Deployment succeeded")

	def step(name: str, fn):
		nonlocal ok, final_message
		job = frappe.get_doc(
			{
				"doctype": "Deployment Job",
				"deployment": dep.name,
				"step_name": name,
				"status": "Running",
				"started_at": now_datetime(),
			}
		)
		job.insert(ignore_permissions=True)
		frappe.db.commit()
		try:
			result = fn()
			success = bool(result.get("ok"))
			job.status = "Success" if success else "Failed"
			job.output = redact_text(json.dumps(result, indent=2, default=str)[-8000:])
			job.finished_at = now_datetime()
			job.save(ignore_permissions=True)
			steps_log.append({"step": name, "ok": success, "result": result})
			if not success:
				ok = False
				final_message = result.get("message") or _("Step failed: {0}").format(name)
			return success
		except Exception as exc:
			job.status = "Failed"
			job.output = redact_text(str(exc))
			job.finished_at = now_datetime()
			job.save(ignore_permissions=True)
			steps_log.append({"step": name, "ok": False, "error": str(exc)})
			ok = False
			final_message = str(exc)
			return False

	# 1) Backup
	def do_backup():
		from frappeops.services.operations.runner import _site_backup

		res = _site_backup(site_doc.name)
		if res.get("ok") and res.get("backup"):
			dep.pre_backup = res["backup"]
			dep.save(ignore_permissions=True)
		return res

	if not step("backup", do_backup):
		return _finish(dep, ok=False, message=final_message, steps=steps_log)

	# 2) Migrate (optional)
	if run_migrate:

		def do_migrate():
			from frappeops.services.provisioning.site import migrate_site

			return migrate_site(site_doc.name)

		if not step("migrate", do_migrate):
			return _finish(dep, ok=False, message=final_message, steps=steps_log)
	else:
		_skip_step(dep.name, "migrate")

	# 3) Build (optional — never bench update)
	if run_build:

		def do_build():
			apps = [a.strip() for a in (apps_to_build or "frappeops").split(",") if a.strip()]
			outs = []
			for app in apps:
				proc = run_bench(["build", "--app", app], timeout=900, check=False)
				outs.append({"app": app, "rc": proc.returncode, "out": (proc.stdout or "")[-1500:]})
				if proc.returncode != 0:
					return {
						"ok": False,
						"message": _("bench build failed for {0}").format(app),
						"output": redact_text("\n".join(o["out"] for o in outs)[-2500:]),
					}
			return {"ok": True, "message": _("Build completed"), "apps": apps, "details": outs}

		if not step("build", do_build):
			return _finish(dep, ok=False, message=final_message, steps=steps_log)
	else:
		_skip_step(dep.name, "build")

	# 4) Clear cache
	def do_cache():
		proc = run_bench(["--site", site_doc.site_name, "clear-cache"], timeout=180, check=False)
		return {
			"ok": proc.returncode == 0,
			"message": _("Cache cleared") if proc.returncode == 0 else _("clear-cache failed"),
			"output": redact_text((proc.stdout or "")[-1500:]),
		}

	step("clear_cache", do_cache)

	# 5) Health
	def do_health():
		from frappeops.services.operations.runner import _site_health

		return _site_health(site_doc.name)

	step("health", do_health)

	return _finish(dep, ok=ok, message=final_message if not ok else _("Deployment pipeline completed"), steps=steps_log)


def _skip_step(deployment: str, name: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Deployment Job",
			"deployment": deployment,
			"step_name": name,
			"status": "Skipped",
			"started_at": now_datetime(),
			"finished_at": now_datetime(),
			"output": "Skipped by operator options",
		}
	).insert(ignore_permissions=True)


def _finish(dep, *, ok: bool, message: str, steps: list) -> dict[str, Any]:
	dep.status = "Success" if ok else "Failed"
	dep.finished_at = now_datetime()
	dep.pipeline_log = redact_text(json.dumps(steps, indent=2, default=str)[-12000:])
	dep.notes = (dep.notes or "") + "\n" + message
	dep.save(ignore_permissions=True)
	write_audit(
		"deploy.site_pipeline",
		resource_type="site",
		resource_name=dep.site,
		status="Success" if ok else "Failed",
		message=message,
		parameters={"deployment": dep.name},
		after={"steps": [s.get("step") for s in steps], "pre_backup": dep.pre_backup},
	)
	return {
		"ok": ok,
		"message": message,
		"deployment": dep.name,
		"pre_backup": dep.pre_backup,
		"steps": [{"step": s.get("step"), "ok": s.get("ok")} for s in steps],
	}
