"""End-to-end run loop against mocked BLS and Telegram endpoints."""

import asyncio
import copy
import json
from datetime import timedelta

import httpx

from macro_bot import main
from macro_bot.settings import Settings

CPI_OCTOBER = {"CUSR0000SA0": "337.0", "CUUR0000SA0": "337.5", "CUSR0000SA0L1E": "339.5", "CUUR0000SA0L1E": "339.9"}


class EveryFewMs:
    def next_slot(self, after):
        return after + timedelta(milliseconds=20)


def with_october_cpi(payload):
    new = copy.deepcopy(payload)
    for series in new["Results"]["series"]:
        if series["seriesID"] in CPI_OCTOBER:
            series["data"].insert(0, {"year": "2026", "period": "M10", "value": CPI_OCTOBER[series["seriesID"]]})
    return new


def test_baseline_then_one_message_per_chat(payload, monkeypatch):
    monkeypatch.setattr(main.config, "SCHEDULE", EveryFewMs())
    released = with_october_cpi(payload)
    bls_calls = 0
    sent: list[dict] = []
    stop = asyncio.Event()

    def handler(request):
        nonlocal bls_calls
        if request.url.host == "api.bls.gov":
            bls_calls += 1
            if bls_calls == 1:
                return httpx.Response(200, json=payload)  # startup baseline: September is old news
            if bls_calls == 2:
                return httpx.Response(503, text="busy")  # a failed poll must not crash the loop
            if bls_calls >= 8:
                stop.set()
            return httpx.Response(200, json=released)
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            settings = Settings("123:token", ("111", "-1001234567890"), "key")
            await asyncio.wait_for(main.Bot(settings, http).run(stop), timeout=10)

    asyncio.run(go())
    assert sorted(m["chat_id"] for m in sent) == ["-1001234567890", "111"]  # once per chat, never repeated
    assert all(m["text"].startswith("<b>US CPI — October 2026</b>\nHeadline: +0.2% m/m") for m in sent)
