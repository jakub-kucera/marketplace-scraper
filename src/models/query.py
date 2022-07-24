from datetime import datetime, timedelta
from random import uniform

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship

# from src.db.db import Base
from src.models import ProductDB, base


class QueryDB(base):
    __tablename__ = 'query'

    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=False, default="")  # TODO replace by TEXT or smth
    category = Column(String, nullable=False, default="")
    price_lower = Column(Integer, nullable=False, default=0)
    price_upper = Column(Integer, nullable=False, default=0)
    location_center = Column(String, nullable=False, default="")  # Integer might work as well
    location_radius = Column(Integer, nullable=False, default=25)

    next_runtime = Column(DateTime, nullable=False, default=datetime.utcnow)
    interval_lower = Column(Integer, nullable=False, default=10)  # minutes  # TODO replace by sqlalchemy.Interval
    interval_upper = Column(Integer, nullable=False, default=60)  # minutes  # TODO replace by sqlalchemy.Interval

    enabled = Column(Boolean, nullable=True, default=True)
    new_query = Column(Boolean, nullable=False, default=True)
    ignore_first_run = Column(Boolean, nullable=False, default=True)
    load_full_description = Column(Boolean, nullable=True, default=True)  # TODO make nullable=False
    # last_top_count = Column(Integer, nullable=False, default=0)

    discord_sender_id = Column(Integer, ForeignKey('discord_sender.id'), nullable=False)
    # logger_id
    products = relationship('ProductDB', backref='query', lazy=True)

    def __repr__(self):
        return f"<Query(id='{self.id}', text='{self.text}', price='{self.price_lower}-{self.price_upper}', category='{self.category}, next_runtime={self.next_runtime}')>"

    def get_next_interval(self):
        return uniform(self.interval_lower, self.interval_upper)

    def set_next_runtime(self, time_delta: timedelta):
        self.next_runtime = datetime.utcnow() + time_delta
        # db.session.commit()

    def is_found_product(self, product: ProductDB):
        return
