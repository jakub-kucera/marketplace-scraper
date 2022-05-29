from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey

# from src.db.db import Base
from src.models import base


class ProductDB(base):
    __tablename__ = 'product'

    id = Column(Integer, primary_key=True)
    bazos_id = Column(Integer, unique=False, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    price = Column(String(30), nullable=True)  # TODO make int and add column for alternatives (Nabídněte, V textu, Dohodou)
    url = Column(String(1024), unique=False, nullable=False)
    location = Column(String(128), nullable=False)
    publish_date = Column(DateTime, nullable=False)  # , default=datetime.utcnow)
    discover_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    ignore_date = Column(Boolean, nullable=False, default=False)
    description = Column(String(300), nullable=False)  # Real max lenght might be 254
    # full_description = Column(String(300), nullable=False)
    # author

    do_send = Column(Boolean, nullable=False, default=True)
    # m:n relationship with senders or Query
    query_id = Column(Integer, ForeignKey('query.id'), nullable=False)

    # m:n relation to Queryproduct

    @property
    def message(self):
        return self.name + '\n' + \
               self.price + '\n' + \
               self.location + '\n' + \
               self.description

    @property
    def link(self):
        return self.url

    def compare_custom(self, other) -> bool:
        """
        Compare two products. Description is not compare, because of different formatting.
        """
        return self.name == other.name and \
               self.price == other.price and \
               self.url == other.url and \
               self.location == other.location and \
               self.publish_date == other.publish_date and \
               self.ignore_date == other.ignore_date and \
               self.description == other.description
