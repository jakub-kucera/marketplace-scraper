from datetime import datetime, timezone
from random import uniform

from django_extensions.db.models import TimeStampedModel
from django.db import models

from bazos.mixins import SendableMixin


class Query(TimeStampedModel):
    text = models.CharField(max_length=120, help_text="Querying text", blank=True)
    category = models.URLField(max_length=120, help_text="Category url", blank=True)
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

        constraints = [
            models.CheckConstraint(
                check=models.Q(price_lower__lte=models.F("price_upper")),
                name="price_lower_lte_price_upper",
            ),
        ]

    # def get_next_interval(self):
    #     return uniform(self.interval_lower, self.interval_upper)

    # def set_next_runtime(self, time_delta: timedelta):
    #     self.next_runtime = datetime.utcnow() + time_delta
    #     # db.session.commit()

    # def is_found_product(self, product: ProductDB):
    # #     idk what I wanted to do here
    #     return


class Ad(TimeStampedModel, SendableMixin):
    # bazos_id = Column(Integer, unique=False, nullable=False, index=True)
    bazos_id = models.IntegerField(db_index=True)
    # url = Column(String(1024), unique=False, nullable=False)
    url = models.URLField(max_length=1024) # TODO unique=True

    # name = Column(String(100), nullable=False)
    name = models.CharField(max_length=120)
    # price = Column(String(30),
    #                nullable=True)  # TODO make int and add column for alternatives (Nabídněte, V textu, Dohodou)
    price_raw = models.CharField(max_length=30)  # TODO make int and add column for alternatives (Nabídněte, V textu, Dohodou)
    # location = Column(String(128), nullable=False)
    location = models.CharField(max_length=128)
    # view_count = Column(Integer, nullable=True)
    view_count = models.IntegerField(help_text="View count at the time of discovery")
    # publish_date = Column(DateTime, nullable=False)  # , default=datetime.utcnow)
    publish_date = models.DateTimeField()
    # ignore_date = Column(Boolean, nullable=False, default=False)
    # TODO add topped count
    topped = models.BooleanField(default=False, help_text="Topped ad, publish date is not accurate")
    # description = Column(String(300), nullable=False)  # Real max lenght might be 254
    short_description = models.CharField(max_length=300)
    # full_description = Column(Text, nullable=True)
    full_description = models.TextField(null=True, blank=True)

    # # author  # phone_id and email_id not tied together, would cause problems if used in 1 model
    # publisher_email_id = Column(Integer, nullable=True)
    publisher_email_id = models.IntegerField()
    # publisher_phone_id = Column(Integer, nullable=True)
    publisher_phone_id = models.IntegerField()
    # publisher_name = Column(String(100), nullable=True)
    publisher_name = models.CharField(max_length=100)

    # do_send = Column(Boolean, nullable=False, default=True)  # not used

    # TODO m:n relationship with Query (+ senders)
    # query_id = Column(Integer, ForeignKey('query.id'), nullable=False)
    query = models.ForeignKey(Query, on_delete=models.PROTECT, related_name='ads')

    def __str__(self):
        return f"{self.name} | {self.price_raw} | {self.location}"

    class Meta:
        verbose_name = "Ad"
        verbose_name_plural = "Ads"
        constraints = []

    @property
    def message(self):
        return self.name + '\n' + \
            self.price + '\n' + \
            self.location + '\n' + \
            self.description

    @property
    def link(self):
        return self.url



