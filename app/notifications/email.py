import logging
from typing import Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import EmailProvider, get_settings

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailSender(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
    ) -> bool: ...


class ResendSender:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
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


def format_welcome_email(calendar_link: str) -> str:
    return (
        '<div style="font-family:sans-serif;max-width:600px;margin:0 auto;">'
        '<h1 style="color:#333;">Vitej v DataTalk Events!</h1>'
        '<p>Pridej si nas kalendar a bud v obraze o vsech data eventech:</p>'
        f'<a href="{calendar_link}" style="display:inline-block;padding:12px 24px;'
        'background:#0066cc;color:#fff;text-decoration:none;border-radius:6px;'
        'font-weight:bold;">Pridat Google Calendar</a>'
        '<p style="margin-top:20px;color:#666;">V den konani akce dostanes '
        "pripominku na nasem Telegram kanalu.</p>"
        "</div>"
    )
