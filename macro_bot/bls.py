"""BLS Public Data API v2 client: batched fetch, response parsing, daily query budget."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .periods import Period

log = logging.getLogger(__name__)

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
MAX_SERIES_PER_REQUEST = 50  # v2 limit for registered keys
YEARS_OF_HISTORY = 2  # plus the current year: enough for y/y of the previous period


class BLSError(Exception):
    """A failed BLS request; the next poll simply tries again."""


class BLSAuthError(BLSError):
    """BLS rejected the API key. Fatal: retrying cannot help."""


class BudgetExhausted(BLSError):
    """The daily query budget is used up (or BLS says so)."""


class QueryBudget:
    """Counts BLS queries per US Eastern day and backs off near the daily limit.

    From `slow_at` of the limit, queries are spaced at least `slow_gap` seconds apart;
    from `stop_at`, no more queries until the next day.
    """

    def __init__(self, limit: int = 500, slow_at: float = 0.85, stop_at: float = 0.98, slow_gap: float = 60.0):
        self.limit = limit
        self.slow_after = int(limit * slow_at)
        self.stop_after = int(limit * stop_at)
        self.slow_gap = slow_gap
        self.used = 0
        self._day: date | None = None
        self._last: datetime | None = None

    def _roll(self, now: datetime) -> None:
        if now.date() != self._day:
            self._day, self.used, self._last = now.date(), 0, None

    def exhausted(self, now: datetime) -> bool:
        self._roll(now)
        return self.used >= self.stop_after

    def allow(self, now: datetime) -> bool:
        if self.exhausted(now):
            return False
        if self.used >= self.slow_after and self._last is not None:
            return (now - self._last).total_seconds() >= self.slow_gap
        return True

    def record(self, now: datetime) -> None:
        self._roll(now)
        self.used += 1
        self._last = now
        if self.used in (self.slow_after, self.stop_after):
            log.warning("BLS queries today: %d of %d; backing off", self.used, self.limit)

    def exhaust(self, now: datetime) -> None:
        self._roll(now)
        self.used = max(self.used, self.stop_after)


def parse_series(payload: Mapping[str, Any]) -> dict[str, dict[Period, Decimal]]:
    """Turn a BLS v2 JSON response into {series ID: {Period: value}}.

    Skips annual averages and non-numeric placeholders such as "-" (BLS uses it
    for months that were never collected, e.g. October 2025).
    """
    out: dict[str, dict[Period, Decimal]] = {}
    for series in (payload.get("Results") or {}).get("series") or []:
        obs: dict[Period, Decimal] = {}
        for row in series.get("data") or []:
            period = Period.parse(row.get("year", ""), row.get("period", ""))
            if period is None:
                continue
            try:
                value = Decimal(str(row.get("value", "")).replace(",", ""))
            except InvalidOperation:
                continue
            if value.is_finite():
                obs[period] = value
        if series.get("seriesID"):
            out[series["seriesID"]] = obs
    return out


def latest_period(obs: Mapping[Period, Decimal] | None) -> Period | None:
    return max(obs) if obs else None


class BLSClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        budget: QueryBudget,
        *,
        url: str = API_URL,
        max_series: int = MAX_SERIES_PER_REQUEST,
        timeout: float = 10.0,
    ):
        self._client = client
        self._key = api_key
        self.budget = budget
        self._url = url
        self._max_series = max_series
        self._timeout = timeout

    async def fetch(self, series_ids: Sequence[str], now: datetime) -> dict[str, dict[Period, Decimal]]:
        """Fetch all series in as few requests as possible (one, up to 50 series)."""
        result: dict[str, dict[Period, Decimal]] = {}
        for i in range(0, len(series_ids), self._max_series):
            chunk = list(series_ids[i : i + self._max_series])
            if not self.budget.allow(now):
                raise BudgetExhausted(f"daily BLS query budget reached ({self.budget.used} used)")
            self.budget.record(now)
            try:
                result.update(await self._request(chunk, now.year))
            except BudgetExhausted:
                self.budget.exhaust(now)
                raise
        return result

    async def _request(self, series_ids: list[str], year: int) -> dict[str, dict[Period, Decimal]]:
        payload: dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": str(year - YEARS_OF_HISTORY),
            "endyear": str(year),
        }
        if self._key:
            payload["registrationkey"] = self._key
        try:
            response = await self._client.post(self._url, json=payload, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise BLSError(f"{type(exc).__name__} talking to BLS") from None
        if response.status_code != 200:
            raise BLSError(f"BLS HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise BLSError("BLS returned a non-JSON response") from None

        status = body.get("status", "")
        messages = self._redact(" ".join(str(m) for m in body.get("message") or []))
        if status != "REQUEST_SUCCEEDED":
            lowered = messages.lower()
            if "key" in lowered and "invalid" in lowered:
                raise BLSAuthError(messages)
            if "threshold" in lowered:
                raise BudgetExhausted(messages)
            if status != "REQUEST_PARTIALLY_PROCESSED":
                raise BLSError(f"{status or 'unknown status'}: {messages}")
        if messages:
            log.debug("BLS messages: %s", messages)
        return parse_series(body)

    def _redact(self, text: str) -> str:
        # BLS echoes a rejected key back in its error message.
        return text.replace(self._key, "***") if self._key else text
