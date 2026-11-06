# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""Install / migrate hooks for FrappeOps."""

from __future__ import annotations

import frappe

from frappeops.core.constants import ROLES


def after_install():
	ensure_roles()
	ensure_defaults()
	frappe.clear_cache()


def after_migrate():
	ensure_roles()
	ensure_defaults()


def ensure_roles():
	for role_name in ROLES:
		if not frappe.db.exists("Role", role_name):
			doc = frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
					"is_custom": 1,
				}
			)
			doc.insert(ignore_permissions=True)

	# Grant Administrator all FrappeOps roles
	user = "Administrator"
	if frappe.db.exists("User", user):
		user_doc = frappe.get_doc("User", user)
		existing = {r.role for r in user_doc.roles}
		changed = False
		for role_name in ROLES:
			if role_name not in existing:
				user_doc.append("roles", {"role": role_name})
				changed = True
		if changed:
			user_doc.save(ignore_permissions=True)


def ensure_defaults():
	if not frappe.db.exists("Organization", "Default Organization"):
		frappe.get_doc(
			{
				"doctype": "Organization",
				"organization_name": "Default Organization",
				"status": "Active",
				"notes": "Created by FrappeOps setup",
			}
		).insert(ignore_permissions=True)

	_ensure_version("Frappe Version", "Frappe 15", "15", "version-15")
	_ensure_version("Frappe Version", "Frappe 16", "16", "version-16")
	_ensure_version("ERPNext Version", "ERPNext 15", "15", "version-15", frappe_link="Frappe 15")
	_ensure_version("ERPNext Version", "ERPNext 16", "16", "version-16", frappe_link="Frappe 16")

	if not frappe.db.exists("Environment", "Control Plane"):
		frappe.get_doc(
			{
				"doctype": "Environment",
				"environment_name": "Control Plane",
				"environment_type": "Control Plane",
				"organization": "Default Organization",
				"notes": "FrappeOps control plane environment",
			}
		).insert(ignore_permissions=True)

	settings = frappe.get_single("FrappeOps Settings")
	if not settings.default_organization:
		settings.default_organization = "Default Organization"
	settings.protect_existing_sites = 1
	settings.require_typed_confirmation_for_critical = 1
	settings.allow_arbitrary_shell = 0
	settings.save(ignore_permissions=True)

	# Local planner provider (no external API keys)
	if frappe.db.exists("DocType", "AI Provider") and not frappe.db.exists("AI Provider", "Local Planner"):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": "Local Planner",
				"provider_type": "Other",
				"enabled": 1,
				"default_model": "local-rules-v1",
				"data_policy": "No External AI",
				"notes": "Deterministic allowlisted planner. Does not call external LLMs.",
			}
		).insert(ignore_permissions=True)

	# Local Ollama planner (loopback only by default)
	if frappe.db.exists("DocType", "AI Provider") and not frappe.db.exists("AI Provider", "Ollama Local"):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": "Ollama Local",
				"provider_type": "Ollama",
				"enabled": 1,
				"api_base_url": "http://127.0.0.1:11434",
				"default_model": "qwen2.5-coder:3b",
				"data_policy": "Selected Context",
				"notes": "Local Ollama. Requires Enable AI Features. Plans are still approve→execute only.",
			}
		).insert(ignore_permissions=True)

	# OpenAI-compatible path proven via local Ollama /v1 (no cloud key required)
	if frappe.db.exists("DocType", "AI Provider") and not frappe.db.exists(
		"AI Provider", "OpenAI Compatible (Ollama)"
	):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": "OpenAI Compatible (Ollama)",
				"provider_type": "OpenAI",
				"enabled": 1,
				"api_base_url": "http://127.0.0.1:11434/v1",
				"default_model": "qwen2.5-coder:3b",
				"data_policy": "Selected Context",
				"notes": (
					"OpenAI-compatible client against local Ollama /v1. "
					"For api.openai.com set API Key + Allow Public AI URLs."
				),
			}
		).insert(ignore_permissions=True)

	# Prefer Ollama as default when AI features get enabled
	if frappe.db.exists("AI Provider", "Ollama Local"):
		settings = frappe.get_single("FrappeOps Settings")
		if hasattr(settings, "default_ai_provider") and not settings.default_ai_provider:
			settings.default_ai_provider = "Ollama Local"
			settings.save(ignore_permissions=True)

	# Seed marketplace catalog (idempotent)
	if frappe.db.exists("DocType", "App Catalog Item"):
		try:
			from frappeops.services.apps.marketplace import seed_catalog

			seed_catalog(overwrite=False)
		except Exception:
			frappe.log_error(title="FrappeOps catalog seed")


def _ensure_version(doctype: str, name: str, major: str, branch: str, frappe_link: str | None = None):
	if frappe.db.exists(doctype, name):
		return
	doc = {
		"doctype": doctype,
		"version_name": name,
		"major_version": major,
		"branch": branch,
		"status": "Supported",
	}
	if frappe_link and doctype == "ERPNext Version":
		doc["compatible_frappe_version"] = frappe_link
	frappe.get_doc(doc).insert(ignore_permissions=True)
