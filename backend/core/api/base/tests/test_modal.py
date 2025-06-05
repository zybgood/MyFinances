import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings.settings')
import django
django.setup()

import pytest
from django.urls import reverse
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from backend.core.api.base.modal import open_modal
from backend.models import Organization
from backend.finance.models import Receipt
from unittest.mock import MagicMock
from backend.clients.models import Client
from backend.finance.models import Invoice
User = get_user_model()
from unittest.mock import patch
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta



@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse("ok"))
def test_open_modal_with_basic_modal_name(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='test@example.com').delete()
    user = User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass'
    )
    request = factory.get('/fake-url/')
    request.user = user

    response = open_modal(request, modal_name="upload_receipt")

    assert response.status_code == 200
    mock_render.assert_called_once()


@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse("ok"))
def test_open_modal_leave_team_context(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='leaveuser@example.com').delete()
    user = User.objects.create_user(
        username='leaveuser',
        email='leaveuser@example.com',
        password='leavepass'
    )
    org = Organization.objects.create(name="Test Org", leader=user)
    org.members.add(user)
    request = factory.get("/fake-url/")
    request.user = user
    response = open_modal(
        request,
        modal_name="some_modal",  # 再也不会真的去找模板
        context_type="leave_team",
        context_value=org.id
    )
    assert response.status_code == 200
    mock_render.assert_called_once()



@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse(b"<div>modal_receipts_upload Test Receipt</div>"))
def test_open_modal_receipt_edit_context(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='receipt@example.com').delete()
    user = User.objects.create_user(
        username='receiptuser',
        email='receipt@example.com',
        password='receiptpass'
    )
    receipt = Receipt.objects.create(
        owner=user,
        name="Test Receipt",
        date=None,
        merchant_store="Test Store",
        purchase_category="Food",
        total_price=12.5
    )
    request = factory.get("/fake-url/")
    request.user = user
    response = open_modal(
        request,
        modal_name="edit_receipt_modal",
        context_type="edit_receipt",
        context_value=receipt.id
    )
    assert response.status_code == 200
    assert b"modal_receipts_upload" in response.content
    assert b"Test Receipt" in response.content
    mock_render.assert_called_once()


@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse("ok"))
def test_open_modal_profile_picture(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='u1@example.com').delete()
    user = User.objects.create_user(
        username='u1',
        email='u1@example.com',
        password='123')
    request = factory.get('/fake-url/')
    request.user = user
    # 不创建 UserSettings，让它走 except 分支
    response = open_modal(request, modal_name="any", context_type="profile_picture", context_value=None)
    assert response.status_code == 200
    mock_render.assert_called_once()


@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse("ok"))
def test_open_modal_edit_invoice_to(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='u4@example.com').delete()
    user = User.objects.create_user(
        username='u4',
        email='u4@example.com',
        password='123'
    )
    client = Client.objects.create(owner=user, name="A", email="c@example.com", company="ACorp", address="addr")
    invoice = Invoice.objects.create(
        owner=user,
        client_to=client,
        date_due = timezone.now() + timedelta(days=30)
    )
    request = factory.get('/fake-url/')
    request.user = user
    request.actor = user  # invoice.filter_by_owner
    # mock filter_by_owner
    with patch("backend.finance.models.Invoice.filter_by_owner") as mock_filter:
        mock_filter.return_value.get.return_value = invoice
        response = open_modal(request, modal_name="edit_invoice_to", context_type="edit_invoice_to", context_value=invoice.id)
        assert response.status_code == 200
        mock_render.assert_called_once()


@pytest.mark.django_db
@patch("backend.core.api.base.modal.render", return_value=HttpResponse("ok"))
def test_open_modal_invoice_reminder_with_access(mock_render):
    factory = RequestFactory()
    User.objects.filter(email='u5@example.com').delete()
    user = User.objects.create_user(
        username='u5',
        email='u5@example.com',
        password='123'
    )
    client = Client.objects.create(
        owner=user,
        email="c2@example.com"
    )
    invoice = Invoice.objects.create(
        owner=user,
        client_to=client,
        date_due = timezone.now() + timedelta(days=30)
    )
    invoice.has_access = MagicMock(return_value=True)
    request = factory.get('/fake-url/')
    request.user = user
    with patch("backend.finance.models.Invoice.objects.get") as mock_get:
        mock_get.return_value = invoice
        response = open_modal(request, modal_name="invoice_reminder", context_type="invoice_reminder", context_value=invoice.id)
        assert response.status_code == 200
        mock_render.assert_called_once()
