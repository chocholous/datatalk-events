import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models import Event

log = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_message(self, chat_id: str, text: str) -> bool:
        settings = get_settings()
        if not settings.telegram_bot_token:
            log.warning("Telegram bot token not set, skipping")
            return False
        url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            return resp.status_code == 200


def format_telegram_message(events: list[Event]) -> str:
    items = "\n\n".join(
        f"*{e.title}*\n{e.location or 'TBD'}\n[Vice info]({e.url})"
        for e in events[:5]
    )
    return f"*Nove eventy*\n\n{items}"
