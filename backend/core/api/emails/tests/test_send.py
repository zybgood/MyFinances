from django.test import TestCase, RequestFactory
from unittest.mock import patch, MagicMock
from backend.core.api.emails import send
from django.utils import timezone
from datetime import timedelta
from backend.models import Client, User
from backend.finance.models import Invoice, InvoiceURL
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings.settings')
import django
django.setup()


class SendEmailTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password"
        )

        self.client_obj = Client.objects.create(
            email="test@example.com",
            name="Test Client",
            user=self.user)

        self.invoice = Invoice.objects.create(
            user=self.user,
            client_email="test@example.com",
            client_name="Client A",
            currency="USD",
            date_due = timezone.now() + timedelta(days=30)
        )

        self.invoice_url = InvoiceURL.objects.create(invoice=self.invoice)

    def add_messages_middleware(self, request):
        """Attach the messages middleware to the request."""
        setattr(request, 'session', 'session')
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)

    @patch("backend.core.api.emails.send.send_email")
    @patch("backend.core.api.emails.send.email_footer", return_value="\n--footer--")
    def test_send_single_email_success(self, mock_footer, mock_send_email):
        mock_send_email.return_value.success = True
        mock_send_email.return_value.response = {"MessageId": "abc123"}

        request = self.factory.post(
            "/send_single/",
            {"email": self.client_obj.email, "subject": "Hello World", "content": "A" * 80}
        )
        request.user = self.user
        request.actor = self.user
        self.add_messages_middleware(request)

        response = send._send_single_email_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Successfully emailed", response.content)

    @patch("backend.core.api.emails.send.send_email")
    def test_send_single_email_invalid_email(self, mock_send_email):
        request = self.factory.post(
            "/send_single/",
            {"email": "invalid-email", "subject": "Invalid Email", "content": "A" * 80}
        )
        request.user = self.user
        request.actor = self.user
        self.add_messages_middleware(request)

        response = send._send_single_email_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email", response.content)
        self.assertFalse(mock_send_email.called)

    @patch("backend.core.api.emails.send.send_templated_bulk_email")
    @patch("backend.core.api.emails.send.email_footer", return_value="\n--footer--")
    def test_send_bulk_email_success(self, mock_footer, mock_bulk_send):
        mock_bulk_send.return_value.failed = False
        mock_bulk_send.return_value.response = {"BulkEmailEntryResults": [{"MessageId": "id1"}]}

        request = self.factory.post(
            "/send_bulk/",
            {"emails": [self.client_obj.email], "subject": "Bulk Subject", "content": "B" * 100}
        )
        request.user = self.user
        request.actor = self.user
        self.add_messages_middleware(request)

        response = send._send_bulk_email_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Successfully emailed", response.content)
