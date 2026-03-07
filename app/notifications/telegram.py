import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models import Event

log = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def _bot_url(self, method: str) -> str:
        settings = get_settings()
        return f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/{method}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_to_channel(self, text: str) -> bool:
        settings = get_settings()
        if not settings.telegram_bot_token or not settings.telegram_channel_id:
            log.warning("Telegram bot token or channel ID not set, skipping")
            return False
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._bot_url("sendMessage"),
                json={
                    "chat_id": settings.telegram_channel_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            return resp.status_code == 200


def format_event_reminder(events: list[Event]) -> str:
    parts = []
    for e in events:
        lines = [f"*{e.title}*"]
        if e.date:
            lines.append(f"Cas: {e.date.strftime('%H:%M')}")
        lines.append(e.location or "TBD")
        speakers_list = json.loads(e.speakers) if e.speakers else []
        if speakers_list:
            lines.append(f"Speakers: {', '.join(speakers_list)}")
        if e.description:
            lines.append(e.description[:200])
        lines.append(f"[Vice info]({e.url})")
        parts.append("\n".join(lines))
    return f"*Za 2 hodiny:*\n\n" + "\n\n".join(parts)
