from __future__ import annotations

import re
from dataclasses import dataclass

from collections.abc import Iterator
from string import Template

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from mypy_boto3_sesv2.type_defs import BulkEmailEntryResultTypeDef

from backend.core.data.default_email_templates import email_footer
from backend.decorators import feature_flag_check, web_require_scopes
from backend.decorators import htmx_only
from backend.finance.models import Invoice, InvoiceURL
from backend.models import Client
from backend.models import EmailSendStatus
from backend.models import QuotaLimit
from backend.models import QuotaUsage
from backend.core.types.emails import (
    BulkEmailEmailItem,
)
from backend.core.types.requests import WebRequest

from settings.helpers import send_email, send_templated_bulk_email, get_var
from backend.core.types.htmx import HtmxHttpRequest


@dataclass
class Ok: ...


@dataclass
class Invalid:
    message: str


@require_POST
@htmx_only("emails:dashboard")
@feature_flag_check("areUserEmailsAllowed", status=True, api=True, htmx=True)
@web_require_scopes("emails:send", False, False, "emails:dashboard")
def send_single_email_view(request: WebRequest) -> HttpResponse:
    # check_usage = False  # quota_usage_check_under(request, "emails-single-count", api=True, htmx=True)
    # if not isinstance(check_usage, bool):
    #     return check_usage

    return _send_single_email_view(request)


@require_POST
@htmx_only("emails:dashboard")
@feature_flag_check("areUserEmailsAllowed", status=True, api=True, htmx=True)
@web_require_scopes("emails:send", False, False, "emails:dashboard")
def send_bulk_email_view(request: WebRequest) -> HttpResponse:
    # email_count = len(request.POST.getlist("emails")) - 1

    # check_usage = quota_usage_check_under(request, "emails-single-count", add=email_count, api=True, htmx=True)
    # if not isinstance(check_usage, bool):
    #     return check_usage
    return _send_bulk_email_view(request)


@require_POST
@htmx_only("emails:dashboard")
@feature_flag_check("areUserEmailsAllowed", status=True, api=True, htmx=True)
@web_require_scopes("emails:send", False, False, "emails:dashboard")
def send_invoice_email_view(request: WebRequest, uuid: str) -> HttpResponse:
    return _send_invoice_email_view(request, uuid)

def _send_invoice_email_view(request: WebRequest, uuid: str) -> HttpResponse:
    to_list: list[str] = request.POST.getlist("emails")
    subj: str          = request.POST.get("subject", "")
    body_raw: str      = request.POST.get("content", "")

    cc_list  = request.POST.get("cc_emails", "").split(",")  if request.POST.get("cc_emails")  else []
    bcc_list = request.POST.get("bcc_emails", "").split(",") if request.POST.get("bcc_emails") else []

    inv_id = InvoiceURL.objects.filter(uuid=uuid).values_list("invoice_id", flat=True).first()
    if not inv_id:
        messages.error(request, "Invalid invoice link")
        return render(request, "base/toast.html")

    invoice = Invoice.objects.select_related().get(id=inv_id)
    product_lines = "\n".join(f"- {p}" for p in invoice.items.values_list("name", flat=True))

    client_filter = {"organization": request.user.logged_in_as_team} if request.user.logged_in_as_team else {"user": request.user}
    clients_qs = Client.objects.filter(**client_filter, email__in=to_list)

    mismatch = validate_bulk_inputs(request=request, emails=to_list, clients=clients_qs, message=body_raw, subject=subj)
    
    if mismatch:
        messages.error(request, mismatch)
        return render(request, "base/toast.html")

    body_raw += email_footer()
    body_html = body_raw.replace("\r\n", "<br>").replace("\n", "<br>")

    shared_vars = {
        "invoice_id"   : invoice.id,
        "invoice_ref"  : invoice.reference or getattr(invoice, "invoice_number", None) or invoice.id,
        "due_date"     : invoice.date_due.strftime("%A, %B %d, %Y"),
        "amount_due"   : invoice.get_total_price(),
        "currency"     : invoice.currency,
        "currency_symbol": invoice.get_currency_symbol(),
        "product_list" : product_lines,
        "company_name" : invoice.self_company or invoice.self_name or "MyFinances Customer",
        "invoice_link" : f"{get_var('SITE_URL')}/invoice/{uuid}",
    }

    bulk_items: list[BulkEmailEmailItem] = []
    for addr in to_list:
        client_obj = clients_qs.filter(email=addr).first()
        recipient_name = (client_obj.name.split()[0] if client_obj else "User")

        txt_render = Template(body_raw ).safe_substitute({"first_name": recipient_name, **shared_vars})
        html_render = Template(body_html).safe_substitute({"first_name": recipient_name, **shared_vars})

        bulk_items.append(
            BulkEmailEmailItem(
                destination=addr,
                cc=cc_list,
                bcc=bcc_list,
                template_data={
                    "users_name" : recipient_name,
                    "content_text": txt_render,
                    "content_html": html_render,
                },
            )
        )

    if get_var("DEBUG", "").lower() == "true":
        print("[EMAIL-DEBUG]", {"count": len(bulk_items), "subject": subj, "samples": bulk_items[:2]})
        messages.success(request, f"[DEBUG] Would send {len(bulk_items)} mails")
        return render(request, "base/toast.html")

    send_res = send_email(
        destination=to_list,
        subject=subj,
        content={
            "template_name": "user_send_client_email",
            "template_data": {
                "subject"     : subj,
                "sender_name" : request.user.first_name or request.user.email,
                "sender_id"   : request.user.id,
                "content_text": Template(body_raw ).safe_substitute(shared_vars),
                "content_html": Template(body_html).safe_substitute(shared_vars),
            },
        },
        from_address=request.user.email,
        cc=cc_list,
        bcc=bcc_list,
    )
    if send_res.failed:
        messages.error(request, send_res.error)
        return render(request, "base/toast.html")

    entry_list = send_res.response.get("BulkEmailEntryResults", [])
    pairs: Iterator[tuple[BulkEmailEmailItem, BulkEmailEntryResultTypeDef]] = zip(bulk_items, entry_list)

    status_bulk = EmailSendStatus.objects.bulk_create(
        [
            EmailSendStatus(
                organization=request.user.logged_in_as_team if request.user.logged_in_as_team else None,
                user=None if request.user.logged_in_as_team else request.user,
                sent_by=request.user,
                recipient=item.destination,
                aws_message_id=res.get("MessageId"),
                status="pending",
            )
            for item, res in pairs
            if res
        ]
    )

    messages.success(request, f"Successfully emailed {len(bulk_items)} people.")

    try:
        limit_map = {q.slug: q for q in QuotaLimit.objects.filter(slug__in=["emails-single-count", "emails-bulk-count"])}
        QuotaUsage.objects.bulk_create(
            [QuotaUsage(user=request.user, quota_limit=limit_map["emails-single-count"], extra_data=s.id) for s in status_bulk] +
            [QuotaUsage(user=request.user, quota_limit=limit_map["emails-bulk-count"])]
        )
    except KeyError:
        pass

    return render(request, "base/toast.html")


def _send_bulk_email_view(request: WebRequest) -> HttpResponse:
    emails: list[str] = request.POST.getlist("emails")
    subject: str = request.POST.get("subject", "")
    message: str = request.POST.get("content", "")
    cc_yourself = True if request.POST.get("cc_yourself") else False
    bcc_yourself = True if request.POST.get("bcc_yourself") else False

    if request.user.logged_in_as_team:
        clients = Client.objects.filter(organization=request.user.logged_in_as_team, email__in=emails)
    else:
        clients = Client.objects.filter(user=request.user, email__in=emails)

    validated_bulk = validate_bulk_inputs(request=request, emails=emails, clients=clients, message=message, subject=subject)

    if validated_bulk:
        messages.error(request, validated_bulk)
        return render(request, "base/toast.html")

    message += email_footer()
    message_single_line_html = message.replace("\r\n", "<br>").replace("\n", "<br>")

    email_list: list[BulkEmailEmailItem] = []

    for email in emails:
        client = clients.filter(email=email).first()

        email_data = {
            "users_name": client.name.split()[0] if client else "User",
            "first_name": client.name.split()[0] if client else "User",
            "company_name": request.actor.name,
        }  # todo: add all variables from https://strelix.link/mfd/user-guide/emails/templates/

        email_list.append(
            BulkEmailEmailItem(
                destination=email,
                cc=[request.user.email] if cc_yourself else [],
                bcc=[request.user.email] if bcc_yourself else [],
                template_data={
                    "users_name": client.name.split()[0] if client else "User",
                    "content_text": Template(message).substitute(email_data),
                    "content_html": Template(message_single_line_html).substitute(email_data),
                },
            )
        )

    if get_var("DEBUG", "").lower() == "true":
        print(
            {
                "email_list": email_list,
                "template_name": "user_send_client_email",
                "default_template_data": {
                    "sender_name": request.user.first_name or request.user.email,
                    "sender_id": request.user.id,
                    "subject": subject,
                },
            }
        )
        messages.success(request, f"Successfully emailed {len(email_list)} people.")
        return render(request, "base/toast.html")

    EMAIL_SENT = send_templated_bulk_email(
        email_list=email_list,
        template_name="user_send_client_email",
        default_template_data={
            "sender_name": request.user.first_name or request.user.email,
            "sender_id": request.user.id,
            "subject": subject,
        },
    )

    if EMAIL_SENT.failed:
        messages.error(request, EMAIL_SENT.error)
        return render(request, "base/toast.html")

    # todo - fix

    EMAIL_RESPONSES: Iterator[tuple[BulkEmailEmailItem, BulkEmailEntryResultTypeDef]] = zip(
        email_list, EMAIL_SENT.response.get("BulkEmailEntryResults")  # type: ignore[arg-type]
    )

    if request.user.logged_in_as_team:
        SEND_STATUS_OBJECTS: list[EmailSendStatus] = EmailSendStatus.objects.bulk_create(
            [
                EmailSendStatus(
                    organization=request.user.logged_in_as_team,
                    sent_by=request.user,
                    recipient=response[0].destination,
                    aws_message_id=response[1].get("MessageId"),
                    status="pending",
                )
                for response in EMAIL_RESPONSES
            ]
        )
    else:
        SEND_STATUS_OBJECTS = EmailSendStatus.objects.bulk_create(
            [
                EmailSendStatus(
                    user=request.user,
                    sent_by=request.user,
                    recipient=response[0].destination,
                    aws_message_id=response[1].get("MessageId"),
                    status="pending",
                )
                for response in EMAIL_RESPONSES
            ]
        )

    messages.success(request, f"Successfully emailed {len(email_list)} people.")

    try:
        quota_limits = QuotaLimit.objects.filter(slug__in=["emails-single-count", "emails-bulk-count"])

        QuotaUsage.objects.bulk_create(
            [
                QuotaUsage(user=request.user, quota_limit=quota_limits.get(slug="emails-single-count"), extra_data=status.id)
                for status in SEND_STATUS_OBJECTS
            ]
            + [QuotaUsage(user=request.user, quota_limit=quota_limits.get(slug="emails-bulk-count"))]
        )
    except QuotaLimit.DoesNotExist:
        ...

    return render(request, "base/toast.html")


def _send_single_email_view(request: WebRequest) -> HttpResponse:
    email: str = str(request.POST.get("email", "")).strip()
    subject: str = request.POST.get("subject", "")
    message: str = request.POST.get("content", "")

    if request.user.logged_in_as_team:
        client = Client.objects.filter(organization=request.user.logged_in_as_team, email=email).first()
    else:
        client = Client.objects.filter(user=request.user, email=email).first()

    validated_single = validate_single_inputs(request=request, email=email, client=client, message=message, subject=subject)

    if validated_single:
        messages.error(request, validated_single)
        return render(request, "base/toast.html")

    message += email_footer()
    message_single_line_html = message.replace("\r\n", "<br>").replace("\n", "<br>")

    email_data = {"company_name": request.actor.name}

    EMAIL_SENT = send_email(
        destination=email,
        subject=subject,
        content={
            "template_name": "user_send_client_email",
            "template_data": {
                "subject": subject,
                "sender_name": request.user.first_name or request.user.email,
                "sender_id": request.user.id,
                "content_text": Template(message).substitute(email_data),
                "content_html": Template(message_single_line_html).substitute(email_data),
            },
        },
    )

    aws_message_id = None
    if EMAIL_SENT.response is not None:
        aws_message_id = EMAIL_SENT.response.get("MessageId")

    status_object = EmailSendStatus(sent_by=request.user, recipient=email, aws_message_id=aws_message_id)

    if EMAIL_SENT.success:
        messages.success(request, f"Successfully emailed {email}.")
        status_object.status = "pending"
    else:
        status_object.status = "failed_to_send"
        messages.error(request, f"Failed to send the email. Error: {EMAIL_SENT.error}")

    if request.user.logged_in_as_team:
        status_object.organization = request.user.logged_in_as_team
    else:
        status_object.user = request.user

    status_object.save()

    QuotaUsage.create_str(request.user, "emails-single-count", status_object.id)

    return render(request, "base/toast.html")


def validate_bulk_inputs(*, request, emails, clients, message, subject) -> str | None:
    def run_validations():
        yield validate_bulk_quotas(request=request, emails=emails)
        yield validate_email_list(emails=emails)
        # yield validate_client_list(clients=clients, emails=emails)
        yield validate_email_content(message=message, request=request)
        yield validate_email_subject(subject=subject)

    for validation in run_validations():
        if validation:
            return validation

    return None


def validate_single_inputs(*, request, email, client, message, subject) -> str | None:
    def run_validations():
        yield validate_client_email(email=email, client=client)
        yield validate_client(client=client)
        yield validate_email_content(message=message, request=request)
        yield validate_email_subject(subject=subject)

    for validation in run_validations():
        if validation:
            return validation

    return None


def validate_bulk_quotas(*, request: HtmxHttpRequest, emails: list) -> str | None:
    email_count = len(emails)

    slugs = ["emails-bulk-count", "emails-bulk-max_sends"]
    quota_limits: QuerySet[QuotaLimit] = QuotaLimit.objects.prefetch_related("quota_overrides", "quota_usage").filter(slug__in=slugs)

    # quota_limits.get().

    above_bulk_sends_limit: bool = quota_limits.get(slug="emails-bulk-count").strict_goes_above_limit(request.user)
    if above_bulk_sends_limit:
        return "You have exceeded the quota limit for bulk email sends per month"

    max_email_count = quota_limits.get(slug="emails-bulk-max_sends").get_quota_limit(user=request.user)

    if email_count > max_email_count:
        return "You have exceeded the quota limit for the number of emails allowed per bulk send"
    else:
        return None


def validate_client_email(email, client) -> str | None:
    if not email:
        return "No email provided"

    try:
        validate_email(email)
    except ValidationError:
        return "Invalid email"

    if client.email != email:
        return "Something went wrong when checking the email of the client"

    return None


def validate_client(client: Client) -> str | None:
    if not client:
        return "Could not find client object"

    # if not client.email_verified:
    #     return "The clients email has not yet been verified"
    return None


def validate_email_list(emails: list[str]) -> str | None:
    if not emails:
        return "There was no emails provided"

    for email in emails:
        try:
            validate_email(email)
        except ValidationError:
            return f"The email {email} is invalid."
    return None


def validate_client_list(clients: QuerySet[Client], emails: list[str]) -> str | None:
    for email in emails:
        if not clients.filter(email=email).exists():
            return f"Could not find client object for {email}"
    return None


def validate_email_subject(subject: str) -> str | None:
    min_count = 8
    max_count = 64

    if len(subject) < min_count:
        return "The minimum character count is 16 for a subject"

    if len(subject) > max_count:
        return "The maximum character count is 64 characters for a subject"

    alpha_count = len(re.findall("[a-zA-Z ]", subject))
    non_alpha_count = len(subject) - alpha_count

    if non_alpha_count > 0 and alpha_count / non_alpha_count < 10:
        return "The subject should have at least 10 letters per 'symbol'"

    return None


def validate_email_content(message: str, request: HtmxHttpRequest) -> str | None:
    min_count = 64
    max_count = QuotaLimit.objects.get(slug="emails-email_character_count").get_quota_limit(user=request.user)

    if len(message) < min_count:
        return "The minimum character count is 64 for an email"

    if len(message) > max_count:
        return "The maximum character count is 1000 characters for an email"
    return None
