from typing import Dict, Set

from src.sendables.product_old import ProductOLD
from src.query_old import QueryOLD


class ProductDatabase:
    def __init__(self):
        self.database: Dict[str, Set[str]] = dict()  # Query : {Products}

    def add_if_not_present(self, product: ProductOLD, query: QueryOLD) -> bool:
        if query.text not in self.database:
            self.database[query.text] = {product.url}
            return True

        according_query = self.database[query.text]

        if product.url not in according_query:
            according_query.add(product.url)
            return True

        return False
