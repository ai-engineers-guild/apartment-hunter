"""Telegram notification channel."""

from __future__ import annotations

import logging

from apartment_hunter.config import get_settings
from apartment_hunter.core.interfaces import Notifier
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Sends apartment cards to a Telegram chat via Bot API."""

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def notify(self, apartment: Apartment, profile: SearchProfile) -> bool:
        settings = get_settings()
        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            log.debug("Telegram not configured, skipping notification")
            return False

        try:
            import httpx

            text = apartment.to_card()
            text += f"\n\n🔍 Профиль: {profile.name}"

            # Use Telegram Bot API directly via httpx (no heavy python-telegram-bot dep)
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": False,
                    },
                )
                if resp.status_code == 200:
                    log.info("Telegram notification sent for %s", apartment.source_id)
                    return True
                else:
                    log.warning("Telegram API error: %s", resp.text)
                    return False
        except Exception as exc:
            log.error("Telegram notification failed: %s", exc)
            return False
