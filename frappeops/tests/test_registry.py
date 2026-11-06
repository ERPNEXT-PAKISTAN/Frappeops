# Copyright (c) 2026, FrappeOps and Contributors
# License: MIT. See LICENSE

import unittest

from frappeops.services.operations.registry import ACTIONS, get_action


class TestRegistry(unittest.TestCase):
	def test_actions_have_required_fields(self):
		for action in ACTIONS:
			self.assertIn("key", action)
			self.assertIn("status", action)
			self.assertIn(action["status"], ("available", "planned"))
			self.assertIn("risk", action)
			self.assertIn(action["risk"], ("Low", "Medium", "High", "Critical"))

	def test_no_shell_action(self):
		keys = {a["key"] for a in ACTIONS}
		self.assertNotIn("shell.run", keys)
		self.assertNotIn("server.shell", keys)

	def test_get_action(self):
		self.assertIsNotNone(get_action("site.health"))
		self.assertIsNone(get_action("not.a.real.action"))

	def test_protected_policy_on_mutate(self):
		clear = get_action("site.clear_cache")
		self.assertFalse(clear.get("allowed_on_protected"))
		health = get_action("site.health")
		self.assertTrue(health.get("allowed_on_protected"))

	def test_wave_0_4_actions_present(self):
		keys = {a["key"] for a in ACTIONS}
		for key in (
			"app.get",
			"app.seed_catalog",
			"app.list_catalog",
			"backup.upload_offsite",
			"backup.test_destination",
			"server.register_vps",
			"server.status",
			"agent.install_script",
		):
			self.assertIn(key, keys)
			self.assertEqual(get_action(key)["status"], "available")


if __name__ == "__main__":
	unittest.main()
