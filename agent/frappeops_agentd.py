#!/usr/bin/env python3
# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Standalone FrappeOps agent listener (control-plane outbound poll target).

Scoped commands only. Bind to loopback by default.
Config JSON (mode 0600):
  {"api_key":"...", "bench_path":"/path", "bind":"127.0.0.1", "port":18765}
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import shutil
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

AGENT_VERSION = "0.2.0"
ALLOWED_COMMANDS = {"ping", "health", "discover", "list_sites", "heartbeat"}


def load_config(path: Path) -> dict[str, Any]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if not data.get("api_key"):
		raise SystemExit("config missing api_key")
	return data


def collect_facts(bench_path: str | None) -> dict[str, Any]:
	bench = Path(bench_path or os.environ.get("FRAPPEOPS_BENCH_PATH") or ".")
	if not (bench / "sites").exists():
		candidate = Path("/home/frappe/frappe-bench")
		if (candidate / "sites").exists():
			bench = candidate
	disk = shutil.disk_usage(str(bench if bench.exists() else "/"))
	mem = _meminfo()
	load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
	sites = []
	sites_dir = bench / "sites"
	if sites_dir.is_dir():
		for child in sorted(sites_dir.iterdir()):
			if child.is_dir() and (child / "site_config.json").exists():
				sites.append(child.name)
	apps = []
	apps_dir = bench / "apps"
	if apps_dir.is_dir():
		apps = sorted([p.name for p in apps_dir.iterdir() if p.is_dir()])
	return {
		"agent_version": AGENT_VERSION,
		"hostname": socket.gethostname(),
		"fqdn": socket.getfqdn(),
		"os": f"{platform.system()} {platform.release()}",
		"architecture": platform.machine(),
		"python_version": platform.python_version(),
		"bench_path": str(bench),
		"disk_total_gb": round(disk.total / (1024**3), 2),
		"disk_used_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
		"ram_percent": mem.get("used_percent"),
		"load_average": [round(x, 2) for x in load],
		"sites": sites,
		"apps": apps,
		"site_count": len(sites),
		"app_count": len(apps),
	}


def _meminfo() -> dict[str, float]:
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


def make_handler(config: dict[str, Any]):
	api_key = str(config["api_key"])
	bench_path = config.get("bench_path")

	class Handler(BaseHTTPRequestHandler):
		server_version = f"FrappeOpsAgent/{AGENT_VERSION}"

		def log_message(self, fmt: str, *args) -> None:
			sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

		def _auth_ok(self) -> bool:
			auth = self.headers.get("Authorization") or ""
			token = ""
			if auth.lower().startswith("bearer "):
				token = auth[7:].strip()
			if not token:
				token = self.headers.get("X-FrappeOps-Key") or ""
			return bool(token) and hmac.compare_digest(token, api_key)

		def _json(self, code: int, payload: dict[str, Any]) -> None:
			body = json.dumps(payload).encode("utf-8")
			self.send_response(code)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)

		def do_GET(self) -> None:
			path = urlparse(self.path).path.rstrip("/") or "/"
			if path in ("/", "/v1/ping", "/health"):
				if not self._auth_ok():
					self._json(401, {"ok": False, "message": "unauthorized"})
					return
				self._json(200, {"ok": True, "agent_version": AGENT_VERSION, "command": "ping"})
				return
			self._json(404, {"ok": False, "message": "not found"})

		def do_POST(self) -> None:
			path = urlparse(self.path).path.rstrip("/") or "/"
			if path not in ("/v1/execute", "/execute"):
				self._json(404, {"ok": False, "message": "not found"})
				return
			if not self._auth_ok():
				self._json(401, {"ok": False, "message": "unauthorized"})
				return
			length = int(self.headers.get("Content-Length") or 0)
			raw = self.rfile.read(max(0, min(length, 1_000_000)))
			try:
				payload = json.loads(raw.decode("utf-8") or "{}")
			except Exception:
				self._json(400, {"ok": False, "message": "invalid json"})
				return
			command = str(payload.get("command") or "").strip()
			if command not in ALLOWED_COMMANDS:
				self._json(400, {"ok": False, "message": f"disallowed command: {command}"})
				return
			facts = collect_facts(bench_path)
			if command == "ping":
				self._json(200, {"ok": True, "agent_version": AGENT_VERSION})
				return
			if command in ("health", "heartbeat", "discover"):
				self._json(
					200,
					{
						"ok": True,
						"command": command,
						"facts": facts,
						"message": f"{command} ok",
					},
				)
				return
			if command == "list_sites":
				self._json(
					200,
					{
						"ok": True,
						"command": command,
						"sites": facts.get("sites") or [],
						"bench_path": facts.get("bench_path"),
					},
				)
				return
			self._json(400, {"ok": False, "message": "not implemented"})

	return Handler


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="FrappeOps agent listener")
	parser.add_argument("--config", required=True, help="Path to agent config JSON")
	args = parser.parse_args(argv)
	config = load_config(Path(args.config))
	bind = config.get("bind") or "127.0.0.1"
	port = int(config.get("port") or 18765)
	# Hard safety: refuse non-loopback bind unless FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK=1
	if bind not in ("127.0.0.1", "localhost", "::1") and os.environ.get(
		"FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK"
	) != "1":
		print("Refusing non-loopback bind without FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK=1", file=sys.stderr)
		return 2
	handler = make_handler(config)
	httpd = ThreadingHTTPServer((bind, port), handler)
	print(f"frappeops-agentd {AGENT_VERSION} listening on http://{bind}:{port}", flush=True)
	try:
		httpd.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		httpd.server_close()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
