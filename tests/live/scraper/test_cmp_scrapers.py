import pytest

from src.notifiers.bazos.bazos_scraper_bs4_url import BazosBazosScraperBS4Url
from src.notifiers.bazos.bazos_scraper_click import BazosBazosScraperClick
from src.notifiers.bazos.bazos_scraper_sel_url import BazosBazosScraperSelUrl
from src.notifiers.bazos.categories import *
from src.notifiers.bazos.bazos_scraper import BazosScraper
from src.query_old import QueryOLD
from src.sendables.product_old import ProductOLD

MAX_PRODUCTS_PER_QUERY = 50


def compare_products(products: list[ProductOLD]):
    return all(p.compare_custom(products[0]) for p in products)
    # return all(p.url == products[0].url for p in products)
    # return all(p == products[0] for p in products)


def check_if_all_None(products: list[ProductOLD]):
    return all(p is None for p in products)


def compare_scrapers_output(scrapers: list[BazosScraper], query: QueryOLD):
    scrapers_iterators = [scraper.run_query(query) for scraper in scrapers]
    for i in range(MAX_PRODUCTS_PER_QUERY):
        print("==========================================================")
        same_products: list[ProductOLD] = []
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
    QueryOLD(text='apple watch 6', price_range=(2000, 7000), skip_round=False, location=('11000', '20')),
    QueryOLD(text='', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20')),
    QueryOLD(text='thinkpad', price_range=(1000, 0), skip_round=True, location=('11000', '20')),
    QueryOLD(text='lednicka', price_range=(0, 0), skip_round=True, category=fridge_bazos),
])
def test_cmp_scrapers(query: QueryOLD):
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
