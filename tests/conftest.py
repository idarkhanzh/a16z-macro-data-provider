import json
from decimal import Decimal
from pathlib import Path

import pytest

from macro_bot.bls import parse_series
from macro_bot.periods import Period

# A real BLS API v2 response captured on 2026-10-16 for every series in config.py
# (observations from January 2024 on).
FIXTURE = Path(__file__).parent / "fixtures" / "bls_2026_10_16.json"


@pytest.fixture(scope="session")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def data(payload) -> dict[str, dict[Period, Decimal]]:
    return parse_series(payload)


def M(year: int, month: int) -> Period:
    return Period(year, month, "M")


def Q(year: int, quarter: int) -> Period:
    return Period(year, quarter, "Q")
