# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Configure cloud OpenAI-compatible providers (API key never logged)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from frappeops.services.ai.providers import test_provider, validate_ai_base_url


def configure_cloud_provider(
	*,
	provider_name: str = "OpenAI Cloud",
	api_base_url: str = "https://api.openai.com/v1",
	default_model: str = "gpt-4o-mini",
	api_key: str | None = None,
	enable_public_urls: bool = True,
	test: bool = True,
) -> dict[str, Any]:
	"""Create/update an OpenAI-compatible provider with encrypted API key."""
	if not api_key or not str(api_key).strip():
		return {
			"ok": False,
			"status": "blocked",
			"message": _(
				"Cloud AI needs an API key. Pass api_key once (stored encrypted on AI Provider). "
				"Example base: https://api.openai.com/v1 or a Claude-compatible gateway."
			),
			"needs": ["api_key"],
		}

	safe = validate_ai_base_url(api_base_url) if not enable_public_urls else {"ok": True}
	# If public URLs not allowed yet, enable setting when operator opted in
	if enable_public_urls:
		frappe.db.set_single_value("FrappeOps Settings", "allow_public_ai_urls", 1)
		frappe.db.set_single_value("FrappeOps Settings", "enable_ai_features", 1)
		frappe.db.commit()
		safe = validate_ai_base_url(api_base_url)

	if not safe.get("ok"):
		return {"ok": False, "message": safe.get("message"), "needs": ["allow_public_ai_urls"]}

	if frappe.db.exists("AI Provider", provider_name):
		doc = frappe.get_doc("AI Provider", provider_name)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": provider_name,
				"provider_type": "OpenAI",
			}
		)

	doc.enabled = 1
	doc.api_base_url = api_base_url.rstrip("/")
	doc.default_model = default_model
	doc.api_key = api_key.strip()
	doc.data_policy = "Selected Context"
	doc.notes = "Cloud OpenAI-compatible provider. API key encrypted."
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)

	frappe.db.set_single_value("FrappeOps Settings", "default_ai_provider", provider_name)
	frappe.db.commit()

	result = {"ok": True, "message": _("Cloud provider configured"), "provider": provider_name}
	if test:
		result["test"] = test_provider(provider_name)
		result["ok"] = bool(result["test"].get("ok"))
		if not result["ok"]:
			result["message"] = result["test"].get("message") or _("Provider saved but test failed")
	return result
