# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""AI Task workflow: plan → review → approve → execute (allowlisted only)."""

from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _

from frappeops.core.audit import write_audit
from frappeops.core.redaction import redact_text
from frappeops.services.operations.registry import get_action


# Local deterministic planner — not an external LLM. Honest about that.
PLAN_RULES = [
	{
		"match": r"health|ping|status",
		"steps": [
			{"action_key": "server.health", "target_type": "server", "risk": "Low"},
			{"action_key": "site.health", "target_type": "site", "risk": "Low"},
		],
	},
	{
		"match": r"backup",
		"steps": [{"action_key": "site.backup", "target_type": "site", "risk": "Medium"}],
	},
	{
		"match": r"discover|scan|inventory",
		"steps": [
			{"action_key": "server.discover", "target_type": "server", "risk": "Low"},
			{"action_key": "agent.discover", "target_type": "server", "risk": "Low"},
		],
	},
	{
		"match": r"cache",
		"steps": [{"action_key": "site.clear_cache", "target_type": "site", "risk": "Medium"}],
	},
	{
		"match": r"alert|monitor",
		"steps": [{"action_key": "monitor.poll", "target_type": "server", "risk": "Low"}],
	},
]


def create_ai_task(
	description: str,
	*,
	title: str | None = None,
	site: str | None = None,
	server: str | None = None,
	provider: str | None = None,
) -> dict[str, Any]:
	desc = (description or "").strip()
	if not desc:
		frappe.throw(_("Task description is required"))

	ai_on = bool(frappe.db.get_single_value("FrappeOps Settings", "enable_ai_features"))
	provider = provider or frappe.db.get_single_value("FrappeOps Settings", "default_ai_provider")
	if ai_on and not provider and frappe.db.exists("AI Provider", "Ollama Local"):
		provider = "Ollama Local"
	if not ai_on:
		provider = "Local Planner" if frappe.db.exists("AI Provider", "Local Planner") else provider

	doc = frappe.get_doc(
		{
			"doctype": "AI Task",
			"title": (title or desc[:80]),
			"status": "Draft",
			"task_description": desc,
			"site": site,
			"server": server or frappe.db.get_value("Server", {"is_local": 1}, "name"),
			"provider": provider,
			"requested_by": frappe.session.user,
			"notes": _("Created. Plan with Ollama when AI Features enabled; else local rules."),
		}
	)
	doc.insert(ignore_permissions=True)
	return {"ok": True, "message": _("AI Task created"), "ai_task": doc.name, "provider": provider}


def plan_ai_task(ai_task: str, *, use_local: bool = False) -> dict[str, Any]:
	doc = frappe.get_doc("AI Task", ai_task)
	if doc.status not in ("Draft", "Planned", "Rejected"):
		return {"ok": False, "message": _("Cannot plan from status {0}").format(doc.status)}

	provider_name = doc.provider
	plan = None
	ai_on = bool(frappe.db.get_single_value("FrappeOps Settings", "enable_ai_features"))
	explicit_local = use_local or (provider_name == "Local Planner")

	if not explicit_local and ai_on:
		from frappeops.services.ai.providers import (
			MODEL_PROVIDER_TYPES,
			generate_plan_with_provider,
			resolve_provider,
		)

		prov = resolve_provider(provider_name)
		if prov and prov.enabled and prov.provider_type in MODEL_PROVIDER_TYPES:
			result = generate_plan_with_provider(
				doc.task_description or "",
				provider_name=prov.name,
				server=doc.server,
				site=doc.site,
			)
			if result.get("ok"):
				plan = result["plan"]
				doc.provider = prov.name
				doc.notes = redact_text(
					(
						(doc.notes or "")
						+ f"\nPlanner: {prov.provider_type} ({prov.default_model})"
					).strip()[-500:]
				)
			elif provider_name and provider_name != "Local Planner":
				# Explicit model provider — fail honestly (no silent fake plan)
				return {
					"ok": False,
					"message": result.get("message") or _("Model planning failed"),
					"ai_task": doc.name,
					"detail": result,
				}
			# else fall through to local rules

	if plan is None:
		plan = _local_rule_plan(doc)
		doc.notes = redact_text(((doc.notes or "") + "\nPlanner: local-rules-v1").strip()[-500:])
		if not doc.provider:
			doc.provider = "Local Planner" if frappe.db.exists("AI Provider", "Local Planner") else doc.provider

	doc.plan_json = json.dumps(plan, indent=2)
	doc.status = "Planned"
	doc.save(ignore_permissions=True)
	write_audit(
		"ai.plan",
		resource_type="ai_task",
		resource_name=doc.name,
		status="Success",
		message=_("Plan generated via {0}").format(plan.get("planner")),
	)
	return {
		"ok": True,
		"message": _("Plan ready ({0} steps) via {1}").format(len(plan.get("steps") or []), plan.get("planner")),
		"ai_task": doc.name,
		"plan": plan,
	}


def _local_rule_plan(doc) -> dict[str, Any]:
	text = (doc.task_description or "").lower()
	steps = []
	for rule in PLAN_RULES:
		if re.search(rule["match"], text):
			for step in rule["steps"]:
				action = get_action(step["action_key"])
				if not action or action.get("status") != "available":
					continue
				if (action.get("risk") or "Low") in ("High", "Critical"):
					continue
				item = {
					**step,
					"label": action.get("label"),
					"risk": action.get("risk"),
					"target_name": _default_target(doc, step["target_type"]),
				}
				if item["target_name"] and item not in steps:
					steps.append(item)

	if not steps:
		steps = [
			{
				"action_key": "monitor.poll",
				"target_type": "server",
				"target_name": doc.server,
				"label": _("Monitoring Poll"),
				"risk": "Low",
				"note": _("No keyword match — defaulted to monitoring poll."),
			}
		]

	return {
		"planner": "local-rules-v1",
		"external_llm": False,
		"steps": steps,
		"disclaimer": "No code changes or shell. Execute only after human approval.",
	}


def submit_ai_task(ai_task: str) -> dict[str, Any]:
	doc = frappe.get_doc("AI Task", ai_task)
	if doc.status != "Planned":
		return {"ok": False, "message": _("Plan the task first")}
	doc.status = "Awaiting Approval"
	doc.save(ignore_permissions=True)
	return {"ok": True, "message": _("Awaiting approval"), "ai_task": doc.name}


def approve_ai_task(ai_task: str) -> dict[str, Any]:
	_require_approver()
	doc = frappe.get_doc("AI Task", ai_task)
	if doc.status != "Awaiting Approval":
		return {"ok": False, "message": _("Task is not awaiting approval")}
	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.save(ignore_permissions=True)
	write_audit("ai.approve", resource_type="ai_task", resource_name=doc.name, status="Success")
	return {"ok": True, "message": _("Approved"), "ai_task": doc.name}


def reject_ai_task(ai_task: str, reason: str | None = None) -> dict[str, Any]:
	_require_approver()
	doc = frappe.get_doc("AI Task", ai_task)
	doc.status = "Rejected"
	doc.notes = (doc.notes or "") + "\n" + (reason or "Rejected")
	doc.save(ignore_permissions=True)
	return {"ok": True, "message": _("Rejected"), "ai_task": doc.name}


def execute_ai_task(ai_task: str, *, confirm: bool = False) -> dict[str, Any]:
	"""Execute approved plan steps via allowlisted run_action only."""
	if not confirm:
		return {
			"ok": False,
			"needs_confirm": True,
			"message": _("Set confirm=1 to execute an approved AI Task plan."),
		}

	doc = frappe.get_doc("AI Task", ai_task)
	if doc.status != "Approved":
		return {"ok": False, "message": _("Task must be Approved before execute")}

	try:
		plan = json.loads(doc.plan_json or "{}")
	except Exception:
		return {"ok": False, "message": _("Invalid plan_json")}

	steps = plan.get("steps") or []
	doc.status = "Executing"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	from frappeops.services.operations.runner import run_action

	results = []
	ok = True
	for step in steps:
		action_key = step.get("action_key")
		action = get_action(action_key)
		if not action or action.get("status") != "available":
			results.append({"action_key": action_key, "ok": False, "message": "unavailable"})
			ok = False
			continue
		if (action.get("risk") or "Low") in ("High", "Critical"):
			results.append({"action_key": action_key, "ok": False, "message": "high-risk blocked in AI execute"})
			ok = False
			continue
		# Protected site guard for site targets
		if step.get("target_type") == "site" and step.get("target_name"):
			if frappe.db.get_value("Site", step["target_name"], "is_protected") and not action.get(
				"allowed_on_protected"
			):
				results.append({"action_key": action_key, "ok": False, "message": "protected site"})
				ok = False
				continue
		try:
			res = run_action(
				action_key,
				step.get("target_type"),
				step.get("target_name"),
				params=json.dumps(step.get("params") or {}),
			)
			results.append({"action_key": action_key, "ok": res.get("ok"), "message": res.get("message"), "job": res.get("operation_job")})
			if not res.get("ok"):
				ok = False
		except Exception as exc:
			results.append({"action_key": action_key, "ok": False, "message": redact_text(str(exc))})
			ok = False

	doc.status = "Success" if ok else "Failed"
	doc.result_json = redact_text(json.dumps(results, indent=2, default=str))
	doc.save(ignore_permissions=True)
	write_audit(
		"ai.execute",
		resource_type="ai_task",
		resource_name=doc.name,
		status="Success" if ok else "Failed",
		after={"results": results},
	)
	return {
		"ok": ok,
		"message": _("AI Task executed") if ok else _("AI Task finished with failures"),
		"ai_task": doc.name,
		"results": results,
	}


def _default_target(doc, target_type: str) -> str | None:
	if target_type == "site":
		if doc.site:
			return doc.site
		# Prefer control plane / non-protected
		return frappe.db.get_value("Site", {"is_control_plane": 1}, "name") or frappe.db.get_value(
			"Site", {"is_protected": 0}, "name"
		)
	if target_type == "server":
		return doc.server or frappe.db.get_value("Server", {"is_local": 1}, "name")
	return None


def _require_approver():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "FrappeOps Administrator"}):
		frappe.throw(_("Only FrappeOps Administrator can approve AI tasks"), frappe.PermissionError)
