from decimal import Decimal

import pytest

from conftest import M, Q
from macro_bot import config
from macro_bot.indicators import Release, all_series_ids, line, mom, validate_releases

RELEASES = {r.key: r for r in config.RELEASES}


def test_cpi_message(data):
    assert RELEASES["cpi"].render(data, M(2026, 9)) == (
        "<b>US CPI — September 2026</b>\n"
        "Headline: +0.6% m/m | 3.7% y/y  (prev +0.4% | 3.4%)\n"
        "Core: +0.3% m/m | 2.6% y/y  (prev +0.3% | 2.4%)"
    )


def test_jobs_message_shows_two_prior_payroll_changes(data):
    assert RELEASES["jobs"].render(data, M(2026, 9)) == (
        "<b>US Jobs Report — September 2026</b>\n"
        "Nonfarm payrolls: +29K  (prev +133K, -10K)\n"
        "Unemployment rate: 4.2%  (prev 4.1%)\n"
        "Avg hourly earnings: +0.1% m/m | 3.0% y/y  (prev +0.3% | 3.1%)"
    )


def test_quarterly_title_and_html_escaping(data):
    text = RELEASES["eci"].render(data, Q(2026, 2))
    assert text.splitlines()[0] == "<b>US Employment Cost Index — Q2 2026</b>"
    assert "Wages &amp; salaries: +0.9% q/q | 3.2% y/y  (prev +0.8% | 3.4%)" in text


def test_productivity_annualized_tag(data):
    text = RELEASES["productivity"].render(data, Q(2026, 2))
    assert "Productivity: +1.4% q/q ann. | 2.2% y/y  (prev +0.8% | 2.9%)" in text


def test_jolts_levels_in_millions(data):
    text = RELEASES["jolts"].render(data, M(2026, 8))
    # Release text: openings 7.1 million, hires 5.2 million, quits 3.1 million, layoffs 1.6 million.
    assert "Job openings: 7.08M  (prev 7.34M)" in text
    assert "Hires: 5.19M" in text and "Quits: 3.07M" in text and "Layoffs: 1.64M" in text


def test_missing_base_period_shows_na(data):
    # October 2026 y/y needs October 2025, which BLS never collected.
    data = {k: dict(v) for k, v in data.items()}
    for sid, value in [("CUSR0000SA0", "337.0"), ("CUUR0000SA0", "337.5"), ("CUSR0000SA0L1E", "339.5"), ("CUUR0000SA0L1E", "339.9")]:
        data[sid][M(2026, 10)] = Decimal(value)
    text = RELEASES["cpi"].render(data, M(2026, 10))
    assert "Headline: +0.2% m/m | n/a y/y  (prev +0.6% | 3.7%)" in text


def test_config_is_valid_and_fits_one_request():
    validate_releases(config.RELEASES)
    assert len(all_series_ids(config.RELEASES)) <= 50


def test_validate_rejects_duplicate_keys():
    r = Release("x", "X", "CUSR0000SA0", (line("A", mom("CUSR0000SA0")),))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_releases([r, r])
