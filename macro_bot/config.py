"""Indicators and schedule. Edit this file to add, remove or reformat indicators.

Each Release is one BLS news release and becomes one Telegram message. The message
is sent when the release's `headline` series has a period newer than the one seen
before. Field helpers (all percent changes are computed from index levels and
rounded half-up to one decimal, like the official tables):

    mom(id)             month-over-month % change        "+0.3% m/m"
    qoq(id)             quarter-over-quarter % change    "+0.9% q/q"
    qoq_annualized(id)  q/q % change at an annual rate   "+1.4% q/q ann."
    yoy(id)             change vs. same period last year "2.9% y/y"
    change(id, ...)     difference vs. previous period   "+29K"
    level(id, ...)      the value itself                 "4.2%"

line(label, *fields, prev=N) shows N earlier periods in "(prev ...)"; prev=0 hides it.

Every series ID below was checked against the live BLS API and its official series
title on data.bls.gov in October 2026.
"""

from datetime import timedelta

from .indicators import Release, change, level, line, mom, qoq, qoq_annualized, yoy
from .schedule import PollSchedule

RELEASES: tuple[Release, ...] = (
    Release(
        key="cpi",
        title="US CPI",
        headline="CUSR0000SA0",
        lines=(
            # BLS headline convention: m/m from the seasonally adjusted index, y/y from the unadjusted one.
            line("Headline", mom("CUSR0000SA0"), yoy("CUUR0000SA0")),
            line("Core", mom("CUSR0000SA0L1E"), yoy("CUUR0000SA0L1E")),
        ),
    ),
    Release(
        key="real_earnings",
        title="US Real Earnings",
        headline="CES0500000013",
        lines=(
            line("Real avg hourly earnings", mom("CES0500000013"), yoy("CES0500000013")),
            line("Real avg weekly earnings", mom("CES0500000012"), yoy("CES0500000012")),
        ),
    ),
    Release(
        key="jobs",
        title="US Jobs Report",
        headline="CES0000000001",
        lines=(
            line("Nonfarm payrolls", change("CES0000000001", suffix="K"), prev=2),
            line("Unemployment rate", level("LNS14000000", suffix="%")),
            line("Avg hourly earnings", mom("CES0500000003"), yoy("CES0500000003")),
        ),
    ),
    Release(
        key="ppi",
        title="US PPI",
        headline="WPSFD4",
        lines=(
            line("Final demand", mom("WPSFD4"), yoy("WPUFD4")),
            line("Core (ex food, energy, trade)", mom("WPSFD49116"), yoy("WPUFD49116")),
            line("Ex food & energy", mom("WPSFD49104"), yoy("WPUFD49104")),
        ),
    ),
    Release(
        key="jolts",
        title="US JOLTS",
        headline="JTS000000000000000JOL",
        lines=(
            line("Job openings", level("JTS000000000000000JOL", 2, scale="0.001", suffix="M")),
            line("Hires", level("JTS000000000000000HIL", 2, scale="0.001", suffix="M")),
            line("Quits", level("JTS000000000000000QUL", 2, scale="0.001", suffix="M")),
            line("Layoffs", level("JTS000000000000000LDL", 2, scale="0.001", suffix="M")),
        ),
    ),
    Release(
        key="eci",
        title="US Employment Cost Index",
        headline="CIS1010000000000I",
        lines=(
            # Civilian workers. q/q from the seasonally adjusted index, y/y from the unadjusted one.
            line("Compensation", qoq("CIS1010000000000I"), yoy("CIU1010000000000I")),
            line("Wages & salaries", qoq("CIS1020000000000I"), yoy("CIU1020000000000I")),
        ),
    ),
    Release(
        key="import_export",
        title="US Import/Export Prices",
        headline="EIUIR",
        lines=(
            # These indexes are published not seasonally adjusted only.
            line("Import prices", mom("EIUIR"), yoy("EIUIR")),
            line("Imports ex fuel", mom("EIUIREXFUELS"), yoy("EIUIREXFUELS")),
            line("Export prices", mom("EIUIQ"), yoy("EIUIQ")),
        ),
    ),
    Release(
        key="productivity",
        title="US Productivity & Costs",
        headline="PRS85006093",
        lines=(
            # Nonfarm business sector indexes (2017=100).
            line("Productivity", qoq_annualized("PRS85006093"), yoy("PRS85006093")),
            line("Unit labor costs", qoq_annualized("PRS85006113"), yoy("PRS85006113")),
        ),
    ),
)

SCHEDULE = PollSchedule(
    release_times=("08:30", "10:00"),  # ET; fast polling around each
    lead=timedelta(seconds=15),
    fast_every=timedelta(seconds=2),
    fast_until=timedelta(minutes=2),
    slow_every=timedelta(seconds=15),
    slow_until=timedelta(minutes=15),
    catchup_from="07:00",
    catchup_to="18:00",
    catchup_every=timedelta(minutes=30),
)

# BLS API v2 allows 500 queries per day per key; the schedule above uses about 260.
DAILY_QUERY_LIMIT = 500

# If a release's headline series is new but some of its other series are not yet,
# keep polling every few seconds for up to this long, then send with "n/a" gaps.
MEMBER_GRACE_SECONDS = 30
