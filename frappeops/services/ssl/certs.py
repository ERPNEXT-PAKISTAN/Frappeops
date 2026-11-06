# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""SSL inspect + gated Certbot issue (honest when tooling/DNS missing)."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from frappeops.core.redaction import redact_text

ISSUE_PHRASE = "ISSUE"
LE_LIVE = Path("/etc/letsencrypt/live")


def certbot_available() -> bool:
	return bool(shutil.which("certbot"))


def check_tooling() -> dict[str, Any]:
	"""Honest SSL readiness report (no mutations)."""
	available = certbot_available()
	nginx = bool(shutil.which("nginx"))
	openssl = bool(shutil.which("openssl"))
	live = LE_LIVE.exists()
	allow = bool(frappe.db.get_single_value("FrappeOps Settings", "allow_ssl_issue"))
	domains = frappe.get_all(
		"Domain",
		fields=["name", "domain_name", "ssl_status", "site"],
		limit_page_length=50,
	)
	publicish = [
		d
		for d in domains
		if d.domain_name
		and not str(d.domain_name).endswith((".local", ".test", ".localhost"))
	]
	blocked_reasons = []
	if not available:
		blocked_reasons.append(_("certbot binary missing"))
	if not nginx:
		blocked_reasons.append(_("nginx binary missing"))
	if not allow:
		blocked_reasons.append(_("Allow SSL Issue is off in Settings"))
	if not publicish:
		blocked_reasons.append(_("no public Domain records (*.local cannot use Let's Encrypt)"))

	ready = available and nginx and allow and bool(publicish)
	return {
		"ok": True,
		"ready_for_issue": ready,
		"certbot": available,
		"nginx": nginx,
		"openssl": openssl,
		"letsencrypt_live": live,
		"allow_ssl_issue": allow,
		"public_domains": [d.domain_name for d in publicish],
		"blocked_reasons": blocked_reasons,
		"message": (
			_("SSL tooling ready for public domains (still dry-run first)")
			if ready
			else _("SSL issue blocked: {0}").format("; ".join(blocked_reasons) or _("unknown"))
		),
		"install_hint": _("sudo apt install -y certbot python3-certbot-nginx") if not available else None,
	}


def issue_status() -> dict[str, Any]:
	"""Legacy probe used before Wave G — prefer inspect_certs / issue_certificate."""
	tooling = check_tooling()
	if not tooling.get("certbot"):
		return {
			"ok": False,
			"status": "blocked",
			"message": tooling.get("message"),
			"install_hint": tooling.get("install_hint"),
		}
	return {
		"ok": False,
		"status": "blocked" if not tooling.get("ready_for_issue") else "ready",
		"message": tooling.get("message"),
		"tooling": tooling,
	}


def inspect_live_certs() -> dict[str, Any]:
	"""Read-only scan of /etc/letsencrypt/live if present."""
	if not LE_LIVE.exists():
		return {"ok": True, "certs": [], "message": _("No Let's Encrypt live directory"), "certbot": certbot_available()}
	certs = []
	for child in sorted(LE_LIVE.iterdir()):
		if child.is_dir() and (child / "fullchain.pem").exists():
			meta = _read_pem_dates(child / "fullchain.pem")
			certs.append(
				{
					"common_name": child.name,
					"path": str(child),
					"not_before": meta.get("not_before"),
					"not_after": meta.get("not_after"),
					"status": meta.get("status") or "Unknown",
					"issuer": meta.get("issuer"),
				}
			)
	return {"ok": True, "certs": certs, "certbot": certbot_available()}


def inspect_certs(*, sync_records: bool = True) -> dict[str, Any]:
	"""Scan live certs and optionally upsert SSL Certificate DocTypes."""
	scan = inspect_live_certs()
	synced = []
	if sync_records:
		for item in scan.get("certs") or []:
			name = _upsert_ssl_certificate(item)
			if name:
				synced.append(name)
	return {
		"ok": True,
		"message": _("SSL inspect complete ({0} certs)").format(len(scan.get("certs") or [])),
		"certbot": certbot_available(),
		"certs": scan.get("certs") or [],
		"synced": synced,
	}


def diagnose_domain(domain_name: str | None = None, hostname: str | None = None) -> dict[str, Any]:
	"""Compare DNS A records vs this host public IP; optional remote cert peek (read-only)."""
	cn = hostname
	domain_doc = None
	if domain_name:
		domain_doc = frappe.get_doc("Domain", domain_name)
		cn = domain_doc.domain_name or domain_doc.name
	if not cn:
		return {"ok": False, "message": _("domain_name or hostname required")}

	public_ip = _public_ip()
	dns_a = _dns_a(cn)
	points_here = bool(public_ip and public_ip in dns_a)
	remote_cert = _fetch_remote_cert(cn)
	if remote_cert.get("ok") and remote_cert.get("common_name"):
		_upsert_ssl_certificate(
			{
				"common_name": remote_cert.get("common_name") or cn,
				"not_before": remote_cert.get("not_before"),
				"not_after": remote_cert.get("not_after"),
				"status": remote_cert.get("status") or "Unknown",
				"issuer": remote_cert.get("issuer"),
				"path": f"remote://{cn}:443",
			}
		)
		if domain_doc:
			domain_doc.ssl_status = remote_cert.get("status") or domain_doc.ssl_status
			domain_doc.save(ignore_permissions=True)

	tooling = check_tooling()
	ready = bool(points_here and tooling.get("certbot") and tooling.get("nginx"))
	return {
		"ok": True,
		"common_name": cn,
		"public_ip": public_ip,
		"dns_a": dns_a,
		"dns_points_to_this_host": points_here,
		"port_443_local": _local_port_open(443),
		"remote_cert": remote_cert,
		"certbot": tooling.get("certbot"),
		"ready_for_certbot_http01": ready and points_here,
		"message": (
			_("DNS points here — Certbot HTTP-01 may work (still gated by Settings + typed ISSUE)")
			if points_here
			else _(
				"DNS for {0} is {1}; this host public IP is {2}. "
				"Point an A record at this host before Live Let's Encrypt."
			).format(cn, ", ".join(dns_a) or "—", public_ip or "unknown")
		),
	}


def issue_certificate(
	domain_name: str | None,
	*,
	confirm: bool = False,
	typed_confirmation: str | None = None,
	dry_run: bool = True,
	email: str | None = None,
) -> dict[str, Any]:
	"""Issue (or dry-run) a Let's Encrypt cert for a managed Domain — never for protected sites."""
	if not domain_name:
		return {"ok": False, "message": _("Domain required")}

	domain = frappe.get_doc("Domain", domain_name)
	site = frappe.get_doc("Site", domain.site) if domain.site else None
	if site and site.is_protected:
		return {
			"ok": False,
			"message": _("Refused: cannot issue managed SSL for protected sites."),
		}

	cn = domain.domain_name or domain.name
	if cn.endswith(".local") or cn.endswith(".test") or cn.endswith(".localhost"):
		return {
			"ok": False,
			"message": _("Refused: {0} is not a public DNS name suitable for Let's Encrypt.").format(cn),
		}

	preflight = diagnose_domain(domain_name=domain.name)
	if not preflight.get("dns_points_to_this_host"):
		return {
			"ok": False,
			"status": "blocked",
			"message": preflight.get("message"),
			"diagnose": preflight,
		}

	if not certbot_available():
		return {
			"ok": False,
			"status": "blocked",
			"message": _("Certbot is not installed on this host."),
			"domain": domain.name,
			"common_name": cn,
		}

	if not frappe.db.get_single_value("FrappeOps Settings", "allow_ssl_issue"):
		return {
			"ok": False,
			"message": _("SSL issue disabled. Enable Allow SSL Issue in FrappeOps Settings."),
		}

	if not confirm:
		return {"ok": False, "message": _("Confirm required for SSL issue.")}

	if (typed_confirmation or "").strip() != ISSUE_PHRASE:
		return {
			"ok": False,
			"message": _("Type {0} to confirm SSL certificate issue.").format(ISSUE_PHRASE),
		}

	cmd = [
		"sudo",
		"-n",
		"certbot",
		"certonly",
		"--nginx",
		"-d",
		cn,
		"--non-interactive",
		"--agree-tos",
	]
	if dry_run:
		cmd.append("--dry-run")
	if email:
		cmd.extend(["--email", str(email)])
	else:
		cmd.append("--register-unsafely-without-email")

	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc)), "domain": domain.name}

	out = redact_text(((proc.stdout or "") + (proc.stderr or ""))[-6000:])
	ok = proc.returncode == 0
	if ok and not dry_run:
		domain.ssl_status = "Valid"
		domain.save(ignore_permissions=True)
		inspect_certs(sync_records=True)

	return {
		"ok": ok,
		"dry_run": dry_run,
		"message": (
			_("Certbot dry-run succeeded for {0}").format(cn)
			if ok and dry_run
			else _("Certificate issued for {0}").format(cn)
			if ok
			else _("Certbot failed for {0}").format(cn)
		),
		"domain": domain.name,
		"common_name": cn,
		"output": out,
		"returncode": proc.returncode,
	}


def _upsert_ssl_certificate(item: dict[str, Any]) -> str | None:
	cn = item.get("common_name")
	if not cn:
		return None
	existing = frappe.db.get_value("SSL Certificate", {"common_name": cn}, "name")
	domain = frappe.db.get_value("Domain", {"domain_name": cn}, "name")
	values = {
		"common_name": cn,
		"domain": domain,
		"status": item.get("status") or "Unknown",
		"issuer": item.get("issuer") or "Let's Encrypt",
		"not_before": item.get("not_before"),
		"not_after": item.get("not_after"),
		"notes": f"path={item.get('path')}",
	}
	if existing:
		doc = frappe.get_doc("SSL Certificate", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc.name
	doc = frappe.get_doc({"doctype": "SSL Certificate", **values})
	doc.insert(ignore_permissions=True)
	return doc.name


def _read_pem_dates(pem: Path) -> dict[str, Any]:
	"""Best-effort openssl x509 parse; never raises to callers."""
	try:
		proc = subprocess.run(
			["openssl", "x509", "-in", str(pem), "-noout", "-dates", "-issuer"],
			capture_output=True,
			text=True,
			timeout=15,
		)
	except Exception:
		return {"status": "Unknown"}

	text = (proc.stdout or "") + (proc.stderr or "")
	not_before = _parse_openssl_date(_match(r"notBefore=(.+)", text))
	not_after = _parse_openssl_date(_match(r"notAfter=(.+)", text))
	issuer = _match(r"issuer\s*=\s*(.+)", text)
	status = "Unknown"
	if not_after:
		now = now_datetime()
		after = get_datetime(not_after)
		days = (after - now).days if after else None
		if days is not None:
			if days < 0:
				status = "Expired"
			elif days <= 14:
				status = "Expiring"
			else:
				status = "Valid"
	return {
		"not_before": not_before,
		"not_after": not_after,
		"issuer": (issuer or "")[:140],
		"status": status,
	}


def _match(pattern: str, text: str) -> str | None:
	m = re.search(pattern, text, re.IGNORECASE)
	return m.group(1).strip() if m else None


def _parse_openssl_date(raw: str | None) -> str | None:
	if not raw:
		return None
	# e.g. Aug 13 12:00:00 2026 GMT
	for fmt in ("%b %d %H:%M:%S %Y %Z", "%b %d %H:%M:%S %Y GMT"):
		try:
			dt = datetime.strptime(raw.strip(), fmt)
			return dt.strftime("%Y-%m-%d %H:%M:%S")
		except Exception:
			continue
	return None


def _public_ip() -> str | None:
	for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
		try:
			import requests

			r = requests.get(url, timeout=5)
			if r.status_code == 200 and r.text.strip():
				return r.text.strip()
		except Exception:
			continue
	return None


def _dns_a(hostname: str) -> list[str]:
	import socket

	out = []
	try:
		for info in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM):
			ip = info[4][0]
			if ":" not in ip and ip not in out:
				out.append(ip)
	except Exception:
		pass
	return out


def _local_port_open(port: int) -> bool:
	import socket

	try:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.settimeout(0.3)
			return s.connect_ex(("127.0.0.1", port)) == 0
	except Exception:
		return False


def _fetch_remote_cert(hostname: str) -> dict[str, Any]:
	"""Read-only TLS peek — does not modify nginx or issue certs."""
	try:
		proc = subprocess.run(
			["openssl", "s_client", "-connect", f"{hostname}:443", "-servername", hostname],
			input=b"",
			capture_output=True,
			timeout=12,
		)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc))}
	text = (proc.stdout or b"").decode("utf-8", errors="ignore")
	if "BEGIN CERTIFICATE" not in text:
		return {"ok": False, "message": _("No certificate returned from {0}:443").format(hostname)}
	# Pipe PEM into openssl x509 via temp stdin
	pem = text[text.find("-----BEGIN CERTIFICATE-----") : text.find("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")]
	try:
		x = subprocess.run(
			["openssl", "x509", "-noout", "-dates", "-issuer", "-subject"],
			input=pem.encode("utf-8"),
			capture_output=True,
			timeout=10,
		)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc))}
	out = (x.stdout or b"").decode("utf-8", errors="ignore")
	subject = _match(r"subject=.*CN\s*=\s*([^,\n]+)", out) or hostname
	meta = {
		"ok": True,
		"common_name": subject.strip(),
		"not_before": _parse_openssl_date(_match(r"notBefore=(.+)", out)),
		"not_after": _parse_openssl_date(_match(r"notAfter=(.+)", out)),
		"issuer": (_match(r"issuer\s*=\s*(.+)", out) or "")[:140],
	}
	status = "Unknown"
	if meta.get("not_after"):
		after = get_datetime(meta["not_after"])
		days = (after - now_datetime()).days if after else None
		if days is not None:
			status = "Expired" if days < 0 else "Expiring" if days <= 14 else "Valid"
	meta["status"] = status
	return meta
