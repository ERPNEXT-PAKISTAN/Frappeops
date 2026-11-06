# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Bench-level diagnostics and gated supervisor restart."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import frappe
from frappe import _

from frappeops.core.redaction import redact_text
from frappeops.utils.bench_cmd import run_bench


RESTART_PHRASE = "RESTART"
SAFE_SUPERVISOR_GROUPS = (
	"frappe-bench-web:",
	"frappe-bench-workers:",
)


def list_versions(bench_name: str | None = None) -> dict[str, Any]:
	"""Inventory Frappe/ERPNext/app versions from the bench tree (read-only)."""
	bench = _resolve_bench(bench_name)
	path = Path(bench.bench_path or frappe.utils.get_bench_path())
	apps_dir = path / "apps"
	versions = []
	if apps_dir.is_dir():
		for app_path in sorted(apps_dir.iterdir()):
			if not app_path.is_dir():
				continue
			ver = _read_app_version(app_path)
			branch = _read_git_branch(app_path)
			versions.append(
				{
					"app": app_path.name,
					"version": ver,
					"branch": branch,
					"path": str(app_path),
				}
			)

	# Sync key fields onto Bench record
	frappe_v = next((v["version"] for v in versions if v["app"] == "frappe"), None)
	if frappe_v:
		frappe.db.set_value("Bench", bench.name, "frappe_version", frappe_v, update_modified=False)

	return {
		"ok": True,
		"message": _("Bench versions inventoried ({0} apps)").format(len(versions)),
		"bench": bench.name,
		"bench_path": str(path),
		"versions": versions,
	}


def build_assets(
	bench_name: str | None,
	*,
	apps: list[str] | None = None,
	confirm: bool = False,
) -> dict[str, Any]:
	"""Run `bench build` for selected apps (or frappeops only by default)."""
	if not confirm:
		return {
			"ok": False,
			"message": _("Confirm required for bench build (CPU/memory intensive on shared host)."),
		}

	bench = _resolve_bench(bench_name)
	path = Path(bench.bench_path or frappe.utils.get_bench_path())
	app_list = [a.strip() for a in (apps or ["frappeops"]) if str(a).strip()]
	if not app_list:
		return {"ok": False, "message": _("At least one app name required")}

	# Never allow shell-like wildcards
	for app in app_list:
		if not app.replace("_", "").replace("-", "").isalnum():
			return {"ok": False, "message": _("Invalid app name: {0}").format(app)}
		if not (path / "apps" / app).is_dir():
			return {"ok": False, "message": _("App not present under apps/: {0}").format(app)}

	outputs = []
	ok = True
	for app in app_list:
		try:
			proc = run_bench(["build", "--app", app], cwd=str(path), timeout=600, check=False)
		except Exception as exc:
			ok = False
			outputs.append({"app": app, "ok": False, "output": redact_text(str(exc))})
			continue
		text = redact_text((proc.stdout or "")[-4000:])
		app_ok = proc.returncode == 0
		ok = ok and app_ok
		outputs.append({"app": app, "ok": app_ok, "returncode": proc.returncode, "output": text})

	return {
		"ok": ok,
		"message": _("Bench build finished") if ok else _("Bench build had failures"),
		"bench": bench.name,
		"apps": app_list,
		"results": outputs,
	}


def _read_app_version(app_path: Path) -> str | None:
	init = app_path / app_path.name / "__init__.py"
	if not init.exists():
		# some apps nest differently
		candidates = list(app_path.glob("*/__init__.py"))
		init = candidates[0] if candidates else None
	if not init or not init.exists():
		return None
	try:
		text = init.read_text(encoding="utf-8", errors="ignore")
	except Exception:
		return None
	import re

	m = re.search(r"""__version__\s*=\s*['\"]([^'\"]+)['\"]""", text)
	return m.group(1) if m else None


def _read_git_branch(app_path: Path) -> str | None:
	head = app_path / ".git" / "HEAD"
	if not head.exists():
		return None
	try:
		raw = head.read_text(encoding="utf-8").strip()
	except Exception:
		return None
	if raw.startswith("ref: refs/heads/"):
		return raw.split("/")[-1]
	return raw[:12]


def run_doctor(bench_name: str | None) -> dict[str, Any]:
	"""Run `bench doctor` for background worker / scheduler diagnostics."""
	bench = _resolve_bench(bench_name)
	path = Path(bench.bench_path or frappe.utils.get_bench_path())
	if not path.is_dir():
		return {"ok": False, "message": _("Bench path missing: {0}").format(path)}

	try:
		proc = run_bench(["doctor"], cwd=str(path), timeout=120, check=False)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc))}

	output = redact_text((proc.stdout or "")[-8000:])
	ok = proc.returncode == 0
	sites = frappe.get_all(
		"Site",
		filters={"bench": bench.name},
		fields=["name", "site_name", "is_protected"],
	)
	return {
		"ok": ok,
		"message": _("Bench doctor finished") if ok else _("Bench doctor reported issues"),
		"bench": bench.name,
		"bench_path": str(path),
		"returncode": proc.returncode,
		"output": output,
		"sites_on_bench": len(sites),
		"protected_sites": [s.site_name for s in sites if s.is_protected],
	}


def restart_bench(
	bench_name: str | None,
	*,
	confirm: bool = False,
	typed_confirmation: str | None = None,
	dry_run: bool = False,
	scope: str = "web_workers",
) -> dict[str, Any]:
	"""Restart Supervisor web/worker groups for this bench (shared host — gated)."""
	bench = _resolve_bench(bench_name)
	path = Path(bench.bench_path or frappe.utils.get_bench_path())

	if not frappe.db.get_single_value("FrappeOps Settings", "allow_bench_restart"):
		return {
			"ok": False,
			"message": _(
				"Bench restart disabled. Enable Allow Bench Restart in FrappeOps Settings "
				"(affects all sites on this shared Supervisor group, including protected ones)."
			),
		}

	if not confirm:
		return {
			"ok": False,
			"message": _("Confirm required. Bench restart briefly interrupts all sites on this host."),
		}

	if (typed_confirmation or "").strip() != RESTART_PHRASE:
		return {
			"ok": False,
			"message": _("Type {0} to confirm bench restart.").format(RESTART_PHRASE),
		}

	sites = frappe.get_all(
		"Site",
		filters={"bench": bench.name},
		fields=["site_name", "is_protected"],
	)
	protected = [s.site_name for s in sites if s.is_protected]
	groups = _groups_for_scope(scope)

	plan = {
		"bench": bench.name,
		"bench_path": str(path),
		"groups": list(groups),
		"sites": [s.site_name for s in sites],
		"protected_sites": protected,
		"warning": _(
			"Shared Supervisor restart will briefly interrupt every site on this bench, "
			"including protected production sites."
		),
	}

	if dry_run:
		return {
			"ok": True,
			"dry_run": True,
			"message": _("Dry run OK — would restart: {0}").format(", ".join(groups)),
			**plan,
		}

	# Prefer passwordless sudo supervisorctl; fall back to bench restart.
	result = _supervisor_restart(groups)
	if not result["ok"]:
		result = _bench_restart(str(path))

	result.update(plan)
	if result.get("ok"):
		result["message"] = _("Bench restart requested: {0}").format(", ".join(groups))
	return result


def _groups_for_scope(scope: str) -> tuple[str, ...]:
	scope = (scope or "web_workers").strip().lower()
	if scope == "web":
		return ("frappe-bench-web:",)
	if scope == "workers":
		return ("frappe-bench-workers:",)
	return SAFE_SUPERVISOR_GROUPS


def _supervisor_restart(groups: tuple[str, ...]) -> dict[str, Any]:
	cmd = ["sudo", "-n", "supervisorctl", "restart", *groups]
	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc)), "method": "supervisorctl"}

	out = redact_text(((proc.stdout or "") + (proc.stderr or ""))[-4000:])
	if proc.returncode != 0:
		return {
			"ok": False,
			"message": _("supervisorctl restart failed (passwordless sudo may be required): {0}").format(
				out or proc.returncode
			),
			"method": "supervisorctl",
			"output": out,
		}
	return {"ok": True, "method": "supervisorctl", "output": out}


def _bench_restart(cwd: str) -> dict[str, Any]:
	try:
		proc = run_bench(["restart"], cwd=cwd, timeout=180, check=False)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc)), "method": "bench restart"}

	out = redact_text((proc.stdout or "")[-4000:])
	ok = proc.returncode == 0
	return {
		"ok": ok,
		"message": _("bench restart completed") if ok else _("bench restart failed"),
		"method": "bench restart",
		"output": out,
		"returncode": proc.returncode,
	}


def _resolve_bench(bench_name: str | None):
	name = bench_name
	if not name:
		local_server = frappe.db.get_value("Server", {"is_local": 1}, "name")
		if local_server:
			name = frappe.db.get_value("Bench", {"server": local_server}, "name")
		if not name:
			name = frappe.db.get_value("Bench", {}, "name", order_by="creation asc")
	if not name:
		frappe.throw(_("No Bench inventory record. Run Scan / Discover first."))
	return frappe.get_doc("Bench", name)
