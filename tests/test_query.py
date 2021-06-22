import pytest
from pydantic import ValidationError

from src.query import Query


@pytest.mark.parametrize(
    "text, low, high",
    (
        ("text", 5, 10),
        ("text", 0, 0),
        ("text", 100, 100),
        ("text", 10, 100),
        ("4764563465", 10, 20),
        ("text32452345", 10, 20),
        ("text 123 foo 3", 10, 20)
    ),
)
def test_query_create_valid(text: str, low: int, high: int):
    query = Query(text=text, price_range=(low, high))
    assert query.price_range == (low, high)
    assert query.text == text


@pytest.mark.parametrize(
    "text, low, high",
    (
        ("text", -5, 10),
        ("text", 30, 20),
        ("text", -10, -20),
        ("text", 10, -20),
        ("", 10, 20),
        ("a;lskdfjaslk", 10, 20),
        ("sdfsda\tljaslk", 10, 20),
        ("sdfsdalja*slk", 10, 20),
        ("\0", 10, 20)
    ),
)
def test_query_create_invalid(text: str, low: int, high: int) -> None:
    with pytest.raises(ValidationError):
        Query(text=text, price_range=(low, high))
