# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""App marketplace catalog + safe bench get-app."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import frappe
from frappe import _

from frappeops.core.redaction import redact_text
from frappeops.utils.bench_cmd import run_bench

SAFE_APP_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
SAFE_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/-]{1,120}$")

# Curated seed list — HTTPS only. Operators can add more via App Catalog Item.
CATALOG_SEED: list[dict[str, Any]] = [
	{
		"app_name": "erpnext",
		"title": "ERPNext",
		"git_url": "https://github.com/frappe/erpnext",
		"default_branch": "version-16",
		"category": "Official",
		"publisher": "Frappe",
		"featured": 1,
		"homepage": "https://erpnext.com",
		"description": "Open source ERP on Frappe.",
	},
	{
		"app_name": "hrms",
		"title": "HRMS",
		"git_url": "https://github.com/frappe/hrms",
		"default_branch": "version-16",
		"category": "HR",
		"publisher": "Frappe",
		"featured": 1,
		"homepage": "https://frappe.io/hr",
		"description": "Human resources management.",
	},
	{
		"app_name": "payments",
		"title": "Payments",
		"git_url": "https://github.com/frappe/payments",
		"default_branch": "version-16",
		"category": "Accounting",
		"publisher": "Frappe",
		"featured": 1,
		"description": "Payment gateway integrations.",
	},
	{
		"app_name": "insights",
		"title": "Insights",
		"git_url": "https://github.com/frappe/insights",
		"default_branch": "develop",
		"category": "Reporting",
		"publisher": "Frappe",
		"featured": 1,
		"description": "Open source business intelligence.",
	},
	{
		"app_name": "crm",
		"title": "Frappe CRM",
		"git_url": "https://github.com/frappe/crm",
		"default_branch": "main",
		"category": "CRM",
		"publisher": "Frappe",
		"featured": 1,
		"description": "Simple, modern open source CRM.",
	},
	{
		"app_name": "helpdesk",
		"title": "Helpdesk",
		"git_url": "https://github.com/frappe/helpdesk",
		"default_branch": "main",
		"category": "CRM",
		"publisher": "Frappe",
		"featured": 0,
		"description": "Customer support / ticketing.",
	},
	{
		"app_name": "wiki",
		"title": "Wiki",
		"git_url": "https://github.com/frappe/wiki",
		"default_branch": "master",
		"category": "Utility",
		"publisher": "Frappe",
		"featured": 0,
		"description": "Wiki app for Frappe.",
	},
	{
		"app_name": "builder",
		"title": "Builder",
		"git_url": "https://github.com/frappe/builder",
		"default_branch": "master",
		"category": "Utility",
		"publisher": "Frappe",
		"featured": 0,
		"description": "Low-code website builder.",
	},
	{
		"app_name": "telephony",
		"title": "Telephony",
		"git_url": "https://github.com/frappe/telephony",
		"default_branch": "develop",
		"category": "Integration",
		"publisher": "Frappe",
		"featured": 0,
		"description": "Telephony integrations.",
	},
	{
		"app_name": "print_designer",
		"title": "Print Designer",
		"git_url": "https://github.com/frappe/print_designer",
		"default_branch": "develop",
		"category": "Utility",
		"publisher": "Frappe",
		"featured": 0,
		"description": "Visual print format designer.",
	},
]


def seed_catalog(*, overwrite: bool = False) -> dict[str, Any]:
	"""Insert curated marketplace rows (idempotent unless overwrite)."""
	created = []
	updated = []
	for row in CATALOG_SEED:
		name = row["app_name"]
		if frappe.db.exists("App Catalog Item", name):
			if not overwrite:
				continue
			doc = frappe.get_doc("App Catalog Item", name)
			for k, v in row.items():
				setattr(doc, k, v)
			doc.enabled = 1
			doc.save(ignore_permissions=True)
			updated.append(name)
		else:
			doc = frappe.get_doc({"doctype": "App Catalog Item", "enabled": 1, **row})
			doc.insert(ignore_permissions=True)
			created.append(name)
	frappe.db.commit()
	return {
		"ok": True,
		"message": _("Catalog seed: {0} created, {1} updated").format(len(created), len(updated)),
		"created": created,
		"updated": updated,
		"total": frappe.db.count("App Catalog Item"),
	}


def list_catalog(*, enabled_only: bool = True) -> dict[str, Any]:
	filters = {"enabled": 1} if enabled_only else {}
	rows = frappe.get_all(
		"App Catalog Item",
		filters=filters,
		fields=[
			"name",
			"app_name",
			"title",
			"git_url",
			"default_branch",
			"category",
			"publisher",
			"featured",
			"description",
			"homepage",
			"enabled",
		],
		order_by="featured desc, title asc",
		limit_page_length=200,
	)
	bench_apps = _apps_on_disk()
	for r in rows:
		r["on_disk"] = r["app_name"] in bench_apps
	return {"ok": True, "apps": rows, "on_disk": sorted(bench_apps)}


def get_app_from_git(
	*,
	git_url: str | None = None,
	app_name: str | None = None,
	branch: str | None = None,
	catalog_item: str | None = None,
	confirm: bool = False,
) -> dict[str, Any]:
	"""Clone app into bench via `bench get-app` (HTTPS git only)."""
	if not confirm:
		return {
			"ok": False,
			"status": "blocked",
			"message": _("Set confirm=1 to run bench get-app (downloads code into apps/)."),
			"needs": ["confirm"],
		}

	if catalog_item and frappe.db.exists("App Catalog Item", catalog_item):
		item = frappe.get_doc("App Catalog Item", catalog_item)
		git_url = git_url or item.git_url
		app_name = app_name or item.app_name
		branch = branch or item.default_branch

	git_url = (git_url or "").strip()
	app_name = (app_name or "").strip()
	branch = (branch or "").strip() or None

	safe = validate_git_url(git_url)
	if not safe.get("ok"):
		return safe

	if app_name and not SAFE_APP_RE.match(app_name):
		return {"ok": False, "message": _("Invalid app_name")}
	if branch and not SAFE_BRANCH_RE.match(branch):
		return {"ok": False, "message": _("Invalid branch")}

	# Derive app name from URL if missing
	if not app_name:
		app_name = Path(urlparse(git_url).path).stem.replace(".git", "")
		if not SAFE_APP_RE.match(app_name):
			return {"ok": False, "message": _("Could not derive safe app_name from URL")}

	apps_dir = Path(frappe.utils.get_bench_path()) / "apps" / app_name
	if apps_dir.exists():
		return {
			"ok": True,
			"message": _("App {0} already present under apps/ — skip get-app").format(app_name),
			"app_name": app_name,
			"already_present": True,
			"path": str(apps_dir),
		}

	args = ["get-app"]
	if branch:
		args.extend(["--branch", branch])
	args.append(git_url)
	# pin folder name when bench supports it
	args.append(app_name)

	proc = run_bench(args, timeout=1800, check=False)
	out = (proc.stdout or "") + "\n" + (proc.stderr or "")
	if proc.returncode != 0:
		# Retry without explicit app name (older bench)
		args2 = ["get-app"]
		if branch:
			args2.extend(["--branch", branch])
		args2.append(git_url)
		proc = run_bench(args2, timeout=1800, check=False)
		out = (proc.stdout or "") + "\n" + (proc.stderr or "")
		if proc.returncode != 0:
			return {
				"ok": False,
				"message": _("bench get-app failed for {0}").format(app_name),
				"output": redact_text(out[-2500:]),
			}

	_upsert_managed_app(app_name, git_url=git_url, branch=branch, source="Catalog" if catalog_item else "GitHub")

	return {
		"ok": True,
		"message": _("Fetched app {0} into bench").format(app_name),
		"app_name": app_name,
		"git_url": git_url,
		"branch": branch,
		"output": redact_text(out[-2000:]),
		"next": _("Use app.install on a non-protected site to install it."),
	}


def validate_git_url(url: str) -> dict[str, Any]:
	url = (url or "").strip()
	if not url:
		return {"ok": False, "message": _("git_url is required")}
	parsed = urlparse(url)
	if parsed.scheme != "https":
		return {"ok": False, "message": _("Only https:// git URLs are allowed")}
	if not parsed.netloc or not parsed.path:
		return {"ok": False, "message": _("Invalid git URL")}
	if "@" in parsed.netloc:
		return {"ok": False, "message": _("Credentials in URL are not allowed")}
	# Block obvious shell metacharacters
	if any(c in url for c in (";", "|", "&", "`", "$", "\n", "\r")):
		return {"ok": False, "message": _("git URL contains disallowed characters")}
	return {"ok": True, "url": url}


def _apps_on_disk() -> set[str]:
	apps_dir = Path(frappe.utils.get_bench_path()) / "apps"
	if not apps_dir.is_dir():
		return set()
	return {p.name for p in apps_dir.iterdir() if p.is_dir() and not p.name.startswith(".")}


def _upsert_managed_app(app_name: str, *, git_url: str, branch: str | None, source: str) -> None:
	server = frappe.db.get_value("Server", {"is_local": 1}, "name")
	bench = frappe.db.get_value("Bench", {"server": server}, "name") if server else None
	if not bench:
		bench = frappe.db.get_value("Bench", {}, "name")
	if not bench:
		return
	existing = frappe.db.get_value("Managed App", {"app_name": app_name, "bench": bench}, "name")
	payload = {
		"app_name": app_name,
		"bench": bench,
		"server": server,
		"git_url": git_url,
		"branch": branch,
		"source": source,
		"installed_state": "Present",
		"repository": git_url,
	}
	if existing:
		doc = frappe.get_doc("Managed App", existing)
		for k, v in payload.items():
			setattr(doc, k, v)
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": "Managed App", **payload}).insert(ignore_permissions=True)
	frappe.db.commit()
