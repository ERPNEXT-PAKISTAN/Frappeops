# Copyright (c) 2026, FrappeOps and Contributors
# License: MIT. See LICENSE

import unittest
from unittest.mock import patch

from frappeops.services.ai.providers import extract_json_object, normalize_plan_steps


class TestAIPlanNormalize(unittest.TestCase):
	def test_extract_json_fenced(self):
		text = 'Here\n```json\n{"steps":[{"action_key":"server.health"}]}\n```\n'
		data = extract_json_object(text)
		self.assertIsInstance(data, dict)
		self.assertIn("steps", data)

	def test_strips_high_risk_and_secrets(self):
		raw = [
			{"action_key": "site.migrate", "target_type": "site", "params": {"password": "x"}},
			{
				"action_key": "server.health",
				"target_type": "server",
				"target_name": "SRV-0001",
				"params": {"token": "abc", "ok": 1},
			},
		]
		with patch("frappeops.services.ai.providers.get_action") as ga:
			ga.side_effect = lambda k: {
				"site.migrate": {"key": "site.migrate", "status": "available", "risk": "High", "target": "site"},
				"server.health": {
					"key": "server.health",
					"status": "available",
					"risk": "Low",
					"target": "server",
					"label": "Health",
				},
			}.get(k)
			steps = normalize_plan_steps(raw, server="SRV-0001")
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0]["action_key"], "server.health")
		self.assertNotIn("token", steps[0]["params"])
		self.assertEqual(steps[0]["params"].get("ok"), 1)


if __name__ == "__main__":
	unittest.main()
