# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Execute allowlisted FrappeOps operations."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text
from frappeops.services.operations.locks import assert_site_action_allowed, is_locked
from frappeops.services.operations.registry import get_action
from frappeops.utils.bench_cmd import run_bench


def _parse_params(params: Any) -> dict:
	if not params:
		return {}
	if isinstance(params, dict):
		return params
	if isinstance(params, str):
		params = params.strip()
		if not params:
			return {}
		return json.loads(params)
	return {}


@frappe.whitelist()
def run_action(
	action_key: str,
	target_type: str | None = None,
	target_name: str | None = None,
	params: Any = None,
) -> dict:
	"""Run an allowlisted action and return a result payload for the UI."""
	_require_operator()
	action = get_action(action_key)
	if not action:
		frappe.throw(_("Unknown action: {0}").format(action_key))

	if action["status"] != "available":
		return {
			"ok": False,
			"status": "not_implemented",
			"message": _("{0} is not implemented yet.").format(action["label"]),
			"action": action,
		}

	params_dict = _parse_params(params)

	if target_type == "site" and target_name:
		assert_site_action_allowed(frappe.get_doc("Site", target_name), action)

	lock_target_type = target_type
	lock_target_name = target_name
	if action_key == "site.create":
		lock_target_type = "bench"
		lock_target_name = target_name or frappe.db.get_value("Bench", {}, "name", order_by="creation asc")

	if lock_target_type and lock_target_name:
		blocking = is_locked(lock_target_type, lock_target_name)
		if blocking:
			return {
				"ok": False,
				"message": _("Resource locked by operation {0}").format(blocking),
				"action": action,
			}

	# Never persist secrets in parameters_json
	_secret_keys = ("password", "token", "api_key", "secret", "enrollment")
	safe_params = {
		k: ("***" if any(s in k.lower() for s in _secret_keys) else v) for k, v in params_dict.items()
	}
	job = frappe.get_doc(
		{
			"doctype": "Operation Job",
			"operation_type": action_key,
			"status": "Running",
			"risk_level": action.get("risk") or "Low",
			"progress": 10,
			"requested_by": frappe.session.user,
			"started_at": now_datetime(),
			"parameters_json": json.dumps(
				{
					"target_type": target_type,
					"target_name": target_name,
					"params": safe_params,
				},
				indent=2,
			),
		}
	)

	if target_type == "site" and target_name:
		site = frappe.get_doc("Site", target_name)
		job.site = site.name
		job.bench = site.bench
		job.server = site.server
	elif target_type == "bench" and target_name:
		bench = frappe.get_doc("Bench", target_name)
		job.bench = bench.name
		job.server = bench.server
	elif target_type == "server" and target_name:
		job.server = target_name
	elif action_key == "site.create" and lock_target_name:
		bench = frappe.get_doc("Bench", lock_target_name)
		job.bench = bench.name
		job.server = bench.server

	job.insert(ignore_permissions=True)
	frappe.db.commit()

	try:
		result = _dispatch(action_key, target_type, target_name, params_dict)
		job.status = "Success" if result.get("ok") else "Failed"
		job.progress = 100
		job.finished_at = now_datetime()
		# Strip one-time secrets from stored output
		store = dict(result)
		for secret_key in ("admin_password", "api_key", "enrollment_token"):
			if secret_key in store:
				store[secret_key] = "***"
		job.output = redact_text(json.dumps(store, indent=2, default=str))
		job.exit_code = 0 if result.get("ok") else 1
		if not result.get("ok"):
			job.error = redact_text(result.get("message") or "Failed")
		if result.get("site") and action_key == "site.create":
			job.site = result["site"]
		job.save(ignore_permissions=True)

		write_audit(
			action_key,
			resource_type=target_type,
			resource_name=target_name or result.get("site_name"),
			status="Success" if result.get("ok") else "Failed",
			message=result.get("message"),
			operation_job=job.name,
			parameters={
				"action": action_key,
				"target_type": target_type,
				"target_name": target_name,
				"params": safe_params,
			},
			after=store,
		)
		result["operation_job"] = job.name
		result["action"] = action
		return result
	except Exception as exc:
		job.status = "Failed"
		job.finished_at = now_datetime()
		job.error = redact_text(str(exc))
		job.exit_code = 1
		job.progress = 100
		job.save(ignore_permissions=True)
		write_audit(
			action_key,
			resource_type=target_type,
			resource_name=target_name,
			status="Failed",
			message=str(exc),
			operation_job=job.name,
		)
		raise


def _dispatch(
	action_key: str,
	target_type: str | None,
	target_name: str | None,
	params: dict | None = None,
) -> dict[str, Any]:
	params = params or {}

	if action_key == "server.discover":
		from frappeops.services.discovery.local import import_local_server

		data = import_local_server()
		return {"ok": True, "message": _("Local discovery completed."), "data": data}

	if action_key == "server.health":
		return _server_health(target_name)

	if action_key == "bench.doctor":
		from frappeops.services.benches.control import run_doctor

		return run_doctor(target_name)

	if action_key == "bench.versions":
		from frappeops.services.benches.control import list_versions

		return list_versions(target_name)

	if action_key == "bench.build":
		from frappeops.services.benches.control import build_assets

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		apps = params.get("apps") or ["frappeops"]
		if isinstance(apps, str):
			apps = [a.strip() for a in apps.replace("\n", ",").split(",") if a.strip()]
		return build_assets(target_name, apps=apps, confirm=confirm)

	if action_key == "bench.restart":
		from frappeops.services.benches.control import restart_bench

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		dry_run = params.get("dry_run") in (True, 1, "1", "true", "yes")
		return restart_bench(
			target_name,
			confirm=confirm,
			typed_confirmation=params.get("typed_confirmation"),
			dry_run=dry_run,
			scope=params.get("scope") or "web_workers",
		)

	if action_key == "site.health":
		return _site_health(target_name)

	if action_key == "site.clear_cache":
		return _site_bench_cmd(target_name, ["clear-cache"], _("Cache cleared for {0}"))

	if action_key == "site.clear_website_cache":
		return _site_bench_cmd(target_name, ["clear-website-cache"], _("Website cache cleared for {0}"))

	if action_key == "site.backup":
		return _site_backup(target_name)

	if action_key == "site.maintenance_on":
		return _site_maintenance(target_name, enable=True)

	if action_key == "site.maintenance_off":
		return _site_maintenance(target_name, enable=False)

	if action_key == "site.migrate":
		from frappeops.services.provisioning.site import migrate_site

		return migrate_site(target_name)

	if action_key == "site.create":
		from frappeops.services.provisioning.site import create_test_site

		apps = params.get("apps") or []
		if isinstance(apps, str):
			apps = [a.strip() for a in apps.split(",") if a.strip()]
		return create_test_site(
			params.get("site_name") or "",
			admin_password=params.get("admin_password"),
			apps=apps,
			mariadb_root_password=params.get("mariadb_root_password"),
			bench_name=target_name,
		)

	if action_key == "app.install":
		from frappeops.services.provisioning.site import install_app_on_site

		return install_app_on_site(target_name, params.get("app") or params.get("app_name") or "")

	if action_key == "app.get":
		from frappeops.services.apps.marketplace import get_app_from_git

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return get_app_from_git(
			git_url=params.get("git_url") or params.get("url"),
			app_name=params.get("app") or params.get("app_name"),
			branch=params.get("branch"),
			catalog_item=params.get("catalog_item") or params.get("catalog"),
			confirm=confirm,
		)

	if action_key == "app.seed_catalog":
		from frappeops.services.apps.marketplace import seed_catalog

		return seed_catalog(overwrite=params.get("overwrite") in (True, 1, "1", "true", "yes"))

	if action_key == "app.list_catalog":
		from frappeops.services.apps.marketplace import list_catalog

		return list_catalog()

	if action_key == "domain.ensure":
		from frappeops.services.nginx.snippets import ensure_domain

		site = params.get("site") or target_name
		domain_name = params.get("domain_name") or params.get("domain")
		if not domain_name or not site:
			return {"ok": False, "message": _("domain_name and site are required")}
		site_doc = frappe.get_doc("Site", site)
		if site_doc.is_protected:
			return {
				"ok": False,
				"message": _("Refused: cannot register managed nginx domains for protected sites."),
			}
		name = ensure_domain(domain_name, site, params.get("domain_type") or "Primary")
		return {"ok": True, "message": _("Domain {0} registered").format(domain_name), "domain": name}

	if action_key == "domain.generate_nginx":
		from frappeops.services.nginx.snippets import generate_nginx

		return generate_nginx(target_name or params.get("domain") or "")

	if action_key == "domain.diff_nginx":
		from frappeops.services.nginx.snippets import diff_nginx

		return diff_nginx(target_name or params.get("domain") or "")

	if action_key == "domain.apply_nginx":
		from frappeops.services.nginx.snippets import apply_nginx

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return apply_nginx(target_name or params.get("domain") or "", confirm=confirm)

	if action_key == "domain.check_dns":
		from frappeops.services.nginx.snippets import check_dns

		return check_dns(target_name or params.get("domain") or "")

	if action_key == "domain.check_http":
		from frappeops.services.nginx.snippets import check_http

		return check_http(target_name or params.get("domain") or "")

	if action_key == "domain.sync_nginx":
		from frappeops.services.nginx.snippets import sync_existing_frappeops_confs

		return sync_existing_frappeops_confs()

	if action_key == "ssl.check_tooling":
		from frappeops.services.ssl.certs import check_tooling

		return check_tooling()

	if action_key == "ssl.diagnose":
		from frappeops.services.ssl.certs import diagnose_domain

		return diagnose_domain(
			domain_name=target_name if target_type == "domain" else params.get("domain"),
			hostname=params.get("hostname") or params.get("domain_name"),
		)

	if action_key == "ssl.inspect":
		from frappeops.services.ssl.certs import inspect_certs

		return inspect_certs(sync_records=True)

	if action_key == "ssl.issue":
		from frappeops.services.ssl.certs import issue_certificate

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		# Default dry_run=True unless explicitly disabled
		dry_run = params.get("dry_run", 1) in (True, 1, "1", "true", "yes", None)
		return issue_certificate(
			target_name or params.get("domain"),
			confirm=confirm,
			typed_confirmation=params.get("typed_confirmation"),
			dry_run=dry_run,
			email=params.get("email"),
		)

	if action_key == "agent.install_local":
		from frappeops.services.agents.local_adapter import install_local_agent

		return install_local_agent(target_name)

	if action_key == "agent.create_token":
		from frappeops.services.agents.enrollment import create_enrollment_token

		return create_enrollment_token(target_name)

	if action_key == "agent.heartbeat":
		from frappeops.services.agents.local_adapter import local_heartbeat
		from frappeops.services.agents.poll import poll_agent

		server = target_name or frappe.db.get_value("Server", {"is_local": 1}, "name")
		server_doc = frappe.get_doc("Server", server) if server else None
		agent_row = frappe.get_all(
			"Server Agent",
			filters={"server": server, "revoked": 0, "listen_url": ["is", "set"]},
			fields=["name", "status", "last_heartbeat", "agent_version"],
			order_by="modified desc",
			limit=1,
		)
		if agent_row:
			return poll_agent(agent_row[0].name, command="health", apply_heartbeat=True)
		if server_doc and server_doc.is_local:
			return local_heartbeat(server)
		agent = frappe.get_all(
			"Server Agent",
			filters={"server": server, "revoked": 0},
			fields=["name", "status", "last_heartbeat", "agent_version"],
			order_by="modified desc",
			limit=1,
		)
		if not agent:
			return {"ok": False, "message": _("No agent enrolled for this server")}
		return {
			"ok": agent[0].status == "Online",
			"message": _("Remote agent status: {0} (last heartbeat {1}; no listen_url for live poll)").format(
				agent[0].status, agent[0].last_heartbeat or "—"
			),
			"agent": agent[0],
		}

	if action_key == "agent.discover":
		from frappeops.services.agents.local_adapter import local_discover
		from frappeops.services.agents.poll import poll_agent

		server = target_name or frappe.db.get_value("Server", {"is_local": 1}, "name")
		server_doc = frappe.get_doc("Server", server)
		# Prefer outbound poll when listen_url is configured
		agent_row = frappe.get_all(
			"Server Agent",
			filters={"server": server, "revoked": 0, "listen_url": ["is", "set"]},
			fields=["name"],
			order_by="modified desc",
			limit=1,
		)
		if agent_row:
			return poll_agent(agent_row[0].name, command="discover", apply_heartbeat=True)
		if server_doc.is_local:
			return local_discover(server)
		return {
			"ok": False,
			"message": _("No listen_url for remote agent. Set Listen URL or start a remote agentd."),
		}

	if action_key == "agent.poll":
		from frappeops.services.agents.poll import poll_agent

		return poll_agent(
			target_name or params.get("agent"),
			command=params.get("command") or "health",
			params=params.get("command_params") if isinstance(params.get("command_params"), dict) else None,
			apply_heartbeat=True,
		)

	if action_key == "agent.install_remote_sim":
		from frappeops.services.agents.remote_sim import install_remote_sim_agent

		return install_remote_sim_agent(port=int(params.get("port") or 18766))

	if action_key == "ai.configure_cloud":
		from frappeops.services.ai.cloud_setup import configure_cloud_provider

		return configure_cloud_provider(
			provider_name=params.get("provider_name") or "OpenAI Cloud",
			api_base_url=params.get("api_base_url") or "https://api.openai.com/v1",
			default_model=params.get("default_model") or "gpt-4o-mini",
			api_key=params.get("api_key"),
			enable_public_urls=params.get("enable_public_urls", 1) in (True, 1, "1", "true", "yes", None),
			test=params.get("test", 1) in (True, 1, "1", "true", "yes", None),
		)

	if action_key == "agent.start_listener":
		from frappeops.services.agents.listener_mgr import start_local_listener

		return start_local_listener(
			target_name or params.get("agent"),
			port=int(params.get("port") or 18765),
		)

	if action_key == "agent.stop_listener":
		from frappeops.services.agents.listener_mgr import stop_local_listener

		return stop_local_listener(target_name or params.get("agent"))

	if action_key == "agent.revoke":
		from frappeops.services.agents.enrollment import revoke_agent

		agent_name = target_name or params.get("agent")
		if not agent_name and params.get("server"):
			agent_name = frappe.db.get_value(
				"Server Agent",
				{"server": params.get("server"), "revoked": 0},
				"name",
				order_by="modified desc",
			)
		if not agent_name:
			return {"ok": False, "message": _("Agent name required")}
		return revoke_agent(agent_name)

	if action_key == "deploy.site_pipeline":
		from frappeops.services.deployments.pipeline import run_site_pipeline

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		run_migrate = params.get("run_migrate", 1) in (True, 1, "1", "true", "yes", None)
		run_build = params.get("run_build") in (True, 1, "1", "true", "yes")
		return run_site_pipeline(
			target_name,
			confirm=confirm,
			run_migrate=run_migrate,
			run_build=run_build,
			apps_to_build=params.get("apps_to_build"),
			deployment_name=params.get("deployment_name"),
		)

	if action_key == "deploy.rollback":
		from frappeops.services.backups.restore import rollback_deployment

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return rollback_deployment(
			target_name or params.get("deployment"),
			confirm=confirm,
			typed_confirmation=params.get("typed_confirmation"),
		)

	if action_key == "backup.restore":
		from frappeops.services.backups.restore import restore_backup

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return restore_backup(
			target_name or params.get("backup"),
			site=params.get("site"),
			confirm=confirm,
			typed_confirmation=params.get("typed_confirmation"),
			take_pre_backup=params.get("take_pre_backup", 1) in (True, 1, "1", "true", "yes", None),
		)

	if action_key == "backup.retention_scan":
		from frappeops.services.backups.retention import scan_expired

		return scan_expired()

	if action_key == "backup.purge_expired":
		from frappeops.services.backups.retention import purge_expired

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return purge_expired(confirm=confirm, typed_confirmation=params.get("typed_confirmation"))

	if action_key == "monitor.poll":
		from frappeops.services.monitoring.alerts import poll_and_alert

		return poll_and_alert()

	if action_key == "ai.create_task":
		from frappeops.services.ai.workflow import create_ai_task

		return create_ai_task(
			params.get("description") or params.get("task_description") or "",
			title=params.get("title"),
			site=params.get("site"),
			server=target_name,
			provider=params.get("provider"),
		)

	if action_key == "ai.plan":
		from frappeops.services.ai.workflow import plan_ai_task

		use_local = params.get("use_local") in (True, 1, "1", "true", "yes")
		return plan_ai_task(target_name or params.get("ai_task"), use_local=use_local)

	if action_key == "ai.test_provider":
		from frappeops.services.ai.providers import test_provider

		return test_provider(params.get("provider") or target_name)

	if action_key == "ai.submit":
		from frappeops.services.ai.workflow import submit_ai_task

		return submit_ai_task(target_name or params.get("ai_task"))

	if action_key == "ai.approve":
		from frappeops.services.ai.workflow import approve_ai_task

		return approve_ai_task(target_name or params.get("ai_task"))

	if action_key == "ai.execute":
		from frappeops.services.ai.workflow import execute_ai_task

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return execute_ai_task(target_name or params.get("ai_task"), confirm=confirm)

	if action_key == "backup.upload_offsite":
		from frappeops.services.backups.offsite import upload_backup

		confirm = params.get("confirm") in (True, 1, "1", "true", "yes")
		return upload_backup(
			target_name or params.get("backup"),
			destination=params.get("destination") or params.get("backup_destination"),
			confirm=confirm,
		)

	if action_key == "backup.test_destination":
		from frappeops.services.backups.offsite import test_destination

		dest = params.get("destination") or params.get("backup_destination") or target_name
		return test_destination(dest)

	if action_key == "server.register_vps":
		from frappeops.services.agents.remote_status import register_vps

		return register_vps(
			server_name=params.get("server_name") or params.get("name") or "",
			ip_address=params.get("ip_address") or params.get("ip") or "",
			hostname=params.get("hostname"),
			provider=params.get("provider"),
			region=params.get("region"),
			ssh_port=int(params.get("ssh_port") or 22),
			create_token=params.get("create_token", 1) in (True, 1, "1", "true", "yes", None),
			notes=params.get("notes"),
		)

	if action_key == "server.status":
		from frappeops.services.agents.remote_status import get_server_status

		return get_server_status(target_name or params.get("server"))

	if action_key == "agent.install_script":
		from frappeops.services.agents.remote_status import generate_install_script

		return generate_install_script(
			server=target_name or params.get("server"),
			enrollment_token=params.get("enrollment_token") or params.get("token"),
			control_url=params.get("control_url"),
			bench_path=params.get("bench_path") or "/home/frappe/frappe-bench",
			listen_port=int(params.get("listen_port") or 18765),
		)

	return {"ok": False, "message": _("Action not implemented."), "status": "not_implemented"}


def _server_health(server_name: str | None) -> dict[str, Any]:
	if not server_name:
		server_name = frappe.db.get_value("Server", {"is_local": 1}, "name")
	if not server_name:
		return {"ok": False, "message": _("No server selected.")}

	server = frappe.get_doc("Server", server_name)
	# Remote servers: prefer agent heartbeat/poll — never report control-plane disk as theirs
	if not server.is_local:
		from frappeops.services.agents.poll import poll_agent
		from frappeops.services.agents.remote_status import get_server_status

		agent_row = frappe.get_all(
			"Server Agent",
			filters={"server": server.name, "revoked": 0},
			fields=["name", "listen_url", "status", "last_heartbeat"],
			order_by="modified desc",
			limit=1,
		)
		if agent_row and agent_row[0].get("listen_url"):
			polled = poll_agent(agent_row[0].name, command="health", apply_heartbeat=True)
			status = get_server_status(server.name)
			return {
				"ok": bool(polled.get("ok")),
				"message": polled.get("message") or _("Remote health via agent"),
				"poll": polled,
				"status": status.get("status"),
			}
		status = get_server_status(server.name)
		return {
			"ok": True,
			"message": _(
				"Remote server — showing last agent facts (no listen_url). "
				"Install agent / set Listen URL for live polls."
			),
			"status": status.get("status"),
			"stale": True,
		}

	bench_path = frappe.db.get_value("Bench", {"server": server.name}, "bench_path") or "/"
	try:
		disk = shutil.disk_usage(bench_path if os.path.isdir(bench_path) else "/")
	except Exception:
		disk = shutil.disk_usage("/")

	disk_percent = round((disk.used / disk.total) * 100, 1) if disk.total else 0
	meminfo = _read_meminfo()
	loadavg = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)

	status = "Healthy"
	if disk_percent >= 90 or meminfo.get("used_percent", 0) >= 95:
		status = "Critical"
	elif disk_percent >= 80 or meminfo.get("used_percent", 0) >= 85:
		status = "Warning"

	details = {
		"disk_percent": disk_percent,
		"disk_free_gb": round(disk.free / (1024**3), 2),
		"ram_percent": meminfo.get("used_percent"),
		"load_average": ",".join(f"{x:.2f}" for x in loadavg),
	}

	health = frappe.get_doc(
		{
			"doctype": "Server Health",
			"server": server.name,
			"status": status,
			"checked_at": now_datetime(),
			"ram_percent": details["ram_percent"],
			"disk_percent": disk_percent,
			"load_average": details["load_average"],
			"details_json": json.dumps(details, indent=2),
		}
	)
	health.insert(ignore_permissions=True)

	server.status = "Online" if status != "Critical" else "Offline"
	server.disk_used_percent = disk_percent
	server.last_health_check = now_datetime()
	server.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Server health: {0}").format(status),
		"status": status,
		"details": details,
		"health_record": health.name,
	}


def _site_health(site_name: str | None) -> dict[str, Any]:
	if not site_name:
		return {"ok": False, "message": _("No site selected.")}
	site = frappe.get_doc("Site", site_name)

	import urllib.request

	http_status = None
	database_ok = 0
	try:
		req = urllib.request.Request(
			"http://127.0.0.1/api/method/frappe.ping",
			headers={"Host": site.site_name},
			method="GET",
		)
		with urllib.request.urlopen(req, timeout=8) as resp:
			http_status = resp.status
	except Exception as exc:
		http_status = 0
		ping_error = str(exc)
	else:
		ping_error = None

	try:
		proc = run_bench(["--site", site.site_name, "list-apps"], timeout=60, check=False)
		out = proc.stdout or ""
		database_ok = 1 if proc.returncode == 0 and out.strip() else 0
	except Exception:
		database_ok = 0
		out = ""

	status = "Healthy"
	if http_status != 200 or not database_ok:
		status = "Critical" if http_status == 0 else "Warning"

	details = {
		"http_status": http_status,
		"database_ok": bool(database_ok),
		"ping_error": ping_error,
		"list_apps_preview": redact_text((out or "")[:500]),
	}
	health = frappe.get_doc(
		{
			"doctype": "Site Health",
			"site": site.name,
			"status": status,
			"checked_at": now_datetime(),
			"http_status": http_status,
			"database_ok": database_ok,
			"details_json": json.dumps(details, indent=2),
		}
	)
	health.insert(ignore_permissions=True)

	site.status = status
	site.last_health_check = now_datetime()
	site.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Site health: {0}").format(status),
		"status": status,
		"details": details,
		"health_record": health.name,
	}


def _site_bench_cmd(site_name: str | None, args: list[str], ok_msg_template) -> dict[str, Any]:
	if not site_name:
		return {"ok": False, "message": _("No site selected.")}
	site = frappe.get_doc("Site", site_name)
	try:
		proc = run_bench(["--site", site.site_name, *args], timeout=180, check=False)
		out = proc.stdout or ""
		if proc.returncode != 0:
			return {
				"ok": False,
				"message": _("Command failed: {0}").format(" ".join(args)),
				"output": redact_text(out[-2000:]),
			}
		return {
			"ok": True,
			"message": ok_msg_template.format(site.site_name),
			"output": redact_text(out[-2000:]),
		}
	except Exception as exc:
		return {
			"ok": False,
			"message": _("Command failed: {0}").format(" ".join(args)),
			"output": redact_text(str(exc)),
		}


def _site_backup(site_name: str | None) -> dict[str, Any]:
	if not site_name:
		return {"ok": False, "message": _("No site selected.")}
	site = frappe.get_doc("Site", site_name)
	bench_path = Path(frappe.utils.get_bench_path())
	backups_dir = bench_path / "sites" / site.site_name / "private" / "backups"
	before = set(backups_dir.glob("*")) if backups_dir.exists() else set()

	backup_doc = frappe.get_doc(
		{
			"doctype": "Backup",
			"backup_name": f"{site.site_name}-{now_datetime().strftime('%Y%m%d-%H%M%S')}",
			"status": "Running",
			"server": site.server,
			"bench": site.bench,
			"site": site.name,
			"backup_type": "Full",
			"taken_at": now_datetime(),
		}
	)
	backup_doc.insert(ignore_permissions=True)

	try:
		proc = run_bench(
			["--site", site.site_name, "backup", "--with-files"],
			timeout=900,
			check=False,
		)
		out = proc.stdout or ""
		if proc.returncode != 0:
			backup_doc.status = "Failed"
			backup_doc.notes = redact_text(out[-1500:])
			backup_doc.save(ignore_permissions=True)
			return {
				"ok": False,
				"message": _("Backup failed for {0}").format(site.site_name),
				"backup": backup_doc.name,
				"output": redact_text(out[-2000:]),
			}
	except Exception as exc:
		backup_doc.status = "Failed"
		backup_doc.notes = redact_text(str(exc))
		backup_doc.save(ignore_permissions=True)
		return {
			"ok": False,
			"message": _("Backup failed for {0}").format(site.site_name),
			"backup": backup_doc.name,
			"output": redact_text(str(exc)),
		}

	after = set(backups_dir.glob("*")) if backups_dir.exists() else set()
	new_files = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
	size_mb = round(sum(p.stat().st_size for p in new_files) / (1024 * 1024), 2) if new_files else 0
	primary = next((p for p in new_files if p.name.endswith(".sql.gz")), new_files[0] if new_files else None)

	backup_doc.status = "Success"
	backup_doc.storage_location = str(primary) if primary else str(backups_dir)
	backup_doc.size_mb = size_mb
	backup_doc.taken_at = now_datetime()
	backup_doc.notes = _("Created {0} file(s)").format(len(new_files))
	if primary and Path(primary).is_file():
		try:
			from frappeops.services.backups.offsite import sha256_file

			backup_doc.checksum = sha256_file(Path(primary))
		except Exception:
			pass
	backup_doc.save(ignore_permissions=True)

	result = {
		"ok": True,
		"message": _("Backup completed for {0} ({1} MB)").format(site.site_name, size_mb),
		"backup": backup_doc.name,
		"files": [str(p) for p in new_files[:20]],
		"output": redact_text(out[-2000:]),
	}
	try:
		from frappeops.services.backups.offsite import maybe_auto_upload

		offsite = maybe_auto_upload(backup_doc.name)
		if offsite is not None:
			result["offsite"] = offsite
			if not offsite.get("ok"):
				result["message"] = _(
					"Backup completed locally; offsite upload issue: {0}"
				).format(offsite.get("message") or _("failed"))
	except Exception as exc:
		result["offsite"] = {"ok": False, "message": redact_text(str(exc))}
	return result


def _site_maintenance(site_name: str | None, enable: bool) -> dict[str, Any]:
	if not site_name:
		return {"ok": False, "message": _("No site selected.")}
	site = frappe.get_doc("Site", site_name)
	value = "1" if enable else "0"
	proc = run_bench(
		["--site", site.site_name, "set-maintenance-mode", value],
		timeout=120,
		check=False,
	)
	out = proc.stdout or ""
	if proc.returncode != 0:
		return {
			"ok": False,
			"message": _("Failed to change maintenance mode"),
			"output": redact_text(out[-2000:]),
		}

	site.maintenance_mode = 1 if enable else 0
	site.status = "Maintenance" if enable else site.status
	if not enable and site.status == "Maintenance":
		site.status = "Unknown"
	site.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Maintenance mode {0} for {1}").format(
			_("enabled") if enable else _("disabled"), site.site_name
		),
		"output": redact_text(out[-1000:]),
	}


def _read_meminfo() -> dict[str, float]:
	try:
		data = {}
		with open("/proc/meminfo", encoding="utf-8") as f:
			for line in f:
				parts = line.split()
				if len(parts) >= 2:
					data[parts[0].rstrip(":")] = float(parts[1])
		total = data.get("MemTotal", 0)
		avail = data.get("MemAvailable", 0)
		used_percent = round(((total - avail) / total) * 100, 1) if total else 0
		return {"used_percent": used_percent}
	except Exception:
		return {"used_percent": 0}


def _require_operator():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not roles.intersection(
		{"FrappeOps Administrator", "FrappeOps Operator", "System Manager"}
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
