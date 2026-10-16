import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest

from macro_bot import config
from macro_bot.bls import BLSAuthError, BLSClient, BLSError, BudgetExhausted, QueryBudget
from macro_bot.indicators import all_series_ids
from macro_bot.schedule import ET

NOW = datetime(2026, 10, 16, 8, 30, 1, tzinfo=ET)
KEY = "abcdef0123456789abcdef0123456789"


def make_client(handler, budget=None, **kwargs):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return http, BLSClient(http, KEY, budget or QueryBudget(), **kwargs)


def fetch(handler, series, **kwargs):
    async def go():
        http, client = make_client(handler, **kwargs)
        async with http:
            return await client.fetch(series, NOW), client
    return asyncio.run(go())


def test_one_batched_request_for_all_series(payload):
    series = all_series_ids(config.RELEASES)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    data, client = fetch(handler, series)
    assert len(requests) == 1
    assert requests[0]["seriesid"] == series
    assert requests[0]["registrationkey"] == KEY
    assert (requests[0]["startyear"], requests[0]["endyear"]) == ("2024", "2026")
    assert set(data) == set(series)
    assert client.budget.used == 1


def test_chunks_above_the_series_limit(payload):
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["seriesid"]))
        return httpx.Response(200, json=payload)

    _, client = fetch(handler, [f"S{i}" for i in range(60)])
    assert sizes == [50, 10]
    assert client.budget.used == 2


def test_invalid_key_is_fatal_and_redacted():
    def handler(request):
        return httpx.Response(200, json={
            "status": "REQUEST_NOT_PROCESSED",
            "message": [f"The key:{KEY} provided by the User is invalid. Please provide a proper key"],
            "Results": {},
        })

    with pytest.raises(BLSAuthError) as err:
        fetch(handler, ["CUSR0000SA0"])
    assert KEY not in str(err.value)
    assert "***" in str(err.value)


def test_daily_threshold_exhausts_budget():
    budget = QueryBudget()

    def handler(request):
        return httpx.Response(200, json={
            "status": "REQUEST_NOT_PROCESSED",
            "message": ["Your daily threshold for total number of requests allocated has been reached."],
            "Results": {},
        })

    with pytest.raises(BudgetExhausted):
        fetch(handler, ["CUSR0000SA0"], budget=budget)
    assert not budget.allow(NOW)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503, text="busy"), httpx.Response(200, text="<html>"), httpx.Response(200, json={"status": "REQUEST_FAILED", "message": ["oops"]})],
)
def test_transient_errors_raise_blserror(response):
    with pytest.raises(BLSError):
        fetch(lambda request: response, ["CUSR0000SA0"])


def test_network_error_raises_blserror():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(BLSError):
        fetch(handler, ["CUSR0000SA0"])


def test_budget_backs_off_near_limit_and_resets_daily():
    budget = QueryBudget(limit=100, slow_at=0.5, stop_at=0.9, slow_gap=60)
    t = NOW
    for _ in range(50):
        assert budget.allow(t)
        budget.record(t)
    # Slow zone: at most one query a minute.
    assert not budget.allow(t + timedelta(seconds=10))
    assert budget.allow(t + timedelta(seconds=60))
    for i in range(40):
        t = NOW + timedelta(minutes=i + 1)
        budget.record(t)
    assert budget.used == 90
    assert not budget.allow(t + timedelta(hours=1))  # stopped for the day
    assert budget.allow(NOW + timedelta(days=1))  # new ET day
    assert budget.used == 0
