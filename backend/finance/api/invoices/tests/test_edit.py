import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.settings")

from django.test import TestCase, RequestFactory
from unittest.mock import patch, MagicMock
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from backend.finance.models import Invoice
from backend.models import User
from backend.core.types.htmx import HtmxHttpRequest
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from backend.finance.api.invoices.edit import change_status
from types import SimpleNamespace


class ChangeStatusTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="12345", email="test@example.com")

        self.invoice = Invoice.objects.create(
            user=self.user,
            status="pending",
            client_email="client@example.com",
            client_name="Client A",
            currency="USD",
            date_due=timezone.now() + timedelta(days=30),
        )

    def add_htmx(self, request):
        request.htmx = SimpleNamespace(boosted=False)
        request.user = self.user
        request.team_id = None
        request.team = None
        setattr(request, "session", {})
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)

    def test_successful_status_change(self):
        request = self.factory.post("/")
        self.add_htmx(request)
        response = change_status(request, self.invoice.id, "paid")
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")

    def test_invoice_not_found(self):
        request = self.factory.post("/")
        self.add_htmx(request)
        response = change_status(request, 99999, "paid")
        self.assertContains(response, "Invoice not found", status_code=200)

    def test_invalid_status(self):
        request = self.factory.post("/")
        self.add_htmx(request)
        response = change_status(request, self.invoice.id, "invalid_status")
        self.assertContains(response, "Invalid status", status_code=200)

    def test_same_status(self):
        request = self.factory.post("/")
        self.add_htmx(request)
        response = change_status(request, self.invoice.id, "pending")
        self.assertContains(response, "Invoice status is already pending", status_code=200)
