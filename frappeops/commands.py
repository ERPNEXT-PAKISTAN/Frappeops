# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Bench CLI helpers: bench --site frappeops.local frappeops-status"""

from __future__ import annotations

import click
from frappe.commands import pass_context


@click.command("frappeops-status")
@pass_context
def frappeops_status(context):
	"""Print FrappeOps control-plane status (v1)."""
	import frappe

	for site in context.sites:
		frappe.init(site=site)
		frappe.connect()
		try:
			from frappeops.api.v1 import status

			click.echo(frappe.as_json(status()))
		finally:
			frappe.destroy()


@click.command("frappeops-monitor")
@pass_context
def frappeops_monitor(context):
	"""Run one monitoring poll and print open alerts."""
	import frappe

	for site in context.sites:
		frappe.init(site=site)
		frappe.connect()
		try:
			from frappeops.services.monitoring.alerts import poll_and_alert

			click.echo(frappe.as_json(poll_and_alert()))
		finally:
			frappe.destroy()


commands = [frappeops_status, frappeops_monitor]
