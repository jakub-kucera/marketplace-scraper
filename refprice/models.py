"""What a reference lookup leaves behind.

Design: `docs/proposals/PRICE_REFERENCE_SERVICE.md` §6. The grain is the point:

- **`RefProduct` is keyed on the product, not the ad.** Many ads map to one catalogue
  entry, which is what makes repeated lookups nearly free — and why the LLM cost in §5's
  ladder amortises rather than scaling with the ad firehose.
- **`RefPricePoint` is a child table, not a JSON blob on the parent.** Same call
  `PriceChange` makes: these are numbers a changelist sorts and charts by.
- **`RefProductLink.confirmed_by_human` is the most valuable column here.** Every admin
  confirmation is a labelled `(ad title -> product id)` pair, and that corpus is what
  would later justify automating any of this. A fully automatic v1 would produce none.
- **`RefLookup` is written per *attempt*, failures included** — `QueryRun`'s rule.
"""
import datetime as dt

from django.db import models
from django.utils import timezone


class MatchMethod(models.TextChoices):
    RULE = "RULE", "Rules"
    LLM = "LLM", "LLM adjudication"
    MANUAL = "MANUAL", "Human"
    CACHED = "CACHED", "Cached"


class LookupStatus(models.TextChoices):
    """Six outcomes, because collapsing them is what makes a caller trust a number it
    should not. `NO_MARKET` and `NO_MATCH` are split on purpose: the first says the
    product exists but nobody sells it any more, which is information about the *ad*."""
    MATCHED = "MATCHED", "Matched"
    AMBIGUOUS = "AMBIGUOUS", "Ambiguous"
    NO_MARKET = "NO_MARKET", "No market (too few shops)"
    NO_MATCH = "NO_MATCH", "No match"
    DECLINED = "DECLINED", "Declined"
    ERROR = "ERROR", "Error"


class RefProduct(models.Model):
    """One catalogue product at one provider, as last seen."""
    provider = models.CharField(max_length=32)
    product_id = models.CharField(max_length=64)
    slug = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=120, blank=True, default="")
    category_id = models.IntegerField(null=True, blank=True)
    #: Manufacturer part number. Kept because product-id stability across re-pairing is
    #: unmeasured (ZBOZI_API.md §9.2) and this is the only other key either site exposes.
    product_no = models.CharField(max_length=120, blank=True, default="")

    #: Whole CZK. Providers convert from hundredths at their own edge, exactly once.
    min_czk = models.IntegerField(null=True, blank=True)
    #: The headline. Not `min` — mis-pairing poisons the bottom of the range, not the middle.
    median_czk = models.IntegerField(null=True, blank=True)
    max_czk = models.IntegerField(null=True, blank=True)

    shop_count = models.PositiveIntegerField(default=0)
    availability = models.CharField(max_length=32, blank=True, default="")
    release_date = models.DateField(null=True, blank=True)
    url = models.CharField(max_length=500, blank=True, default="")

    fetched_at = models.DateTimeField(default=timezone.now)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "product_id"],
                                    name="refproduct_unique_provider_product"),
        ]
        indexes = [models.Index(fields=["provider", "slug"])]
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.provider}:{self.product_id})"

    @property
    def has_market(self) -> bool:
        """Two merchants is the floor for calling a number a price rather than an offer."""
        return self.shop_count >= 2

    def is_fresh(self, ttl: dt.timedelta) -> bool:
        return timezone.now() - self.fetched_at < ttl


class RefPricePoint(models.Model):
    """One day's min/median/max for one product. Append-only in intent; the newest point
    is today's and moves during the day, so writes are `update_or_create`."""
    product = models.ForeignKey(RefProduct, on_delete=models.CASCADE,
                                related_name="price_points")
    date = models.DateField()
    min_czk = models.IntegerField(null=True, blank=True)
    median_czk = models.IntegerField(null=True, blank=True)
    max_czk = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "date"],
                                    name="refpricepoint_unique_product_date"),
        ]
        ordering = ("date",)

    def __str__(self) -> str:
        return f"{self.product_id}@{self.date}: {self.median_czk}"


class RefProductLink(models.Model):
    """This ad, matched to that product — and whether a person has vouched for it."""
    ad = models.ForeignKey("bazos.Ad", on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="reference_links")
    #: Snapshot, so "what was this matched to" still answers after the ad is deleted —
    #: the same trick `QueryChange.query_label` uses, and what keeps confirmations usable
    #: as training data once the listing is long gone.
    ad_title = models.CharField(max_length=255, blank=True, default="")

    provider = models.CharField(max_length=32)
    #: Null is meaningful: a human rejection ("none of these match") is a negative label
    #: worth keeping, not an absent row.
    product = models.ForeignKey(RefProduct, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="links")

    confidence = models.FloatField(default=0.0)
    method = models.CharField(max_length=16, choices=MatchMethod.choices,
                              default=MatchMethod.RULE)
    phrase_used = models.CharField(max_length=255, blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    confirmed_by_human = models.BooleanField(default=False)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ad", "provider"],
                                    name="refproductlink_unique_ad_provider"),
        ]
        indexes = [models.Index(fields=["confirmed_by_human", "-created"])]
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"{self.ad_title} -> {self.product or 'no match'}"


class RefLookup(models.Model):
    """One attempt. Written on success and failure alike, so a gap in the results is
    always attributable to something."""
    ad = models.ForeignKey("bazos.Ad", on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="reference_lookups")
    provider = models.CharField(max_length=32)
    phrase_used = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=LookupStatus.choices)
    detail = models.TextField(blank=True, default="")

    http_requests = models.PositiveIntegerField(default=0)
    llm_calls = models.PositiveIntegerField(default=0)
    llm_tokens_in = models.PositiveIntegerField(default=0)
    llm_tokens_out = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    duration_ms = models.PositiveIntegerField(default=0)

    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"{self.phrase_used or '?'} -> {self.status}"
