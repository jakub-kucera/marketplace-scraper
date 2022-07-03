import pytest

from src.sendables.product_old import ProductOLD


 # TODO use on the new ProductDB class

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
