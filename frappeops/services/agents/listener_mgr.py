# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Start/stop local loopback agent listener for outbound poll tests."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import frappe
from frappe import _

from frappeops.services.agents.poll import poll_agent, set_listen_url

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 18765


def agent_dir() -> Path:
	path = Path(frappe.utils.get_bench_path()) / "config" / "frappeops-agent"
	path.mkdir(parents=True, exist_ok=True)
	return path


def daemon_script() -> Path:
	return Path(frappe.get_app_path("frappeops")).parent / "agent" / "frappeops_agentd.py"


def start_local_listener(
	agent_name: str | None = None,
	*,
	port: int = DEFAULT_PORT,
	bind: str = DEFAULT_BIND,
) -> dict[str, Any]:
	"""Write config, start loopback agentd, set listen_url, smoke-poll."""
	_require_admin()
	agent = _resolve_agent(agent_name)
	server = frappe.get_doc("Server", agent.server)
	allow_sim = (server.ip_address or "") in ("127.0.0.1", "localhost") and bind in (
		"127.0.0.1",
		"localhost",
		"::1",
	)
	if not server.is_local and not allow_sim:
		return {
			"ok": False,
			"message": _(
				"Start Local Listener only works for the local server agent (or loopback remote-sim)."
			),
		}

	api_key = _ensure_api_key(agent, server.name)
	if not api_key:
		return {
			"ok": False,
			"message": _("No API key available. Run Install Local Agent first."),
		}

	script = daemon_script()
	if not script.is_file():
		return {"ok": False, "message": _("Agent daemon script missing: {0}").format(script)}

	cfg_path = agent_dir() / f"{agent.name}.json"
	pid_path = agent_dir() / f"{agent.name}.pid"
	log_path = agent_dir() / f"{agent.name}.log"

	# Stop previous if running
	stop_local_listener(agent.name, quiet=True)

	cfg = {
		"api_key": api_key,
		"bench_path": frappe.utils.get_bench_path(),
		"bind": bind,
		"port": int(port),
		"agent": agent.name,
		"server": server.name,
	}
	cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
	os.chmod(cfg_path, 0o600)

	import sys

	python = str(Path(frappe.utils.get_bench_path()) / "env" / "bin" / "python")
	if not Path(python).is_file():
		python = sys.executable
	with open(log_path, "ab") as logf:
		proc = subprocess.Popen(
			[python, str(script), "--config", str(cfg_path)],
			stdout=logf,
			stderr=subprocess.STDOUT,
			cwd=str(frappe.utils.get_bench_path()),
			start_new_session=True,
		)
	pid_path.write_text(str(proc.pid), encoding="utf-8")

	listen_url = f"http://{bind}:{int(port)}"
	set_listen_url(agent.name, listen_url, poll_enabled=True)
	frappe.db.commit()

	# Wait briefly for bind (do not abort start if early pings fail)
	deadline = time.time() + 5
	last: dict[str, Any] | None = None
	while time.time() < deadline:
		try:
			last = poll_agent(agent.name, command="ping", apply_heartbeat=False)
			frappe.db.commit()
			if last.get("ok"):
				break
		except Exception as exc:
			last = {"ok": False, "message": str(exc)}
		time.sleep(0.4)

	return {
		"ok": bool(last and last.get("ok")),
		"message": _("Local agent listener started on {0}").format(listen_url)
		if last and last.get("ok")
		else _("Listener started but ping failed: {0}").format((last or {}).get("message")),
		"agent": agent.name,
		"listen_url": listen_url,
		"pid": proc.pid,
		"config": str(cfg_path),
		"ping": last,
	}


def stop_local_listener(agent_name: str | None = None, *, quiet: bool = False) -> dict[str, Any]:
	_require_admin()
	agent = _resolve_agent(agent_name)
	pid_path = agent_dir() / f"{agent.name}.pid"
	stopped = False
	if pid_path.exists():
		try:
			pid = int(pid_path.read_text(encoding="utf-8").strip())
			os.kill(pid, signal.SIGTERM)
			stopped = True
		except Exception:
			pass
		try:
			pid_path.unlink(missing_ok=True)
		except Exception:
			pass

	# Disable poll when stopped (listen_url kept for re-start)
	agent.reload()
	agent.poll_enabled = 0
	agent.last_poll_status = "Listener stopped"
	agent.save(ignore_permissions=True)

	if quiet:
		return {"ok": True, "stopped": stopped}
	return {
		"ok": True,
		"message": _("Local listener stop requested"),
		"agent": agent.name,
		"stopped": stopped,
	}


def _ensure_api_key(agent, server_name: str) -> str | None:
	try:
		key = agent.get_password("api_key_secret")
		if key:
			return key
	except Exception:
		pass
	cached = frappe.cache.get_value(f"frappeops:local_agent_key:{server_name}")
	if cached:
		agent.api_key_secret = cached
		agent.save(ignore_permissions=True)
		frappe.db.commit()
		return cached
	return None


def _resolve_agent(agent_name: str | None):
	name = agent_name
	if not name:
		local_server = frappe.db.get_value("Server", {"is_local": 1}, "name")
		name = frappe.db.get_value(
			"Server Agent",
			{"server": local_server, "revoked": 0},
			"name",
			order_by="modified desc",
		)
	if not name:
		frappe.throw(_("No local Server Agent. Install Local Agent first."))
	return frappe.get_doc("Server Agent", name)


def _require_admin():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "FrappeOps Administrator", "FrappeOps Operator"}):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
