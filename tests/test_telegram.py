import asyncio
import json

import httpx

from macro_bot.telegram import TelegramSender

TOKEN = "123456:secret"


def run_send(handler, chat_ids, text="<b>hi</b>"):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            sender = TelegramSender(http, TOKEN, chat_ids, sleep=fake_sleep)
            return await sender.send_all(text)

    return asyncio.run(go()), sleeps


def test_each_chat_is_independent_and_retried():
    calls: dict[str, int] = {}

    def handler(request):
        assert request.url.path == f"/bot{TOKEN}/sendMessage"
        body = json.loads(request.content)
        assert body["parse_mode"] == "HTML" and body["text"] == "<b>hi</b>"
        chat = body["chat_id"]
        calls[chat] = calls.get(chat, 0) + 1
        if chat == "111":  # rate limited once
            if calls[chat] == 1:
                return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}})
            return httpx.Response(200, json={"ok": True})
        if chat == "-1001234567890":  # bot not in channel: permanent failure
            return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot is not a member"})
        if chat == "333":  # network blip, then Telegram 502, then success
            if calls[chat] == 1:
                raise httpx.ConnectError("reset")
            if calls[chat] == 2:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(chat)

    results, sleeps = run_send(handler, ["111", "-1001234567890", "333"])
    assert results == {"111": True, "-1001234567890": False, "333": True}
    assert calls == {"111": 2, "-1001234567890": 1, "333": 3}
    assert sorted(sleeps) == [1.0, 2.0, 3.5]  # backoff 1s, 2s; retry_after 3s + 0.5s margin


def test_gives_up_after_max_attempts():
    results, sleeps = run_send(lambda request: httpx.Response(500, text="down"), ["111"])
    assert results == {"111": False}
    assert len(sleeps) == 4


def test_follows_supergroup_migration():
    seen = []

    def handler(request):
        chat = json.loads(request.content)["chat_id"]
        seen.append(chat)
        if chat == "-123":
            return httpx.Response(400, json={"ok": False, "parameters": {"migrate_to_chat_id": -1009999}})
        return httpx.Response(200, json={"ok": True})

    results, _ = run_send(handler, ["-123"])
    assert results == {"-123": True}
    assert seen == ["-123", "-1009999"]
