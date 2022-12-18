from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship

# from src.db.db import Base
from src.models import base


class DiscordSenderDB(base):
    __tablename__ = 'discord_sender'

    id = Column(Integer, primary_key=True)
    channel_name = Column(String(20), nullable=False)
    url = Column(String(200), unique=False, nullable=False)  # maybe unique not necessary
    notify = Column(Boolean, nullable=False, default=False)
    for_logging = Column(Boolean, nullable=False, default=False, index=True)
    # N:1 relation with queryDB
    queries = relationship('QueryDB', backref='discord_sender', lazy=True)

    def __repr__(self):
        return f"<DiscordSender(id='{self.id}', channel_name='{self.channel_name}', notify='{self.notify}')>"
