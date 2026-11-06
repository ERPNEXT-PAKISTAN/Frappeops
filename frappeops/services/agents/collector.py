# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Host facts collected by the FrappeOps agent (local or remote process)."""

from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Any

from frappeops.services.agents.protocol import AGENT_VERSION


def collect_host_facts(bench_path: str | None = None) -> dict[str, Any]:
	"""Read-only host snapshot for heartbeat / discovery."""
	bench = Path(bench_path or os.environ.get("FRAPPEOPS_BENCH_PATH") or os.getcwd())
	# Prefer common bench layout
	if not (bench / "sites").exists():
		candidate = Path("/home/frappe/frappe-bench")
		if (candidate / "sites").exists():
			bench = candidate

	disk = shutil.disk_usage(str(bench if bench.exists() else "/"))
	mem = _meminfo()
	load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
	cpu_cores = os.cpu_count() or 0

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
		"kernel": platform.release(),
		"architecture": platform.machine(),
		"python_version": platform.python_version(),
		"bench_path": str(bench),
		"disk_total_gb": round(disk.total / (1024**3), 2),
		"disk_used_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
		"ram_percent": mem.get("used_percent"),
		"ram_gb": mem.get("total_gb"),
		"cpu_cores": cpu_cores,
		"cpu_percent": _cpu_percent(),
		"load_average": [round(x, 2) for x in load],
		"public_ip": _guess_public_ip(),
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
		return {"used_percent": used_percent, "total_gb": round(total / (1024 * 1024), 2)}
	except Exception:
		return {"used_percent": 0, "total_gb": 0}


def _cpu_percent() -> float:
	"""Cheap 1-sample CPU busy estimate from /proc/stat."""
	try:
		with open("/proc/stat", encoding="utf-8") as f:
			parts = f.readline().split()
		# user nice system idle iowait irq softirq steal
		vals = [float(x) for x in parts[1:8]]
		idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
		total = sum(vals)
		if total <= 0:
			return 0.0
		return round(max(0.0, min(100.0, (1 - idle / total) * 100)), 1)
	except Exception:
		return 0.0


def _guess_public_ip() -> str | None:
	"""Best-effort public IP (does not fail heartbeat)."""
	try:
		import urllib.request

		with urllib.request.urlopen("https://api.ipify.org", timeout=2) as resp:
			ip = resp.read().decode("utf-8").strip()
			return ip if ip else None
	except Exception:
		return None
