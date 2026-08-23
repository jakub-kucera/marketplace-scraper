from random import randint
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin, urlparse

from django_extensions.db.models import TimeStampedModel
from django.db import models

from bazos.const import BAZOS_BASE_URL, SBAZAR_BASE_URL, VINTED_BASE_URL


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
    VINTED    = "vinted",    "Vinted"
    SBAZAR    = "sbazar",    "Sbazar"


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

    extra_params = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Marketplace-specific search params. Ignored by Bazos. Vinted: "
            '{"base_url": "https://www.vinted.sk", "catalog_ids": [1194]}. '
            "Vinted text search is fuzzy — a 'macbook' search returns unrelated items — so "
            "setting filter_required is strongly recommended on Vinted queries."
        ),
    )

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
        if self.marketplace == Marketplace.VINTED:
            return self.extra_params.get("base_url", VINTED_BASE_URL)
        if self.marketplace == Marketplace.SBAZAR:
            return self.extra_params.get("base_url", SBAZAR_BASE_URL)
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


#: Safety bound on the identity-graph walk in :meth:`SellerAdCounts.for_ad`. Each round is
#: 2 queries. 95.3% of publishers pair with exactly one partner (2024-03 export), so the
#: walk almost always settles on the first round; the bound only matters for a pathological
#: chain, where stopping early under-counts rather than hanging the sender.
MAX_IDENTITY_ROUNDS = 5


@dataclass(frozen=True)
class SellerAdCounts:
    """Ad counts for the seller behind an ad, counted three ways.

    A frozen dataclass rather than a `NamedTuple` for a boring reason: as a `NamedTuple`
    with a `for_ad(ad: "Ad")` forward reference, mypy + django-stubs fails outright with
    `INTERNAL ERROR: maximum semantic analysis iteration count reached`. Same API, no
    tuple-unpacking, and the type checker stays happy.

    Kept as three numbers rather than one because **their disagreement is the signal**:
    "12 by email, 3 by phone" says the seller rotates phone numbers, which is far more
    interesting than any single total.

    ``combined`` walks the identity graph transitively — ad → its email → that email's
    other phones → those phones' other emails, to a fixpoint — because one hop is not
    enough. Measured on the 2024-03 export, 13.7% of ads get a different answer under the
    transitive walk than under ``max(by_email, by_phone)``.

    **These count ads in *this* database, i.e. ones our own queries happened to scrape —
    not the seller's true Bazos total.** A dealer with 500 live listings can show 2 here.
    The real figure is `user_ads_count` on the API's detail endpoint (see
    docs/research/bazos-api/HIDDEN_API.md §5.2), which is why the wording below says
    "seen" rather than "has".
    """

    by_email: int
    by_phone: int
    combined: int

    @classmethod
    def for_ad(cls, ad: "Ad") -> "SellerAdCounts":
        email_ids = {ad.email_publisher_id} if ad.email_publisher_id else set()
        phone_ids = {ad.phone_publisher_id} if ad.phone_publisher_id else set()
        if not email_ids and not phone_ids:
            return cls(by_email=0, by_phone=0, combined=0)

        by_email = Ad.objects.filter(email_publisher_id__in=email_ids).count() if email_ids else 0
        by_phone = Ad.objects.filter(phone_publisher_id__in=phone_ids).count() if phone_ids else 0

        # Expand both id sets until neither grows: publishers reached through a shared ad
        # belong to the same seller. A `bazos_id=0` sentinel would merge unrelated sellers
        # here, which is why migration 0025 removed it and the scraper now stores NULL.
        for _ in range(MAX_IDENTITY_ROUNDS):
            grown_phones = set(
                Ad.objects.filter(email_publisher_id__in=email_ids)
                .exclude(phone_publisher=None)
                .values_list("phone_publisher_id", flat=True)
            )
            grown_emails = set(
                Ad.objects.filter(phone_publisher_id__in=phone_ids)
                .exclude(email_publisher=None)
                .values_list("email_publisher_id", flat=True)
            )
            if grown_phones <= phone_ids and grown_emails <= email_ids:
                break
            phone_ids |= grown_phones
            email_ids |= grown_emails

        combined = (
            Ad.objects.filter(
                models.Q(email_publisher_id__in=email_ids) | models.Q(phone_publisher_id__in=phone_ids)
            )
            .distinct()
            .count()
        )
        return cls(by_email=by_email, by_phone=by_phone, combined=combined)

    @property
    def has_split_identity(self) -> bool:
        """True when the seller posts under more than one email/phone pairing.

        A present side that covers only *part* of the seller's ads proves the other side
        varies: the recruiter with one email and three phones has
        ``by_email == combined == 3`` but ``by_phone == 1``. Note ``combined >
        max(by_email, by_phone)`` does NOT work — it misses exactly that case.

        Each side is checked only when present (``> 0``), so an ad with no email publisher
        at all reads as "one side missing", not as a split identity.
        """
        return (
            (0 < self.by_email < self.combined)
            or (0 < self.by_phone < self.combined)
        )

    @property
    def summary(self) -> str:
        """One line for the Discord notification."""
        if not self.combined:
            return "Seller: unknown"
        plural = "" if self.combined == 1 else "s"
        line = f"Seller: {self.combined} ad{plural} seen"
        if self.by_email != self.by_phone or self.has_split_identity:
            line += f" (email {self.by_email} / phone {self.by_phone})"
        return line


class PriceType(models.TextChoices):
    """Price-placeholder vocabulary — see docs/research/PRICE_PARSING.md.

    Two carry a real `Ad.price`: EXACT (a real number) and FREE (a known zero — "Zdarma"
    is NOT the same as "unknown", see §3.3). The other four — NEGOTIABLE/IN_TEXT/
    MAKE_OFFER/INDIFFERENT — are Bazos's placeholder strings with no numeric value at all
    (`price` stays None). Measured exhaustive against the 2024-03 export (16,981 ads) —
    no long tail beyond these six (§3.1). CURRENT_BID is reserved for Aukro's live-bid
    semantics (§7) — no scraper sets it yet, kept here so this stays the one cross-
    marketplace enum rather than growing a second one once Aukro lands. UNKNOWN means
    parsing failed, i.e. a marketplace started using a price string this list doesn't
    know about yet.
    """
    EXACT       = "exact",       "Exact"
    NEGOTIABLE  = "negotiable",  "Dohodou / by agreement"
    IN_TEXT     = "in_text",     "V textu"
    MAKE_OFFER  = "make_offer",  "Nabídněte"
    INDIFFERENT = "indifferent", "Nerozhoduje"
    FREE        = "free",        "Zdarma / giveaway"
    CURRENT_BID = "current_bid", "Auction current bid"
    UNKNOWN     = "unknown",     "Unknown"


class AdStatus(models.TextChoices):
    PENDING       = "PENDING"       # scraped, awaiting filter
    APPROVED      = "APPROVED"      # passed filters, awaiting send
    REJECTED      = "REJECTED"      # dropped by a filter rule
    SUPPRESSED    = "SUPPRESSED"    # deliberately not sent (e.g. ignore_first_run)
    PRICE_CHANGED = "PRICE_CHANGED" # re-enters pipeline for price update notification
    SENT          = "SENT"          # successfully delivered
    FAILED        = "FAILED"        # send failed after retries


class Ad(TimeStampedModel):
    external_id = models.BigIntegerField(db_index=True)
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices, default=Marketplace.BAZOS, db_index=True)
    url = models.URLField(max_length=1024)  # TODO unique=True

    # TODO add relation to Category model. (some init method where from URL take category, bazos_id)

    name = models.CharField(max_length=120)
    price_raw = models.CharField(max_length=30)  # human-readable audit trail; see price/price_type
    price = models.BigIntegerField(null=True, blank=True, db_index=True, help_text="Parsed CZK amount. Null for a non-EXACT price_type or an unparseable price_raw.")
    price_type = models.CharField(max_length=20, choices=PriceType.choices, default=PriceType.UNKNOWN)
    location = models.CharField(max_length=128)
    view_count = models.IntegerField(null=True, blank=True, help_text="View count at the time of discovery. Null when the marketplace doesn't expose it (e.g. Vinted).")
    publish_date = models.DateTimeField(null=True, blank=True, help_text="Null when the marketplace doesn't expose it (e.g. Vinted) — never synthesise a value here.")
    # TODO add topped count
    topped = models.BooleanField(default=False, help_text="Topped ad, publish date is not accurate")
    short_description = models.CharField(max_length=300)
    full_description = models.TextField(null=True, blank=True)

    publisher_name = models.CharField(max_length=100)
    email_publisher = models.ForeignKey('EmailPublisher', on_delete=models.PROTECT, null=True, related_name='ads')
    phone_publisher = models.ForeignKey('PhonePublisher', on_delete=models.PROTECT, null=True, related_name='ads')

    # do_send = Column(Boolean, nullable=False, default=True)  # not used

    def __str__(self):
        return f"{self.name} | {self.price_raw} | {self.location}"

    class Meta:
        verbose_name = "Ad"
        verbose_name_plural = "Ads"
        constraints: List[models.BaseConstraint] = [
            models.UniqueConstraint(fields=["marketplace", "external_id"], name="unique_ad_per_marketplace"),
        ]

    def seller_ad_counts(self) -> "SellerAdCounts":
        """How many ads this seller has, counted three ways. See :class:`SellerAdCounts`."""
        return SellerAdCounts.for_ad(self)

    @property
    def message(self):
        return self.name + '\n' + \
            self.price_raw + '\n' + \
            self.location + '\n' + \
            self.short_description + '\n' + \
            self.seller_ad_counts().summary

    @property
    def link(self):
        return self.url


class AdDelivery(TimeStampedModel):
    """One query's interest in one ad, and the delivery state machine for it.

    Split out from `Ad` because delivery is a property of (ad, query, sender): the same
    real-world listing matching two queries must notify both channels. `Ad` holds the
    scraped facts; this holds everything the pipeline does about them.
    """
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="deliveries")
    query = models.ForeignKey(Query, on_delete=models.PROTECT, related_name="deliveries")

    status = models.CharField(max_length=20, choices=AdStatus.choices, default=AdStatus.PENDING)
    filter_reason = models.CharField(max_length=255, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    send_attempts = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Ad delivery"
        verbose_name_plural = "Ad deliveries"
        constraints = [
            models.UniqueConstraint(fields=["ad", "query"], name="unique_delivery_per_ad_query"),
        ]
        indexes = [
            # Both pollers do filter(status__in=[...]).order_by("created")[:BATCH] — a
            # leading-status composite index serves the filter+sort in one scan and also
            # covers a plain status= lookup, making a standalone status index redundant.
            # AdDelivery accumulates at N-per-query-per-ad rather than Ad's old 1-per-ad
            # rate, so this matters more here than a single-column index would have.
            models.Index(fields=["status", "created"], name="addelivery_status_created_idx"),
        ]

    def __str__(self):
        return f"{self.ad} → {self.query} [{self.status}]"


class PriceChange(TimeStampedModel):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.CharField(max_length=30)
    new_price = models.CharField(max_length=30)
    old_price_amount = models.BigIntegerField(null=True, blank=True)
    new_price_amount = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.ad} | {self.old_price} -> {self.new_price}"


class PublisherMixin:
    """Shared identity behaviour for `EmailPublisher` / `PhonePublisher`.

    A seller on Bazos is identified by a *pair* of opaque ids (email_id, phone_id), and the
    same person routinely posts under several pairings — one real email in the 2024-03
    export pairs with 69 distinct phones. Neither id alone is the seller, so both models
    need the same "who else appears alongside me" lookup; it lives here rather than in the
    admin so `Ad` and the sender can reuse it.

    Plain mixin, not an abstract model: it adds no fields, so it needs no migration.
    """

    #: Name of the FK on `Ad` pointing at the *other* publisher type.
    partner_ad_field: str = ""

    def partner_rows(self):
        """Publishers of the other type sharing at least one ad, most-shared first.

        One aggregate query rather than a lookup per partner — a publisher can have dozens.
        Returns dicts keyed by ``<partner_ad_field>``, ``..._bazos_id``, ``..._blocked``
        and ``shared_ads``.
        """
        return (
            self.ads.exclude(**{self.partner_ad_field: None})  # type: ignore[attr-defined]
            .values(
                self.partner_ad_field,
                f"{self.partner_ad_field}__bazos_id",
                f"{self.partner_ad_field}__blocked",
            )
            .annotate(shared_ads=models.Count("id"))
            .order_by("-shared_ads")
        )


class PhonePublisher(PublisherMixin, TimeStampedModel):
    partner_ad_field = "email_publisher"

    bazos_id = models.IntegerField(db_index=True, unique=True)
    # Todo use phone number field. Have some conversion with prefix, so it matches FB DB. Has to be valid ob Bazos?
    phone = models.CharField(max_length=30, null=True, blank=True)
    fb_user = models.ForeignKey('facebook.FBUser', on_delete=models.PROTECT, related_name='phone_publishers', null=True, blank=True)
    blocked = models.BooleanField(default=False)


class EmailPublisher(PublisherMixin, TimeStampedModel):
    partner_ad_field = "phone_publisher"

    bazos_id = models.IntegerField(db_index=True, unique=True)
    # Todo use email field
    email = models.CharField(max_length=30, null=True, blank=True)  # Is really unique?
    blocked = models.BooleanField(default=False)
