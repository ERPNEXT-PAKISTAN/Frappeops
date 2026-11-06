# Copyright (c) 2026, FrappeOps and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from frappeops.core.redaction import redact_dict, redact_text


class AuditLog(Document):
	def before_insert(self):
		self.message = redact_text(self.message)
		for fieldname in ("before_json", "after_json", "parameters_json"):
			raw = self.get(fieldname)
			if not raw:
				continue
			try:
				import json

				data = json.loads(raw) if isinstance(raw, str) else raw
				if isinstance(data, dict):
					self.set(fieldname, json.dumps(redact_dict(data), indent=2))
				else:
					self.set(fieldname, redact_text(str(raw)))
			except Exception:
				self.set(fieldname, redact_text(str(raw)))

	def on_trash(self):
		frappe.throw("Audit Log records cannot be deleted")
