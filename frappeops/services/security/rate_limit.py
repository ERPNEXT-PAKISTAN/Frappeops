# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Simple Redis/cache rate limits for agent guest APIs."""

from __future__ import annotations

import frappe
from frappe import _


def check_rate_limit(bucket: str, *, limit: int = 60, window_seconds: int = 60) -> None:
	"""Raise if bucket exceeded. Uses frappe.cache incr with TTL."""
	key = f"frappeops:rl:{bucket}"
	cache = frappe.cache
	try:
		count = cache.incr(key)
		if count == 1:
			cache.expire(key, window_seconds)
		if count > limit:
			frappe.throw(
				_("Rate limit exceeded. Try again later."),
				frappe.RateLimitExceededError if hasattr(frappe, "RateLimitExceededError") else frappe.ValidationError,
			)
	except frappe.ValidationError:
		raise
	except Exception:
		# If cache backend lacks incr, fail open for control-plane ops (not ideal, but available)
		pass
