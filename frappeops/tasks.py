# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Scheduled tasks for FrappeOps control plane."""

from __future__ import annotations


def local_agent_heartbeat():
	"""Push heartbeat for enrolled local agent when cache key exists."""
	import frappe

	try:
		from frappeops.services.agents.local_adapter import local_heartbeat

		server = frappe.db.get_value("Server", {"is_local": 1}, "name")
		if not server:
			return
		if not frappe.cache.get_value(f"frappeops:local_agent_key:{server}"):
			return
		local_heartbeat(server)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="FrappeOps local agent heartbeat failed")


def monitor_poll():
	"""Scheduled monitoring → Ops Alerts."""
	import frappe

	try:
		from frappeops.services.monitoring.alerts import poll_and_alert

		poll_and_alert()
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="FrappeOps monitor poll failed")


def fail_stale_jobs():
	"""Fail Operation Jobs stuck Running/Queued too long."""
	import frappe

	try:
		from frappeops.services.operations.maintenance import fail_stale_operation_jobs

		fail_stale_operation_jobs(hours=2)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="FrappeOps stale job cleanup failed")


def agent_outbound_poll():
	"""Outbound poll for agents with poll_enabled + listen_url."""
	import frappe

	try:
		from frappeops.services.agents.poll import poll_enabled_agents

		poll_enabled_agents()
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="FrappeOps agent outbound poll failed")
