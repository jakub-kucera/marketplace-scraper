import json
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.db.models import Count, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.http import urlencode
from django_db_logger.admin import StatusLogAdmin
from django_db_logger.models import StatusLog
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action as unfold_action
from unfold.widgets import UnfoldAdminCheckboxSelectMultipleWidget

from bazos.filters import RULE_REGISTRY
from bazos.geo import normalize_postal_code
from bazos.models import AdPriceScore, PostalCode, Query, QueryChange, Ad, AdDelivery, PriceChange, Section, Category, EmailPublisher, PhonePublisher, QueryRun


class CategoryInline(TabularInline):
    model = Category
    extra = 0
    readonly_fields = [
        "name",
        "url",
        "bazos_id",
    ]


class HasFullDescriptionFilter(admin.SimpleListFilter):
    title = 'has full description'
    parameter_name = 'has_full_description'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Has description'),
            ('no', 'No description'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(full_description__isnull=True).exclude(full_description='')
        if self.value() == 'no':
            return queryset.filter(full_description__isnull=True) | queryset.filter(full_description='')


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = (
        "name",
        "section",
        "bazos_id",
    )
    list_filter = ("section",)
    search_fields = ("name", "section__name")


@admin.register(Section)
class SectionAdmin(ModelAdmin):
    list_display = (
        "name",
        "url",
        "bazos_id",
    )
    readonly_fields = [
        "name",
        "url",
        "bazos_id",
    ]
    search_fields = ("name",)
    inlines = (CategoryInline,)


def ad_changelist_url(ad_fk_name: str, pk) -> str:
    """URL of the Ad changelist filtered to one related row.

    `ad_fk_name` is the FK on `Ad` — "email_publisher", "phone_publisher".
    A link rather than an inline everywhere it's used: inlines render every row on the
    page, and the biggest seller in the 2024-03 export has 369 ads (a broad query, far
    more). The changelist is paginated and inherits `AdAdmin.ordering` (newest first).
    """
    return f"{reverse('admin:bazos_ad_changelist')}?{urlencode({f'{ad_fk_name}__id__exact': pk})}"


def ads_browse_link(ad_fk_name: str, obj):
    """Readonly-field renderer: 'Browse N ads — newest first', or a dash."""
    if obj.pk is None:
        return "—"
    count = obj.ads.count()
    if not count:
        return "— (no ads)"
    return format_html(
        '<a href="{}">Browse {} ad{}</a> — newest first',
        ad_changelist_url(ad_fk_name, obj.pk),
        count,
        "" if count == 1 else "s",
    )


#: Longest rendering of a single old/new value before it is elided. `extra_params` and
#: the keyword lists are the ones that get long, and a changelist row has to stay one line.
CHANGE_VALUE_MAX_CHARS = 80


def format_change_value(value) -> str:
    """One config value as compact JSON — `null`, `["dell", "hp"]`, `"macbook"`.

    JSON rather than `repr` so an empty list reads as `[]` instead of `[]`-vs-`()`
    ambiguity, and so Czech characters in a blocklist survive as themselves.
    """
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:  # pragma: no cover - JSONField cannot hold non-serialisable values
        rendered = repr(value)
    if len(rendered) > CHANGE_VALUE_MAX_CHARS:
        return rendered[: CHANGE_VALUE_MAX_CHARS - 1] + "\u2026"
    return rendered


def render_change_diff(obj):
    """A `QueryChange` as `field: old -> new` lines.

    Styled with Django's own admin CSS variables rather than literal colours, so it stays
    legible in the dark theme — the struck-through old value and bold new one carry the
    meaning, and neither depends on hue.
    """
    if not obj.changes:
        return "\u2014"
    return format_html(
        '<ul style="margin:0;padding:0;list-style:none">{}</ul>',
        format_html_join(
            "",
            '<li><code>{}</code>: '
            '<span style="color:var(--body-quiet-color)"><s>{}</s></span> '
            '&rarr; <strong>{}</strong></li>',
            (
                (
                    name,
                    format_change_value(obj.changes[name].get("old")),
                    format_change_value(obj.changes[name].get("new")),
                )
                for name in obj.changed_fields
            ),
        ),
    )


class QueryChangeInline(TabularInline):
    """Recent config edits, on the Query change form."""

    model = QueryChange
    fk_name = "query"
    extra = 0
    can_delete = False
    fields = ("created", "diff")
    readonly_fields = ("created", "diff")
    ordering = ("-created",)
    verbose_name_plural = "Recent config changes"

    #: A change form renders every inline row — there is no pagination — so the history is
    #: capped here and the full list lives one click away on the changelist. See the
    #: `ad_changelist_url` docstring for the same trade-off made the other way.
    MAX_ROWS = 15

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        recent = qs.order_by("-created").values_list("pk", flat=True)[: self.MAX_ROWS]
        return qs.filter(pk__in=list(recent))

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Change")
    def diff(self, obj):
        return render_change_diff(obj)


def query_change_changelist_url(query_pk) -> str:
    return (
        f"{reverse('admin:bazos_querychange_changelist')}"
        f"?{urlencode({'query__id__exact': query_pk})}"
    )


class QueryAdminForm(forms.ModelForm):
    filter_rule_names = forms.MultipleChoiceField(
        choices=[(name, name.replace("_", " ").title()) for name in RULE_REGISTRY],
        # Unfold styles the widgets it maps from model fields, but this one is declared by
        # hand, so it has to name the themed widget itself. It subclasses Django's
        # CheckboxSelectMultiple, so nothing that checks the widget type has to change.
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
        required=False,
        help_text="Filter rules applied to this query. None checked = all rules (default).",
    )

    class Meta:
        model = Query
        fields = "__all__"

    def clean_extra_params(self):
        # `{}` is one of Django's JSONField "empty values" (like `[]` for
        # filter_blocklist/filter_required below), so an emptied widget round-trips as
        # None rather than `{}` — which would violate the NOT NULL column.
        return self.cleaned_data.get("extra_params") or {}

    def clean_filter_blocklist(self):
        return self.cleaned_data.get("filter_blocklist") or []

    def clean_filter_required(self):
        return self.cleaned_data.get("filter_required") or []

    def clean_filter_location_center(self):
        raw = (self.cleaned_data.get("filter_location_center") or "").strip()
        if not raw:
            return ""
        normalized = normalize_postal_code(raw)
        if normalized is None:
            raise forms.ValidationError("Not a postal code — expected five digits, e.g. 110 00.")
        # Stored normalised so the filter never has to guess which of "110 00"/"11000" a
        # given row used, and so the PostalCode cache keys line up on sight in the admin.
        return normalized

    def clean(self):
        cleaned = super().clean()
        center = cleaned.get("filter_location_center")
        radius = cleaned.get("filter_location_radius")
        # Half a distance filter is not a weaker filter, it is no filter — and it looks
        # exactly like a configured one on the change form. Refuse it rather than let a
        # query silently notify everything the user thought it had narrowed.
        if bool(center) != (radius is not None):
            raise forms.ValidationError(
                "Set both filter_location_center and filter_location_radius, or neither — "
                "one alone does nothing."
            )
        return cleaned


@admin.register(Query)
class QueryAdmin(ModelAdmin):
    form = QueryAdminForm
    list_display = (
        "query_name",
        "text",
        "category",
        "section",
        "marketplace",
        "enabled",
        "load_full_description",
        "randomly_generated",
        "sender",
        "ad_count",
        "last_run",
    )
    list_filter = (
        "enabled",
        "load_full_description",
        "randomly_generated",
        ("marketplace", ChoicesDropdownFilter),
        ("section", RelatedDropdownFilter),
        ("category", RelatedDropdownFilter),
    )
    # str(Query) reads text/category/section, so without this the changelist does a
    # section+category lookup per row.
    list_select_related = ("category", "section", "sender")
    actions = ["enable_queries", "disable_queries"]
    actions_list = ["force_run_now"]
    autocomplete_fields = ["category", "section", "sender"]
    inlines = (QueryChangeInline,)
    readonly_fields = ("config_history",)
    ordering = ("-enabled", "marketplace", "text")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Correlated subqueries, deliberately NOT annotate(Max('runs__...'),
        # Count('deliveries')). Two aggregates over two different reverse FKs make Django
        # join BOTH tables into one query, so Postgres materialises a deliveries x runs
        # product per Query row — a query with 5k deliveries and 2k runs is 10M
        # intermediate rows, and the `distinct=True` that was needed to un-inflate the
        # count then has to de-duplicate all of them. That is what made this changelist
        # slow, and it degrades as history accumulates (QueryRun especially: a
        # blacklisted query now writes one row per retry attempt).
        #
        # Each subquery below reads exactly one table through its own query_id FK index,
        # so the cost is per-table and independent of the other relation's size.
        last_run_subquery = (
            QueryRun.objects
            .filter(query=OuterRef('pk'))
            .order_by()  # clear any default ordering, or it leaks into the GROUP BY
            .values('query')
            .annotate(last=Coalesce(Max('run_end'), Max('run_start')))
            .values('last')[:1]
        )
        ad_count_subquery = (
            AdDelivery.objects
            .filter(query=OuterRef('pk'))
            .order_by()
            .values('query')
            .annotate(n=Count('pk'))
            .values('n')[:1]
        )
        return qs.annotate(
            last_run=Subquery(last_run_subquery),
            # An aggregate subquery over zero rows yields no row at all, i.e. NULL — so a
            # query that has never found an ad needs the Coalesce to read as 0, not blank.
            ad_count=Coalesce(Subquery(ad_count_subquery), 0, output_field=IntegerField()),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        center = obj.filter_location_center
        if center and not PostalCode.objects.filter(code=center).exists():
            # Saved anyway, and the next scrape pass resolves it
            # (`ScrapeRunner._ensure_filter_centres`) — but say so, because until then the
            # rule PASSes everything, which from the change form is indistinguishable from
            # a working filter. The command is the way to close the window immediately.
            self.message_user(
                request,
                f"Postal code {center} is not geocoded yet, so the distance filter on this "
                f"query does nothing until the next scrape pass resolves it. To do it now: "
                f"python manage.py geocode_postal_codes --codes {center}",
                messages.WARNING,
            )

    @admin.display(description="Query", ordering="pk")
    def query_name(self, obj):
        """First column, so it is the clickable link into the change form — the pk it
        replaced identified nothing you could read.

        Ordered by pk because str(Query) has no single backing field (it falls back
        text -> category -> section); sorting by pk at least keeps the column sortable,
        in the creation order the pk column used to give.
        """
        return str(obj)

    def last_run(self, obj):
        return getattr(obj, 'last_run', None)

    last_run.admin_order_field = models.F('last_run').desc(nulls_last=True)  # type: ignore[attr-defined]
    last_run.short_description = 'Last run'  # type: ignore[attr-defined]

    @admin.display(description="Ads", ordering="ad_count")
    def ad_count(self, obj):
        return obj.ad_count

    @admin.display(description="Config history")
    def config_history(self, obj):
        """Link to this query's full edit history — the inline below is capped."""
        if obj.pk is None:
            return "\u2014 (saved queries only)"
        count = obj.config_history.count()
        if not count:
            return "\u2014 (no changes recorded yet)"
        return format_html(
            '<a href="{}">Browse {} change{}</a> \u2014 newest first',
            query_change_changelist_url(obj.pk),
            count,
            "" if count == 1 else "s",
        )

    @admin.action(description="Enable selected queries")
    def enable_queries(self, request, queryset):
        updated = queryset.update(enabled=True)
        self.message_user(request, f"{updated} query(ies) enabled successfully.")

    @admin.action(description="Disable selected queries")
    def disable_queries(self, request, queryset):
        updated = queryset.update(enabled=False)
        self.message_user(request, f"{updated} query(ies) disabled successfully.")

    @unfold_action(description="Force Run Now", icon="bolt", url_path="force-run")
    def force_run_now(self, request):
        """Touch the sentinel flag file so the runner wakes from sleep immediately.

        `actions_list` puts this in the changelist header and registers the URL, which is
        what replaced a `get_urls` override plus a `change_list.html` that hooked Django's
        `object-tools-items` block to hand-draw the button. `url_path` keeps the address
        it has always had (`force-run/`); only the URL *name* changed, to the
        `bazos_query_force_run_now` that unfold derives from the method.
        """
        flag_path = Path(settings.FORCE_RUN_FLAG_PATH)
        flag_path.touch()
        self.message_user(
            request,
            "⚡ Force-run flag set — the runner will start a new cycle within ~5 seconds.",
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))


@admin.register(QueryRun)
class QueryRunAdmin(ModelAdmin):
    list_display = (
        "query",
        "run_start",
        "run_end",
        "duration",
        "new_ads_count",
        "exit_ip",
        "success",
        "error",
    )
    # query__marketplace as its own filter even though str(Query) now carries the
    # marketplace: reading it off every row is not the same as slicing the list by it.
    list_filter = (
        ("query", RelatedDropdownFilter),
        ("query__marketplace", ChoicesDropdownFilter),
        "success",
        ("run_start", RangeDateTimeFilter),
    )
    list_filter_submit = True
    list_select_related = ("query", "query__category", "query__section")
    # exit_ip only. `error` is an unindexed TextField holding stack traces, and admin
    # search is an unanchored icontains — on a table that now grows by one row per retry
    # attempt that is a seq scan over every trace on every keystroke-submitted search.
    search_fields = ("exit_ip",)

    def get_queryset(self, request):
        # Two columns of the same row, so unlike QueryAdmin's aggregates this adds no
        # join and cannot multiply rows.
        return super().get_queryset(request).annotate(
            duration=models.F("run_end") - models.F("run_start"),
        )

    def duration(self, obj):
        delta = getattr(obj, "duration", None)
        if delta is None:
            # A run with no run_end has no duration rather than a zero one — it either
            # crashed or is still in flight. None renders as the admin's empty value.
            return None
        return f"{delta.total_seconds():.1f} s"

    # Descending is the direction the column is for ("which runs are slow"), and nulls
    # belong at that end's bottom; Django reverses an OrderBy by flipping the null
    # placement too, so the ascending click reads shortest-first with the unmeasured
    # runs leading. Same shape as QueryAdmin.last_run.
    duration.admin_order_field = models.F("duration").desc(nulls_last=True)  # type: ignore[attr-defined]
    duration.short_description = "Duration"  # type: ignore[attr-defined]


@admin.register(QueryChange)
class QueryChangeAdmin(ModelAdmin):
    """Config edit log, across every query. Read-only — the rows are an audit trail."""

    list_display = ("created", "query_display", "fields_changed", "diff")
    list_filter = (
        ("query", RelatedDropdownFilter),
        ("query__marketplace", ChoicesDropdownFilter),
        ("created", RangeDateTimeFilter),
    )
    list_filter_submit = True
    list_select_related = ("query", "query__category", "query__section")
    # str(Query) is not a column, so the label snapshot is the only searchable text —
    # and it is also the only thing left once the query itself is deleted.
    search_fields = ("query_label",)
    date_hierarchy = "created"
    ordering = ("-created",)
    readonly_fields = ("created", "query", "query_label", "changes", "diff")
    fields = ("created", "query", "query_label", "diff", "changes")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Query", ordering="query")
    def query_display(self, obj):
        """The live query, linked; the label snapshot once the query is gone."""
        if obj.query is None:
            return format_html("{} <em>(deleted)</em>", obj.query_label or "\u2014")
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:bazos_query_change", args=[obj.query_id]),
            str(obj.query),
        )

    @admin.display(description="Fields")
    def fields_changed(self, obj):
        return ", ".join(obj.changed_fields) or "\u2014"

    @admin.display(description="Change")
    def diff(self, obj):
        return render_change_diff(obj)


class PriceChangeInline(TabularInline):
    model = PriceChange
    extra = 0
    readonly_fields = ("old_price", "new_price", "created")
    can_delete = False


class AdPriceScoreInline(TabularInline):
    """What the price model thought, on the ad's own page.

    P23 step 4's point: a rule that only returns APPROVE/REJECT/PASS throws away the
    interesting number. This is where the number becomes visible.
    """
    model = AdPriceScore
    extra = 0
    fields = ("model_name", "model_version", "predicted", "discount_pct", "z_score",
              "seller_prior_ads", "features", "declined_reason", "created")
    readonly_fields = fields
    can_delete = False


class AdDeliveryInline(TabularInline):
    model = AdDelivery
    extra = 0
    fields = ("query", "status", "filter_reason", "sent_at", "send_attempts", "created")
    readonly_fields = ("query", "status", "filter_reason", "sent_at", "send_attempts", "created")
    can_delete = False


@admin.register(Ad)
class AdAdmin(ModelAdmin):
    list_display = (
        "name",
        "marketplace",
        "external_id",
        "topped",
        "price_raw",
        "publish_date",
        "url",
        "query_count",
        "price_discount",
        "price_z",
        "created",
    )
    # Plain "-publish_date" would put every Vinted ad (publish_date is always null —
    # see VINTED_SCRAPER.md §2.2) above the newest Bazos ads: Postgres's DESC
    # defaults to NULLS FIRST. nulls_last keeps "newest first" meaning what it says.
    ordering = (models.F("publish_date").desc(nulls_last=True),)  # type: ignore[assignment]  # django-stubs types ordering as Sequence[str]; F().desc() is valid at runtime
    # A price range and a date window are the two questions this changelist could not
    # answer before — both are field-backed, so they cost no custom queryset code. The
    # query filter becomes a dropdown because the list of queries is unbounded and grows.
    list_filter = (
        "marketplace",
        ("deliveries__query", RelatedDropdownFilter),
        ("price", RangeNumericFilter),
        ("price_type", ChoicesDropdownFilter),
        ("created", RangeDateTimeFilter),
        HasFullDescriptionFilter,
    )
    # Range filters collect two inputs, so they need something to submit them.
    list_filter_submit = True
    search_fields = ("name", "external_id", "url")
    readonly_fields = (
        "external_id", "marketplace",
        "seller_ad_counts",
    )
    inlines = (AdDeliveryInline, PriceChangeInline, AdPriceScoreInline)
    # query_count's Count(...) annotation forces a GROUP BY over the whole ad × addelivery
    # join. Without this, the changelist paginator's separate "N results" count query runs
    # that GROUP BY as a subquery aggregate over the FULL table on every page load — cheap
    # today, not at scale. This only drops the extra full-table count; the displayed page's
    # own query (bounded by page size) still pays the join, same as QueryAdmin.ad_count.
    show_full_result_count = False

    def get_queryset(self, request):
        # distinct=True: an Ad matching several queries has one delivery per query, and
        # without it the join would multiply rows the same way QueryAdmin.ad_count's
        # comment describes for the mirror-image annotation.
        #
        # The two score columns are correlated subqueries, NOT a second and third
        # aggregate: adding Max('price_scores__...') alongside the Count above would join
        # deliveries x price_scores and materialise the product per row, which is exactly
        # what QueryAdmin.get_queryset was rewritten to avoid.
        scores = (
            AdPriceScore.objects
            .filter(ad=OuterRef("pk"), predicted__isnull=False)
            .order_by("-created")
        )
        return super().get_queryset(request).annotate(
            query_count=Count('deliveries', distinct=True),
            price_discount=Subquery(scores.values("discount_pct")[:1]),
            price_z=Subquery(scores.values("z_score")[:1]),
        )

    @admin.display(description="Queries", ordering="query_count")
    def query_count(self, obj):
        return obj.query_count

    # nulls_last for the same reason as `ordering` above and QueryAdmin.last_run: most ads
    # are never scored (no registered model claims them), and Postgres DESC is NULLS FIRST,
    # so "biggest discount first" would open on a page of blanks.
    @admin.display(description="Disc. %", ordering=models.F("price_discount").desc(nulls_last=True))
    def price_discount(self, obj):
        return "—" if obj.price_discount is None else f"{obj.price_discount:+.0f}%"

    @admin.display(description="z", ordering=models.F("price_z").asc(nulls_last=True))
    def price_z(self, obj):
        return "—" if obj.price_z is None else f"{obj.price_z:+.2f}"

    @admin.display(description="Seller history")
    def seller_ad_counts(self, obj):
        """Three counts plus links to each identity — see `SellerAdCounts` for why three.

        Detail page only, deliberately: this walks the identity graph (a handful of
        queries), which is fine once per page but not once per changelist row.
        """
        if obj.pk is None:
            return "—"
        counts = obj.seller_ad_counts()
        if not counts.combined:
            return "— (no publisher on this ad)"

        links = []
        for publisher, label in ((obj.email_publisher, "email"), (obj.phone_publisher, "phone")):
            if publisher is None:
                links.append(format_html("<li>{}: —</li>", label))
                continue
            url = reverse(f"admin:bazos_{publisher._meta.model_name}_change", args=[publisher.pk])
            count = counts.by_email if label == "email" else counts.by_phone
            links.append(
                format_html(
                    '<li>{}: <a href="{}">{}</a> — {} ad{}</li>',
                    label, url, publisher.bazos_id, count, "" if count == 1 else "s",
                )
            )
        note = (
            " — this seller posts under more than one email/phone pairing"
            if counts.has_split_identity
            else ""
        )
        return format_html(
            "<b>{} ad{} seen from this seller</b>{}<ul style=\"margin:0;padding-left:1.2em\">{}</ul>"
            "<small>Counts ads in this database (what our queries scraped), not the seller's "
            "Bazos total.</small>",
            counts.combined,
            "" if counts.combined == 1 else "s",
            note,
            mark_safe("".join(links)),
        )


@admin.register(AdDelivery)
class AdDeliveryAdmin(ModelAdmin):
    """The pipeline view: one row per (ad, query), where `Ad.status` used to live."""

    list_display = ("ad", "query", "status", "filter_reason", "sent_at", "send_attempts", "created")
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("query", RelatedDropdownFilter),
        ("created", RangeDateTimeFilter),
    )
    list_filter_submit = True
    search_fields = ("ad__name", "ad__external_id")
    ordering = ("-created",)
    readonly_fields = ("ad", "query", "status", "filter_reason", "sent_at", "send_attempts")


PARTNER_DISPLAY_LIMIT = 50


class PublisherAdminBase(ModelAdmin):
    """Shared behaviour for the `EmailPublisher` / `PhonePublisher` admins.

    Both models are the same shape — an opaque Bazos id, an unpopulated contact field, and
    a `blocked` flag — and differ only in which `Ad` FK points at them. Subclasses declare
    that difference via `own_ad_field` / `partner_ad_field` / `partner_model`.

    The partner list is the point: a seller's identity on Bazos is a *pair* of ids, and the
    same person routinely posts under several. One email pairing with four phones over four
    months is a real, observed pattern (a recruiter posting job ads), and it's invisible
    until you look at the pairing. See docs/backlog/BACKLOG_IDEAS.md — this is the cheap
    precursor to reseller detection.
    """

    #: Name of the FK on `Ad` pointing at *this* admin's model.
    own_ad_field: str = ""
    #: Name of the FK on `Ad` pointing at the *other* publisher type.
    partner_ad_field: str = ""
    #: The other publisher model, used to build admin links.
    partner_model: type[models.Model] | None = None

    list_filter = ("blocked",)
    actions = ["block_publishers", "unblock_publishers"]

    def get_queryset(self, request):
        # Annotated so the changelist column costs one query rather than one per row.
        return super().get_queryset(request).annotate(
            partner_count=Count(f"ads__{self.partner_ad_field}", distinct=True),
            ad_count=Count("ads", distinct=True),
        )

    @admin.display(description="Ads", ordering="ad_count")
    def ad_count(self, obj):
        if not obj.ad_count:
            return obj.ad_count
        return format_html('<a href="{}">{}</a>', self.ads_changelist_url(obj), obj.ad_count)

    @admin.display(description="Partner ids", ordering="partner_count")
    def partner_count(self, obj):
        return obj.partner_count

    @admin.display(description="Seen together with")
    def partners(self, obj):
        if obj.pk is None:
            return "—"
        # Query lives on the model (PublisherMixin) so the sender and any future
        # reseller-detection code share one definition of "seen together with".
        rows = list(obj.partner_rows()[: PARTNER_DISPLAY_LIMIT + 1])
        if not rows:
            return "— (no ads with a publisher of the other type)"

        assert self.partner_model is not None
        url_name = f"admin:bazos_{self.partner_model._meta.model_name}_change"
        overflow = len(rows) > PARTNER_DISPLAY_LIMIT
        items = []
        for row in rows[:PARTNER_DISPLAY_LIMIT]:
            pk = row[self.partner_ad_field]
            shared = row["shared_ads"]
            items.append(
                format_html(
                    '<li><a href="{}">{}</a> — {} ad{}{}</li>',
                    reverse(url_name, args=[pk]),
                    row[f"{self.partner_ad_field}__bazos_id"],
                    shared,
                    "" if shared == 1 else "s",
                    " · blocked" if row[f"{self.partner_ad_field}__blocked"] else "",
                )
            )
        suffix = format_html("<li>… more than {} — see the ad list</li>", PARTNER_DISPLAY_LIMIT) if overflow else ""
        return format_html('<ul style="margin:0;padding-left:1.2em">{}{}</ul>', mark_safe("".join(items)), suffix)

    def ads_changelist_url(self, obj) -> str:
        return ad_changelist_url(self.own_ad_field, obj.pk)

    @admin.display(description="All ads by this publisher")
    def ads_link(self, obj):
        return ads_browse_link(self.own_ad_field, obj)

    @admin.action(description="Block selected publishers")
    def block_publishers(self, request, queryset):
        updated = queryset.update(blocked=True)
        self.message_user(request, f"{updated} publisher(s) blocked successfully.")

    @admin.action(description="Unblock selected publishers")
    def unblock_publishers(self, request, queryset):
        updated = queryset.update(blocked=False)
        self.message_user(request, f"{updated} publisher(s) unblocked successfully.")


@admin.register(EmailPublisher)
class EmailPublisherAdmin(PublisherAdminBase):
    own_ad_field = "email_publisher"
    partner_ad_field = "phone_publisher"
    partner_model = PhonePublisher

    list_display = ("bazos_id", "email", "blocked", "ad_count", "partner_count")
    readonly_fields = ("ads_link", "partners")


@admin.register(PhonePublisher)
class PhonePublisherAdmin(PublisherAdminBase):
    own_ad_field = "phone_publisher"
    partner_ad_field = "email_publisher"
    partner_model = EmailPublisher

    list_display = ("bazos_id", "phone", "blocked", "ad_count", "partner_count")
    readonly_fields = ("ads_link", "partners")


@admin.register(PostalCode)
class PostalCodeAdmin(ModelAdmin):
    """The geocode cache. Read-mostly — rows are written by the scraper and by
    `manage.py geocode_postal_codes`; editing one here is the escape hatch for a code
    zip.php places badly.
    """
    list_display = ("code", "city", "latitude", "longitude", "created")
    search_fields = ("code", "city")
    ordering = ("code",)


# django-db-logger registers StatusLog with a stock ModelAdmin. Under Unfold that still
# renders — the chrome comes from the templates — but its filters and widgets stay
# unthemed, and this is not an incidental third-party table: the app loggers write here
# (see Observability in CLAUDE.md) and it sits in the sidebar. Re-registering on the
# themed base is the documented way to adopt a third-party admin.
admin.site.unregister(StatusLog)


@admin.register(StatusLog)
class ThemedStatusLogAdmin(StatusLogAdmin, ModelAdmin):
    list_filter = (
        ("level", ChoicesDropdownFilter),
        ("create_datetime", RangeDateTimeFilter),
    )
    list_filter_submit = True
    search_fields = ("msg", "logger_name")
