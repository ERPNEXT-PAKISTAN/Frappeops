# Copyright (c) 2026, FrappeOps and Contributors
# License: MIT. See LICENSE

import socket
import unittest
from unittest.mock import patch

from frappeops.services.agents.poll import validate_listen_url
from frappeops.services.ai.providers import validate_ai_base_url


class TestSSRFGuards(unittest.TestCase):
	def test_listen_url_rejects_credentials_and_query(self):
		self.assertFalse(validate_listen_url("http://user:pass@127.0.0.1:18765")["ok"])
		self.assertFalse(validate_listen_url("http://127.0.0.1:18765?x=1")["ok"])
		self.assertFalse(validate_listen_url("ftp://127.0.0.1:18765")["ok"])

	def test_listen_url_allows_loopback(self):
		self.assertTrue(validate_listen_url("http://127.0.0.1:18765")["ok"])
		self.assertTrue(validate_listen_url("http://localhost:18765")["ok"])

	@patch("frappe.db.get_single_value", return_value=0)
	@patch("socket.getaddrinfo")
	def test_listen_url_blocks_public_by_default(self, mock_gai, _mock_sv):
		mock_gai.return_value = [
			(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 18765)),
		]
		result = validate_listen_url("http://example.com:18765")
		self.assertFalse(result["ok"])

	def test_ai_url_allows_loopback(self):
		self.assertTrue(validate_ai_base_url("http://127.0.0.1:11434")["ok"])
		self.assertTrue(validate_ai_base_url("http://127.0.0.1:11434/v1")["ok"])

	@patch("frappe.db.get_single_value", return_value=0)
	@patch("socket.getaddrinfo")
	def test_ai_url_blocks_openai_by_default(self, mock_gai, _mock_sv):
		mock_gai.return_value = [
			(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.66.0.243", 443)),
		]
		result = validate_ai_base_url("https://api.openai.com/v1")
		self.assertFalse(result["ok"])


if __name__ == "__main__":
	unittest.main()
