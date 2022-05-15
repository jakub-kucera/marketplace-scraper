from datetime import datetime

from src.sendables.product import Product
from src.sendables.product_database import ProductDatabase
from src.query import Query


def test_product_database_add_if_not_present():
    database = ProductDatabase()

    product1 = Product(name="foobar name", price="1000 Kč", url="https://pc.bazos.cz/random_string-12345",
                       location="Prague 6 16000", date=datetime(day=11, month=11, year=2021), ignore_date=True,
                       description="this is a nice product...")
    query1 = Query(text="this is a query text", price_range=(0, 0), skip_round=False)
    assert database.add_if_not_present(product1, query1)
    assert not database.add_if_not_present(product1, query1)

    query2 = Query(text="idk some other query", price_range=(10, 20), skip_round=True)
    assert database.add_if_not_present(product1, query2)
    assert not database.add_if_not_present(product1, query2)

    product2 = Product(name="different name", price="1 Billion Dollars",
                       url="https://elektro.bazos.cz/some-url-lskdjf;asdlkjf;asdlkfj", location="Prague 10, 11000",
                       date=datetime(day=1, month=1, year=1), ignore_date=False, description="worst product ever")
    assert database.add_if_not_present(product2, query1)
    assert not database.add_if_not_present(product2, query1)
    assert not database.add_if_not_present(product1, query1)
    assert not database.add_if_not_present(product2, query1)
