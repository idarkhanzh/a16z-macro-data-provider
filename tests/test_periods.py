import pytest

from macro_bot.bls import latest_period, parse_series
from macro_bot.periods import Period


@pytest.mark.parametrize(
    ("year", "code", "expected"),
    [
        ("2026", "M09", Period(2026, 9, "M")),
        ("2026", "Q02", Period(2026, 2, "Q")),
        ("2026", "S01", Period(2026, 1, "S")),
        ("2026", "M13", None),  # annual average
        ("2026", "Q05", None),  # annual average
        ("2026", "A01", None),  # annual data
        ("2026", "M00", None),
    ],
)
def test_parse(year, code, expected):
    assert Period.parse(year, code) == expected


def test_ordering_across_year_boundary():
    assert Period(2027, 1) > Period(2026, 12)
    assert Period(2026, 10) > Period(2026, 9)
    assert Period(2026, 9) == Period(2026, 9)
    assert max([Period(2025, 12), Period(2026, 2), Period(2026, 1)]) == Period(2026, 2)
    assert Period(2026, 1, "Q") > Period(2025, 4, "Q")


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        (Period(2026, 1), -1, Period(2025, 12)),
        (Period(2026, 9), -12, Period(2025, 9)),
        (Period(2025, 12), 1, Period(2026, 1)),
        (Period(2026, 1, "Q"), -1, Period(2025, 4, "Q")),
        (Period(2026, 2, "Q"), -4, Period(2025, 2, "Q")),
    ],
)
def test_shift(start, n, expected):
    assert start.shift(n) == expected


def test_labels():
    assert Period(2026, 9).label() == "September 2026"
    assert Period(2026, 2, "Q").label() == "Q2 2026"
    assert str(Period(2026, 9)) == "2026 M09"


def test_latest_period_ignores_placeholders_and_annual_averages():
    payload = {
        "Results": {
            "series": [
                {
                    "seriesID": "X",
                    "data": [
                        {"year": "2026", "period": "M13", "value": "300.0"},
                        {"year": "2026", "period": "M10", "value": "-"},
                        {"year": "2026", "period": "M09", "value": "336.298"},
                        {"year": "2025", "period": "M12", "value": "325.0"},
                    ],
                }
            ]
        }
    }
    data = parse_series(payload)
    assert latest_period(data["X"]) == Period(2026, 9)
    assert latest_period({}) is None
