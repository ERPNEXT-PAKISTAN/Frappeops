# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Poll inventory health and raise Ops Alerts (no silent noise storms)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.redaction import redact_dict
from frappeops.services.agents.collector import collect_host_facts


def _threshold(name: str, default: float) -> float:
	"""Read Settings threshold; treat missing/0 as unset (Frappe Singles often store 0)."""
	try:
		val = frappe.db.get_single_value("FrappeOps Settings", name)
		if val is None or val == "":
			return default
		num = float(val)
		if num <= 0:
			return default
		return num
	except Exception:
		return default


def upsert_alert(
	*,
	title: str,
	severity: str,
	alert_type: str,
	message: str,
	server: str | None = None,
	site: str | None = None,
	details: dict | None = None,
) -> str:
	fp_src = f"{alert_type}|{server or ''}|{site or ''}|{title}"
	fingerprint = hashlib.sha256(fp_src.encode()).hexdigest()[:32]
	existing = frappe.db.get_value(
		"Ops Alert",
		{"fingerprint": fingerprint, "status": ["in", ["Open", "Acknowledged"]]},
		"name",
	)
	if existing:
		frappe.db.set_value(
			"Ops Alert",
			existing,
			{
				"last_seen": now_datetime(),
				"severity": severity,
				"message": message,
				"details_json": json.dumps(redact_dict(details or {}), indent=2, default=str),
			},
		)
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Ops Alert",
			"title": title[:140],
			"severity": severity,
			"status": "Open",
			"alert_type": alert_type,
			"server": server,
			"site": site,
			"fingerprint": fingerprint,
			"last_seen": now_datetime(),
			"message": message,
			"details_json": json.dumps(redact_dict(details or {}), indent=2, default=str),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def resolve_alert_fingerprint(fingerprint: str) -> None:
	for name in frappe.get_all(
		"Ops Alert",
		filters={"fingerprint": fingerprint, "status": ["in", ["Open", "Acknowledged"]]},
		pluck="name",
	):
		frappe.db.set_value("Ops Alert", name, "status", "Resolved")


def poll_and_alert() -> dict[str, Any]:
	"""Collect local facts + inventory signals; open/update Ops Alerts."""
	created = []
	active_fingerprints: set[str] = set()
	disk_warn = _threshold("disk_warn_percent", 80)
	disk_crit = _threshold("disk_crit_percent", 90)
	ram_warn = _threshold("ram_warn_percent", 85)
	ram_crit = _threshold("ram_crit_percent", 95)

	server = frappe.db.get_value("Server", {"is_local": 1}, "name")
	facts = collect_host_facts()
	disk = float(facts.get("disk_used_percent") or 0)
	ram = float(facts.get("ram_percent") or 0)

	if server:
		# Refresh lightweight health via existing runner helper
		try:
			from frappeops.services.operations.runner import _server_health

			_server_health(server)
		except Exception:
			pass

	def fire(**kwargs):
		name = upsert_alert(**kwargs)
		created.append(name)
		doc = frappe.get_doc("Ops Alert", name)
		if doc.fingerprint:
			active_fingerprints.add(doc.fingerprint)
		return name

	if disk >= disk_crit:
		fire(
			title=_("Disk critical on local server"),
			severity="Critical",
			alert_type="Disk",
			message=_("Disk used {0}% (critical ≥ {1}%)").format(disk, disk_crit),
			server=server,
			details={"disk_used_percent": disk},
		)
	elif disk >= disk_warn:
		fire(
			title=_("Disk warning on local server"),
			severity="Warning",
			alert_type="Disk",
			message=_("Disk used {0}% (warn ≥ {1}%)").format(disk, disk_warn),
			server=server,
			details={"disk_used_percent": disk},
		)

	if ram >= ram_crit:
		fire(
			title=_("Memory critical on local server"),
			severity="Critical",
			alert_type="Memory",
			message=_("RAM used {0}% (critical ≥ {1}%)").format(ram, ram_crit),
			server=server,
			details={"ram_percent": ram},
		)
	elif ram >= ram_warn:
		fire(
			title=_("Memory warning on local server"),
			severity="Warning",
			alert_type="Memory",
			message=_("RAM used {0}% (warn ≥ {1}%)").format(ram, ram_warn),
			server=server,
			details={"ram_percent": ram},
		)

	# Offline agents
	for agent in frappe.get_all(
		"Server Agent",
		filters={"status": "Offline", "revoked": 0},
		fields=["name", "server", "last_heartbeat"],
	):
		fire(
			title=_("Agent offline: {0}").format(agent.name),
			severity="Warning",
			alert_type="Agent",
			message=_("Last heartbeat: {0}").format(agent.last_heartbeat or "—"),
			server=agent.server,
			details={"agent": agent.name},
		)

	# Critical sites
	for site in frappe.get_all(
		"Site",
		filters={"status": ["in", ["Critical", "Offline"]]},
		fields=["name", "site_name", "server", "status"],
	):
		fire(
			title=_("Site {0} is {1}").format(site.site_name, site.status),
			severity="Critical",
			alert_type="Site",
			message=_("Site health status is {0}").format(site.status),
			server=site.server,
			site=site.name,
		)

	# SSL expiry (if Certificate records have not_after)
	for cert in frappe.get_all(
		"SSL Certificate",
		filters={"not_after": ["is", "set"]},
		fields=["name", "common_name", "not_after", "site", "server", "status"],
		limit_page_length=100,
	):
		from frappe.utils import get_datetime, now_datetime as _now

		try:
			days_left = (get_datetime(cert.not_after) - _now()).days
		except Exception:
			continue
		if days_left <= 14:
			sev = "Critical" if days_left <= 7 else "Warning"
			fire(
				title=_("SSL expiring: {0}").format(cert.common_name),
				severity=sev,
				alert_type="SSL",
				message=_("{0} days until expiry ({1})").format(days_left, cert.not_after),
				server=cert.server,
				site=cert.site,
				details={"certificate": cert.name, "days_left": days_left},
			)

	resolved = _auto_resolve_recovered(active_fingerprints, server=server, disk=disk, ram=ram, disk_warn=disk_warn, ram_warn=ram_warn)

	open_count = frappe.db.count("Ops Alert", {"status": "Open"})
	return {
		"ok": True,
		"message": _("Monitoring poll complete ({0} open alerts)").format(open_count),
		"alerts_touched": list(dict.fromkeys(created)),
		"resolved": resolved,
		"open_alerts": open_count,
		"facts": {"disk_used_percent": disk, "ram_percent": ram},
	}


def _auto_resolve_recovered(
	active_fingerprints: set[str],
	*,
	server: str | None,
	disk: float,
	ram: float,
	disk_warn: float,
	ram_warn: float,
) -> list[str]:
	"""Resolve Open Disk/Memory/Agent/Site alerts that no longer apply."""
	resolved = []
	# Recovered disk/memory on local server
	if disk < disk_warn and server:
		for name in frappe.get_all(
			"Ops Alert",
			filters={"status": ["in", ["Open", "Acknowledged"]], "alert_type": "Disk", "server": server},
			pluck="name",
		):
			frappe.db.set_value("Ops Alert", name, "status", "Resolved")
			resolved.append(name)
	if ram < ram_warn and server:
		for name in frappe.get_all(
			"Ops Alert",
			filters={"status": ["in", ["Open", "Acknowledged"]], "alert_type": "Memory", "server": server},
			pluck="name",
		):
			frappe.db.set_value("Ops Alert", name, "status", "Resolved")
			resolved.append(name)

	# Agents that are Online again
	online_agents = set(
		frappe.get_all("Server Agent", filters={"status": "Online", "revoked": 0}, pluck="name")
	)
	for alert in frappe.get_all(
		"Ops Alert",
		filters={"status": ["in", ["Open", "Acknowledged"]], "alert_type": "Agent"},
		fields=["name", "title", "details_json"],
	):
		# title pattern: Agent offline: AGT-xxxx
		for ag in online_agents:
			if ag in (alert.title or ""):
				frappe.db.set_value("Ops Alert", alert.name, "status", "Resolved")
				resolved.append(alert.name)
				break

	# Sites healthy again
	for alert in frappe.get_all(
		"Ops Alert",
		filters={"status": ["in", ["Open", "Acknowledged"]], "alert_type": "Site", "site": ["is", "set"]},
		fields=["name", "site"],
	):
		st = (frappe.db.get_value("Site", alert.site, "status") or "").lower()
		if st in ("healthy", "warning", "maintenance", "unknown"):
			if st != "critical" and st != "offline":
				frappe.db.set_value("Ops Alert", alert.name, "status", "Resolved")
				resolved.append(alert.name)

	return list(dict.fromkeys(resolved))


def acknowledge_alert(alert: str) -> dict[str, Any]:
	doc = frappe.get_doc("Ops Alert", alert)
	doc.status = "Acknowledged"
	doc.save(ignore_permissions=True)
	return {"ok": True, "message": _("Acknowledged {0}").format(alert), "alert": alert}


def resolve_alert(alert: str) -> dict[str, Any]:
	doc = frappe.get_doc("Ops Alert", alert)
	doc.status = "Resolved"
	doc.save(ignore_permissions=True)
	return {"ok": True, "message": _("Resolved {0}").format(alert), "alert": alert}
