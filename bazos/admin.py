from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.db.models import Count, Max
from django.db.models.functions import Coalesce
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import urlencode

from bazos.filters import RULE_REGISTRY
from bazos.models import Query, Ad, PriceChange, Section, Category, EmailPublisher, PhonePublisher, QueryRun


class CategoryInline(admin.TabularInline):
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
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "section",
        "bazos_id",
    )
    list_filter = ("section",)
    search_fields = ("name", "section__name")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
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


class QueryAdminForm(forms.ModelForm):
    filter_rule_names = forms.MultipleChoiceField(
        choices=[(name, name.replace("_", " ").title()) for name in RULE_REGISTRY],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Filter rules applied to this query. None checked = all rules (default).",
    )

    class Meta:
        model = Query
        fields = "__all__"


@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    form = QueryAdminForm
    list_display = (
        "pk",
        "text",
        "category",
        "section",
        "marketplace",
        "enabled",
        "randomly_generated",
        "sender",
        "last_run",
    )
    list_filter = ("enabled", "randomly_generated", "marketplace", "section", "category")
    actions = ["enable_queries", "disable_queries"]
    autocomplete_fields = ["category", "section", "sender"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # annotate last_run as the latest run_end if present, otherwise run_start
        return qs.annotate(last_run=Coalesce(Max('runs__run_end'), Max('runs__run_start')))

    def last_run(self, obj):
        return getattr(obj, 'last_run', None)

    last_run.admin_order_field = 'last_run'  # type: ignore[attr-defined]
    last_run.short_description = 'Last run'  # type: ignore[attr-defined]

    @admin.action(description="Enable selected queries")
    def enable_queries(self, request, queryset):
        updated = queryset.update(enabled=True)
        self.message_user(request, f"{updated} query(ies) enabled successfully.")

    @admin.action(description="Disable selected queries")
    def disable_queries(self, request, queryset):
        updated = queryset.update(enabled=False)
        self.message_user(request, f"{updated} query(ies) disabled successfully.")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "force-run/",
                self.admin_site.admin_view(self.force_run_now),
                name="bazos_query_force_run",
            )
        ]
        return custom + urls

    def force_run_now(self, request):
        """Touch the sentinel flag file so the runner wakes from sleep immediately."""
        flag_path = Path(settings.FORCE_RUN_FLAG_PATH)
        flag_path.touch()
        self.message_user(
            request,
            "⚡ Force-run flag set — the runner will start a new cycle within ~5 seconds.",
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["force_run_url"] = "force-run/"
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(QueryRun)
class QueryRunAdmin(admin.ModelAdmin):
    list_display = (
        "query",
        "run_start",
        "run_end",
        "new_ads_count",
        "success",
        "error",
    )
    list_filter = ("query", "success")


class PriceChangeInline(admin.TabularInline):
    model = PriceChange
    extra = 0
    readonly_fields = ("old_price", "new_price", "created")
    can_delete = False


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "marketplace",
        "external_id",
        "status",
        "topped",
        "price_raw",
        "publish_date",
        "url",
        "query",
        "created",
    )
    ordering = ("-publish_date",)
    list_filter = ("status", "marketplace", "query", HasFullDescriptionFilter)
    search_fields = ("name", "external_id", "url")
    readonly_fields = (
        "external_id", "marketplace", "status", "filter_reason", "sent_at", "send_attempts",
        "seller_ad_counts",
    )
    inlines = (PriceChangeInline,)

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
            format_html("".join(links)),
        )


PARTNER_DISPLAY_LIMIT = 50


class PublisherAdminBase(admin.ModelAdmin):
    """Shared behaviour for the `EmailPublisher` / `PhonePublisher` admins.

    Both models are the same shape — an opaque Bazos id, an unpopulated contact field, and
    a `blocked` flag — and differ only in which `Ad` FK points at them. Subclasses declare
    that difference via `own_ad_field` / `partner_ad_field` / `partner_model`.

    The partner list is the point: a seller's identity on Bazos is a *pair* of ids, and the
    same person routinely posts under several. One email pairing with four phones over four
    months is a real, observed pattern (a recruiter posting job ads), and it's invisible
    until you look at the pairing. See docs/refactor/BACKLOG_IDEAS.md — this is the cheap
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
        return format_html('<ul style="margin:0;padding-left:1.2em">{}{}</ul>', format_html("".join(items)), suffix)

    def ads_changelist_url(self, obj) -> str:
        """URL of the Ad changelist filtered to this publisher.

        A link rather than an inline on purpose: inlines render every row on the page, and
        the biggest real seller in the 2024-03 export has 369 ads. The changelist is
        paginated, searchable and sortable, and inherits `AdAdmin.ordering` (newest first).
        """
        query = urlencode({f"{self.own_ad_field}__id__exact": obj.pk})
        return f"{reverse('admin:bazos_ad_changelist')}?{query}"

    @admin.display(description="All ads by this publisher")
    def ads_link(self, obj):
        if obj.pk is None:
            return "—"
        count = obj.ads.count()
        if not count:
            return "— (no ads)"
        return format_html(
            '<a href="{}">Browse {} ad{}</a> — newest first',
            self.ads_changelist_url(obj),
            count,
            "" if count == 1 else "s",
        )

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
