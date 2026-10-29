import pytest

from marketplace.scraping.bazos.bazos_scraper import BazosScraper


def test_extract_date_parses_day_month_year():
    result = BazosScraper.extract_date("[24.05.2026]")
    assert result.day == 24
    assert result.month == 5
    assert result.year == 2026


def test_extract_date_returns_timezone_aware():
    result = BazosScraper.extract_date("[01.01.2026]")
    assert result.tzinfo is not None


def test_extract_date_handles_top_prefix():
    result = BazosScraper.extract_date("TOP [24.05.2026]")
    assert result.day == 24
    assert result.month == 5
    assert result.year == 2026


def test_extract_date_handles_surrounding_whitespace():
    result = BazosScraper.extract_date("  [15.03.2025]  ")
    assert result.day == 15
    assert result.month == 3
    assert result.year == 2025


@pytest.mark.parametrize("date_raw,expected_day,expected_month,expected_year", [
    ("[01.01.2024]", 1, 1, 2024),
    ("[29.02.2024]", 29, 2, 2024),  # leap year
    ("[31.12.2025]", 31, 12, 2025),
])
def test_extract_date_parametrized(date_raw, expected_day, expected_month, expected_year):
    result = BazosScraper.extract_date(date_raw)
    assert result.day == expected_day
    assert result.month == expected_month
    assert result.year == expected_year
