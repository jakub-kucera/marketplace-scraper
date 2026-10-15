from copy import deepcopy
from random import randint
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin, urlparse

from django_extensions.db.models import TimeStampedModel
from django.conf import settings
from django.db import models, transaction
from django.urls import reverse

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

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return f"{self.name} | {self.section}"

    @property
    def full_url(self):
        # TODO check if `/` is needed at the end - looks like it is not
        return urljoin(self.section.full_url, self.url)


class PostalCode(TimeStampedModel):
    """One PSČ and where it is, cached from Bazos's `zip.php` geocoder.

    A cache, not a reference table: rows appear as the scraper meets new codes, so it is
    always incomplete and a miss must never be read as "that place does not exist". It is
    a table rather than a bundled JSON artifact (the shape `bazos/pricing/artifacts/` uses)
    because it grows at runtime — nobody has the CZ postal-code list up front, and `zip.php`
    caps a prefix search at ~9 rows, so it cannot be enumerated offline either.

    Coordinates are the post office's, not the seller's: an ad's true location is somewhere
    inside its delivery area. That puts a floor of a few km on the accuracy of any distance
    measured from these, which is why `Query.filter_location_radius` is in whole km and
    should not be set to values that pretend to more precision than that.
    """
    code = models.CharField(max_length=5, unique=True, help_text="Five digits, no space, e.g. 11000")
    city = models.CharField(max_length=128, blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        verbose_name = "Postal code"
        verbose_name_plural = "Postal codes"
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} {self.city}".strip()


class Marketplace(models.TextChoices):
    BAZOS     = "bazos",     "Bazos"
    BAZOS_API = "bazos_api", "Bazos (API)"
    VINTED    = "vinted",    "Vinted"
    SBAZAR    = "sbazar",    "Sbazar"


class MarketplaceCategory(models.Model):  # type: ignore[django-manager-missing]
    """One node of a marketplace's own category tree — a lookup, **not** a `Query` FK.

    Deliberately nothing points at this from `Query`. Vinted's tree is ~2,920 nodes that
    have to be re-seeded from the live site, and a `PROTECT` FK would make a re-seed fail
    the moment Vinted retires a node some `Query` still references, while `SET_NULL` would
    silently widen that query to the whole marketplace — the worse of the two. With the ids
    living in `Query.extra_params`, a retired node degrades to "returns nothing" and
    `create_vinted_catalogs` can just warn about it. See
    docs/backlog/VINTED_REWRITE.md §2.1.

    Bazos keeps its own `Section`/`Category` and is **not** migrated in here: those two are
    URL builders (`Section.full_url` is a subdomain, `Category.full_url` joins onto it), not
    lookups, and this model has no equivalent of either.

    `marketplace` is a column from day one rather than this being a `VintedCategory`:
    Sbazar already stores `extra_params["category_id"]` and will want the same picker.
    """
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices, db_index=True)
    external_id = models.CharField(max_length=32, help_text="The marketplace's own id, e.g. Vinted '3580'.")
    name = models.CharField(max_length=120)
    slug = models.CharField(max_length=160, blank=True, help_text="URL segment, e.g. '3580-laptops'.")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )

    class Meta:
        verbose_name = "Marketplace category"
        verbose_name_plural = "Marketplace categories"
        ordering = ("marketplace", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["marketplace", "external_id"], name="unique_category_per_marketplace"
            ),
        ]

    def __str__(self):
        return self.path

    @property
    def path(self) -> str:
        """`Elektronika > Pocitace a prislusenstvi > Notebooky`.

        Not decoration: 205 Vinted titles are shared by more than one node — 575 of 2,920
        (20%) are ambiguous by name alone, and "Ostatní" appears 35 times. A picker
        labelled by `name` is unusable.

        ⚠️ Walks `parent`, so this is one query per level unless the caller prefetched.
        Never call it in a loop over a queryset — build labels in one pass instead (see
        `MarketplaceCategory.path_map`).
        """
        names: list[str] = []
        node: "MarketplaceCategory | None" = self
        seen: set[int] = set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)          # a cycle would otherwise hang the admin
            names.append(node.name)
            node = node.parent
        return " > ".join(reversed(names))

    @classmethod
    def path_map(cls, marketplace: str) -> dict[int, str]:
        """`{pk: "A > B > C"}` for one marketplace, in a **single** query regardless of depth.

        The bulk counterpart to :attr:`path`. Resolving 2,920 nodes through the property
        would be ~12k queries on a single admin form render.
        """
        rows = list(cls.objects.filter(marketplace=marketplace).values("pk", "name", "parent_id"))
        by_pk = {r["pk"]: r for r in rows}
        cache: dict[int, str] = {}

        def resolve(pk: int, seen: frozenset[int] = frozenset()) -> str:
            if pk in cache:
                return cache[pk]
            row = by_pk.get(pk)
            if row is None or pk in seen:
                return ""
            parent_id = row["parent_id"]
            prefix = resolve(parent_id, seen | {pk}) if parent_id else ""
            cache[pk] = f"{prefix} > {row['name']}" if prefix else row["name"]
            return cache[pk]

        return {pk: resolve(pk) for pk in by_pk}


#: `Query` fields whose changes are worth an audit row in :class:`QueryChange`.
TRACKED_CONFIG_FIELDS = (
    "text",
    "section_id",
    "category_id",
    "price_lower",
    "price_upper",
    "location_center",
    "location_radius",
    "enabled",
    "ignore_first_run",
    "load_full_description",
    "marketplace",
    "filter_blocklist",
    "filter_required",
    "filter_rule_names",
    "filter_location_center",
    "filter_location_radius",
    "filter_price_model_z",
    "filter_price_model_min_discount",
    "extra_params",
    "sender_id",
)


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
    filter_rule_names = models.JSONField(default=list, blank=True, help_text="Which filter rules to apply (empty = all default rules). Valid names: price_range, blocklist_keyword, required_keyword, publisher_blocklist, price_drop, location_distance, price_model (opt-in only).")

    # Distinct from location_center/location_radius above, which are search params sent to
    # the marketplace and therefore decide what is *scraped*. These two decide what is
    # *notified*, at the filter stage, out of whatever was scraped — so a query can watch
    # all of Czechia and still only ping the channel for ads within pickup range. Both
    # blank (the default) means no distance filtering at all.
    filter_location_center = models.CharField(
        max_length=10,
        blank=True,
        help_text="PSČ to measure ad distance from, e.g. 110 00. Blank = no distance filter.",
    )
    filter_location_radius = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Reject ads further than this many km from filter_location_center. Blank = no distance filter.",
    )

    # Per-query overrides for the two `price_model` thresholds. Blank falls back to
    # settings, then to bazos.const — so an unset query behaves exactly as before.
    #
    # Both are tracked in TRACKED_CONFIG_FIELDS on purpose. Calibrating these is done by
    # feel against a stream of notifications, and without an audit row "when did I loosen
    # this, and what did it let through afterwards" is unanswerable. See
    # docs/research/MACBOOK_PRICE_MODEL.md §6 for why the shipped defaults are a starting
    # point rather than a measured optimum.
    filter_price_model_z = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "price_model: reject unless z_score <= this. HIGHER is more permissive "
            "(-2.0 strict, -1.0 looser, 0.0 nearly off). Blank = use the global default."
        ),
    )
    filter_price_model_min_discount = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "price_model: reject unless the ad is at least this % below the predicted price. "
            "LOWER is more permissive (10.0 strict, 0.0 loose, negative accepts ads priced "
            "above prediction). Blank = use the global default."
        ),
    )

    extra_params = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Marketplace-specific search params. Ignored by Bazos. "
            'Vinted: {"catalog_ids": [3580], "brand_ids": [54661], "status_ids": [2], '
            '"base_url": "https://www.vinted.sk"}. '
            "⚠️ Vinted text search is fuzzy — a 'macbook' search returned 22 unrelated "
            "items in 96, including clothing — so prefer catalog_ids + brand_ids over "
            "text, and keep filter_required as a backstop. Category ids are in "
            "Marketplace categories (seed with manage.py create_vinted_catalogs); brand "
            "ids come from an item page's /brand/<id>-<slug> link. status_ids: "
            "1=new without tags, 2=very good, 3=good, 4=satisfactory, 6=new with tags, "
            "7=limited functionality — NOT the condition id shown on an item page. "
            'Sbazar: {"category_id": 123}.'
        ),
    )

    sender = models.ForeignKey('senders.Discord', on_delete=models.SET_NULL, null=True, related_name='queries')
    # logger_id
    # TODO Ads
    # products = relationship('ProductDB', backref='query', lazy=True)

    def __str__(self):
        # Marketplace is part of the identity, not decoration: the same text/price pair
        # can exist on Bazos and Vinted as two separate rows, and every admin surface
        # that shows a Query by name (QueryRun list, AdDelivery list, filters) would
        # otherwise render them identically.
        return (
            f"{self.text or self.category or self.section} "
            f"| {self.price_lower}-{self.price_upper} "
            f"| {self.get_marketplace_display()}"
        )

    class Meta:
        verbose_name = "Query"
        verbose_name_plural = "Queries"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_lower__lte=models.F("price_upper")),
                name="price_lower_lte_price_upper",
            ),
            models.CheckConstraint(
                condition=models.Q(section__isnull=True) | models.Q(category__isnull=True),
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

    # ------------------------------------------------------------------
    # Config change tracking -> QueryChange
    #
    # The old values are snapshotted when the row is loaded, not re-SELECTed at save
    # time, because `ScrapeRunner._run_query_with_rotation` calls `query.save()` after
    # every successful run: a read-back would add a query per query per pass to persist
    # a flag this log does not even track. Snapshot-on-load costs nothing extra.
    #
    # Blind spot, on purpose: `Query.objects.filter(...).update(...)` never calls
    # `save()`, so a queryset update is invisible here. The one in production
    # (`ScrapeRunner`'s `randomly_generated` force-clear) touches no tracked field.
    # ------------------------------------------------------------------

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # `field_names` is the list of attnames actually loaded, so a `.only()`/`.defer()`
        # queryset snapshots the subset it fetched instead of triggering a refetch here.
        instance._config_snapshot = instance._config_state(field_names)
        return instance

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        # Re-baseline, or the snapshot still describes the pre-refresh row. Live case:
        # `_run_query_with_rotation` refreshes a query between blacklist retries.
        self._snapshot_config()

    def _config_state(self, loaded):
        """Deep copy of the tracked fields present in `loaded` (an iterable of attnames).

        Deep, because `filter_blocklist` and friends are mutable JSON: a caller that does
        `query.filter_blocklist.append(...)` would otherwise mutate the snapshot too and
        the diff would come out empty.
        """
        loaded = set(loaded)
        return {
            name: deepcopy(getattr(self, name))
            for name in TRACKED_CONFIG_FIELDS
            if name in loaded
        }

    def _snapshot_config(self):
        deferred = self.get_deferred_fields()
        self._config_snapshot = self._config_state(
            name for name in TRACKED_CONFIG_FIELDS if name not in deferred
        )

    def _pending_config_changes(self, update_fields=None):
        """`{field: {"old": ..., "new": ...}}` for tracked fields this save will change."""
        snapshot = getattr(self, "_config_snapshot", None)
        if snapshot is None:
            # No snapshot means the instance was built in memory rather than loaded
            # (`Query(pk=7, ...)`), so there is no "old" to diff against. Recording the
            # current values as a change from nothing would be a fabricated history, so
            # this save goes unlogged instead.
            return {}
        names = set(snapshot)
        if update_fields is not None:
            # Fields outside `update_fields` are not written by this save; logging them
            # would claim a change that never reached the database.
            names &= {str(field) for field in update_fields}
        changes = {}
        for name in TRACKED_CONFIG_FIELDS:  # fixed order, so the stored dict is stable
            if name not in names:
                continue
            old, new = snapshot[name], getattr(self, name)
            if old != new:
                changes[name] = {"old": old, "new": new}
        return changes

    def save(self, *args, **kwargs):
        changes = self._pending_config_changes(kwargs.get("update_fields"))
        if changes:
            # Atomic only when there is something to log. The no-change path is the hot
            # one (once per query per pass, mid-scrape) and opening a real transaction
            # there would hold row locks across the rest of the pass for nothing.
            with transaction.atomic():
                super().save(*args, **kwargs)
                QueryChange.objects.create(
                    query=self,
                    query_label=str(self)[: QueryChange.LABEL_MAX_LENGTH],
                    changes=changes,
                )
        else:
            super().save(*args, **kwargs)
        self._snapshot_config()

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


class QueryChange(TimeStampedModel):
    """One `Query` save that altered its configuration, as a field-level diff.

    A separate append-only table rather than a JSON blob on `Query` itself, for the same
    reasons `PriceChange` is one: `Query` is re-read on every pass and rendered on an
    admin changelist that already had to be tuned for cost (see `QueryAdmin.get_queryset`),
    so growing that row without bound is the one thing to avoid. It also keeps the history
    queryable — `changes__has_key="filter_required"` finds every query whose required-list
    was touched — and lets a change outlive the query it describes.

    Diffs, not snapshots: the question this answers is "what did I change on the 14th",
    and past state is reconstructable by replaying diffs backwards from the live row.

    `created` is the timestamp of the change; there is no second `changed_at` column
    because it would always hold the same value. Rows are never edited, so `modified`
    (inherited, unused) stays equal to it.
    """

    #: Kept in sync with the `query_label` column below; `Query.save` truncates to it.
    LABEL_MAX_LENGTH = 200

    query = models.ForeignKey(
        Query,
        # SET_NULL, not CASCADE: "when did this query stop being scraped, and what did it
        # look like" is a question you ask *after* deleting it. `query_label` is what keeps
        # an orphaned row readable.
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="config_history",
    )
    query_label = models.CharField(
        max_length=LABEL_MAX_LENGTH,
        blank=True,
        default="",
        help_text="str(Query) as of this change — survives the query being deleted.",
    )
    changes = models.JSONField(
        default=dict,
        help_text='{"field": {"old": ..., "new": ...}} for the fields this save altered.',
    )

    class Meta:
        ordering = ("-created",)
        verbose_name = "Query change"
        verbose_name_plural = "Query changes"
        indexes = [
            # Every read is "this query's history, newest first" — the inline on the
            # Query change form, and the changelist filtered to one query.
            models.Index(fields=["query", "-created"], name="querychange_query_created"),
        ]

    def __str__(self):
        return f"{self.query_label or self.query} | {', '.join(self.changed_fields)}"

    @property
    def changed_fields(self) -> List[str]:
        """Tracked field names this row touched, in `TRACKED_CONFIG_FIELDS` order."""
        return [name for name in TRACKED_CONFIG_FIELDS if name in self.changes]

    @property
    def summary(self) -> str:
        """One-line `field: old -> new` rendering. Pure — the admin formats it as HTML."""
        return "; ".join(
            f"{name}: {self.changes[name].get('old')!r} -> {self.changes[name].get('new')!r}"
            for name in self.changed_fields
        )


class QueryRun(models.Model):
    query = models.ForeignKey(Query, on_delete=models.CASCADE, related_name='runs')
    # Indexed because every reader of this table filters on a time window and none of them
    # could use an index before: the admin dashboard's three aggregates, the changelist's
    # date-range filter, and `prune_query_runs`' `run_start__lt` cutoff. Measured on
    # production 2026-09-20 at 26 131 rows: a 14-day aggregate was a 10.8 ms sequential
    # scan, and the table grows ~900 rows/day against a 90-day horizon.
    run_start = models.DateTimeField(db_index=True)
    run_end = models.DateTimeField(null=True, blank=True)
    new_ads_count = models.IntegerField(null=True)
    success = models.BooleanField(default=True)
    error = models.TextField(null=True, blank=True)
    exit_ip = models.CharField(
        max_length=45,  # fits an IPv6 literal
        blank=True,
        default="",
        # Indexed because grouping/filtering failures by IP is the entire reason the
        # column exists, on the fastest-growing table here.
        db_index=True,
        help_text=(
            "Egress IP the marketplace reported when it blocked this run, read out of the "
            "403 body. Empty on a successful run — the transport isolates circuits per "
            "destination host, so there is no IP-echo lookup that would answer for the "
            "circuit the marketplace was actually served by."
        ),
    )


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


class AdSource(models.TextChoices):
    """How this ad got into the database.

    Until seller-inventory fetches existed, every row was here because a `Query` matched it,
    and "how many ads do we have" and "how many did our queries find" were the same number.
    They are not any more, and the difference is invisible without this column: a
    seller-sweep ad has no `AdDelivery` at all, so it is absent from every per-query count
    while still inflating every total.

    Recording it is cheap; discovering the ambiguity six months into an analysis is not.
    """
    QUERY = "query", "Found by a query"
    SELLER_SWEEP = "seller_sweep", "Pulled from a seller's inventory"


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
    # TextField, not CharField(300): this is the free-form listing snippet scraped from
    # the marketplace and there is no real invariant behind any particular bound. A Bazos
    # ad longer than 300 chars raised DataError inside _resolve_ad's save(), which aborted
    # the whole query walk — and did so every pass, wedging the query indefinitely
    # (observed live 2026-08-23 on the `audeze` query). Widened rather than truncated
    # because the keyword rules match against `name + short_description`, so a truncated
    # tail silently stops `filter_blocklist`/`filter_required` phrases from matching.
    short_description = models.TextField()
    full_description = models.TextField(null=True, blank=True)

    # Structured specs exactly as the marketplace stated them — the same split as
    # price_raw/price: this is the audit trail, and any parse is derived from it at read
    # time. Stored RAW and never normalised on write ({"computer_ram": "16 GB"}, not
    # {"ram_gb": 16}): normalising here would bake in today's parser and leave nothing to
    # re-derive from when it improves, which is the bind `rescore_ads` exists to work
    # around. Values stay strings; nothing is coerced.
    #
    # The seam this keeps: `attributes` is what the marketplace said, `AdPriceScore.features`
    # is what a model made of it — which is the reason `features` is JSON at all.
    #
    # Empty for marketplaces that publish no structured specs (Bazos, Sbazar today). Do NOT
    # write regex-derived values in here from Bazos free text; that destroys the
    # stated-vs-derived distinction the column exists for. Only populated when the query
    # has load_full_description=True — Vinted serves specs on the detail page, not the
    # listing row. See docs/backlog/VINTED_REWRITE.md §2.3.
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured specs as the marketplace stated them, verbatim, e.g. "
            '{"computer_ram": "16 GB"}. Empty when the marketplace publishes none.'
        ),
    )

    # Defaults to QUERY so every pre-existing row keeps the meaning it was written with —
    # they were all found by a query, and backfilling any other value would be a claim the
    # data cannot support.
    source = models.CharField(
        max_length=20, choices=AdSource.choices, default=AdSource.QUERY, db_index=True,
        help_text="How this ad entered the database. Only 'query' ads have deliveries.",
    )

    # Set by `bazos/reposts.py`, never by the scraper: it is a *conclusion* about two rows,
    # not a fact either listing states. SET_NULL rather than CASCADE — deleting the older
    # listing must not delete the one still for sale.
    reposted_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reposts",
        help_text="The earlier listing this one appears to be a relist of. Inferred, not stated.",
    )

    publisher_name = models.CharField(max_length=100)
    email_publisher = models.ForeignKey('EmailPublisher', on_delete=models.PROTECT, null=True, related_name='ads')
    phone_publisher = models.ForeignKey('PhonePublisher', on_delete=models.PROTECT, null=True, related_name='ads')

    # Delisting observation. Two timestamps, deliberately **not** an `AdStatus` value:
    # `AdStatus` is the *delivery* state machine and lives on `AdDelivery`, while being
    # removed is a property of the listing. An ad can be SENT and later removed; those are
    # not alternatives, so they must not share a column.
    #
    # ⚠️ `removed_at` means "no longer served by the marketplace", which is NOT "sold". It
    # conflates sold, withdrawn, deleted, and — the big one — **expired**: Bazos listings
    # age out on their own, so a disappearance near the expiry horizon says more about the
    # clock than about a buyer. There is deliberately no `sold` boolean: the column name is
    # the claim, and this one cannot honestly make it. `AdOutcome` is where ground truth
    # goes.
    last_seen_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="Last delisting sweep that still found this ad. Null = never swept.",
    )
    removed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="First sweep that did NOT find it. Null means still listed OR never swept "
                  "OR past the watch horizon — see DELIST_MAX_AGE_DAYS.",
    )

    # do_send = Column(Boolean, nullable=False, default=True)  # not used

    def __str__(self):
        return f"{self.name} | {self.price_raw} | {self.location}"

    class Meta:
        verbose_name = "Ad"
        verbose_name_plural = "Ads"
        constraints = [
            models.UniqueConstraint(fields=["marketplace", "external_id"], name="unique_ad_per_marketplace"),
        ]
        indexes = [
            # The delisting sweep's "what is due" query is the only hot path over these
            # columns, and it never looks at an ad already known removed — so the index is
            # partial. Without the WHERE it would carry every dead ad forever, which is the
            # majority of the table in steady state.
            models.Index(
                fields=["last_seen_at"],
                condition=models.Q(removed_at__isnull=True),
                name="ad_live_last_seen_idx",
            ),
        ]

    def seller_ad_counts(self) -> "SellerAdCounts":
        """How many ads this seller has, counted three ways. See :class:`SellerAdCounts`."""
        return SellerAdCounts.for_ad(self)

    def current_price_score(self):
        """The claiming model's newest non-declined `AdPriceScore`, or None. Cached per instance.

        Both notification lines below need it, and `Ad.message` runs once per ad in
        `run_sender`'s batch — so this is read once and reused rather than fetched twice.
        The cache lives on the instance, which is the lifetime of one send.

        **Keyed on the model that claims the ad, not on `-created`.** Nothing ever deletes an
        `AdPriceScore`, so a renamed or retired model leaves its rows in place forever, and
        `update_or_create` never refreshes `created` — so ordering by it alone surfaced
        whichever model scored the ad *later*, which need not be the one that governed the
        filter decision (docs/backlog/PRICE_MODEL_DEFECTS.md §9). No claiming model therefore
        means no score to report, which is the same answer `score_ad` would give today.
        """
        if not hasattr(self, "_price_score_cache"):
            # Imported here, not at module scope: bazos.pricing imports this module.
            from bazos.pricing.registry import get_price_model

            model = get_price_model(self)
            self._price_score_cache = None if model is None else (
                self.price_scores
                .filter(model_name=model.name)
                .exclude(predicted__isnull=True)
                .order_by("-created")
                .first()
            )
        return self._price_score_cache

    @property
    def price_score_summary(self) -> str:
        """One line about what a price model thought, or "" if none had an opinion.

        Costs one extra query on top of `seller_ad_counts()`'s several — the warning
        against calling `.message` in a loop over a large queryset applies here too, only
        more so. Declined scores render as nothing: "a model looked and had no opinion" is
        worth storing (see `AdPriceScore`) but not worth a line in a notification.
        """
        score = self.current_price_score()
        if score is None:
            return ""
        line = f"Model: {score.predicted} Kč predicted"
        if score.discount_pct is not None:
            line += f" | {score.discount_pct:+.0f}%"
        if score.z_score is not None:
            line += f" | z {score.z_score:+.1f}"
        return f"{line} ({score.model_name} {score.model_version})"

    @property
    def message(self):
        parts = [
            self.name,
            self.price_raw,
            self.location,
            self.short_description,
            self.seller_ad_counts().summary,
        ]
        # Appended rather than interleaved so every existing golden message keeps its
        # shape — test_pipeline_e2e pins these strings, and an ad nothing scored is
        # byte-identical to before.
        for line in (self.price_score_summary, self.comparables_summary):
            if line:
                parts.append(line)
        return '\n'.join(parts)

    @property
    def comparables_summary(self) -> str:
        """Where this ad sits among current listings of the same thing, or "".

        Costs one query, and only for an ad that has a score — `find_comparables` reads the
        spec bucket off the score, so an unscored ad short-circuits before touching the DB.
        That keeps an unscored ad's message at its previous query count and confines the
        extra cost to ads that were going to carry a model line anyway.
        """
        from bazos.comparables import find_comparables

        score = self.current_price_score()
        if score is None:
            return ""
        found = find_comparables(self, subject_score=score)
        return found.summary() if found is not None else ""

    @property
    def link(self):
        return self.url

    @property
    def admin_url(self) -> str:
        return settings.SITE_BASE_URL.rstrip("/") + reverse("admin:bazos_ad_change", args=[self.pk])


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


class OutcomeKind(models.TextChoices):
    """What actually happened about one ad, as recorded by a human.

    `LOST_TO_OTHER_BUYER` is its own value rather than folded into `NO_REPLY` because it is
    the direct evidence of whether latency is still costing deals — the question the whole
    latency half of the backlog exists to answer.
    """
    INTERESTED   = "interested",   "Interested, not acted on yet"
    CONTACTED    = "contacted",    "Contacted the seller"
    NO_REPLY     = "no_reply",     "Contacted, no reply"
    LOST         = "lost",         "Lost to another buyer"
    REJECTED     = "rejected",     "Looked, decided against it"
    BOUGHT       = "bought",       "Bought it"
    NOT_AS_LISTED = "not_as_listed", "Misrepresented / damaged / scam"


class AdOutcome(TimeStampedModel):
    """What a human did about one ad, and what it was worth. The only ground truth here.

    `Ad.removed_at` measures *time to disappear*, which is a proxy for selling and a
    confounded one — expiry looks identical. This table is how that proxy gets calibrated:
    a few dozen honestly-recorded rows are enough to estimate how often "disappeared" means
    "sold", and nothing else in the database can supply that.

    One row per ad, not per delivery: what happened is a fact about the listing, the same
    reason `AdPriceScore` hangs off `Ad`.

    ⚠️ Its value depends entirely on being filled in. A logbook nobody writes to is worse
    than none, because it looks like data — so the entry point is an admin action on the ad
    changelist rather than a form someone has to remember to visit.
    """
    ad = models.OneToOneField(Ad, on_delete=models.CASCADE, related_name="outcome")
    kind = models.CharField(max_length=20, choices=OutcomeKind.choices)
    #: What it actually changed hands for, when that is known. Null for every outcome except
    #: BOUGHT, and null even then if the number was never agreed — an asking price copied
    #: into this column would quietly poison the one table that is supposed to hold truth.
    realised_price = models.BigIntegerField(
        null=True, blank=True,
        help_text="CZK actually paid. Only for 'bought', and only if genuinely known.",
    )
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = "Ad outcome"
        verbose_name_plural = "Ad outcomes"
        ordering = ("-created",)

    def __str__(self):
        return f"{self.get_kind_display()} — {self.ad}"


class AdSpecExtraction(TimeStampedModel):
    """Specs an LLM read out of one ad's free text, and which prompt version read them.

    **A separate table, and deliberately not `Ad.attributes`.** That column means "specs as
    the marketplace *stated* them, verbatim", and its own comment forbids writing derived
    values into it: doing so destroys the stated-vs-derived distinction it exists for, and
    leaves nothing to re-derive from when extraction improves. A Bazos ad states nothing —
    every spec is in prose — so anything read out of it is derived by construction.

    Why this is worth building at all: `PRICE_MODEL_BENCHMARK.md` §3.1 measured **two
    extractor regexes as worth more R² than the entire choice of estimator**. Extraction, not
    model class, is the bottleneck, and regexes are where the current extractor tops out.

    Versioned on the prompt, like `AdPriceScore` is on the artifact: re-running v1 updates
    its row, and a v2 is a new one, so "what did v1 think" survives the upgrade. A declined
    extraction is stored with `specs` empty and a reason, because "the model looked and had
    no opinion" is a different fact from "nothing looked" — the same call `AdPriceScore`
    makes.

    ⚠️ **Nothing consumes this yet.** It ships the way `llm/` did: inert, with its first
    consumer a separate decision. Wiring it into a `PriceModel` means deciding what happens
    when an extraction disagrees with the regexes, which is not a question to answer in
    passing.
    """
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="spec_extractions")
    specs = models.JSONField(
        default=dict, blank=True,
        help_text='Derived specs, e.g. {"ram_gb": 16, "cpu": "i5-10400"}. Empty when declined.',
    )
    provider = models.CharField(max_length=20)
    model_name = models.CharField(max_length=60)
    prompt_version = models.CharField(max_length=10)
    declined_reason = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("ad", "prompt_version"), name="unique_extraction_per_ad_prompt"
            )
        ]
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"{self.ad} — {self.prompt_version} ({len(self.specs)} specs)"


class AdPriceScore(TimeStampedModel):
    """What a price model thinks one ad is worth, and how unusual its asking price is.

    A child table of `Ad` rather than columns on it, for the same reasons `PriceChange` is
    one: `Ad` is re-read on every scraper pass and rendered on an admin changelist that has
    already had to be tuned for cost, so widening that row is the thing to avoid. It is on
    `Ad` and not `AdDelivery` because the score does not vary by query -- what a listing is
    worth is a fact about the listing. Whether that is cheap *enough to notify about* is the
    per-query decision, and that lives in the filter layer.

    Declined scores are stored too, with null numbers and `declined_reason` set: "a model
    looked and had no opinion" is a different fact from "nothing ever looked", and only the
    second is worth retrying.

    Design: docs/proposals/ML_PRICE_SCORING.md §2.
    """
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="price_scores")

    model_name = models.CharField(max_length=64, help_text="Registry key of the model that produced this.")
    model_version = models.CharField(max_length=32, help_text="Artifact version, so a bad model's rows are findable.")

    predicted = models.BigIntegerField(null=True, blank=True, help_text="Predicted price in CZK. Null when the model declined.")
    residual_log = models.FloatField(null=True, blank=True, help_text="ln(actual) - ln(predicted). Negative = cheaper than expected.")
    discount_pct = models.FloatField(null=True, blank=True, help_text="(1 - actual/predicted) * 100. Positive = below prediction.")
    z_score = models.FloatField(null=True, blank=True, help_text="Residual over the seller's own residual spread. Comparable across seller types.")
    seller_prior_ads = models.IntegerField(null=True, blank=True, help_text="Other ads from this seller when scored; picks the sigma prior.")
    # JSON rather than columns because the feature set differs per model and is the
    # model's own vocabulary, not this table's. The numbers above stay typed on purpose:
    # they are what you sort and filter a changelist by, and a JSON blob cannot do that.
    features = models.JSONField(null=True, blank=True, help_text="Parsed inputs the prediction was computed from. Null when the model declined or does not expose them.")
    declined_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Ad price score"
        verbose_name_plural = "Ad price scores"
        constraints = [
            # One current score per model per ad. Not (ad, model, version): the question asked
            # at read time is "what does the current model say", and this bounds growth. Score
            # history becomes worth keeping once P24 gives outcomes to calibrate against --
            # that is a deliberate later change, not something to bolt on now.
            models.UniqueConstraint(fields=["ad", "model_name"], name="unique_price_score_per_ad_model"),
        ]
        indexes = [
            models.Index(fields=["model_name", "z_score"], name="adpricescore_model_z_idx"),
        ]

    def __str__(self):
        if self.predicted is None:
            return f"{self.ad} | {self.model_name}: declined"
        return f"{self.ad} | {self.model_name}: {self.predicted} Kc ({self.discount_pct:+.1f}%)"


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


class SellerRatingFields(models.Model):
    """Aggregate rating counts for one publisher id. Abstract; both publisher models get it.

    **Counts, never identities, and that is the whole design.** `ratings.php` is public and
    unauthenticated, and it returns each reviewer's `name`, real unmasked `phone` and the
    free-text `message` — private individuals who left feedback, not the seller.
    `HIDDEN_API.md` §6.2(5) flagged that as "a step up in what we'd be collecting" and asked
    for a deliberate decision; §6.4b then recommended its own answer, which this adopts.

    Three reasons, in the order to re-litigate them if anyone wants to change it:

    - The counts answer the question. "Does this seller have negative feedback, how much,
      how recent" is the decision input; a reviewer's name and number contribute nothing.
    - `./backups/` is gitignored because dumps already hold *seller* PII. Adding
      *third-party* PII widens a leak to people with no relationship to this project.
    - `MONETIZATION.md` §6 outranks convenience here: the reviewer data has no lawful basis
      that the seller ids do not already have.

    ⚠️ What is given up is the text of negative reviews — "never shipped" is more actionable
    than `negative: 3`. That turned out to matter, and the escape hatch this docstring
    prescribed now exists: `STORE_SELLER_REVIEWS` (default **off**, mirroring
    `PRICE_MODEL_SHADOW_MODE`) persists the full entries as `SellerReview` rows. The counts
    here stay the always-on answer and are written either way, so nothing downstream has to
    know whether the flag is set. Read `SellerReview` before turning it on: it widens
    `./backups/` from seller PII to third-party PII, and it is the only place in the schema
    that would know a reviewer exists at all.

    An abstract model rather than fields on `PublisherMixin`: that mixin is deliberately
    plain ("it adds no fields, so it needs no migration"), and declaring these six twice to
    preserve the property would be worse than adding a second, honest base.
    """

    ratings_positive = models.PositiveIntegerField(default=0)
    ratings_negative = models.PositiveIntegerField(default=0)
    ratings_neutral = models.PositiveIntegerField(default=0)
    #: Bounds of the rating history. A seller with three negatives from 2019 is a different
    #: proposition from one with three from last month, and the counts alone cannot say.
    ratings_first_at = models.DateTimeField(null=True, blank=True)
    ratings_last_at = models.DateTimeField(null=True, blank=True)
    #: Null means nobody has looked — distinct from "looked, found none", which is zeroes
    #: with a timestamp. Same distinction `AdPriceScore`'s declined rows exist to keep.
    ratings_fetched_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When ratings.php was last read for this id. Null = never looked.",
    )

    class Meta:
        abstract = True

    @property
    def ratings_total(self) -> int:
        return self.ratings_positive + self.ratings_negative + self.ratings_neutral


class PhonePublisher(PublisherMixin, SellerRatingFields, TimeStampedModel):
    partner_ad_field = "email_publisher"
    #: `ratings.php` takes one of two mutually exclusive params; this names ours.
    ratings_param = "phone_id"

    bazos_id = models.IntegerField(db_index=True, unique=True)
    phone = models.CharField(max_length=30, null=True, blank=True)
    blocked = models.BooleanField(default=False)

    def __str__(self):
        # Without this every FK dropdown and inline row reads "PhonePublisher object (12)",
        # which names the row but not the seller. bazos_id is the identity; the number is
        # what the partner tables and the Ad change page are keyed on.
        return f"{self.phone} | {self.bazos_id}" if self.phone else f"phone id {self.bazos_id}"


class EmailPublisher(PublisherMixin, SellerRatingFields, TimeStampedModel):
    partner_ad_field = "phone_publisher"
    ratings_param = "email_id"

    bazos_id = models.IntegerField(db_index=True, unique=True)
    # Todo use email field
    email = models.CharField(max_length=30, null=True, blank=True)  # Is really unique?
    blocked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.email} | {self.bazos_id}" if self.email else f"email id {self.bazos_id}"


class SellerReview(TimeStampedModel):
    """One review left for one seller, stored verbatim. Written only when
    `STORE_SELLER_REVIEWS` is on.

    `SellerRatingFields` deliberately reduces `ratings.php` to counts before anything is
    persisted, and says that if the review *text* ever turns out to matter the move is a
    setting defaulting to off rather than quietly widening what is collected. This is that
    setting's table; the counts on the publisher row remain the always-on answer and are
    written whether or not this is enabled.

    **What a row here contains is third-party personal data.** The reviewer is a private
    individual who bought from or sold to one of our sellers - not a seller themselves, and
    not someone with any relationship to this project. `reviewer_phone` is a real, unmasked
    number that `ratings.php` hands out unauthenticated. Two consequences that do not
    follow automatically and have to be chosen: `./backups/` is already gitignored for
    holding seller PII and now holds this too, and a GDPR erasure request about a *reviewer*
    is answerable only by deleting rows here, because nothing else in the schema knows they
    exist.

    Keyed to whichever publisher id was queried, mirroring `Ad`'s two nullable FKs: a Bazos
    seller is a pair of opaque ids and `ratings.php` takes one or the other, so a review
    fetched by `email_id` cannot be assumed to belong to the paired phone id.

    Refresh is **delete-and-replace per publisher**, not upsert. The endpoint returns the
    seller's whole history in one unpaginated response, so the response *is* the truth: a
    review edited or withdrawn upstream should disappear here, which an upsert keyed on a
    natural key would silently preserve. It also avoids inventing an identity for a row that
    has no stable id of its own - `from` is a timestamp that can repeat and can be
    unparseable, and the reviewer id can be blank.
    """
    VERDICTS = (("positive", "positive"), ("negative", "negative"), ("neutral", "neutral"))

    email_publisher = models.ForeignKey(
        "EmailPublisher", on_delete=models.CASCADE, null=True, blank=True, related_name="reviews"
    )
    phone_publisher = models.ForeignKey(
        "PhonePublisher", on_delete=models.CASCADE, null=True, blank=True, related_name="reviews"
    )

    #: The reviewer's own `email_id` from the payload. Blank often enough that it cannot be
    #: an identity, kept because it is what links a reviewer to their own publisher row if
    #: they also sell.
    reviewer_external_id = models.CharField(max_length=32, blank=True, db_index=True)
    reviewer_name = models.CharField(max_length=120, blank=True)
    #: Unmasked, and often empty - roughly half the sampled entries carry one.
    reviewer_phone = models.CharField(max_length=30, blank=True)
    verdict = models.CharField(max_length=10, choices=VERDICTS, db_index=True)
    message = models.TextField(blank=True)
    #: Null when `from` was unparseable. The row is still worth keeping - the verdict and
    #: the text are the point - so an unreadable date does not drop it.
    rated_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-rated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(email_publisher__isnull=False, phone_publisher__isnull=True)
                    | models.Q(email_publisher__isnull=True, phone_publisher__isnull=False)
                ),
                name="seller_review_belongs_to_exactly_one_publisher",
            ),
        ]

    def __str__(self):
        when = f"{self.rated_at:%Y-%m-%d}" if self.rated_at else "undated"
        return f"{self.verdict} {when}"
