# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BackupDestination(Document):
	def validate(self):
		if self.is_default and self.enabled:
			others = frappe.get_all(
				"Backup Destination",
				filters={"is_default": 1, "name": ["!=", self.name or ""]},
				pluck="name",
			)
			for name in others:
				frappe.db.set_value("Backup Destination", name, "is_default", 0)
