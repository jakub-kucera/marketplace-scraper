from datetime import datetime, timezone
from random import uniform

from django.db import models
from django_extensions.db.models import TimeStampedModel


class Query(TimeStampedModel):
    text = models.CharField(max_length=120, help_text="Querying text", blank=True)
    category = models.CharField(max_length=120, help_text="Category url", blank=True)
    # price_lower = Column(Integer, nullable=False, default=0)
    price_lower = models.IntegerField(default=0)
    # price_upper = Column(Integer, nullable=False, default=0)
    price_upper = models.IntegerField(default=0)
    # location_center = Column(String, nullable=False, default="")  # Integer might work as well
    location_center = models.CharField(max_length=10, help_text="Location center PSC")
    # location_radius = Column(Integer, nullable=False, default=25)
    location_radius = models.IntegerField(default=25)

    # next_runtime = Column(DateTime, nullable=False, default=datetime.utcnow)
    # next_runtime = models.DateTimeField(default=datetime.now(timezone.utc))
    # TODO remove interval here, since this should be the same for all queries
    # interval_lower = Column(Integer, nullable=False, default=10)  # minutes  # TODO replace by sqlalchemy.Interval
    # interval_lower = models.IntegerField(default=10, help_text="Interval lower bound in minutes")
    # interval_upper = Column(Integer, nullable=False, default=60)  # minutes  # TODO replace by sqlalchemy.Interval
    # interval_upper = models.IntegerField(default=10, help_text="Interval lower bound in minutes")

    # enabled = Column(Boolean, nullable=True, default=True)
    enabled = models.BooleanField(default=True)
    # new_query = Column(Boolean, nullable=False, default=True)
    new_query = models.BooleanField(default=True, help_text="Is this a new query? Needed for first run, to only load limited count.")
    # ignore_first_run = Column(Boolean, nullable=False, default=True)
    ignore_first_run = models.BooleanField(default=True, help_text="Do not send Ads from first run.")
    # load_full_description = Column(Boolean, nullable=True, default=True)  # TODO make nullable=False
    load_full_description = models.BooleanField(default=False)
    # last_top_count = Column(Integer, nullable=False, default=0)

    # discord_sender_id = Column(Integer, ForeignKey('discord_sender.id'), nullable=False)
    sender = models.ForeignKey('senders.Discord', on_delete=models.SET_NULL, null=True, related_name='queries')
    # logger_id
    # TODO Ads
    # products = relationship('ProductDB', backref='query', lazy=True)

    def __str__(self):
        return f"{self.text} | {self.price_lower}-{self.price_upper} | {self.category}"

    class Meta:
        verbose_name = "Query"
        verbose_name_plural = "Queries"

    # def get_next_interval(self):
    #     return uniform(self.interval_lower, self.interval_upper)

    # def set_next_runtime(self, time_delta: timedelta):
    #     self.next_runtime = datetime.utcnow() + time_delta
    #     # db.session.commit()

    # def is_found_product(self, product: ProductDB):
    # #     idk what I wanted to do here
    #     return
