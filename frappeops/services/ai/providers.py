# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

"""AI provider adapters (Ollama local; OpenAI-compatible gated)."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

import frappe
import requests
from frappe import _

from frappeops.core.redaction import redact_text
from frappeops.services.operations.registry import ACTIONS, get_action

PLAN_TIMEOUT = 240
ALLOWED_RISKS = {"Low", "Medium"}
# Native Ollama + OpenAI-compatible chat APIs
MODEL_PROVIDER_TYPES = {"Ollama", "OpenAI", "Other", "Claude", "Gemini", "Codex", "Cursor"}
OPENAI_COMPAT_TYPES = {"OpenAI", "Other", "Claude", "Gemini", "Codex", "Cursor"}


def list_plannable_actions() -> list[dict[str, str]]:
	out = []
	for a in ACTIONS:
		if a.get("status") != "available":
			continue
		if (a.get("risk") or "Low") not in ALLOWED_RISKS:
			continue
		out.append(
			{
				"action_key": a["key"],
				"target": a.get("target") or "",
				"risk": a.get("risk") or "Low",
				"label": str(a.get("label") or a["key"]),
			}
		)
	return out


def resolve_provider(name: str | None = None):
	if name and frappe.db.exists("AI Provider", name):
		return frappe.get_doc("AI Provider", name)
	default = frappe.db.get_single_value("FrappeOps Settings", "default_ai_provider")
	if default and frappe.db.exists("AI Provider", default):
		doc = frappe.get_doc("AI Provider", default)
		if doc.enabled:
			return doc
	rows = frappe.get_all(
		"AI Provider",
		filters={"enabled": 1, "provider_type": "Ollama"},
		pluck="name",
		limit=1,
	)
	if rows:
		return frappe.get_doc("AI Provider", rows[0])
	return None


def test_provider(provider_name: str | None = None) -> dict[str, Any]:
	doc = resolve_provider(provider_name)
	if not doc:
		return {"ok": False, "message": _("No enabled AI Provider found")}
	if doc.provider_type == "Ollama":
		return _ollama_tags(doc)
	if doc.provider_type in OPENAI_COMPAT_TYPES:
		return _openai_models(doc)
	return {"ok": False, "message": _("Unsupported provider type"), "provider": doc.name}


def generate_plan_with_provider(
	description: str,
	*,
	provider_name: str | None = None,
	server: str | None = None,
	site: str | None = None,
) -> dict[str, Any]:
	"""Call enabled provider to propose allowlisted steps. Validates strictly."""
	if not frappe.db.get_single_value("FrappeOps Settings", "enable_ai_features"):
		return {
			"ok": False,
			"message": _("Enable AI Features in FrappeOps Settings to use external/local model planners."),
		}

	doc = resolve_provider(provider_name)
	if not doc or not doc.enabled:
		return {"ok": False, "message": _("No enabled AI Provider. Enable Ollama Local or pick a provider.")}

	if doc.provider_type not in MODEL_PROVIDER_TYPES:
		return {
			"ok": False,
			"status": "blocked",
			"message": _("Provider type {0} is not executable.").format(doc.provider_type),
			"provider": doc.name,
		}

	default_base = (
		"http://127.0.0.1:11434/v1"
		if doc.provider_type in OPENAI_COMPAT_TYPES
		else "http://127.0.0.1:11434"
	)
	safe = validate_ai_base_url(doc.api_base_url or default_base)
	if not safe["ok"]:
		return {"ok": False, "message": safe["message"], "provider": doc.name}

	# Remote (non-loopback) OpenAI-compatible endpoints require an API key
	if doc.provider_type in OPENAI_COMPAT_TYPES and not _is_loopback_url(doc.api_base_url or default_base):
		if not _get_api_key(doc):
			return {
				"ok": False,
				"message": _("API Key required on AI Provider for non-loopback OpenAI-compatible URLs."),
				"provider": doc.name,
			}

	actions = list_plannable_actions()
	prompt = _build_prompt(description, actions, server=server, site=site)
	if doc.provider_type == "Ollama":
		raw = _ollama_chat(doc, prompt)
		planner_prefix = "ollama"
		local_model = True
	else:
		raw = _openai_chat(doc, prompt)
		planner_prefix = "openai-compat"
		local_model = _is_loopback_url(doc.api_base_url or default_base)

	if not raw.get("ok"):
		return raw

	parsed = extract_json_object(raw.get("text") or "")
	if not parsed:
		return {
			"ok": False,
			"message": _("Model returned non-JSON plan"),
			"provider": doc.name,
			"raw_excerpt": redact_text((raw.get("text") or "")[:500]),
		}

	steps = normalize_plan_steps(parsed.get("steps") or [], server=server, site=site)
	if not steps:
		return {
			"ok": False,
			"message": _("Model plan had no valid allowlisted Low/Medium steps"),
			"provider": doc.name,
			"raw_excerpt": redact_text((raw.get("text") or "")[:500]),
		}

	plan = {
		"planner": f"{planner_prefix}:{doc.default_model or 'model'}",
		"provider": doc.name,
		"external_llm": True,
		"local_model": local_model,
		"steps": steps,
		"disclaimer": "Human approval required. High/Critical and arbitrary shell are blocked.",
	}
	return {
		"ok": True,
		"message": _("Model plan ready ({0} steps)").format(len(steps)),
		"provider": doc.name,
		"plan": plan,
		"model": doc.default_model,
	}


def validate_ai_base_url(url: str) -> dict[str, Any]:
	try:
		parsed = urlparse((url or "").strip())
	except Exception:
		return {"ok": False, "message": _("Invalid AI base URL")}
	if parsed.scheme not in ("http", "https"):
		return {"ok": False, "message": _("AI base URL must be http or https")}
	if parsed.username or parsed.password:
		return {"ok": False, "message": _("AI base URL must not embed credentials")}
	host = parsed.hostname
	if not host:
		return {"ok": False, "message": _("AI base URL host required")}
	allow_public = bool(frappe.db.get_single_value("FrappeOps Settings", "allow_public_ai_urls"))
	try:
		infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
	except Exception as exc:
		return {"ok": False, "message": _("Cannot resolve AI host: {0}").format(redact_text(str(exc)))}
	for info in infos:
		ip = ipaddress.ip_address(info[4][0])
		if ip.is_loopback:
			continue
		if ip.is_link_local or str(ip).startswith("169.254."):
			return {"ok": False, "message": _("Link-local / metadata AI URLs are blocked")}
		if allow_public:
			continue
		return {
			"ok": False,
			"message": _(
				"AI URL host {0} resolves to {1}. Loopback-only by default; "
				"enable Allow Public AI URLs for private/remote endpoints."
			).format(host, ip),
		}
	return {"ok": True, "host": host}


def normalize_plan_steps(
	raw_steps: list,
	*,
	server: str | None = None,
	site: str | None = None,
) -> list[dict[str, Any]]:
	steps = []
	seen = set()
	for raw in raw_steps:
		if not isinstance(raw, dict):
			continue
		key = (raw.get("action_key") or "").strip()
		action = get_action(key)
		if not action or action.get("status") != "available":
			continue
		if (action.get("risk") or "Low") not in ALLOWED_RISKS:
			continue
		target_type = (raw.get("target_type") or action.get("target") or "").strip()
		if target_type != action.get("target"):
			target_type = action.get("target")
		target_name = raw.get("target_name")
		if not target_name:
			if target_type == "server":
				target_name = server or frappe.db.get_value("Server", {"is_local": 1}, "name")
			elif target_type == "site":
				target_name = site or frappe.db.get_value("Site", {"is_control_plane": 1}, "name")
		sig = (key, target_type, target_name)
		if sig in seen:
			continue
		seen.add(sig)
		params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
		# Strip dangerous param keys
		safe_params = {
			k: v
			for k, v in params.items()
			if not any(s in str(k).lower() for s in ("password", "token", "api_key", "secret", "shell", "cmd"))
		}
		steps.append(
			{
				"action_key": key,
				"target_type": target_type,
				"target_name": target_name,
				"label": action.get("label"),
				"risk": action.get("risk"),
				"params": safe_params,
			}
		)
		if len(steps) >= 8:
			break
	return steps


def extract_json_object(text: str) -> dict | None:
	text = (text or "").strip()
	if not text:
		return None
	try:
		data = json.loads(text)
		return data if isinstance(data, dict) else None
	except Exception:
		pass
	# fenced ```json
	m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
	if m:
		try:
			data = json.loads(m.group(1))
			return data if isinstance(data, dict) else None
		except Exception:
			pass
	start = text.find("{")
	end = text.rfind("}")
	if start >= 0 and end > start:
		try:
			data = json.loads(text[start : end + 1])
			return data if isinstance(data, dict) else None
		except Exception:
			return None
	return None


def _build_prompt(description: str, actions: list[dict], *, server, site) -> str:
	catalog = json.dumps(actions, indent=2)
	return (
		"You are FrappeOps, an infrastructure control-plane planner.\n"
		"Return ONLY a JSON object with this shape:\n"
		'{"steps":[{"action_key":"server.health","target_type":"server","target_name":null,"params":{}}]}\n'
		"Rules:\n"
		"- Use only action_key values from the catalog below.\n"
		"- Only Low or Medium risk actions.\n"
		"- No shell, no SQL, no file writes, no High/Critical.\n"
		"- Prefer server.health, site.health, monitor.poll, server.discover, site.backup, agent.poll.\n"
		"- At most 5 steps.\n"
		f"- Default server name hint: {server or 'null'}\n"
		f"- Default site name hint: {site or 'null'}\n"
		f"Catalog:\n{catalog}\n"
		f"Operator request:\n{description.strip()}\n"
	)


def _ollama_chat(doc, prompt: str) -> dict[str, Any]:
	base = (doc.api_base_url or "http://127.0.0.1:11434").rstrip("/")
	model = doc.default_model or "qwen2.5-coder:3b"
	url = f"{base}/api/chat"
	payload = {
		"model": model,
		"stream": False,
		"format": "json",
		"options": {"temperature": 0.1},
		"messages": [
			{"role": "system", "content": "Return valid JSON only. No markdown."},
			{"role": "user", "content": prompt},
		],
	}
	try:
		resp = requests.post(url, json=payload, timeout=PLAN_TIMEOUT, allow_redirects=False)
	except Exception as exc:
		return {"ok": False, "message": _("Ollama request failed: {0}").format(redact_text(str(exc)))}
	if resp.status_code != 200:
		return {
			"ok": False,
			"message": _("Ollama HTTP {0}").format(resp.status_code),
			"raw_excerpt": redact_text((resp.text or "")[:400]),
		}
	try:
		data = resp.json()
	except Exception:
		return {"ok": False, "message": _("Ollama returned non-JSON")}
	text = ((data.get("message") or {}).get("content")) or data.get("response") or ""
	return {"ok": True, "text": text, "model": model, "provider": doc.name}


def _ollama_tags(doc) -> dict[str, Any]:
	safe = validate_ai_base_url(doc.api_base_url or "http://127.0.0.1:11434")
	if not safe["ok"]:
		return {"ok": False, "message": safe["message"], "provider": doc.name}
	base = (doc.api_base_url or "http://127.0.0.1:11434").rstrip("/")
	# If operator stored /v1 base by mistake, strip for native tags
	if base.endswith("/v1"):
		base = base[:-3]
	try:
		resp = requests.get(f"{base}/api/tags", timeout=10, allow_redirects=False)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc)), "provider": doc.name}
	if resp.status_code != 200:
		return {"ok": False, "message": f"HTTP {resp.status_code}", "provider": doc.name}
	data = resp.json() if resp.content else {}
	models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
	return {
		"ok": True,
		"message": _("Ollama reachable ({0} models)").format(len(models)),
		"provider": doc.name,
		"models": models,
		"default_model": doc.default_model,
	}


def _openai_base(doc) -> str:
	base = (doc.api_base_url or "http://127.0.0.1:11434/v1").rstrip("/")
	if not base.endswith("/v1") and "openai.com" not in base:
		# Allow bare host:port → append /v1 for compat servers
		if "11434" in base and not base.endswith("/v1"):
			base = base + "/v1"
	return base


def _openai_chat(doc, prompt: str) -> dict[str, Any]:
	base = _openai_base(doc)
	model = doc.default_model or "gpt-4o-mini"
	url = f"{base}/chat/completions"
	headers = {"Content-Type": "application/json"}
	api_key = _get_api_key(doc)
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"
	payload = {
		"model": model,
		"temperature": 0.1,
		"response_format": {"type": "json_object"},
		"messages": [
			{"role": "system", "content": "Return valid JSON only. No markdown."},
			{"role": "user", "content": prompt},
		],
	}
	try:
		resp = requests.post(url, headers=headers, json=payload, timeout=PLAN_TIMEOUT, allow_redirects=False)
	except Exception as exc:
		return {"ok": False, "message": _("OpenAI-compatible request failed: {0}").format(redact_text(str(exc)))}
	if resp.status_code != 200:
		# Retry without response_format for servers that reject it (some Ollama builds)
		if resp.status_code in (400, 404, 422):
			payload.pop("response_format", None)
			try:
				resp = requests.post(
					url, headers=headers, json=payload, timeout=PLAN_TIMEOUT, allow_redirects=False
				)
			except Exception as exc:
				return {
					"ok": False,
					"message": _("OpenAI-compatible request failed: {0}").format(redact_text(str(exc))),
				}
	if resp.status_code != 200:
		return {
			"ok": False,
			"message": _("OpenAI-compatible HTTP {0}").format(resp.status_code),
			"raw_excerpt": redact_text((resp.text or "")[:400]),
		}
	try:
		data = resp.json()
	except Exception:
		return {"ok": False, "message": _("OpenAI-compatible returned non-JSON")}
	choices = data.get("choices") or []
	text = ""
	if choices:
		text = ((choices[0].get("message") or {}).get("content")) or ""
	return {"ok": True, "text": text, "model": model, "provider": doc.name}


def _openai_models(doc) -> dict[str, Any]:
	safe = validate_ai_base_url(doc.api_base_url or "http://127.0.0.1:11434/v1")
	if not safe["ok"]:
		return {"ok": False, "message": safe["message"], "provider": doc.name}
	if not _is_loopback_url(doc.api_base_url or "") and not _get_api_key(doc):
		return {
			"ok": False,
			"message": _("API Key required for non-loopback OpenAI-compatible test."),
			"provider": doc.name,
		}
	base = _openai_base(doc)
	headers = {}
	api_key = _get_api_key(doc)
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"
	try:
		resp = requests.get(f"{base}/models", headers=headers, timeout=15, allow_redirects=False)
	except Exception as exc:
		return {"ok": False, "message": redact_text(str(exc)), "provider": doc.name}
	if resp.status_code != 200:
		return {"ok": False, "message": f"HTTP {resp.status_code}", "provider": doc.name}
	data = resp.json() if resp.content else {}
	models = []
	for row in data.get("data") or []:
		if isinstance(row, dict) and row.get("id"):
			models.append(row["id"])
	return {
		"ok": True,
		"message": _("OpenAI-compatible reachable ({0} models)").format(len(models)),
		"provider": doc.name,
		"models": models[:50],
		"default_model": doc.default_model,
		"base": base,
	}


def _get_api_key(doc) -> str | None:
	try:
		return doc.get_password("api_key")
	except Exception:
		return None


def _is_loopback_url(url: str) -> bool:
	try:
		host = urlparse((url or "").strip()).hostname or ""
	except Exception:
		return False
	if host in ("127.0.0.1", "localhost", "::1"):
		return True
	try:
		return ipaddress.ip_address(host).is_loopback
	except Exception:
		return False
