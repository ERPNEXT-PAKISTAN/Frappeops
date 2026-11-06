# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""FrappeOps-owned nginx snippet management (never edits frappe-bench.conf)."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.redaction import redact_text

LIVE_DIR = Path("/etc/nginx/conf.d")
FORBIDDEN_LIVE_FILES = {
	"frappe-bench.conf",
	"frappe-bench.conf.bak",
	"default",
	"default.conf",
}
SAFE_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,80}[a-z0-9])?$")


def draft_dir() -> Path:
	path = Path(frappe.utils.get_bench_path()) / "config" / "frappeops-nginx"
	path.mkdir(parents=True, exist_ok=True)
	return path


def conf_filename(domain_name: str) -> str:
	safe = domain_name.strip().lower().replace("/", "")
	if not SAFE_NAME_RE.match(safe):
		frappe.throw(_("Invalid domain name: {0}").format(domain_name))
	return f"frappeops-{safe}.conf"


def live_candidates(domain_name: str) -> list[Path]:
	"""Preferred new name first; legacy frappeops.local.conf style second."""
	safe = domain_name.strip().lower()
	return [
		LIVE_DIR / conf_filename(safe),
		LIVE_DIR / f"{safe}.conf",  # e.g. frappeops.local.conf
	]


def live_path(domain_name: str) -> Path:
	"""Resolve existing FrappeOps-owned conf, else preferred new filename."""
	for path in live_candidates(domain_name):
		if path.exists() and _is_safe_live_filename(path.name):
			return path
	return live_candidates(domain_name)[0]


def draft_path(domain_name: str) -> Path:
	return draft_dir() / conf_filename(domain_name)


def _is_safe_live_filename(name: str) -> bool:
	if name in FORBIDDEN_LIVE_FILES or name.endswith(".bak"):
		return False
	return name.startswith("frappeops") and name.endswith(".conf")


def assert_nginx_site_allowed(site_doc) -> None:
	"""Nginx apply is blocked for protected / production sites."""
	if site_doc.is_protected:
		frappe.throw(
			_("Refused: nginx changes are blocked for protected site {0}.").format(site_doc.site_name),
			title=_("Protected Site"),
		)
	if (site_doc.site_name or "").lower() == "ss.frappe.my":
		frappe.throw(_("Refused: ss.frappe.my is never managed by FrappeOps nginx snippets."))


def render_http_server_block(domain_name: str, site_name: str, web_port: int = 8000, socketio_port: int = 9000) -> str:
	"""Generate a Frappe-compatible HTTP vhost (HTTP only for Wave C)."""
	slug = re.sub(r"[^a-z0-9]+", "_", domain_name.lower()).strip("_")
	bench_sites = str(Path(frappe.utils.get_bench_path()) / "sites")
	return f"""# Managed by FrappeOps — do not hand-edit for long; regenerate from Domain {domain_name}
# Target site: {site_name}
# This file is owned by FrappeOps. Never merge into frappe-bench.conf blindly.

upstream frappeops_{slug}_frappe {{
	server 127.0.0.1:{web_port} fail_timeout=0;
}}

upstream frappeops_{slug}_socketio {{
	server 127.0.0.1:{socketio_port} fail_timeout=0;
}}

server {{
	listen 80;
	listen [::]:80;
	server_name {domain_name};

	root {bench_sites};

	proxy_buffer_size 128k;
	proxy_buffers 4 256k;
	proxy_busy_buffers_size 256k;

	location /assets {{
		try_files $uri =404;
		add_header Cache-Control "max-age=31536000";
	}}

	location ~ ^/protected/(.*) {{
		internal;
		try_files /{site_name}/$1 =404;
	}}

	location /socket.io {{
		proxy_http_version 1.1;
		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";
		proxy_set_header X-Frappe-Site-Name {site_name};
		proxy_set_header Origin $scheme://$http_host;
		proxy_set_header Host $host;
		proxy_pass http://frappeops_{slug}_socketio;
	}}

	location / {{
		rewrite ^(.+)/$ $1 permanent;
		rewrite ^(.+)/index\\.html$ $1 permanent;
		rewrite ^(.+)\\.html$ $1 permanent;

		location ~* ^/files/.*.(htm|html|svg|xml) {{
			add_header Content-disposition "attachment";
			try_files /{site_name}/public/$uri @webserver;
		}}

		try_files /{site_name}/public/$uri @webserver;
	}}

	location @webserver {{
		proxy_set_header X-Forwarded-For $remote_addr;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_set_header X-Frappe-Site-Name {site_name};
		proxy_set_header Host $host;
		proxy_pass http://frappeops_{slug}_frappe;
	}}
}}
"""


def ensure_domain(domain_name: str, site: str, domain_type: str = "Primary") -> str:
	"""Create or update a Domain document linked to a Site."""
	domain_name = (domain_name or "").strip().lower()
	if not SAFE_NAME_RE.match(domain_name):
		frappe.throw(_("Invalid domain name: {0}").format(domain_name))

	site_doc = frappe.get_doc("Site", site)
	name = frappe.db.exists("Domain", domain_name)
	if name:
		doc = frappe.get_doc("Domain", name)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Domain",
				"domain_name": domain_name,
				"site": site_doc.name,
				"server": site_doc.server,
				"domain_type": domain_type,
				"protocol": "HTTP",
				"port": 80,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	doc.site = site_doc.name
	doc.server = site_doc.server
	doc.domain_type = domain_type or doc.domain_type
	doc.save(ignore_permissions=True)
	return doc.name


def generate_nginx(domain_name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Domain", domain_name)
	site = frappe.get_doc("Site", doc.site)
	assert_nginx_site_allowed(site)

	common = {}
	try:
		import json

		raw = (Path(frappe.utils.get_bench_path()) / "sites" / "common_site_config.json").read_text()
		common = json.loads(raw)
	except Exception:
		common = {}

	conf = render_http_server_block(
		doc.domain_name,
		site.site_name,
		web_port=int(common.get("webserver_port") or 8000),
		socketio_port=int(common.get("socketio_port") or 9000),
	)
	path = draft_path(doc.domain_name)
	path.write_text(conf)

	doc.nginx_conf_path = str(path)
	doc.nginx_draft = conf
	doc.apply_status = "Ready"
	doc.nginx_status = "Missing" if not live_path(doc.domain_name).exists() else doc.nginx_status
	doc.last_diff = _diff_text(_read_live(doc.domain_name), conf)
	doc.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Nginx draft generated for {0}").format(doc.domain_name),
		"domain": doc.name,
		"draft_path": str(path),
		"live_path": str(live_path(doc.domain_name)),
		"diff": doc.last_diff,
	}


def diff_nginx(domain_name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Domain", domain_name)
	draft = doc.nginx_draft or (draft_path(doc.domain_name).read_text() if draft_path(doc.domain_name).exists() else "")
	live = _read_live(doc.domain_name)
	diff = _diff_text(live, draft)
	doc.last_diff = diff
	doc.nginx_live_preview = live or ""
	doc.save(ignore_permissions=True)
	return {
		"ok": True,
		"message": _("Diff ready for {0}").format(doc.domain_name),
		"diff": diff,
		"has_changes": bool(diff.strip()),
		"live_exists": bool(live),
	}


def apply_nginx(domain_name: str, *, confirm: bool = False) -> dict[str, Any]:
	"""Copy FrappeOps draft into /etc/nginx/conf.d/frappeops-*.conf after nginx -t."""
	if not confirm:
		return {
			"ok": False,
			"message": _("Set confirm=1 to apply nginx changes after reviewing the diff."),
			"needs_confirm": True,
		}

	doc = frappe.get_doc("Domain", domain_name)
	site = frappe.get_doc("Site", doc.site)
	assert_nginx_site_allowed(site)

	dest = live_path(doc.domain_name)
	filename = dest.name
	if not _is_safe_live_filename(filename):
		frappe.throw(_("Refused: unsafe nginx target filename {0}").format(filename))

	draft = doc.nginx_draft
	if not draft:
		gen = generate_nginx(doc.name)
		if not gen.get("ok"):
			return gen
		doc.reload()
		draft = doc.nginx_draft

	# Stage under /tmp then install with root-friendly tools
	tmp = Path(f"/tmp/{filename}")
	tmp.write_text(draft)

	# Prefer direct write when process can write; else sudo -n
	copied = False
	copy_msg = ""
	try:
		if os.access(str(LIVE_DIR), os.W_OK):
			shutil.copyfile(tmp, dest)
			copied = True
			copy_msg = _("Wrote {0}").format(dest)
		else:
			r = subprocess.run(
				["sudo", "-n", "cp", str(tmp), str(dest)],
				capture_output=True,
				text=True,
			)
			if r.returncode == 0:
				copied = True
				copy_msg = _("Installed via sudo: {0}").format(dest)
			else:
				copy_msg = redact_text((r.stderr or r.stdout or "sudo cp failed")[-500:])
	except Exception as exc:
		copy_msg = redact_text(str(exc))

	if not copied:
		doc.apply_status = "Failed"
		doc.nginx_status = "Error"
		doc.notes = (doc.notes or "") + f"\nApply failed: draft at {tmp}"
		doc.save(ignore_permissions=True)
		return {
			"ok": False,
			"message": _("Could not write nginx conf. Draft left at {0}. {1}").format(tmp, copy_msg),
			"draft_tmp": str(tmp),
			"dest": str(dest),
		}

	test = _nginx_test()
	if not test["ok"]:
		# leave file in place but mark failed — operator must fix; do not touch frappe-bench.conf
		doc.apply_status = "Failed"
		doc.nginx_status = "Error"
		doc.notes = (doc.notes or "") + "\n" + test.get("message", "")
		doc.save(ignore_permissions=True)
		return {
			"ok": False,
			"message": _("nginx -t failed; conf written but not reloaded"),
			"nginx_test": test,
		}

	reload = _nginx_reload()
	doc.apply_status = "Applied" if reload.get("ok") else "Failed"
	doc.nginx_status = "Configured" if reload.get("ok") else "Error"
	doc.last_applied_at = now_datetime()
	doc.nginx_live_preview = _read_live(doc.domain_name)
	doc.last_diff = _diff_text(doc.nginx_live_preview, draft)
	doc.save(ignore_permissions=True)

	# Best-effort hosts entry for *.local
	hosts = _ensure_hosts(doc.domain_name) if doc.domain_name.endswith(".local") else {"ok": True, "skipped": True}

	return {
		"ok": bool(reload.get("ok")),
		"message": _("Nginx applied for {0}").format(doc.domain_name)
		if reload.get("ok")
		else _("Nginx written but reload failed"),
		"live_path": str(dest),
		"nginx_test": test,
		"reload": reload,
		"hosts": hosts,
	}


def check_dns(domain_name: str) -> dict[str, Any]:
	import socket

	doc = frappe.get_doc("Domain", domain_name)
	host = doc.domain_name
	results = {"A": [], "AAAA": []}
	try:
		for info in socket.getaddrinfo(host, None):
			family = info[0]
			sockaddr = info[4]
			ip = sockaddr[0]
			if family == socket.AF_INET and ip not in results["A"]:
				results["A"].append(ip)
			elif family == socket.AF_INET6 and ip not in results["AAAA"]:
				results["AAAA"].append(ip)
		status = "Valid" if results["A"] or results["AAAA"] else "Invalid"
	except Exception as exc:
		status = "Invalid"
		results["error"] = redact_text(str(exc))

	# Local hosts file hint
	hosts_hit = False
	try:
		hosts_hit = host in Path("/etc/hosts").read_text()
	except Exception:
		hosts_hit = False

	doc.dns_status = status
	doc.save(ignore_permissions=True)
	return {
		"ok": status == "Valid",
		"message": _("DNS {0} for {1}").format(status, host),
		"status": status,
		"records": results,
		"in_etc_hosts": hosts_hit,
	}


def check_http(domain_name: str) -> dict[str, Any]:
	import urllib.request

	doc = frappe.get_doc("Domain", domain_name)
	site = frappe.get_doc("Site", doc.site)
	try:
		req = urllib.request.Request(
			"http://127.0.0.1/api/method/frappe.ping",
			headers={"Host": doc.domain_name},
			method="GET",
		)
		with urllib.request.urlopen(req, timeout=8) as resp:
			http_status = resp.status
			body = resp.read(200).decode("utf-8", errors="replace")
	except Exception as exc:
		return {
			"ok": False,
			"message": _("HTTP check failed for {0}").format(doc.domain_name),
			"error": redact_text(str(exc)),
			"site": site.site_name,
		}

	ok = http_status == 200
	return {
		"ok": ok,
		"message": _("HTTP {0} for Host {1} → site {2}").format(http_status, doc.domain_name, site.site_name),
		"http_status": http_status,
		"body_preview": redact_text(body[:200]),
	}


def sync_existing_frappeops_confs() -> dict[str, Any]:
	"""Import existing /etc/nginx/conf.d/frappeops-*.conf into Domain docs when possible."""
	imported = []
	if not LIVE_DIR.exists():
		return {"ok": True, "imported": [], "message": _("No nginx conf.d")}

	for path in sorted(LIVE_DIR.glob("frappeops*.conf")):
		if not _is_safe_live_filename(path.name):
			continue
		text = path.read_text(errors="replace")
		m = re.search(r"server_name\s+([^;]+);", text)
		if not m:
			continue
		domain_name = m.group(1).strip().split()[0].lower()
		site_m = re.search(r"X-Frappe-Site-Name\s+([^\s;]+);", text)
		site_name = site_m.group(1).strip() if site_m else domain_name
		site = frappe.db.get_value("Site", {"site_name": site_name}, "name")
		if not site:
			continue
		# Skip protected production sites even if a conf exists
		if frappe.db.get_value("Site", site, "is_protected"):
			continue
		name = ensure_domain(domain_name, site)
		doc = frappe.get_doc("Domain", name)
		doc.nginx_status = "Configured"
		doc.apply_status = "Applied"
		doc.nginx_live_preview = text
		doc.nginx_conf_path = str(draft_path(domain_name))
		doc.save(ignore_permissions=True)
		imported.append(domain_name)

	return {"ok": True, "imported": imported, "message": _("Synced {0} domain conf(s)").format(len(imported))}


def _read_live(domain_name: str) -> str:
	path = live_path(domain_name)
	if path.exists() and _is_safe_live_filename(path.name):
		return path.read_text(errors="replace")
	return ""


def _diff_text(old: str, new: str) -> str:
	old_lines = (old or "").splitlines()
	new_lines = (new or "").splitlines()
	diff = difflib.unified_diff(old_lines, new_lines, fromfile="live", tofile="draft", lineterm="")
	return "\n".join(diff)


def _nginx_test() -> dict[str, Any]:
	cmds = [["nginx", "-t"], ["sudo", "-n", "nginx", "-t"]]
	last = _("nginx -t unavailable")
	for cmd in cmds:
		try:
			r = subprocess.run(cmd, capture_output=True, text=True)
			out = (r.stderr or "") + (r.stdout or "")
			if r.returncode == 0:
				return {"ok": True, "message": redact_text(out[-500:]), "cmd": cmd[0]}
			last = redact_text(out[-500:])
		except Exception as exc:
			last = redact_text(str(exc))
	return {"ok": False, "message": last}


def _nginx_reload() -> dict[str, Any]:
	cmds = [
		["nginx", "-s", "reload"],
		["sudo", "-n", "systemctl", "reload", "nginx"],
		["sudo", "-n", "service", "nginx", "reload"],
	]
	for cmd in cmds:
		try:
			r = subprocess.run(cmd, capture_output=True, text=True)
			if r.returncode == 0:
				return {"ok": True, "message": _("Reloaded"), "cmd": " ".join(cmd)}
		except Exception:
			continue
	return {"ok": False, "message": _("Could not reload nginx (need privileges)")}


def _ensure_hosts(domain_name: str) -> dict[str, Any]:
	line = f"127.0.0.1\t{domain_name}"
	try:
		text = Path("/etc/hosts").read_text()
		if domain_name in text:
			return {"ok": True, "message": _("Already in /etc/hosts")}
		if os.access("/etc/hosts", os.W_OK):
			with open("/etc/hosts", "a", encoding="utf-8") as f:
				f.write("\n" + line + "\n")
			return {"ok": True, "message": _("Added to /etc/hosts")}
		r = subprocess.run(
			["sudo", "-n", "bash", "-c", f"echo '{line}' >> /etc/hosts"],
			capture_output=True,
			text=True,
		)
		if r.returncode == 0:
			return {"ok": True, "message": _("Added to /etc/hosts")}
		return {"ok": False, "message": _("Add manually: {0}").format(line)}
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc))}
