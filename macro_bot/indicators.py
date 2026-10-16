"""Building blocks for indicator definitions (used by config.py) and message rendering."""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .calc import format_number, pct_change
from .periods import Period

SeriesData = Mapping[Period, Decimal]
Dataset = Mapping[str, SeriesData]  # series ID -> observations


@dataclass(frozen=True)
class Field:
    """One number on a message line, computed from a single BLS series."""

    series: str
    kind: Literal["pct", "change", "level"]
    tag: str = ""  # shown after the current value, e.g. "m/m"
    lag: int | Literal["year"] = 1  # periods back for pct/change; "year" = same period a year earlier
    annualize: bool = False  # compound a one-period pct change to an annual rate
    signed: bool = False  # show "+" on positive values
    decimals: int = 1
    scale: Decimal = Decimal(1)  # multiply the value before formatting (e.g. thousands -> millions)
    suffix: str = ""

    def value(self, data: Dataset, period: Period) -> Decimal | None:
        obs = data.get(self.series, {})
        current = obs.get(period)
        if current is None:
            return None
        if self.kind == "level":
            return current * self.scale
        lag = period.per_year if self.lag == "year" else self.lag
        base = obs.get(period.shift(-lag))
        if base is None:
            return None
        if self.kind == "change":
            return (current - base) * self.scale
        return pct_change(current, base, period.per_year if self.annualize else None)

    def render(self, data: Dataset, period: Period, with_tag: bool = True) -> str:
        text = format_number(self.value(data, period), self.decimals, self.signed, self.suffix)
        return f"{text} {self.tag}" if with_tag and self.tag else text


@dataclass(frozen=True)
class Line:
    """A labelled message line: "Core: +0.3% m/m | 2.6% y/y  (prev +0.3% | 2.4%)"."""

    label: str
    fields: tuple[Field, ...]
    prev: int = 1  # how many earlier periods to show in "(prev ...)"; 0 hides it

    def render(self, data: Dataset, period: Period) -> str:
        current = " | ".join(f.render(data, period) for f in self.fields)
        text = f"{html.escape(self.label)}: {current}"
        if self.prev:
            earlier = [
                " | ".join(f.render(data, period.shift(-k), with_tag=False) for f in self.fields)
                for k in range(1, self.prev + 1)
            ]
            text += f"  (prev {(', ' if len(self.fields) == 1 else '; ').join(earlier)})"
        return text


@dataclass(frozen=True)
class Release:
    """A BLS news release: its series are grouped into one message.

    The message is sent once the headline series shows a period newer than the one
    held in memory.
    """

    key: str
    title: str
    headline: str
    lines: tuple[Line, ...]

    @property
    def series_ids(self) -> list[str]:
        return _unique([self.headline, *(f.series for line in self.lines for f in line.fields)])

    def render(self, data: Dataset, period: Period) -> str:
        """The Telegram (HTML parse mode) message for this release at `period`."""
        title = f"<b>{html.escape(self.title)} — {period.label()}</b>"
        return "\n".join([title, *(line.render(data, period) for line in self.lines)])


# --- Helpers that keep config.py short and readable ---------------------------------


def line(label: str, *fields: Field, prev: int = 1) -> Line:
    return Line(label, fields, prev)


def mom(series: str) -> Field:
    """Month-over-month percent change from index levels."""
    return Field(series, "pct", tag="m/m", signed=True, suffix="%")


def qoq(series: str) -> Field:
    """Quarter-over-quarter percent change (not annualized)."""
    return Field(series, "pct", tag="q/q", signed=True, suffix="%")


def qoq_annualized(series: str) -> Field:
    """Quarter-over-quarter percent change at a compound annual rate."""
    return Field(series, "pct", tag="q/q ann.", signed=True, annualize=True, suffix="%")


def yoy(series: str) -> Field:
    """Percent change from the same period a year earlier."""
    return Field(series, "pct", tag="y/y", lag="year", suffix="%")


def change(series: str, decimals: int = 0, scale: str = "1", suffix: str = "") -> Field:
    """Signed difference from the previous period, e.g. payrolls "+29K"."""
    return Field(series, "change", signed=True, decimals=decimals, scale=Decimal(scale), suffix=suffix)


def level(series: str, decimals: int = 1, scale: str = "1", suffix: str = "") -> Field:
    """The value itself, e.g. the unemployment rate "4.2%"."""
    return Field(series, "level", decimals=decimals, scale=Decimal(scale), suffix=suffix)


def all_series_ids(releases: Iterable[Release]) -> list[str]:
    return _unique([s for r in releases for s in r.series_ids])


def validate_releases(releases: Iterable[Release]) -> None:
    """Catch config mistakes at startup instead of at release time."""
    keys: set[str] = set()
    for r in releases:
        if r.key in keys:
            raise ValueError(f"Duplicate release key in config: {r.key!r}")
        keys.add(r.key)
        if not r.lines:
            raise ValueError(f"Release {r.key!r} has no lines")
        for sid in r.series_ids:
            if not sid or sid != sid.strip().upper():
                raise ValueError(f"Release {r.key!r}: bad series ID {sid!r} (use upper case, no spaces)")


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))
