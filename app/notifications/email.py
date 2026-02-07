import base64
import logging
from typing import Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import EmailProvider, get_settings
from app.ical import event_to_ical
from app.models import Event

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailSender(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        attachments: list[dict] | None = None,
    ) -> bool: ...


class ResendSender:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        attachments: list[dict] | None = None,
    ) -> bool:
        settings = get_settings()
        if not settings.resend_api_key:
            log.warning("Resend API key not set, skipping email")
            return False
        payload: dict = {
            "from": settings.email_from,
            "to": to,
            "subject": subject,
            "html": html,
        }
        if attachments:
            payload["attachments"] = attachments
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
            )
            if resp.status_code == 200:
                log.info(f"Email sent to {to} via Resend")
                return True
            log.error(f"Resend failed: {resp.text}")
            return False


class SendGridSender:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        attachments: list[dict] | None = None,
    ) -> bool:
        settings = get_settings()
        if not settings.sendgrid_api_key:
            log.warning("SendGrid API key not set, skipping email")
            return False
        payload: dict = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": settings.email_from},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}],
        }
        if attachments:
            payload["attachments"] = [
                {
                    "content": att["content"],
                    "filename": att["filename"],
                    "type": att.get("type", "text/calendar"),
                }
                for att in attachments
            ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SENDGRID_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code in (200, 202):
                log.info(f"Email sent to {to} via SendGrid")
                return True
            log.error(f"SendGrid failed: {resp.text}")
            return False


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_provider == EmailProvider.SENDGRID:
        return SendGridSender()
    return ResendSender()


def make_ics_attachment(event: Event) -> dict:
    """Create base64-encoded .ics attachment for email."""
    ics_bytes = event_to_ical(event)
    return {
        "content": base64.b64encode(ics_bytes).decode(),
        "filename": f"event-{event.id}.ics",
        "type": "text/calendar",
    }
