"""In-memory release detection: which releases have a new headline period."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from .bls import latest_period
from .indicators import Dataset, Release
from .periods import Period

log = logging.getLogger(__name__)


class ReleaseMonitor:
    """Tracks the latest headline period per release, in memory only.

    `baseline` records what BLS already has, so a deploy or restart never resends old
    data. `check` reports a release once its headline series shows a newer period
    (never on value changes alone, since revisions happen) and its other series have
    caught up, or `grace_seconds` have passed since the headline moved.
    """

    def __init__(self, releases: Sequence[Release], grace_seconds: float = 30.0):
        self.releases = list(releases)
        self.grace_seconds = grace_seconds
        self.known: dict[str, Period] = {}
        self._waiting_since: dict[str, float] = {}

    @property
    def waiting(self) -> bool:
        """True while a release is new but some of its series are still missing."""
        return bool(self._waiting_since)

    def baseline(self, data: Dataset) -> None:
        for release in self.releases:
            latest = latest_period(data.get(release.headline))
            if latest is not None:
                self.known[release.key] = latest

    def check(self, data: Dataset, now: float) -> list[tuple[Release, Period]]:
        """Releases to announce now (each at most once per period). `now` is a monotonic clock."""
        ready: list[tuple[Release, Period]] = []
        for release in self.releases:
            latest = latest_period(data.get(release.headline))
            if latest is None:
                continue
            known = self.known.get(release.key)
            if known is None:
                # Headline was missing at startup: treat its first sighting as the baseline.
                self.known[release.key] = latest
                log.info("%s: baseline %s", release.key, latest)
                continue
            if latest <= known:
                continue

            lagging = [s for s in release.series_ids if (p := latest_period(data.get(s))) is None or p < latest]
            if lagging:
                since = self._waiting_since.setdefault(release.key, now)
                if now - since < self.grace_seconds:
                    log.info("%s: %s is new; waiting for %s", release.key, latest, ", ".join(lagging))
                    continue
                log.warning("%s: sending %s without %s", release.key, latest, ", ".join(lagging))

            self._waiting_since.pop(release.key, None)
            self.known[release.key] = latest
            ready.append((release, latest))
        return ready
