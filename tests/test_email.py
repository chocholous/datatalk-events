from unittest.mock import patch

import httpx
import pytest
import respx

from app.notifications.email import (
    ResendSender,
    SendGridSender,
    format_welcome_email,
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


def test_welcome_email_contains_calendar_link():
    """Welcome email includes the Google Calendar link."""
    html = format_welcome_email("https://calendar.google.com/calendar/r?cid=test123")
    assert "https://calendar.google.com/calendar/r?cid=test123" in html
    assert "Pridat Google Calendar" in html
