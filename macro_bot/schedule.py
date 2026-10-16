"""In-process poll schedule in US Eastern time (DST handled by zoneinfo)."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


@dataclass(frozen=True)
class PollSchedule:
    """When to query BLS on a weekday.

    Around each release time: start `lead` early, poll every `fast_every` until
    `fast_until` after the release time, then every `slow_every` until `slow_until`
    after it. Outside those windows, a catch-up poll runs every `catchup_every`
    from `catchup_from` to `catchup_to`. Weekends have no polls.
    """

    release_times: tuple[str, ...]  # "HH:MM" in ET
    lead: timedelta
    fast_every: timedelta
    fast_until: timedelta
    slow_every: timedelta
    slow_until: timedelta
    catchup_from: str
    catchup_to: str
    catchup_every: timedelta

    def windows(self, day: date) -> list[tuple[datetime, datetime]]:
        return [(t - self.lead, t + self.slow_until) for t in (_at(day, hhmm) for hhmm in self.release_times)]

    def slots(self, day: date) -> list[datetime]:
        """Every poll time on `day`, sorted (ET-aware datetimes)."""
        if day.weekday() >= 5:
            return []
        slots: set[datetime] = set()
        for hhmm in self.release_times:
            release = _at(day, hhmm)
            t = release - self.lead
            while t < release + self.fast_until:
                slots.add(t)
                t += self.fast_every
            t = release + self.fast_until
            while t <= release + self.slow_until:
                slots.add(t)
                t += self.slow_every
        windows = self.windows(day)
        t, end = _at(day, self.catchup_from), _at(day, self.catchup_to)
        while t <= end:
            if not any(start <= t <= stop for start, stop in windows):
                slots.add(t)
            t += self.catchup_every
        return sorted(slots)

    def next_slot(self, after: datetime) -> datetime:
        """The first poll time strictly after `after`."""
        after = after.astimezone(ET)
        for offset in range(8):
            slots = self.slots(after.date() + timedelta(days=offset))
            i = bisect.bisect_right(slots, after)
            if i < len(slots):
                return slots[i]
        raise RuntimeError("Poll schedule has no slots in the next week")


def _at(day: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=ET)
