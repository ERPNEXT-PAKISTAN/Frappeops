# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Control-plane → agent outbound poll (SSRF-restricted)."""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.redaction import redact_dict, redact_text
from frappeops.services.agents.heartbeat import record_heartbeat

DEFAULT_PORT = 18765
POLL_TIMEOUT = 15
ALLOWED_COMMANDS = {"ping", "health", "discover", "list_sites", "heartbeat"}


def poll_agent(
	agent_name: str | None,
	*,
	command: str = "health",
	params: dict | None = None,
	apply_heartbeat: bool = True,
) -> dict[str, Any]:
	"""HTTP poll an enrolled agent listen_url with encrypted API key."""
	agent = _resolve_agent(agent_name)
	if agent.revoked or agent.status == "Revoked":
		return {"ok": False, "message": _("Agent is revoked")}

	url = (agent.listen_url or "").strip()
	if not url:
		return {
			"ok": False,
			"message": _("No listen_url on agent. Start Local Listener or set Listen URL."),
			"agent": agent.name,
		}

	safe = validate_listen_url(url)
	if not safe["ok"]:
		return {"ok": False, "message": safe["message"], "agent": agent.name}

	command = (command or "health").strip()
	if command not in ALLOWED_COMMANDS:
		return {"ok": False, "message": _("Disallowed poll command: {0}").format(command)}

	api_key = _get_api_key(agent)
	if not api_key:
		return {
			"ok": False,
			"message": _(
				"No encrypted API key for outbound poll. Re-run Install Local Agent "
				"(or re-enroll) so the key is stored encrypted."
			),
			"agent": agent.name,
		}

	base = url.rstrip("/")
	headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
	try:
		if command == "ping":
			resp = requests.get(f"{base}/v1/ping", headers=headers, timeout=POLL_TIMEOUT, allow_redirects=False)
			payload = _safe_json(resp)
		else:
			resp = requests.post(
				f"{base}/v1/execute",
				headers=headers,
				data=json.dumps({"command": command, "params": params or {}}),
				timeout=POLL_TIMEOUT,
				allow_redirects=False,
			)
			payload = _safe_json(resp)
	except Exception as exc:
		_mark_poll(agent, False, redact_text(str(exc))[:180])
		return {"ok": False, "message": _("Poll failed: {0}").format(redact_text(str(exc))), "agent": agent.name}

	ok = resp.status_code == 200 and bool(payload.get("ok"))
	status_text = "OK" if ok else f"HTTP {resp.status_code}"
	_mark_poll(agent, ok, status_text)

	facts = payload.get("facts") if isinstance(payload, dict) else None
	hb = None
	if ok and apply_heartbeat and facts and command in ("health", "heartbeat", "discover"):
		# Reuse inbound heartbeat path with the same key
		hb = record_heartbeat(api_key, facts)

	return {
		"ok": ok,
		"message": _("Polled {0}: {1}").format(agent.name, status_text if ok else payload.get("message") or status_text),
		"agent": agent.name,
		"command": command,
		"http_status": resp.status_code,
		"payload": redact_dict(payload) if isinstance(payload, dict) else {},
		"heartbeat": hb,
		"listen_url": base,
	}


def poll_enabled_agents() -> dict[str, Any]:
	"""Scheduler: poll agents with poll_enabled + listen_url."""
	rows = frappe.get_all(
		"Server Agent",
		filters={"poll_enabled": 1, "revoked": 0, "listen_url": ["is", "set"]},
		pluck="name",
	)
	results = []
	for name in rows:
		try:
			results.append(poll_agent(name, command="health", apply_heartbeat=True))
		except Exception as exc:
			results.append({"ok": False, "agent": name, "message": redact_text(str(exc))})
		frappe.db.commit()
	return {"ok": True, "polled": len(results), "results": results}


def validate_listen_url(url: str) -> dict[str, Any]:
	"""Allow only http(s) to loopback/private hosts unless Settings override."""
	try:
		parsed = urlparse(url.strip())
	except Exception:
		return {"ok": False, "message": _("Invalid listen URL")}

	if parsed.scheme not in ("http", "https"):
		return {"ok": False, "message": _("Listen URL must be http or https")}
	if parsed.username or parsed.password:
		return {"ok": False, "message": _("Listen URL must not embed credentials")}
	if parsed.query or parsed.fragment:
		return {"ok": False, "message": _("Listen URL must not include query/fragment")}
	host = parsed.hostname
	if not host:
		return {"ok": False, "message": _("Listen URL host required")}
	port = parsed.port or (443 if parsed.scheme == "https" else 80)
	if port < 1 or port > 65535:
		return {"ok": False, "message": _("Invalid port")}

	allow_public = bool(frappe.db.get_single_value("FrappeOps Settings", "allow_public_agent_urls"))
	try:
		infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
	except Exception as exc:
		return {"ok": False, "message": _("Cannot resolve listen host: {0}").format(redact_text(str(exc)))}

	for info in infos:
		ip_str = info[4][0]
		try:
			ip = ipaddress.ip_address(ip_str)
		except Exception:
			return {"ok": False, "message": _("Invalid resolved address")}
		if ip.is_loopback:
			continue
		if allow_public and not ip.is_unspecified and not ip.is_multicast:
			# still block link-local / metadata
			if ip.is_link_local or str(ip).startswith("169.254."):
				return {"ok": False, "message": _("Link-local / metadata addresses are blocked")}
			continue
		if ip.is_private and not ip.is_link_local:
			continue
		return {
			"ok": False,
			"message": _(
				"Listen URL host {0} resolves to non-private address {1}. "
				"Enable Allow Public Agent URLs only when intentional."
			).format(host, ip_str),
		}
	return {"ok": True, "host": host, "port": port}


def set_listen_url(agent_name: str, listen_url: str, *, poll_enabled: bool = True) -> dict[str, Any]:
	agent = frappe.get_doc("Server Agent", agent_name)
	safe = validate_listen_url(listen_url)
	if not safe["ok"]:
		return {"ok": False, "message": safe["message"]}
	agent.listen_url = listen_url.rstrip("/")
	agent.poll_enabled = 1 if poll_enabled else 0
	agent.save(ignore_permissions=True)
	return {"ok": True, "message": _("Listen URL saved"), "agent": agent.name, "listen_url": agent.listen_url}


def _resolve_agent(agent_name: str | None):
	name = agent_name
	if not name:
		name = frappe.db.get_value(
			"Server Agent",
			{"revoked": 0, "listen_url": ["is", "set"]},
			"name",
			order_by="modified desc",
		) or frappe.db.get_value("Server Agent", {"revoked": 0}, "name", order_by="modified desc")
	if not name:
		frappe.throw(_("No Server Agent found"))
	return frappe.get_doc("Server Agent", name)


def _get_api_key(agent) -> str | None:
	try:
		key = agent.get_password("api_key_secret")
		if key:
			return key
	except Exception:
		pass
	# Fall back to local cache for this control-plane host
	server = agent.server
	cached = frappe.cache.get_value(f"frappeops:local_agent_key:{server}")
	if cached:
		# Persist encrypted for future polls
		try:
			agent.api_key_secret = cached
			agent.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			pass
		return cached
	return None


def _mark_poll(agent, ok: bool, status: str) -> None:
	text = (("OK" if ok else "Error") + f": {status}")[:140]
	values = {
		"last_poll_at": now_datetime(),
		"last_poll_status": text,
	}
	if ok:
		values["status"] = "Online"
	frappe.db.set_value("Server Agent", agent.name, values, update_modified=True)


def _safe_json(resp) -> dict:
	try:
		data = resp.json()
		return data if isinstance(data, dict) else {"ok": False, "message": "non-object json"}
	except Exception:
		return {"ok": False, "message": redact_text((resp.text or "")[:300])}
