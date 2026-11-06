# Copyright (c) 2026, FrappeOps and Contributors
# License: MIT. See LICENSE

import unittest

from frappeops.services.apps.marketplace import validate_git_url


class TestMarketplaceGit(unittest.TestCase):
	def test_https_ok(self):
		r = validate_git_url("https://github.com/frappe/hrms")
		self.assertTrue(r["ok"])

	def test_reject_ssh(self):
		r = validate_git_url("git@github.com:frappe/hrms.git")
		self.assertFalse(r["ok"])

	def test_reject_creds(self):
		r = validate_git_url("https://user:pass@github.com/frappe/hrms")
		self.assertFalse(r["ok"])

	def test_reject_shell_chars(self):
		r = validate_git_url("https://github.com/frappe/hrms;rm -rf /")
		self.assertFalse(r["ok"])


if __name__ == "__main__":
	unittest.main()
