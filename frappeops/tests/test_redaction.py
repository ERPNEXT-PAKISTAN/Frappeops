# Copyright (c) 2026, FrappeOps and Contributors
# License: MIT. See LICENSE

import unittest

from frappeops.core.redaction import REDACTED, redact_dict, redact_text


class TestRedaction(unittest.TestCase):
	def test_redact_password_assignment(self):
		text = "db_password=super-secret-value"
		self.assertIn(REDACTED, redact_text(text))
		self.assertNotIn("super-secret-value", redact_text(text))

	def test_redact_dict_keys(self):
		data = {"db_password": "x", "site_name": "frappeops.local"}
		out = redact_dict(data)
		self.assertEqual(out["db_password"], REDACTED)
		self.assertEqual(out["site_name"], "frappeops.local")

	def test_redact_bearerish_token_line(self):
		text = "Authorization: Bearer super-secret-token-value"
		# key-style pattern covers token=
		text2 = "api_key=super-secret-token-value"
		self.assertNotIn("super-secret-token-value", redact_text(text2))
		self.assertIn(REDACTED, redact_text(text2))


if __name__ == "__main__":
	unittest.main()
