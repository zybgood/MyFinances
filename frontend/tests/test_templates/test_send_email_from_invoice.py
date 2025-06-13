import pytest
from django.template.loader import render_to_string
from django.utils.html import escape
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.settings")
import django

django.setup()


@pytest.mark.django_db
def test_send_email_modal_template_renders_successfully():

    email_list = [
        {"email": "client1@example.com", "name": "Client One"},
        {"email": "client2@example.com", "name": "Client Two"},
    ]
    selected_clients = ["client2@example.com"]
    context = {
        "email_list": email_list,
        "selected_clients": selected_clients,
        "invoice_url": "test-invoice-url-123",
        "content_min_length": 10,
        "content_max_length": 1000,
    }

    rendered = render_to_string("modals/send_email_from_invoice.html", context)

    assert "form" in rendered
    assert "modal_send_invoice_email-form" in rendered
    assert "Client Email" in rendered
    assert "Send Email" in rendered
    assert "Content" in rendered
    assert escape(email_list[0]["email"]) in rendered
    assert escape(email_list[1]["name"]) in rendered
    assert "test-invoice-url-123" in rendered
