# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Offsite backup upload (S3-compatible native; Drive/Dropbox via rclone)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.redaction import redact_text


def resolve_destination(name: str | None = None):
	"""Return enabled Backup Destination (explicit, default, or Settings link)."""
	if name and frappe.db.exists("Backup Destination", name):
		doc = frappe.get_doc("Backup Destination", name)
		if not doc.enabled:
			frappe.throw(_("Backup Destination {0} is disabled").format(name))
		return doc

	settings = frappe.get_single("FrappeOps Settings")
	default = getattr(settings, "default_backup_destination", None)
	if default and frappe.db.exists("Backup Destination", default):
		doc = frappe.get_doc("Backup Destination", default)
		if doc.enabled:
			return doc

	row = frappe.db.get_value(
		"Backup Destination",
		{"enabled": 1, "is_default": 1},
		"name",
	)
	if row:
		return frappe.get_doc("Backup Destination", row)
	row = frappe.db.get_value("Backup Destination", {"enabled": 1}, "name")
	if row:
		return frappe.get_doc("Backup Destination", row)
	return None


def sha256_file(path: Path) -> str:
	h = hashlib.sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest()


def upload_backup(
	backup_name: str,
	*,
	destination: str | None = None,
	confirm: bool = False,
) -> dict[str, Any]:
	"""Upload local Backup artifacts to an offsite destination."""
	if not confirm:
		return {
			"ok": False,
			"status": "blocked",
			"message": _("Set confirm=1 after reviewing destination credentials."),
			"needs": ["confirm"],
		}

	if not frappe.db.exists("Backup", backup_name):
		return {"ok": False, "message": _("Backup {0} not found").format(backup_name)}

	backup = frappe.get_doc("Backup", backup_name)
	if backup.status not in ("Success", "Verified"):
		return {
			"ok": False,
			"message": _("Backup must be Success/Verified before offsite upload (status={0})").format(
				backup.status
			),
		}

	dest = resolve_destination(destination or getattr(backup, "backup_destination", None))
	if not dest:
		return {
			"ok": False,
			"status": "blocked",
			"message": _(
				"No Backup Destination configured. Create one (S3 / Drive / Dropbox) under Backup Destination."
			),
			"needs": ["backup_destination"],
		}

	local_path = Path(backup.storage_location or "")
	if not local_path.exists():
		return {
			"ok": False,
			"message": _("Local backup file missing: {0}").format(backup.storage_location),
		}

	files = _collect_artifacts(local_path)
	if not files:
		return {"ok": False, "message": _("No backup files found near {0}").format(local_path)}

	if not backup.checksum and local_path.is_file():
		backup.checksum = sha256_file(local_path)

	backup.offsite_status = "Uploading"
	backup.backup_destination = dest.name
	backup.save(ignore_permissions=True)
	frappe.db.commit()

	try:
		if dest.provider in ("S3 Compatible", "AWS S3"):
			result = _upload_s3(dest, files, backup)
		elif dest.provider in ("Google Drive", "Dropbox"):
			result = _upload_rclone(dest, files, backup)
		elif dest.provider == "Local":
			result = _upload_local_copy(dest, files, backup)
		else:
			result = {"ok": False, "message": _("Unsupported provider: {0}").format(dest.provider)}
	except Exception as exc:
		backup.offsite_status = "Failed"
		backup.notes = ((backup.notes or "") + "\n" + redact_text(str(exc))).strip()
		backup.save(ignore_permissions=True)
		return {"ok": False, "message": _("Offsite upload failed: {0}").format(redact_text(str(exc)))}

	if result.get("ok"):
		backup.offsite_status = "Uploaded"
		backup.offsite_uri = result.get("uri") or backup.offsite_uri
		backup.offsite_uploaded_at = now_datetime()
		if result.get("checksum"):
			backup.checksum = result["checksum"]
		backup.notes = ((backup.notes or "") + "\n" + (result.get("message") or "")).strip()
		backup.save(ignore_permissions=True)
	else:
		backup.offsite_status = "Failed"
		backup.notes = ((backup.notes or "") + "\n" + (result.get("message") or "")).strip()
		backup.save(ignore_permissions=True)

	return result


def maybe_auto_upload(backup_name: str) -> dict[str, Any] | None:
	"""Called after local backup success when Settings.auto_upload_backups is on."""
	settings = frappe.get_single("FrappeOps Settings")
	if not getattr(settings, "auto_upload_backups", 0):
		return None
	if not resolve_destination():
		return {
			"ok": False,
			"message": _("auto_upload_backups is on but no Backup Destination is configured"),
		}
	return upload_backup(backup_name, confirm=True)


def test_destination(destination_name: str) -> dict[str, Any]:
	"""Lightweight connectivity check (list bucket / rclone about)."""
	if not destination_name or not frappe.db.exists("Backup Destination", destination_name):
		return {"ok": False, "message": _("Destination not found")}
	dest = frappe.get_doc("Backup Destination", destination_name)
	if not dest.enabled:
		return {"ok": False, "message": _("Destination disabled")}

	if dest.provider in ("S3 Compatible", "AWS S3"):
		return _test_s3(dest)
	if dest.provider in ("Google Drive", "Dropbox"):
		return _test_rclone(dest)
	if dest.provider == "Local":
		prefix = Path(dest.prefix or "/tmp/frappeops-backups")
		prefix.mkdir(parents=True, exist_ok=True)
		return {"ok": True, "message": _("Local path writable: {0}").format(prefix)}
	return {"ok": False, "message": _("Unsupported provider")}


def _collect_artifacts(primary: Path) -> list[Path]:
	if primary.is_file():
		stem = primary.name.split("-")[0] if "-" in primary.name else primary.stem
		siblings = []
		for p in primary.parent.glob("*"):
			if not p.is_file():
				continue
			# Same timestamp family: share common prefix before last -YYYYMMDD or identical mtime band
			if abs(p.stat().st_mtime - primary.stat().st_mtime) <= 120:
				siblings.append(p)
		return sorted(set(siblings) | {primary})
	if primary.is_dir():
		return sorted([p for p in primary.iterdir() if p.is_file()])[:30]
	return []


def _key_for(dest, backup, path: Path) -> str:
	prefix = (dest.prefix or "frappeops-backups").strip().strip("/")
	site = ""
	if backup.site:
		site = frappe.db.get_value("Site", backup.site, "site_name") or backup.site
	parts = [prefix, site or "unknown-site", backup.name, path.name]
	return "/".join(p for p in parts if p)


def _upload_s3(dest, files: list[Path], backup) -> dict[str, Any]:
	if dest.rclone_remote and shutil.which("rclone"):
		return _upload_rclone(dest, files, backup)

	try:
		import boto3
		from botocore.client import Config
	except ImportError:
		if shutil.which("rclone") and dest.rclone_remote:
			return _upload_rclone(dest, files, backup)
		return {
			"ok": False,
			"message": _(
				"boto3 is not installed and no rclone remote set. "
				"pip install boto3 in the bench env, or configure rclone_remote."
			),
			"needs": ["boto3_or_rclone"],
		}

	if not dest.bucket or not dest.access_key_id:
		return {"ok": False, "message": _("S3 bucket and access_key_id are required")}

	try:
		secret = dest.get_password("secret_access_key")
	except Exception:
		secret = None
	if not secret:
		return {"ok": False, "message": _("Secret Access Key is required")}

	kwargs: dict[str, Any] = {
		"service_name": "s3",
		"region_name": dest.region or "us-east-1",
		"aws_access_key_id": dest.access_key_id,
		"aws_secret_access_key": secret,
	}
	if dest.endpoint_url:
		kwargs["endpoint_url"] = dest.endpoint_url.strip()
	if dest.path_style:
		kwargs["config"] = Config(s3={"addressing_style": "path"})

	client = boto3.client(**kwargs)
	uploaded = []
	for path in files:
		key = _key_for(dest, backup, path)
		client.upload_file(str(path), dest.bucket, key)
		uploaded.append(key)

	uri = f"s3://{dest.bucket}/{uploaded[0]}" if uploaded else ""
	return {
		"ok": True,
		"message": _("Uploaded {0} file(s) to S3").format(len(uploaded)),
		"uri": uri,
		"keys": uploaded,
		"checksum": backup.checksum,
	}


def _upload_rclone(dest, files: list[Path], backup) -> dict[str, Any]:
	remote = (dest.rclone_remote or "").strip()
	if not remote:
		return {
			"ok": False,
			"status": "blocked",
			"message": _(
				"Google Drive / Dropbox need rclone. Run `rclone config`, then set Rclone Remote "
				"(e.g. gdrive or dropbox) on Backup Destination."
			),
			"needs": ["rclone_remote"],
		}
	if not shutil.which("rclone"):
		return {
			"ok": False,
			"message": _("rclone binary not found on PATH"),
			"needs": ["rclone"],
		}

	prefix = (dest.prefix or "frappeops-backups").strip().strip("/")
	site = ""
	if backup.site:
		site = frappe.db.get_value("Site", backup.site, "site_name") or backup.site
	remote_dir = f"{remote}:{prefix}/{site or 'unknown-site'}/{backup.name}"

	uploaded = []
	for path in files:
		cmd = ["rclone", "copy", str(path), remote_dir, "--retries", "3"]
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
		if proc.returncode != 0:
			err = redact_text((proc.stderr or proc.stdout or "")[-800:])
			return {"ok": False, "message": _("rclone failed: {0}").format(err)}
		uploaded.append(path.name)

	return {
		"ok": True,
		"message": _("Uploaded {0} file(s) via rclone to {1}").format(len(uploaded), remote_dir),
		"uri": remote_dir,
		"files": uploaded,
		"checksum": backup.checksum,
	}


def _upload_local_copy(dest, files: list[Path], backup) -> dict[str, Any]:
	root = Path(dest.prefix or "/tmp/frappeops-backups")
	target = root / (backup.name or "backup")
	target.mkdir(parents=True, exist_ok=True)
	for path in files:
		shutil.copy2(path, target / path.name)
	return {
		"ok": True,
		"message": _("Copied {0} file(s) to {1}").format(len(files), target),
		"uri": str(target),
		"checksum": backup.checksum,
	}


def _test_s3(dest) -> dict[str, Any]:
	try:
		import boto3
		from botocore.client import Config
	except ImportError:
		if dest.rclone_remote and shutil.which("rclone"):
			return _test_rclone(dest)
		return {"ok": False, "message": _("boto3 not installed"), "needs": ["boto3"]}

	try:
		secret = dest.get_password("secret_access_key")
	except Exception:
		secret = None
	if not dest.bucket or not dest.access_key_id or not secret:
		return {"ok": False, "message": _("bucket, access_key_id, secret_access_key required")}

	kwargs: dict[str, Any] = {
		"service_name": "s3",
		"region_name": dest.region or "us-east-1",
		"aws_access_key_id": dest.access_key_id,
		"aws_secret_access_key": secret,
	}
	if dest.endpoint_url:
		kwargs["endpoint_url"] = dest.endpoint_url.strip()
	if dest.path_style:
		kwargs["config"] = Config(s3={"addressing_style": "path"})
	client = boto3.client(**kwargs)
	client.head_bucket(Bucket=dest.bucket)
	return {"ok": True, "message": _("S3 bucket reachable: {0}").format(dest.bucket)}


def _test_rclone(dest) -> dict[str, Any]:
	remote = (dest.rclone_remote or "").strip()
	if not remote:
		return {"ok": False, "message": _("Set Rclone Remote first"), "needs": ["rclone_remote"]}
	if not shutil.which("rclone"):
		return {"ok": False, "message": _("rclone not installed"), "needs": ["rclone"]}
	proc = subprocess.run(
		["rclone", "about", f"{remote}:", "--json"],
		capture_output=True,
		text=True,
		timeout=60,
	)
	if proc.returncode != 0:
		# about is not supported on all remotes — lsd is enough
		proc2 = subprocess.run(
			["rclone", "lsd", f"{remote}:"],
			capture_output=True,
			text=True,
			timeout=60,
		)
		if proc2.returncode != 0:
			return {"ok": False, "message": redact_text((proc2.stderr or proc.stderr or "")[-500:])}
	return {"ok": True, "message": _("rclone remote reachable: {0}").format(remote)}
