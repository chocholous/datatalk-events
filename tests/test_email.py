import base64
from unittest.mock import patch

import httpx
import pytest
import respx

from app.models import Event
from app.notifications.email import (
    ResendSender,
    SendGridSender,
    make_ics_attachment,
)


@pytest.mark.anyio
@respx.mock
async def test_resend_sender_sends_email():
    """Mock Resend API and verify the call is made correctly."""
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "test-id"})
    )
    with patch(
        "app.notifications.email.get_settings"
    ) as mock_settings:
        mock_settings.return_value.resend_api_key = "test-key"
        mock_settings.return_value.email_from = "test@example.com"

        sender = ResendSender()
        result = await sender.send(
            to="user@example.com",
            subject="Test Subject",
            html="<p>Hello</p>",
        )

    assert result is True
    assert route.called
    request = route.calls[0].request
    assert b"user@example.com" in request.content
    assert b"Test Subject" in request.content


@pytest.mark.anyio
@respx.mock
async def test_sendgrid_sender_sends_email():
    """Mock SendGrid API and verify the call is made correctly."""
    route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
        return_value=httpx.Response(202)
    )
    with patch(
        "app.notifications.email.get_settings"
    ) as mock_settings:
        mock_settings.return_value.sendgrid_api_key = "sg-test-key"
        mock_settings.return_value.email_from = "test@example.com"

        sender = SendGridSender()
        result = await sender.send(
            to="user@example.com",
            subject="Test Subject",
            html="<p>Hello</p>",
        )

    assert result is True
    assert route.called
    request = route.calls[0].request
    assert b"user@example.com" in request.content
    assert b"Test Subject" in request.content


def test_ics_attachment_is_valid():
    """make_ics_attachment returns valid base64-encoded calendar data."""
    event = Event(
        id=1,
        external_id="test-ext-id",
        title="Test Event",
        url="https://example.com/event",
        location="Prague",
    )
    attachment = make_ics_attachment(event)

    assert attachment["filename"] == "event-1.ics"
    assert attachment["type"] == "text/calendar"

    # Decode and verify it's valid iCal
    decoded = base64.b64decode(attachment["content"])
    assert b"BEGIN:VCALENDAR" in decoded
    assert b"Test Event" in decoded
    assert b"Prague" in decoded
