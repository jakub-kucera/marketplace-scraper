from typing import Tuple

from pydantic import BaseModel, validator


class Query(BaseModel):
    text: str
    price_range: Tuple[int, int]
    # location: str
    # category: str

    @validator('price_range')
    def price_range_format(cls, value: Tuple[int, int]):
        lower, higher = value

        assert lower <= higher
        assert lower >= 0
        assert higher >= 0

        return value

    @validator('text')
    def text_format(cls, value: str):
        assert len(value) > 0
        assert value.replace(" ", "").isalnum()
        return value
