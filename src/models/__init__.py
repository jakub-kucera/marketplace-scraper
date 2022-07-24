from sqlalchemy import orm
from sqlalchemy.ext.declarative import declarative_base
import sqlalchemy as sa

DATABASE_URL = 'sqlite:///scraper.db'

base = declarative_base()
engine = sa.create_engine(DATABASE_URL)
base.metadata.bind = engine
session = orm.scoped_session(orm.sessionmaker(autocommit=False, autoflush=False))(bind=engine)


from .discord_sender_db import DiscordSenderDB  # noqa
from .product import ProductDB  # noqa
from .query import QueryDB  # noqa
