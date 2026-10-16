"""Send messages through the Telegram Bot API sendMessage endpoint."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramSender:
    """Delivers each message to every chat independently, with retries.

    Retries 429s after Telegram's `retry_after`, and network errors and 5xx with
    exponential backoff. Other 4xx errors (bad chat ID, bot not in the chat) are
    logged and not retried. One failing chat never delays or blocks the others.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str,
        chat_ids: Sequence[str],
        *,
        max_attempts: int = 5,
        timeout: float = 15.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        self._client = client
        self._url = f"{API_BASE}/bot{token}/sendMessage"
        self.chat_ids = list(chat_ids)
        self._max_attempts = max_attempts
        self._timeout = timeout
        self._sleep = sleep
        self._migrated: dict[str, str] = {}  # group upgraded to supergroup: old ID -> new ID

    async def send_all(self, text: str) -> dict[str, bool]:
        results = await asyncio.gather(*(self.send(chat, text) for chat in self.chat_ids), return_exceptions=True)
        outcome: dict[str, bool] = {}
        for chat, result in zip(self.chat_ids, results):
            if isinstance(result, BaseException):
                log.error("chat %s: unexpected error %s", chat, type(result).__name__)
            outcome[chat] = result is True
        return outcome

    async def send(self, chat_id: str, text: str) -> bool:
        target = self._migrated.get(chat_id, chat_id)
        payload = {
            "chat_id": target,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        for attempt in range(1, self._max_attempts + 1):
            last_try = attempt == self._max_attempts
            try:
                response = await self._client.post(self._url, json=payload, timeout=self._timeout)
            except httpx.HTTPError as exc:
                # Log the exception type only: httpx messages can include the URL, which holds the token.
                log.warning("chat %s: %s (attempt %d/%d)", target, type(exc).__name__, attempt, self._max_attempts)
                if not last_try:
                    await self._sleep(_backoff(attempt))
                continue

            body = _json(response)
            if response.status_code == 200 and body.get("ok"):
                log.info("chat %s: sent", target)
                return True

            params = body.get("parameters") or {}
            description = body.get("description", "")
            if response.status_code == 429:
                delay = float(params.get("retry_after", 5))
                log.warning("chat %s: rate limited, retrying in %.0fs", target, delay)
                if not last_try:
                    await self._sleep(delay + 0.5)
                continue
            if params.get("migrate_to_chat_id"):
                new_id = str(params["migrate_to_chat_id"])
                log.warning("chat %s became supergroup %s; update TELEGRAM_CHAT_IDS", target, new_id)
                self._migrated[chat_id] = target = payload["chat_id"] = new_id
                continue
            if response.status_code >= 500:
                log.warning("chat %s: Telegram HTTP %d (attempt %d/%d)", target, response.status_code, attempt, self._max_attempts)
                if not last_try:
                    await self._sleep(_backoff(attempt))
                continue

            log.error("chat %s: rejected by Telegram (HTTP %d): %s", target, response.status_code, description)
            return False

        log.error("chat %s: giving up after %d attempts", target, self._max_attempts)
        return False


def _backoff(attempt: int) -> float:
    return min(2.0 ** (attempt - 1), 30.0)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
