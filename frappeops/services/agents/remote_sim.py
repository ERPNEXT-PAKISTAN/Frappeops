# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Simulate a second remote server agent on this host (loopback :18766).

Honest substitute until a real second VM is available. Creates Server SRV record
(is_local=0), enrolls agent, starts agentd on a separate port, enables poll.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from frappeops.services.agents.enrollment import create_enrollment_token, enroll_with_token
from frappeops.services.agents.listener_mgr import start_local_listener, stop_local_listener
from frappeops.services.agents.poll import poll_agent, set_listen_url
from frappeops.services.agents.protocol import AGENT_VERSION, DEFAULT_SCOPES
from frappeops.services.agents.collector import collect_host_facts

REMOTE_SIM_NAME = "remote-sim"
REMOTE_SIM_PORT = 18766


def ensure_remote_sim_server() -> dict[str, Any]:
	"""Create/update a non-local Server inventory row for multi-agent demos."""
	org = frappe.db.get_value("Organization", {}, "name", order_by="creation asc")
	existing = frappe.db.get_value("Server", {"server_name": REMOTE_SIM_NAME}, "name")
	if existing:
		doc = frappe.get_doc("Server", existing)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Server",
				"server_name": REMOTE_SIM_NAME,
				"organization": org,
				"status": "Online",
				"enabled": 1,
				"hostname": REMOTE_SIM_NAME,
				"ip_address": "127.0.0.1",
				"server_type": "Development",
				"is_local": 0,
				"is_protected": 0,
				"notes": "Simulated remote for outbound poll until a real second VM exists.",
			}
		)
		doc.insert(ignore_permissions=True)
	doc.is_local = 0
	doc.ip_address = "127.0.0.1"
	doc.status = "Online"
	doc.notes = "Simulated remote for outbound poll until a real second VM exists."
	doc.save(ignore_permissions=True)
	return {"ok": True, "server": doc.name, "server_name": doc.server_name}


def install_remote_sim_agent(*, port: int = REMOTE_SIM_PORT) -> dict[str, Any]:
	"""Enroll agent for remote-sim and start loopback listener on a dedicated port."""
	ensured = ensure_remote_sim_server()
	server = ensured["server"]

	# listener_mgr.start_local_listener currently requires is_local — use lower-level path
	token_result = create_enrollment_token(
		server, scopes=DEFAULT_SCOPES, agent_name=f"{REMOTE_SIM_NAME}-agent"
	)
	facts = collect_host_facts()
	facts["hostname"] = REMOTE_SIM_NAME
	enrolled = enroll_with_token(
		token_result["enrollment_token"],
		hostname=REMOTE_SIM_NAME,
		agent_version=AGENT_VERSION,
		facts=facts,
	)
	agent_name = enrolled["agent"]
	api_key = enrolled["api_key"]

	# Cache key under sim server id for listener config write
	frappe.cache.set_value(
		f"frappeops:local_agent_key:{server}",
		api_key,
		expires_in_sec=60 * 60 * 24 * 30,
	)

	started = start_local_listener(agent_name, port=int(port), bind="127.0.0.1")
	set_listen_url(agent_name, f"http://127.0.0.1:{int(port)}", poll_enabled=True)
	polled = poll_agent(agent_name, command="health", apply_heartbeat=True)

	return {
		"ok": bool(started.get("ok") and polled.get("ok")),
		"message": _("Remote-sim agent ready on port {0}").format(port)
		if polled.get("ok")
		else _("Remote-sim started but poll failed"),
		"server": server,
		"agent": agent_name,
		"listen_url": f"http://127.0.0.1:{int(port)}",
		"api_key": api_key,
		"start": started,
		"poll": polled,
		"note": _(
			"This is a loopback second agent (not a real second VM). "
			"Provide a private IP for true multi-server acceptance."
		),
	}


def teardown_remote_sim() -> dict[str, Any]:
	server = frappe.db.get_value("Server", {"server_name": REMOTE_SIM_NAME}, "name")
	if not server:
		return {"ok": True, "message": _("No remote-sim server")}
	agents = frappe.get_all("Server Agent", filters={"server": server, "revoked": 0}, pluck="name")
	for a in agents:
		try:
			stop_local_listener(a, quiet=True)
		except Exception:
			pass
		frappe.db.set_value("Server Agent", a, {"status": "Revoked", "revoked": 1, "poll_enabled": 0})
	return {"ok": True, "message": _("Remote-sim listeners stopped"), "server": server, "agents": agents}
