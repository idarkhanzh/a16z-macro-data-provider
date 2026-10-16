from decimal import Decimal

from conftest import M
from macro_bot import config
from macro_bot.monitor import ReleaseMonitor

CPI_SERIES = ("CUSR0000SA0", "CUUR0000SA0", "CUSR0000SA0L1E", "CUUR0000SA0L1E")


def copy(data):
    return {k: dict(v) for k, v in data.items()}


def with_october_cpi(data, series=CPI_SERIES):
    data = copy(data)
    for sid in series:
        data[sid][M(2026, 10)] = data[sid][M(2026, 9)] + Decimal("1")
    return data


def test_baseline_never_sends(data):
    monitor = ReleaseMonitor(config.RELEASES)
    monitor.baseline(data)
    assert monitor.known["cpi"] == M(2026, 9)
    assert monitor.check(data, now=0) == []


def test_new_period_sends_once(data):
    monitor = ReleaseMonitor(config.RELEASES)
    monitor.baseline(data)
    new = with_october_cpi(data)
    sent = monitor.check(new, now=1)
    assert [(r.key, p) for r, p in sent] == [("cpi", M(2026, 10))]
    assert monitor.check(new, now=2) == []


def test_revision_without_new_period_is_ignored(data):
    monitor = ReleaseMonitor(config.RELEASES)
    monitor.baseline(data)
    revised = copy(data)
    revised["CUSR0000SA0"][M(2026, 9)] += Decimal("0.5")
    revised["CES0000000001"][M(2026, 8)] += 50
    assert monitor.check(revised, now=1) == []


def test_older_period_after_newer_is_ignored(data):
    monitor = ReleaseMonitor(config.RELEASES)
    monitor.baseline(with_october_cpi(data))
    assert monitor.check(data, now=1) == []  # e.g. a stale API node


def test_waits_for_lagging_series_then_sends_after_grace(data):
    monitor = ReleaseMonitor(config.RELEASES, grace_seconds=30)
    monitor.baseline(data)
    partial = with_october_cpi(data, series=CPI_SERIES[:3])  # NSA core not updated yet
    assert monitor.check(partial, now=100) == []
    assert monitor.waiting
    assert monitor.check(partial, now=110) == []
    sent = monitor.check(partial, now=131)
    assert [r.key for r, _ in sent] == ["cpi"]
    assert not monitor.waiting


def test_lagging_series_catching_up_sends_immediately(data):
    monitor = ReleaseMonitor(config.RELEASES, grace_seconds=30)
    monitor.baseline(data)
    assert monitor.check(with_october_cpi(data, series=CPI_SERIES[:1]), now=100) == []
    assert [r.key for r, _ in monitor.check(with_october_cpi(data), now=102)] == ["cpi"]


def test_headline_missing_at_startup_becomes_baseline_later(data):
    monitor = ReleaseMonitor(config.RELEASES)
    without_cpi = {k: v for k, v in data.items() if k != "CUSR0000SA0"}
    monitor.baseline(without_cpi)
    assert "cpi" not in monitor.known
    assert monitor.check(data, now=1) == []  # first sighting: baseline only
    assert monitor.known["cpi"] == M(2026, 9)
