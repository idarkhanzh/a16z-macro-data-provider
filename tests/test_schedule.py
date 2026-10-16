from datetime import date, datetime, timedelta, timezone

from macro_bot.config import SCHEDULE
from macro_bot.schedule import ET


def test_weekday_query_count_fits_budget():
    slots = SCHEDULE.slots(date(2026, 10, 15))  # Thursday
    # Per window: 68 polls every 2s (08:29:45-08:31:59) + 53 every 15s (08:32:00-08:45:00).
    # Catch-up: 23 half-hour slots 07:00-18:00, minus the 08:30 and 10:00 ones inside windows.
    assert len(slots) == 2 * (68 + 53) + 21
    assert len(slots) < 500 * 0.85


def test_window_shape():
    slots = SCHEDULE.slots(date(2026, 10, 15))
    times = [s.strftime("%H:%M:%S") for s in slots]
    assert times[0] == "07:00:00"
    assert "08:29:45" in times and "08:29:43" not in times
    assert "08:30:01" in times and "08:31:59" in times
    assert "08:32:00" in times and "08:32:15" in times and "08:45:00" in times
    assert "09:59:45" in times and "10:15:00" in times
    assert times[-1] == "18:00:00"
    assert min(b - a for a, b in zip(slots, slots[1:])) >= timedelta(seconds=1)


def test_no_polls_on_weekends():
    assert SCHEDULE.slots(date(2026, 10, 17)) == []  # Saturday
    assert SCHEDULE.slots(date(2026, 10, 18)) == []  # Sunday


def test_daylight_saving_is_handled():
    winter = SCHEDULE.slots(date(2026, 1, 15))
    summer = SCHEDULE.slots(date(2026, 7, 15))
    first_fast = lambda slots: next(s for s in slots if s.strftime("%H:%M:%S") == "08:29:45")
    assert first_fast(winter).astimezone(timezone.utc).strftime("%H:%M:%S") == "13:29:45"  # EST, UTC-5
    assert first_fast(summer).astimezone(timezone.utc).strftime("%H:%M:%S") == "12:29:45"  # EDT, UTC-4


def test_next_slot_is_strictly_after():
    t = datetime(2026, 10, 15, 8, 29, 45, tzinfo=ET)
    assert SCHEDULE.next_slot(t) == t + timedelta(seconds=2)
    assert SCHEDULE.next_slot(t - timedelta(microseconds=1)) == t


def test_next_slot_skips_weekend():
    friday_evening = datetime(2026, 10, 16, 18, 0, 1, tzinfo=ET)
    assert SCHEDULE.next_slot(friday_evening) == datetime(2026, 10, 19, 7, 0, tzinfo=ET)


def test_next_slot_accepts_utc_input():
    utc = datetime(2026, 10, 15, 12, 29, 44, tzinfo=timezone.utc)  # 08:29:44 EDT
    assert SCHEDULE.next_slot(utc) == datetime(2026, 10, 15, 8, 29, 45, tzinfo=ET)
