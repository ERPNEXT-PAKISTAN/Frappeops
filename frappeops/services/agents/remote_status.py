# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Register remote VPS servers and surface complete agent status."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_url, now_datetime

from frappeops.services.agents.enrollment import create_enrollment_token


def register_vps(
	*,
	server_name: str,
	ip_address: str,
	hostname: str | None = None,
	provider: str | None = None,
	region: str | None = None,
	ssh_port: int | None = 22,
	create_token: bool = True,
	notes: str | None = None,
) -> dict[str, Any]:
	"""Create/update a non-local Server inventory row (Contabo, Hetzner, etc.)."""
	server_name = (server_name or "").strip()
	ip_address = (ip_address or "").strip()
	if not server_name or not ip_address:
		return {"ok": False, "message": _("server_name and ip_address are required")}

	settings = frappe.get_single("FrappeOps Settings")
	if not getattr(settings, "enable_remote_agents", 0):
		return {
			"ok": False,
			"status": "blocked",
			"message": _("Enable Remote Agents in FrappeOps Settings first."),
			"needs": ["enable_remote_agents"],
		}

	org = frappe.db.get_value("Organization", {}, "name")
	name = frappe.db.get_value("Server", {"ip_address": ip_address}, "name") or frappe.db.get_value(
		"Server", {"server_name": server_name}, "name"
	)
	payload = {
		"server_name": server_name,
		"hostname": (hostname or server_name).strip(),
		"ip_address": ip_address,
		"server_type": "VPS",
		"status": "Unknown",
		"enabled": 1,
		"is_local": 0,
		"ssh_port": ssh_port or 22,
		"provider": (provider or "").strip() or None,
		"region": (region or "").strip() or None,
		"notes": notes
		or _("Registered via FrappeOps. Install agent with enrollment token for live status."),
	}
	if org:
		payload["organization"] = org

	if name:
		doc = frappe.get_doc("Server", name)
		for k, v in payload.items():
			if v is not None and hasattr(doc, k):
				setattr(doc, k, v)
		doc.is_local = 0
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Server", **{k: v for k, v in payload.items() if v is not None}})
		doc.insert(ignore_permissions=True)
		name = doc.name

	frappe.db.commit()
	out: dict[str, Any] = {
		"ok": True,
		"message": _("VPS server inventoried"),
		"server": name,
		"server_name": server_name,
		"ip_address": ip_address,
	}
	if create_token:
		tok = create_enrollment_token(name, agent_name=f"{server_name}-agent")
		out["enrollment"] = {
			"agent": tok.get("agent"),
			"enrollment_token": tok.get("enrollment_token"),
			"expires_at": tok.get("expires_at"),
			"enroll_endpoint": tok.get("enroll_endpoint"),
		}
		out["install_script"] = generate_install_script(
			server=name,
			enrollment_token=tok.get("enrollment_token"),
		).get("script")
	return out


def generate_install_script(
	*,
	server: str | None = None,
	enrollment_token: str | None = None,
	control_url: str | None = None,
	bench_path: str = "/home/frappe/frappe-bench",
	listen_port: int = 18765,
) -> dict[str, Any]:
	"""Return a bash snippet to enroll + run agentd on a remote VPS."""
	control_url = (control_url or get_url()).rstrip("/")
	token = enrollment_token or ""
	if not token and server:
		# Do not invent tokens — operator must create_token first
		pending = frappe.get_all(
			"Server Agent",
			filters={"server": server, "status": "Pending", "revoked": 0},
			fields=["name", "enrollment_token_hint"],
			limit=1,
		)
		if pending:
			return {
				"ok": False,
				"message": _(
					"Pending agent {0} exists ({1}) but token is shown only once. "
					"Create a new enrollment token."
				).format(pending[0].name, pending[0].enrollment_token_hint),
				"needs": ["enrollment_token"],
			}

	script = f"""#!/usr/bin/env bash
set -euo pipefail
# FrappeOps remote agent bootstrap (Contabo / any VPS)
CONTROL_URL="{control_url}"
TOKEN="{token}"
BENCH_PATH="{bench_path}"
LISTEN_PORT="{listen_port}"
AGENT_DIR="$BENCH_PATH/config/frappeops-agent"
mkdir -p "$AGENT_DIR"

HOST_NAME="$(hostname)"
RESP=$(curl -fsS -X POST "$CONTROL_URL/api/method/frappeops.api.agent.enroll" \\
  -H "Content-Type: application/json" \\
  -d "{{\\"token\\":\\"$TOKEN\\",\\"hostname\\":\\"$HOST_NAME\\",\\"agent_version\\":\\"0.2\\"}}")
echo "$RESP" > "$AGENT_DIR/enroll.json"
API_KEY=$(RESP="$RESP" python3 -c 'import json,os; d=json.loads(os.environ["RESP"]); m=d.get("message") or d; print(m.get("api_key") or "")')
if [[ -z "$API_KEY" ]]; then
  echo "Enrollment failed — check token / control URL reachability from this VPS" >&2
  cat "$AGENT_DIR/enroll.json" >&2 || true
  exit 1
fi

RESP="$RESP" API_KEY="$API_KEY" CONTROL_URL="$CONTROL_URL" BENCH_PATH="$BENCH_PATH" LISTEN_PORT="$LISTEN_PORT" AGENT_DIR="$AGENT_DIR" python3 - <<'PY'
import json, os
cfg = {{
  "api_key": os.environ["API_KEY"],
  "control_url": os.environ["CONTROL_URL"],
  "bench_path": os.environ["BENCH_PATH"],
  "listen_host": "0.0.0.0",
  "listen_port": int(os.environ["LISTEN_PORT"]),
}}
path = os.path.join(os.environ["AGENT_DIR"], "agent.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
os.chmod(path, 0o600)
print("Wrote", path)
PY

curl -fsS -X POST "$CONTROL_URL/api/method/frappeops.api.agent.heartbeat" \\
  -H "Content-Type: application/json" \\
  -d "{{\\"api_key\\":\\"$API_KEY\\"}}" || true

AGENTD="$BENCH_PATH/apps/frappeops/agent/frappeops_agentd.py"
if [[ -f "$AGENTD" ]]; then
  export FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK=1
  nohup python3 "$AGENTD" --config "$AGENT_DIR/agent.json" >"$AGENT_DIR/agentd.log" 2>&1 &
  echo "agentd started pid $!"
else
  echo "Copy apps/frappeops/agent/frappeops_agentd.py to this host, then:"
  echo "  FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK=1 python3 frappeops_agentd.py --config $AGENT_DIR/agent.json"
fi

echo "Done. On control plane: set Server Agent Listen URL to http://THIS_VPS_IP:$LISTEN_PORT"
echo "Enable Poll Enabled + FrappeOps Settings → Allow Public Agent URLs (if public IP)."
"""
	return {
		"ok": True,
		"message": _("Install script generated"),
		"control_url": control_url,
		"script": script,
		"server": server,
	}


def get_server_status(server: str) -> dict[str, Any]:
	"""Aggregate Server + Agent + latest Health + remote site list from facts."""
	if not server or not frappe.db.exists("Server", server):
		return {"ok": False, "message": _("Server not found")}

	doc = frappe.get_doc("Server", server)
	agents = frappe.get_all(
		"Server Agent",
		filters={"server": server, "revoked": 0},
		fields=[
			"name",
			"agent_name",
			"status",
			"listen_url",
			"poll_enabled",
			"last_poll_at",
			"last_poll_status",
			"last_heartbeat",
			"agent_version",
			"permission_scope",
		],
		order_by="modified desc",
	)
	health = frappe.get_all(
		"Server Health",
		filters={"server": server},
		fields=[
			"name",
			"status",
			"checked_at",
			"cpu_percent",
			"ram_percent",
			"disk_percent",
			"load_average",
			"details_json",
		],
		order_by="creation desc",
		limit_page_length=1,
	)
	latest = health[0] if health else None
	facts = {}
	if latest and latest.get("details_json"):
		try:
			facts = json.loads(latest["details_json"])
		except Exception:
			facts = {}

	sites = frappe.get_all(
		"Site",
		filters={"server": server},
		fields=["name", "site_name", "status", "is_protected", "installed_apps", "primary_domain"],
		limit_page_length=100,
	)
	benches = frappe.get_all(
		"Bench",
		filters={"server": server},
		fields=["name", "bench_name", "status", "bench_path", "frappe_version"],
		limit_page_length=20,
	)

	online = any((a.get("status") or "").lower() == "online" for a in agents)
	complete = {
		"identity": {
			"name": doc.name,
			"server_name": doc.server_name,
			"hostname": doc.hostname,
			"ip_address": doc.ip_address,
			"provider": getattr(doc, "provider", None),
			"region": getattr(doc, "region", None),
			"server_type": doc.server_type,
			"is_local": doc.is_local,
			"ssh_port": doc.ssh_port,
		},
		"status": doc.status,
		"agent_status": doc.agent_status,
		"agent_version": doc.agent_version,
		"last_heartbeat": str(doc.last_heartbeat) if doc.last_heartbeat else None,
		"last_health_check": str(doc.last_health_check) if doc.last_health_check else None,
		"resources": {
			"disk_gb": doc.disk_gb,
			"disk_used_percent": doc.disk_used_percent,
			"ram_gb": getattr(doc, "ram_gb", None),
			"cpu_cores": getattr(doc, "cpu_cores", None),
			"os": getattr(doc, "operating_system", None),
			"architecture": getattr(doc, "architecture", None),
		},
		"agents": agents,
		"health": latest,
		"facts": {
			"sites": facts.get("sites") or [],
			"apps": facts.get("apps") or [],
			"bench_path": facts.get("bench_path"),
			"load_average": facts.get("load_average"),
			"public_ip": facts.get("public_ip"),
		},
		"inventory_sites": sites,
		"inventory_benches": benches,
		"agent_online": online,
		"checked_at": str(now_datetime()),
	}
	return {
		"ok": True,
		"message": _("Server status for {0}").format(doc.server_name or server),
		"server": server,
		"status": complete,
	}
