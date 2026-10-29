"""The admin surface — which is this feature's actual UI.

Explicit invocation is the posture, and the admin is where it happens: CLAUDE.md calls
the admin "a real operational surface, not scaffolding", and the force-run button is the
precedent for an operator-triggered action.

**The wiring onto `AdAdmin` happens here, not in `bazos/admin.py`.** The dependency has
to point inward — deleting this app must break nothing in the pipeline — so this module
appends its inline and action to `AdAdmin` rather than `bazos` importing `refprice`.
Admin modules are loaded in `INSTALLED_APPS` order, and `refprice` sits after `bazos`.
"""
import logging

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from unfold.decorators import action as unfold_action
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from marketplace.admin import AdAdmin
from marketplace.models import Ad
from django_q.tasks import async_task

from refprice.jobs import LOOKUP_REFERENCE_PRICE
from refprice.models import LookupStatus, RefLookup, RefPricePoint, RefProduct, RefProductLink

logger = logging.getLogger(__name__)

STATUS_COLOURS = {
    LookupStatus.MATCHED.value: "#1a7f37",
    LookupStatus.AMBIGUOUS.value: "#8a5a06",
    LookupStatus.NO_MARKET.value: "#8a5a06",
    LookupStatus.NO_MATCH.value: "#69737d",
    LookupStatus.DECLINED.value: "#69737d",
    LookupStatus.ERROR.value: "#b42318",
}


def _money(value: int | None) -> str:
    return f"{value:,} Kč".replace(",", " ") if value else "—"


class RefPricePointInline(TabularInline):
    model = RefPricePoint
    extra = 0
    can_delete = False
    fields = ("date", "min_czk", "median_czk", "max_czk")
    readonly_fields = fields
    #: A change form renders every inline row with no pagination, and a product carries
    #: ~100 points. Same cap as QueryChangeInline, for the same reason.
    max_num = 30
    ordering = ("-date",)

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(RefProduct)
class RefProductAdmin(ModelAdmin):
    list_display = ("name", "brand", "provider", "median_display", "range_display",
                    "shop_count", "availability", "product_no", "fetched_at")
    list_filter = ("provider", "availability", "brand")
    search_fields = ("name", "slug", "product_no", "product_id")
    ordering = ("name",)
    inlines = (RefPricePointInline,)

    @admin.display(description="Median", ordering="median_czk")
    def median_display(self, obj: RefProduct) -> str:
        return _money(obj.median_czk)

    @admin.display(description="Range")
    def range_display(self, obj: RefProduct) -> str:
        if obj.shop_count < 2:
            # One merchant is not a market; saying so on the row stops the number being
            # read as a price.
            return format_html('<span style="color:#8a5a06">thin — {} shop</span>',
                               obj.shop_count)
        return f"{_money(obj.min_czk)} – {_money(obj.max_czk)}"


@admin.register(RefProductLink)
class RefProductLinkAdmin(ModelAdmin):
    list_display = ("ad_title", "product", "confidence", "method", "confirmed_by_human",
                    "phrase_used", "created")
    #: Deliberately editable: confirming a match is the point of the whole feature, and
    #: every confirmation is one labelled row of the corpus that would justify automation.
    list_editable = ("confirmed_by_human",)
    list_filter = ("provider", "method", "confirmed_by_human")
    search_fields = ("ad_title", "phrase_used", "product__name")
    readonly_fields = ("ad", "ad_title", "phrase_used", "evidence", "created", "modified")
    ordering = ("-created",)


@admin.register(RefLookup)
class RefLookupAdmin(ModelAdmin):
    list_display = ("created", "phrase_used", "status_badge", "provider",
                    "http_requests", "llm_calls", "duration_ms")
    list_filter = ("status", "provider")
    search_fields = ("phrase_used", "detail")
    # Latent rather than live - refprice_reflookup is empty in production - but this FK
    # points at Ad, so the first row written makes this page as slow as the Ad page was.
    autocomplete_fields = ("ad",)
    date_hierarchy = "created"
    ordering = ("-created",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: RefLookup) -> str:
        return format_html('<b style="color:{}">{}</b>',
                           STATUS_COLOURS.get(obj.status, "#69737d"),
                           obj.get_status_display())

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# wiring onto the Ad admin
# ---------------------------------------------------------------------------

class ReferenceLinkInline(TabularInline):
    """What this ad was matched to, and the price behind it."""
    model = RefProductLink
    fk_name = "ad"
    extra = 0
    max_num = 4
    fields = ("product", "reference_price", "confidence", "method",
              "confirmed_by_human", "phrase_used")
    readonly_fields = ("product", "reference_price", "confidence", "method", "phrase_used")
    verbose_name_plural = "Reference prices"

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="New price (median)")
    def reference_price(self, obj: RefProductLink) -> str:
        if obj.product is None:
            return "— no match"
        if not obj.product.has_market:
            return format_html(
                '<span style="color:#8a5a06">{} · thin ({} shop)</span>',
                _money(obj.product.median_czk), obj.product.shop_count,
            )
        return format_html("{} · {} shops", _money(obj.product.median_czk),
                           obj.product.shop_count)


@admin.action(description="Look up reference price (Zboží)")
def look_up_reference_price(modeladmin, request, queryset):
    """Explicit, operator-triggered — and *queued*, not done inline.

    This used to call `lookup_reference_price` synchronously, once per selected ad, inside
    the admin request. The posture was right (explicit invocation, never on the scrape or
    filter path) and it predated the job cluster, but fifty selected ads meant fifty
    sequential HTTP calls to Zboží while the browser waited: a gateway timeout, and the
    results lost with it.

    One task per ad, not one per selection, so a failure loses one lookup and each gets its
    own row in the run log. The message says "queued", never "looked up" — the outcome lives
    on the Success/Failure rows, and claiming otherwise here would be a lie the admin tells
    every time the cluster is down.
    """
    pks = list(queryset.values_list("pk", flat=True))
    for pk in pks:
        async_task(LOOKUP_REFERENCE_PRICE, pk)

    modeladmin.message_user(
        request,
        f"Queued {len(pks)} reference lookup(s). Results appear on each ad, and in "
        f"Scheduled tasks → Successful/Failed tasks.",
        messages.INFO,
    )


@unfold_action(description="Reference price", icon="sell", url_path="reference-price")
def look_up_reference_price_detail(self, request, object_id):
    """The same lookup as the changelist action, on the ad's own page.

    Registered onto `AdAdmin.actions_detail` from here rather than declared there, the same
    seam `actions` and `inlines` already use: the dependency points inward and `bazos` must
    stay independent of what is built on it.
    """
    async_task(LOOKUP_REFERENCE_PRICE, int(object_id))
    self.message_user(
        request,
        "Queued a reference lookup. The result appears in the Reference price panel below.",
        messages.INFO,
    )
    return HttpResponseRedirect(reverse("admin:bazos_ad_change", args=[object_id]))

# Appended rather than imported by bazos: see the module docstring. mypy infers the
# original tuple's exact member types from the literal, so widening it needs the ignore.
AdAdmin.inlines = (*AdAdmin.inlines, ReferenceLinkInline)  # type: ignore[assignment]
AdAdmin.actions = (*(AdAdmin.actions or ()), look_up_reference_price)
# `actions_detail` is resolved by NAME via getattr on the admin instance, unlike
# `actions`, which accepts a callable. So the function has to be attached to the
# class first and referenced as a string - appending the bare function raises
# "attribute name must be string" at import time.
AdAdmin.look_up_reference_price_detail = look_up_reference_price_detail
AdAdmin.actions_detail = (*AdAdmin.actions_detail, "look_up_reference_price_detail")
admin.site.unregister(Ad)
admin.site.register(Ad, AdAdmin)
