# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Resolve and run the bench CLI from web workers (PATH often lacks ~/.local/bin)."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import frappe
from frappe import _


@lru_cache(maxsize=1)
def get_bench_executable() -> str:
	"""Return absolute path to the `bench` CLI."""
	candidates: list[str] = []

	home_local = Path.home() / ".local" / "bin" / "bench"
	candidates.append(str(home_local))
	candidates.append("/usr/local/bin/bench")
	candidates.append("/usr/bin/bench")

	env_path = os.environ.get("PATH", "")
	extra = f"{Path.home() / '.local' / 'bin'}{os.pathsep}{env_path}"
	which = shutil.which("bench", path=extra)
	if which:
		candidates.insert(0, which)

	for path in candidates:
		if path and os.path.isfile(path) and os.access(path, os.X_OK):
			return path

	frappe.throw(
		_("bench CLI not found. Expected it under ~/.local/bin/bench or on PATH."),
		title=_("Bench Missing"),
	)
	return "bench"  # unreachable


def bench_env() -> dict[str, str]:
	"""Environment for subprocesses that need the frappe user's PATH."""
	env = os.environ.copy()
	local_bin = str(Path.home() / ".local" / "bin")
	path = env.get("PATH", "")
	if local_bin not in path.split(os.pathsep):
		env["PATH"] = f"{local_bin}{os.pathsep}{path}" if path else local_bin
	return env


def run_bench(
	args: list[str],
	*,
	cwd: str | None = None,
	timeout: int = 300,
	check: bool = True,
) -> subprocess.CompletedProcess[str]:
	"""Run `bench <args...>` with a resolved executable and sane PATH."""
	cmd = [get_bench_executable(), *args]
	return subprocess.run(
		cmd,
		cwd=cwd or frappe.utils.get_bench_path(),
		env=bench_env(),
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		timeout=timeout,
		text=True,
		check=check,
	)
