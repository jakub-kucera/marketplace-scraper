import pytest
from pydantic import ValidationError

from src.query_old import QueryOLD


@pytest.mark.parametrize(
    "text, low, high, skip_round",
    (
        ("text", 5, 10, False),
        ("text", 5, 10, True),
        ("text", 0, 0, False),
        ("text", 100, 100, False),
        ("text", 10, 100, False),
        ("4764563465", 10, 20, False),
        ("text32452345", 10, 20, False),
        ("text 123 foo 3", 10, 20, False),
    ),
)
def test_query_create_valid(text: str, low: int, high: int, skip_round: bool):
    query = QueryOLD(text=text, price_range=(low, high), skip_round=skip_round)
    assert query.price_range == (low, high)
    assert query.text == text
    assert query.skip_round is skip_round


@pytest.mark.parametrize(
    "text, low, high, skip_round",
    (
        ("text", -5, 10, False),
        ("text", 30, 20, False),
        ("text", 30, 20, True),
        ("text", -10, -20, False),
        ("text", 10, -20, False),
        ("", 10, 20, False),
        ("a;lskdfjaslk", 10, 20, False),
        ("sdfsda\tljaslk", 10, 20, False),
        ("sdfsdalja*slk", 10, 20, False),
        ("\0", 10, 20, False),
    ),
)
def test_query_create_invalid(text: str, low: int, high: int, skip_round: bool) -> None:
    with pytest.raises(ValidationError):
        QueryOLD(text=text, price_range=(low, high), skip_round=skip_round)


@pytest.mark.parametrize(
    "text, low, high, skip_round",
    (
        ("text", 5, 10, False),
        ("text", 5, 10, True),
    ),
)
def test_query_skip(text: str, low: int, high: int, skip_round: bool):
    query = QueryOLD(text=text, price_range=(low, high), skip_round=skip_round)
    assert query.skip_round is skip_round
    assert query.can_skip_first_round() is skip_round
    assert query.skip_round is False
    assert query.can_skip_first_round() is False
    assert query.skip_round is False
