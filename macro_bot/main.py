"""Entry point: python -m macro_bot [--dry-run | --test-send]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta

import httpx

from . import config
from .bls import BLSAuthError, BLSClient, BLSError, BudgetExhausted, QueryBudget, latest_period
from .indicators import Dataset, all_series_ids, validate_releases
from .monitor import ReleaseMonitor
from .schedule import ET, now_et
from .settings import ConfigError, Settings, load_dotenv, load_settings
from .telegram import TelegramSender

log = logging.getLogger("macro_bot")

HEADERS = {"User-Agent": "macro-bot/1.0"}
BASELINE_RETRY_SECONDS = 30
BASELINE_RETRY_MAX_SECONDS = 600
SHUTDOWN_WAIT_SECONDS = 10  # finish in-flight sends; Railway's drainingSeconds is 15
WAITING_POLL_SECONDS = 3  # re-poll interval while a release waits for its other series
IDLE_LOG_SECONDS = 300  # log "next poll at ..." before sleeps longer than this


class Bot:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.series = all_series_ids(config.RELEASES)
        self.bls = BLSClient(http, settings.bls_api_key, QueryBudget(config.DAILY_QUERY_LIMIT))
        self.sender = TelegramSender(http, settings.telegram_bot_token, settings.telegram_chat_ids)
        self.monitor = ReleaseMonitor(config.RELEASES, config.MEMBER_GRACE_SECONDS)
        self._sends: set[asyncio.Task[None]] = set()
        self._budget_warned: date | None = None

    async def run(self, stop: asyncio.Event) -> None:
        log.info(
            "Starting: %d releases, %d series, %d chat(s)",
            len(config.RELEASES), len(self.series), len(self.sender.chat_ids),
        )
        data = await self._fetch_baseline(stop)
        if data is None:
            return
        self.monitor.baseline(data)
        for release in config.RELEASES:
            log.info("%s: baseline %s (not sent)", release.key, self.monitor.known.get(release.key, "no data yet"))
        _warn_missing(self.series, data)

        last_poll = now_et()
        idle_logged: datetime | None = None
        while not stop.is_set():
            now = now_et()
            due = config.SCHEDULE.next_slot(last_poll)
            if self.monitor.waiting:
                due = min(due, last_poll + timedelta(seconds=WAITING_POLL_SECONDS))
            delay = (due - now).total_seconds()
            if delay > 0:
                if delay > IDLE_LOG_SECONDS and idle_logged != due:
                    log.info("Next poll at %s ET (BLS queries today: %d)", f"{due:%a %Y-%m-%d %H:%M:%S}", self.bls.budget.used)
                    idle_logged = due
                await _sleep(stop, min(delay, 60))
                continue
            last_poll = now
            await self.poll(now)

        if self._sends:
            log.info("Waiting for %d message delivery task(s) before exit", len(self._sends))
            await asyncio.wait(self._sends, timeout=SHUTDOWN_WAIT_SECONDS)

    async def poll(self, now: datetime) -> None:
        budget = self.bls.budget
        if not budget.allow(now):
            if budget.exhausted(now):
                self._warn_budget(now, f"{budget.used} queries used")
            return  # near the limit: this slot is skipped to space queries out
        started = time.monotonic()
        try:
            data = await self.bls.fetch(self.series, now)
        except BudgetExhausted as exc:
            self._warn_budget(now, str(exc))
            return
        except BLSAuthError:
            raise
        except BLSError as exc:
            log.warning("BLS poll failed: %s", exc)
            return
        log.debug("Poll ok in %.0f ms (queries today: %d)", (time.monotonic() - started) * 1000, self.bls.budget.used)
        self.announce(data)

    def _warn_budget(self, now: datetime, reason: str) -> None:
        if self._budget_warned != now.date():
            log.warning("Daily BLS query budget reached (%s); pausing polls until tomorrow (ET)", reason)
            self._budget_warned = now.date()

    def announce(self, data: Dataset) -> None:
        for release, period in self.monitor.check(data, time.monotonic()):
            text = release.render(data, period)
            log.info("%s: new period %s; sending to %d chat(s)", release.key, period, len(self.sender.chat_ids))
            task = asyncio.create_task(self._deliver(release.key, text))
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)

    async def _deliver(self, key: str, text: str) -> None:
        results = await self.sender.send_all(text)
        failed = [chat for chat, ok in results.items() if not ok]
        if failed:
            log.error("%s: delivery failed for chat(s) %s", key, ", ".join(failed))

    async def _fetch_baseline(self, stop: asyncio.Event) -> Dataset | None:
        delay = BASELINE_RETRY_SECONDS
        while not stop.is_set():
            try:
                return await self.bls.fetch(self.series, now_et())
            except BLSAuthError:
                raise
            except BLSError as exc:
                log.warning("Startup fetch failed (%s); retrying in %ds", exc, delay)
            await _sleep(stop, delay)
            delay = min(delay * 2, BASELINE_RETRY_MAX_SECONDS)
        return None


async def run(settings: Settings) -> None:
    validate_releases(config.RELEASES)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows
            pass
    async with httpx.AsyncClient(headers=HEADERS) as http:
        await Bot(settings, http).run(stop)
    log.info("Stopped")


async def dry_run(settings: Settings) -> int:
    validate_releases(config.RELEASES)
    series = all_series_ids(config.RELEASES)
    async with httpx.AsyncClient(headers=HEADERS) as http:
        bls = BLSClient(http, settings.bls_api_key, QueryBudget(config.DAILY_QUERY_LIMIT))
        data = await bls.fetch(series, now_et())
    for release in config.RELEASES:
        period = latest_period(data.get(release.headline))
        print(f"--- {release.key}: headline {release.headline}, latest period {period} ---")
        print(release.render(data, period) if period else "No data for the headline series.")
        print()
    missing = _warn_missing(series, data)
    print(f"Fetched {len(series)} series in {bls.budget.used} BLS request(s). Nothing was sent.")
    return 1 if missing else 0


async def test_send(settings: Settings) -> int:
    text = f"✅ <b>Macro bot test</b>\nDelivery works. Sent {now_et():%Y-%m-%d %H:%M:%S} ET."
    async with httpx.AsyncClient(headers=HEADERS) as http:
        results = await TelegramSender(http, settings.telegram_bot_token, settings.telegram_chat_ids).send_all(text)
    for chat, ok in results.items():
        print(f"{chat}: {'OK' if ok else 'FAILED'}")
    return 0 if all(results.values()) else 1


def _warn_missing(series: list[str], data: Dataset) -> list[str]:
    missing = [s for s in series if not data.get(s)]
    if missing:
        log.warning("No data returned for series: %s (check the IDs in config.py)", ", ".join(missing))
    return missing


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


class RedactingFormatter(logging.Formatter):
    """Replaces secret values anywhere in a log line (tracebacks included); times in ET."""

    secrets: tuple[str, ...] = ()

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, ET).strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging() -> RedactingFormatter:
    formatter = RedactingFormatter("%(asctime)s.%(msecs)03d ET %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), handlers=[handler], force=True)
    # httpx logs full request URLs at INFO, and the Telegram URL contains the bot token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return formatter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="macro_bot", description="Send BLS macro releases to Telegram.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="fetch the latest data and print every message without sending")
    mode.add_argument("--test-send", action="store_true", help="send one test message to every chat ID")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    formatter = setup_logging()
    load_dotenv()
    try:
        if args.dry_run:
            settings = load_settings(required=("BLS_API_KEY",))
        elif args.test_send:
            settings = load_settings(required=("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS"))
        else:
            settings = load_settings()
        formatter.secrets = tuple(settings.secrets())

        if args.dry_run:
            return asyncio.run(dry_run(settings))
        if args.test_send:
            return asyncio.run(test_send(settings))
        asyncio.run(run(settings))
        return 0
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except BLSAuthError as exc:
        log.error("BLS rejected BLS_API_KEY: %s", exc)
        return 2
    except BLSError as exc:
        log.error("BLS request failed: %s", exc)
        return 1
    except KeyboardInterrupt:
        return 0
