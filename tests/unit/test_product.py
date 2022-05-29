import pytest

from src.sendables.product_old import ProductOLD


@pytest.mark.parametrize(
    "name, description, price, url, location",
    (
        ("product", "this is a nice product...", "1000 Kč", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("foobar", "this is a nice product...", "1000 Kč", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("foobar", "this is a nice product...", "Neuvedeno", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("foobar", "this is a nice product...", "Zdarma", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("foobar", "this is a nice product...", "V textu", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("product", "", "1000 Kč", "https://pc.bazos.cz/", "Praha 6 16000"),
        ("product", "this is a nice product...", "1000 Kč", "https://aukro.cz/elektro", "Praha 6 16000"),
        ("product", "this is a nice product...", "1000 Kč", "https://www.facebookasdfasfd.com/marketplace", "Praha 6 16000"),
    ),
)
def test_product_create_valid(name: str, description: str, price: str, url: str, location: str):
    product = ProductOLD(name=name, description=description, price=price, url=url, location=location)
    assert product.name == name
    assert product.description == description
    assert product.price == price
    assert product.url == url


# @pytest.mark.parametrize(
#     "name, description, price, url",
#     (
#         ("product", "this is a nice product...", "1000 Kč", "https://pc.baasdfasdfzos.cz/"),
#         # ("foobar", "this is a nice product...", "1000 Kč", "https://pc.bazos.cz/"),
#     ),
# )
# def test_product_create_invalid(name: str, description: str, price: str, url: str):
#     with pytest.raises(ValidationError):
#         Product(name=name, description=description, price=price, url=url)

@pytest.mark.parametrize(
    "original, desirable",
    (
            ('1000', 1000),
            ('1000 Kč', 1000),
            ('  1000 Kč', 1000),
    ),
)
def test_product_price_converter_valid(original, desirable):
    assert ProductOLD.convert_price(original) == desirable


@pytest.mark.parametrize(
    "original",
    (
            "Neuvedeno",
            "Zdarma",
            "V textu",
            "d 1000 Kč",
            "1 Kč",
            "0",
    ),
)
def test_product_price_converter_invalid(original):
    assert ProductOLD.convert_price(original) is None
