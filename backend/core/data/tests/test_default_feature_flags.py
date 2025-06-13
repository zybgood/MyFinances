import unittest
from backend.core.data import default_feature_flags
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.settings")


class TestDefaultFeatureFlags(unittest.TestCase):
    def test_all_flags_have_required_fields(self):
        for flag in default_feature_flags.default_feature_flags:
            self.assertIsInstance(flag.name, str)
            self.assertIsInstance(flag.description, str)
            self.assertIsInstance(flag.default, bool)

    def test_expected_flags_present(self):
        names = {flag.name for flag in default_feature_flags.default_feature_flags}
        self.assertIn("areSignupsEnabled", names)
        self.assertIn("isInvoiceSchedulingEnabled", names)
        self.assertIn("areUserEmailsAllowed", names)
        self.assertIn("areInvoiceRemindersEnabled", names)
