import unittest
from backend.core.data import default_email_templates as templates
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.settings")


class TestDefaultEmailTemplates(unittest.TestCase):
    def test_invoice_created_template_contains_placeholders(self):
        template = templates.recurring_invoices_invoice_created_default_email_template()
        self.assertIn("$first_name", template)
        self.assertIn("$invoice_id", template)
        self.assertIn("$due_date", template)
        self.assertIn("$currency_symbol", template)
        self.assertIn("$amount_due", template)
        self.assertIn("$invoice_link", template)
        self.assertIn("$company_name", template)

    def test_invoice_overdue_template_contains_placeholders(self):
        template = templates.recurring_invoices_invoice_overdue_default_email_template()
        self.assertIn("$first_name", template)
        self.assertIn("$invoice_id", template)
        self.assertIn("$due_date", template)
        self.assertIn("$currency_symbol", template)
        self.assertIn("$amount_due", template)
        self.assertIn("$company_name", template)

    def test_invoice_cancelled_template_contains_placeholders(self):
        template = templates.recurring_invoices_invoice_cancelled_default_email_template()
        self.assertIn("$first_name", template)
        self.assertIn("$invoice_id", template)
        self.assertIn("$company_name", template)

    def test_email_footer_contains_company_name(self):
        footer = templates.email_footer()
        self.assertIn("Strelix MyFinances", footer)
        self.assertIn("$company_name", footer)
        self.assertIn("abuse@strelix.org", footer)
