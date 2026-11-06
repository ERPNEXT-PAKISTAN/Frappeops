# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Safe local site provisioning (test sites only)."""

from __future__ import annotations

import json
import os
import re
import secrets
import string
from pathlib import Path
from typing import Any

import frappe
from frappe import _

from frappeops.core.redaction import redact_text
from frappeops.utils.bench_cmd import run_bench

# Disposable test sites only — never production hostnames.
TEST_SITE_RE = re.compile(r"^test-[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?\.local$")
BLOCKED_SITE_NAMES = {
	"ss.frappe.my",
	"frappeops.local",
	"localhost",
	"default",
}


def assert_test_site_name(site_name: str) -> None:
	name = (site_name or "").strip().lower()
	if name in BLOCKED_SITE_NAMES:
		frappe.throw(_("Site name {0} is reserved / protected.").format(site_name))
	if not TEST_SITE_RE.match(name):
		frappe.throw(
			_("Only disposable names matching test-<name>.local are allowed (got {0}).").format(
				site_name
			)
		)


def list_local_apps() -> list[str]:
	apps_dir = Path(frappe.utils.get_bench_path()) / "apps"
	if not apps_dir.is_dir():
		return []
	apps = []
	for child in sorted(apps_dir.iterdir()):
		if not child.is_dir():
			continue
		if (
			(child / "pyproject.toml").exists()
			or (child / "setup.py").exists()
			or (child / child.name).is_dir()
		):
			apps.append(child.name)
	apps_txt = Path(frappe.utils.get_bench_path()) / "sites" / "apps.txt"
	if apps_txt.exists():
		ordered = [line.strip() for line in apps_txt.read_text().splitlines() if line.strip()]
		rest = [a for a in apps if a not in ordered]
		return [a for a in ordered if a in apps] + rest
	return apps


def create_test_site(
	site_name: str,
	*,
	admin_password: str | None = None,
	apps: list[str] | None = None,
	mariadb_root_password: str | None = None,
	bench_name: str | None = None,
) -> dict[str, Any]:
	"""Create a disposable test site with bench new-site (local adapter)."""
	if not frappe.db.get_single_value("FrappeOps Settings", "allow_test_site_create"):
		frappe.throw(_("Test site creation is disabled in FrappeOps Settings."))

	assert_test_site_name(site_name)
	site_name = site_name.strip().lower()

	bench_path = Path(frappe.utils.get_bench_path())
	site_dir = bench_path / "sites" / site_name
	if site_dir.exists():
		frappe.throw(_("Site directory already exists: {0}").format(site_name))

	if frappe.db.exists("Site", {"site_name": site_name}):
		frappe.throw(_("Site record already exists for {0}").format(site_name))

	admin_password = admin_password or _generate_password()
	root_password = mariadb_root_password or _settings_db_root_password()
	if not root_password:
		frappe.throw(
			_(
				"MariaDB root password required. Set it in FrappeOps Settings or pass it once in the create dialog."
			)
		)

	install_apps = []
	for app in apps or []:
		app = (app or "").strip()
		if not app or app == "frappe":
			continue
		if app not in list_local_apps():
			frappe.throw(_("App {0} is not present under apps/.").format(app))
		install_apps.append(app)

	args = [
		"new-site",
		site_name,
		"--admin-password",
		admin_password,
		"--mariadb-root-password",
		root_password,
		"--db-root-username",
		"root",
		"--mariadb-user-host-login-scope=%",
	]

	try:
		proc = run_bench(args, timeout=1200, check=False)
	except Exception as exc:
		return {"ok": False, "message": _("new-site failed to start"), "error": redact_text(str(exc))}

	if proc.returncode != 0:
		return {
			"ok": False,
			"message": _("bench new-site failed for {0}").format(site_name),
			"output": redact_text((proc.stdout or "")[-3000:]),
		}

	outputs = [proc.stdout or ""]
	for app in install_apps:
		inst = run_bench(["--site", site_name, "install-app", app], timeout=1200, check=False)
		outputs.append(inst.stdout or "")
		if inst.returncode != 0:
			return {
				"ok": False,
				"message": _("Site created but install-app {0} failed").format(app),
				"site_name": site_name,
				"output": redact_text("\n".join(outputs)[-3000:]),
			}

	# Mark developer mode for test sites
	run_bench(["--site", site_name, "set-config", "developer_mode", "1"], timeout=60, check=False)

	# Soften directory perms so nginx can resolve site path (same issue as frappeops.local)
	try:
		os.chmod(site_dir, 0o755)
	except Exception:
		pass

	nginx_hint = _write_nginx_snippet(site_name)
	hosts_hint = _ensure_hosts_entry(site_name)

	# Re-import inventory
	from frappeops.services.discovery.local import import_local_server

	import_local_server()
	site_doc_name = frappe.db.get_value("Site", {"site_name": site_name}, "name")

	# Ensure test site is not accidentally protected
	if site_doc_name:
		frappe.db.set_value("Site", site_doc_name, {"is_protected": 0, "environment": "Test"})

	return {
		"ok": True,
		"message": _("Created test site {0}").format(site_name),
		"site_name": site_name,
		"site": site_doc_name,
		"installed_apps": ["frappe", *install_apps],
		"nginx": nginx_hint,
		"hosts": hosts_hint,
		"output": redact_text("\n".join(outputs)[-2500:]),
		# Admin password returned once to the operator UI; never audited as-is (caller redacts)
		"admin_password": admin_password,
	}


def install_app_on_site(site_doc_name: str, app_name: str) -> dict[str, Any]:
	site = frappe.get_doc("Site", site_doc_name)
	if site.is_protected:
		frappe.throw(_("Refused: protected site cannot install apps via FrappeOps."))
	app_name = (app_name or "").strip()
	if app_name not in list_local_apps():
		frappe.throw(_("App {0} is not present under apps/.").format(app_name))

	proc = run_bench(["--site", site.site_name, "install-app", app_name], timeout=1200, check=False)
	if proc.returncode != 0:
		return {
			"ok": False,
			"message": _("install-app failed for {0} on {1}").format(app_name, site.site_name),
			"output": redact_text((proc.stdout or "")[-2500:]),
		}

	# Refresh installed apps string on Site
	apps_proc = run_bench(["--site", site.site_name, "list-apps", "--format", "json"], timeout=120, check=False)
	installed = []
	try:
		installed = [a.get("app") or a.get("name") for a in json.loads(apps_proc.stdout or "[]")]
		installed = [a for a in installed if a]
	except Exception:
		installed = [x for x in (site.installed_apps or "").split(",") if x.strip()]
		if app_name not in installed:
			installed.append(app_name)
	site.installed_apps = ", ".join(installed)
	site.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Installed {0} on {1}").format(app_name, site.site_name),
		"installed_apps": installed,
		"output": redact_text((proc.stdout or "")[-2000:]),
	}


def migrate_site(site_doc_name: str) -> dict[str, Any]:
	site = frappe.get_doc("Site", site_doc_name)
	if site.is_protected:
		frappe.throw(_("Refused: migrate is blocked on protected sites."))
	proc = run_bench(["--site", site.site_name, "migrate"], timeout=1800, check=False)
	if proc.returncode != 0:
		return {
			"ok": False,
			"message": _("Migrate failed for {0}").format(site.site_name),
			"output": redact_text((proc.stdout or "")[-3000:]),
		}
	return {
		"ok": True,
		"message": _("Migrate completed for {0}").format(site.site_name),
		"output": redact_text((proc.stdout or "")[-2000:]),
	}


def _settings_db_root_password() -> str | None:
	try:
		doc = frappe.get_single("FrappeOps Settings")
		pwd = doc.get_password("mariadb_root_password", raise_exception=False)
		return pwd or None
	except Exception:
		return None


def _generate_password(length: int = 16) -> str:
	alphabet = string.ascii_letters + string.digits
	return "".join(secrets.choice(alphabet) for _ in range(length))


def _write_nginx_snippet(site_name: str) -> dict[str, Any]:
	"""Write FrappeOps-owned nginx server block (requires sudo write)."""
	conf = f"""# Managed by FrappeOps — test site {site_name}
upstream frappeops_{site_name.replace('.', '_').replace('-', '_')}_frappe {{
	server 127.0.0.1:8000 fail_timeout=0;
}}
upstream frappeops_{site_name.replace('.', '_').replace('-', '_')}_socketio {{
	server 127.0.0.1:9000 fail_timeout=0;
}}
server {{
	listen 80;
	listen [::]:80;
	server_name {site_name};
	root /home/frappe/frappe-bench/sites;
	location /assets {{
		try_files $uri =404;
	}}
	location / {{
		proxy_set_header X-Frappe-Site-Name {site_name};
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_pass http://127.0.0.1:8000;
	}}
}}
"""
	path = Path(f"/etc/nginx/conf.d/frappeops-{site_name}.conf")
	try:
		# Prefer writing via temp + sudo tee when not root
		tmp = Path(f"/tmp/frappeops-{site_name}.conf")
		tmp.write_text(conf)
		import subprocess

		r = subprocess.run(
			["sudo", "-n", "cp", str(tmp), str(path)],
			capture_output=True,
			text=True,
		)
		if r.returncode != 0:
			return {
				"written": False,
				"path": str(path),
				"message": _("Could not write nginx conf (sudo required). Snippet saved to {0}").format(
					tmp
				),
				"tmp": str(tmp),
			}
		test = subprocess.run(["sudo", "-n", "nginx", "-t"], capture_output=True, text=True)
		if test.returncode == 0:
			subprocess.run(["sudo", "-n", "systemctl", "reload", "nginx"], capture_output=True, text=True)
			return {"written": True, "path": str(path), "reloaded": True}
		return {
			"written": True,
			"path": str(path),
			"reloaded": False,
			"message": redact_text((test.stderr or test.stdout or "")[-500:]),
		}
	except Exception as exc:
		return {"written": False, "message": redact_text(str(exc))}


def _ensure_hosts_entry(site_name: str) -> dict[str, Any]:
	line = f"127.0.0.1\t{site_name}"
	try:
		hosts = Path("/etc/hosts").read_text()
		if site_name in hosts:
			return {"ok": True, "message": _("Already in /etc/hosts")}
		import subprocess

		r = subprocess.run(
			["sudo", "-n", "bash", "-c", f"echo '{line}' >> /etc/hosts"],
			capture_output=True,
			text=True,
		)
		if r.returncode == 0:
			return {"ok": True, "message": _("Added to /etc/hosts")}
		return {
			"ok": False,
			"message": _("Add manually to /etc/hosts: {0}").format(line),
		}
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc))}
