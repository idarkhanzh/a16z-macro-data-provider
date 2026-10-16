"""Calculations checked against figures BLS published in its news releases."""

from decimal import Decimal

import pytest

from conftest import M, Q
from macro_bot.calc import format_number, pct_change, round_half_up
from macro_bot.indicators import change, level, mom, qoq, qoq_annualized, yoy


def rounded(field, data, period) -> float:
    return float(round_half_up(field.value(data, period)))


# --- Pure helpers -------------------------------------------------------------------


def test_pct_change_is_exact():
    assert pct_change(Decimal("336.298"), Decimal("334.131")) == (Decimal("336.298") / Decimal("334.131") - 1) * 100


def test_pct_change_zero_base():
    assert pct_change(Decimal(1), Decimal(0)) is None


def test_annualized_change_compounds():
    # 1% a quarter compounds to 4.06% a year.
    assert round_half_up(pct_change(Decimal("101"), Decimal("100"), annualize=4), 2) == Decimal("4.06")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.25", "0.3"), ("-0.25", "-0.3"), ("0.249", "0.2"), ("-0.04", "0.0"), ("1.05", "1.1")],
)
def test_round_half_up(value, expected):
    result = round_half_up(Decimal(value))
    assert str(result) == expected


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ("0.31", {"signed": True, "suffix": "%"}, "+0.3%"),
        ("-0.44", {"signed": True, "suffix": "%"}, "-0.4%"),
        ("-0.04", {"signed": True, "suffix": "%"}, "0.0%"),  # never "-0.0%" or "+0.0%"
        ("2.94", {"suffix": "%"}, "2.9%"),
        ("1234", {"decimals": 0, "signed": True, "suffix": "K"}, "+1,234K"),
        (None, {"suffix": "%"}, "n/a"),
    ],
)
def test_format_number(value, kwargs, expected):
    assert format_number(None if value is None else Decimal(value), **kwargs) == expected


# --- CPI, September 2026 (USDL-26-1574, Oct 14 2026) --------------------------------


def test_cpi_headline_and_core(data):
    sep, aug = M(2026, 9), M(2026, 8)
    assert rounded(mom("CUSR0000SA0"), data, sep) == 0.6
    assert rounded(yoy("CUUR0000SA0"), data, sep) == 3.7
    assert rounded(mom("CUSR0000SA0"), data, aug) == 0.4
    assert rounded(yoy("CUUR0000SA0"), data, aug) == 3.4
    assert rounded(mom("CUSR0000SA0L1E"), data, sep) == 0.3
    assert rounded(yoy("CUUR0000SA0L1E"), data, sep) == 2.6
    assert rounded(mom("CUSR0000SA0L1E"), data, aug) == 0.3
    assert rounded(yoy("CUUR0000SA0L1E"), data, aug) == 2.4


def test_cpi_table_a_monthly_history(data):
    # Table A, seasonally adjusted changes Mar..Sep 2026.
    published_all = [0.9, 0.6, 0.5, -0.4, 0.1, 0.4, 0.6]
    published_core = [0.2, 0.4, 0.2, 0.0, 0.2, 0.3, 0.3]
    months = [M(2026, m) for m in range(3, 10)]
    assert [rounded(mom("CUSR0000SA0"), data, p) for p in months] == published_all
    assert [rounded(mom("CUSR0000SA0L1E"), data, p) for p in months] == published_core


def test_cpi_shutdown_gap_gives_none(data):
    # October 2025 was never collected (BLS value "-"), so Nov 2025 m/m cannot be computed.
    assert M(2025, 10) not in data["CUSR0000SA0"]
    assert mom("CUSR0000SA0").value(data, M(2025, 11)) is None


# --- Real Earnings, September 2026 (USDL-26-1575) -----------------------------------


def test_real_earnings(data):
    sep = M(2026, 9)
    assert rounded(mom("CES0500000013"), data, sep) == -0.5
    assert rounded(yoy("CES0500000013"), data, sep) == -0.7
    assert rounded(mom("CES0500000012"), data, sep) == -0.5
    assert rounded(yoy("CES0500000012"), data, sep) == -0.1


# --- Employment Situation, September 2026 (USDL-26-1549, Oct 2 2026) ---------------


def test_payrolls_and_revisions(data):
    payrolls = change("CES0000000001")
    assert payrolls.value(data, M(2026, 9)) == 29
    assert payrolls.value(data, M(2026, 8)) == 133  # revised from +162K
    assert payrolls.value(data, M(2026, 7)) == -10  # revised from +21K


def test_unemployment_and_wages(data):
    sep = M(2026, 9)
    assert rounded(level("LNS14000000"), data, sep) == 4.2
    assert rounded(mom("CES0500000003"), data, sep) == 0.1
    assert rounded(yoy("CES0500000003"), data, sep) == 3.0


# --- PPI, September 2026 (USDL 26-1576, Oct 15 2026), Table A, Sep 2025..Sep 2026 ---

PPI_MONTHS = [M(2025, m) for m in range(9, 13)] + [M(2026, m) for m in range(1, 10)]


@pytest.mark.parametrize(
    ("field", "published"),
    [
        (mom("WPSFD4"), [0.6, 0.1, 0.4, 0.4, 0.6, 0.5, 0.8, 1.1, 0.5, -0.1, 0.2, 0.5, 1.3]),
        (mom("WPSFD49116"), [0.2, 0.6, 0.3, 0.1, 0.5, 0.5, 0.2, 0.5, 0.8, 0.2, 0.5, 0.3, 0.5]),
        (yoy("WPUFD4"), [3.0, 2.8, 3.1, 3.1, 3.1, 3.4, 4.3, 5.7, 5.9, 5.6, 4.9, 5.6, 6.3]),
        (yoy("WPUFD49116"), [3.0, 3.5, 3.6, 3.4, 3.5, 3.5, 3.6, 4.4, 5.0, 5.0, 4.9, 4.8, 5.0]),
    ],
    ids=["final-demand-m/m", "core-m/m", "final-demand-y/y", "core-y/y"],
)
def test_ppi_table_a(data, field, published):
    assert [rounded(field, data, p) for p in PPI_MONTHS] == published


# --- Import/Export Price Indexes, August 2026 (USDL-26-1514, Sep 16 2026) ----------


def test_import_export_prices(data):
    aug, jul, jun = M(2026, 8), M(2026, 7), M(2026, 6)
    assert [rounded(mom("EIUIR"), data, p) for p in (aug, jul, jun)] == [0.7, -0.3, -0.3]
    assert rounded(yoy("EIUIR"), data, aug) == 7.0
    assert [rounded(mom("EIUIREXFUELS"), data, p) for p in (aug, jul)] == [0.8, 0.3]
    assert rounded(yoy("EIUIREXFUELS"), data, aug) == 5.5
    assert [rounded(mom("EIUIQ"), data, p) for p in (aug, jul)] == [0.6, -1.4]
    assert rounded(yoy("EIUIQ"), data, aug) == 8.6


# --- Quarterly: computed from index levels vs BLS's own published % change series ---


def test_employment_cost_index(data):
    # CIS1010000000000Q / CIU1010000000000A and CIS1020000000000Q / CIU1020000000000A.
    q2, q1 = Q(2026, 2), Q(2026, 1)
    assert [rounded(qoq("CIS1010000000000I"), data, p) for p in (q2, q1)] == [0.9, 0.9]
    assert [rounded(yoy("CIU1010000000000I"), data, p) for p in (q2, q1)] == [3.4, 3.4]
    assert [rounded(qoq("CIS1020000000000I"), data, p) for p in (q2, q1)] == [0.9, 0.8]
    assert [rounded(yoy("CIU1020000000000I"), data, p) for p in (q2, q1)] == [3.2, 3.4]


def test_productivity_and_costs(data):
    # PRS85006092 / PRS85006091 (productivity) and PRS85006112 / PRS85006111 (unit labor costs).
    q2, q1 = Q(2026, 2), Q(2026, 1)
    assert [rounded(qoq_annualized("PRS85006093"), data, p) for p in (q2, q1)] == [1.4, 0.8]
    assert [rounded(yoy("PRS85006093"), data, p) for p in (q2, q1)] == [2.2, 2.9]
    assert [rounded(qoq_annualized("PRS85006113"), data, p) for p in (q2, q1)] == [1.2, 1.3]
    assert [rounded(yoy("PRS85006113"), data, p) for p in (q2, q1)] == [1.4, 0.4]
