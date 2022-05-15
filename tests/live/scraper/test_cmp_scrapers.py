import pytest

from src.notifiers.bazos.bazos_scraper_bs4_url import BazosBazosScraperBS4Url
from src.notifiers.bazos.bazos_scraper_click import BazosBazosScraperClick
from src.notifiers.bazos.bazos_scraper_sel_url import BazosBazosScraperSelUrl
from src.notifiers.bazos.categories import *
from src.notifiers.bazos.bazosscraper import BazosScraper
from src.query import Query
from src.sendables.product import Product

MAX_PRODUCTS_PER_QUERY = 50


def compare_products(products: list[Product]):
    return all(p.compare_custom(products[0]) for p in products)
    # return all(p.url == products[0].url for p in products)
    # return all(p == products[0] for p in products)


def check_if_all_None(products: list[Product]):
    return all(p is None for p in products)


def compare_scrapers_output(scrapers: list[BazosScraper], query: Query):
    scrapers_iterators = [scraper.run_query(query) for scraper in scrapers]
    for i in range(MAX_PRODUCTS_PER_QUERY):
        print("==========================================================")
        same_products: list[Product] = []
        for scraper in scrapers_iterators:
            product = next(scraper, None)
            same_products.append(product)
        print(f"{same_products=}")

        if check_if_all_None(same_products):
            print("No new products")
            return True

        if compare_products(same_products):
            print("All products are the same")
        else:
            print("PRODUCTS ARE DIFFERENT")
            return False
    return True


@pytest.mark.parametrize("query", [
    Query(text='apple watch 6', price_range=(2000, 7000), skip_round=False, location=('11000', '20')),
    Query(text='', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20')),
    Query(text='thinkpad', price_range=(1000, 0), skip_round=True, location=('11000', '20')),
    Query(text='lednicka', price_range=(0, 0), skip_round=True, category=fridge_bazos),
])
def test_cmp_scrapers(query: Query):
    scrapers = [BazosBazosScraperClick(), BazosBazosScraperBS4Url()]
    assert compare_scrapers_output(scrapers, query)


# if __name__ == "__main__":
#     # query = Query(text='Audeze', price_range=(0, 0), skip_round=False, category=headphones_bazos)
#     # query = Query(text='apple watch 6', price_range=(2000, 7000), skip_round=False, location=('11000', '20'))
#     # query = Query(text='', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20'))
#     # query = Query(text='thinkpad', price_range=(1000, 0), skip_round=True, location=('11000', '20')),
#     scrapers = [BazosScraperSelUrl(), BazosScraperClick()]
#     queries = [
#         Query(text='apple watch 6', price_range=(2000, 7000), skip_round=False, location=('11000', '20')),
#         Query(text='', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20')),
#         Query(text='thinkpad', price_range=(1000, 0), skip_round=True, location=('11000', '20')),
#     ]
#     for query in queries:
#         compare_scrapers_output(scrapers, query)

#
# Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='21 000 Kč', url='https://pc.bazos.cz/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6, 160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný. Model A2289, MXK32CZ/A MacBook Pro 13" 2020 Intel i5 Quad Core 1,4 GHz 256 GB SSD 8 GB RAM Displej 13,3" Retina 2560x1600 Touch Bar Touch ID Baterie 201 cyklů V super stavu, ž ...'),
# Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='21 000 Kč', url='/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný.\r\nModel A2289, MXK32CZ/A\r\n\r\nMacBook Pro 13" 2020\r\nIntel i5 Quad Core 1,4 GHz\r\n256 GB SSD\r\n8 GB RAM\r\nDisplej 13,3" Retina 2560x1600\r\nTouch Bar\r\nTouch ID\r\nBaterie 201 cyklů\r\n\r\nV super stavu, ž ...')]
