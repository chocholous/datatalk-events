from unittest.mock import patch

import httpx
import pytest
import respx

from app.notifications.telegram import TelegramNotifier


@pytest.mark.anyio
@respx.mock
async def test_telegram_sends_message():
    """Mock Telegram API and verify message is sent."""
    route = respx.post(
        "https://api.telegram.org/bottest-token/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    with patch(
        "app.notifications.telegram.get_settings"
    ) as mock_settings:
        mock_settings.return_value.telegram_bot_token = "test-token"

        notifier = TelegramNotifier()
        result = await notifier.send_message(
            chat_id="12345", text="Hello from test"
        )

    assert result is True
    assert route.called
    request = route.calls[0].request
    assert b"12345" in request.content
    assert b"Hello from test" in request.content


@pytest.mark.anyio
async def test_telegram_skips_without_token():
    """No token configured returns False."""
    with patch(
        "app.notifications.telegram.get_settings"
    ) as mock_settings:
        mock_settings.return_value.telegram_bot_token = ""

        notifier = TelegramNotifier()
        result = await notifier.send_message(
            chat_id="12345", text="Hello"
        )

    assert result is False
