from random import randint
from typing import List
from urllib.parse import urljoin, urlparse

from django_extensions.db.models import TimeStampedModel
from django.db import models

from bazos.const import BAZOS_BASE_URL


class Section(models.Model):  # type: ignore[django-manager-missing]
    bazos_id = models.CharField(unique=True, max_length=2)
    name = models.CharField(max_length=20, unique=True)
    url = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name

    @property
    def full_url(self):
        parsed_url = urlparse(BAZOS_BASE_URL)
        updated_netloc = f"{self.url}.{parsed_url.netloc}"
        return parsed_url._replace(netloc=updated_netloc).geturl()


class Category(models.Model):  # type: ignore[django-manager-missing]
    bazos_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=50, unique=False)
    url = models.CharField(max_length=50, unique=False)
    section = models.ForeignKey(Section, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.name} | {self.section}"

    @property
    def full_url(self):
        # TODO check if `/` is needed at the end - looks like it is not
        return urljoin(self.section.full_url, self.url)


class Marketplace(models.TextChoices):
    BAZOS     = "bazos",     "Bazos"
    BAZOS_API = "bazos_api", "Bazos (API)"
    # VINTED  = "vinted",     "Vinted"  # Stage 8 — add once VintedScraper is registered


class Query(TimeStampedModel):
    text = models.CharField(max_length=120, help_text="Querying text", blank=True)

    section = models.ForeignKey(Section, on_delete=models.PROTECT, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, blank=True, null=True)

    price_lower = models.IntegerField(default=0)
    price_upper = models.IntegerField(default=0)

    location_center = models.CharField(max_length=10, blank=True, help_text="Location center PSC")
    location_radius = models.IntegerField(default=20)

    enabled = models.BooleanField(default=True)
    new_query = models.BooleanField(default=True, help_text="Is this a new query? Needed for first run, to only load limited count.")
    ignore_first_run = models.BooleanField(default=True, help_text="Do not send Ads from first run.")
    load_full_description = models.BooleanField(default=False)
    # last_top_count = Column(Integer, nullable=False, default=0)
    randomly_generated = models.BooleanField(default=False)
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices, default=Marketplace.BAZOS)

    filter_blocklist = models.JSONField(default=list, blank=True, help_text="Reject if name/description contains any of these phrases.")
    filter_required = models.JSONField(default=list, blank=True, help_text="Reject unless name/description contains at least one of these phrases.")
    filter_rule_names = models.JSONField(default=list, blank=True, help_text="Which filter rules to apply (empty = all default rules). Valid names: price_range, blocklist_keyword, required_keyword, publisher_blocklist, price_drop.")

    sender = models.ForeignKey('senders.Discord', on_delete=models.SET_NULL, null=True, related_name='queries')
    # logger_id
    # TODO Ads
    # products = relationship('ProductDB', backref='query', lazy=True)

    def __str__(self):
        return f"{self.text or self.category or self.section} | {self.price_lower}-{self.price_upper}"
        # return f"{self.text} | {self.category or self.section} | {self.price_lower}-{self.price_upper}"

    class Meta:
        verbose_name = "Query"
        verbose_name_plural = "Queries"

        constraints = [
            models.CheckConstraint(
                check=models.Q(price_lower__lte=models.F("price_upper")),
                name="price_lower_lte_price_upper",
            ),
            models.CheckConstraint(
                check=models.Q(section__isnull=True) | models.Q(category__isnull=True),
                name="not_section_or_not_category",
            ),
        ]

    @property
    def url(self):
        if self.section:
            return self.section.full_url
        elif self.category:
            return self.category.full_url
        return BAZOS_BASE_URL

    @staticmethod
    def generate_random_queries(count: int = 1) -> list["Query"]:
        queries: list[Query] = []
        for _ in range(count):
            # TODO log this
            # could be improved to sometimes pick section, or even no section
            category = Category.objects.order_by('?').first()
            # the query name could be better generated. (If no FK to category, then use name of random category/section)
            query_text = category.name
            queries.append(Query.objects.create(
                text=query_text,
                category=category,
                # price_lower=0,
                # price_upper=100,
                # TODO check if can be used?
                location_center=randint(10000, 99999),
                # location_center="12345",
                # location_radius=25,
                randomly_generated=True,
                new_query=True,  # TODO modify query_runner
            ))
        return queries

    # def is_found_product(self, product: ProductDB):
    # #     idk what I wanted to do here
    #     return


class QueryRun(models.Model):
    query = models.ForeignKey(Query, on_delete=models.CASCADE, related_name='runs')
    run_start = models.DateTimeField()
    run_end = models.DateTimeField(null=True, blank=True)
    new_ads_count = models.IntegerField(null=True)
    success = models.BooleanField(default=True)
    error = models.TextField(null=True, blank=True)


class AdStatus(models.TextChoices):
    PENDING       = "PENDING"       # scraped, awaiting filter
    APPROVED      = "APPROVED"      # passed filters, awaiting send
    REJECTED      = "REJECTED"      # dropped by a filter rule
    SUPPRESSED    = "SUPPRESSED"    # deliberately not sent (e.g. ignore_first_run)
    PRICE_CHANGED = "PRICE_CHANGED" # re-enters pipeline for price update notification
    SENT          = "SENT"          # successfully delivered
    FAILED        = "FAILED"        # send failed after retries


class Ad(TimeStampedModel):
    external_id = models.IntegerField(db_index=True)  # TODO unique=True (requires M:N to queries)
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices, default=Marketplace.BAZOS, db_index=True)
    url = models.URLField(max_length=1024)  # TODO unique=True

    # TODO add relation to Category model. (some init method where from URL take category, bazos_id)

    name = models.CharField(max_length=120)
    price_raw = models.CharField(max_length=30)  # TODO make int and add column for alternatives (Nabídněte, V textu, Dohodou)
    location = models.CharField(max_length=128)
    view_count = models.IntegerField(help_text="View count at the time of discovery")
    publish_date = models.DateTimeField()
    # TODO add topped count
    topped = models.BooleanField(default=False, help_text="Topped ad, publish date is not accurate")
    short_description = models.CharField(max_length=300)
    full_description = models.TextField(null=True, blank=True)

    publisher_name = models.CharField(max_length=100)
    email_publisher = models.ForeignKey('EmailPublisher', on_delete=models.PROTECT, null=True, related_name='ads')
    phone_publisher = models.ForeignKey('PhonePublisher', on_delete=models.PROTECT, null=True, related_name='ads')

    # do_send = Column(Boolean, nullable=False, default=True)  # not used

    # TODO m:n relationship with Query (+ senders)
    # query_id = Column(Integer, ForeignKey('query.id'), nullable=False)
    query = models.ForeignKey(Query, on_delete=models.PROTECT, related_name='ads')

    status = models.CharField(max_length=20, choices=AdStatus.choices, default=AdStatus.PENDING)
    filter_reason = models.CharField(max_length=255, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    send_attempts = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.name} | {self.price_raw} | {self.location}"

    class Meta:
        verbose_name = "Ad"
        verbose_name_plural = "Ads"
        constraints: List[models.BaseConstraint] = []

    @property
    def message(self):
        return self.name + '\n' + \
            self.price_raw + '\n' + \
            self.location + '\n' + \
            self.short_description

    @property
    def link(self):
        return self.url


class PriceChange(TimeStampedModel):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.CharField(max_length=30)
    new_price = models.CharField(max_length=30)

    def __str__(self):
        return f"{self.ad} | {self.old_price} -> {self.new_price}"


class PhonePublisher(TimeStampedModel):
    bazos_id = models.IntegerField(db_index=True, unique=True)
    # Todo use phone number field. Have some conversion with prefix, so it matches FB DB. Has to be valid ob Bazos?
    phone = models.CharField(max_length=30, null=True, blank=True)
    fb_user = models.ForeignKey('facebook.FBUser', on_delete=models.PROTECT, related_name='phone_publishers', null=True, blank=True)
    blocked = models.BooleanField(default=False)


class EmailPublisher(TimeStampedModel):
    bazos_id = models.IntegerField(db_index=True, unique=True)
    # Todo use email field
    email = models.CharField(max_length=30, null=True, blank=True)  # Is really unique?
    blocked = models.BooleanField(default=False)
