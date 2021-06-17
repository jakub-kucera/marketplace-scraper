from pydantic import BaseModel, validator


class Product(BaseModel):
    name: str
    description: str
    price: str  # todo change to Optional[int]
    link: str

    # @validator('price')
    # def convert_price(cls, value):
    #     pass
