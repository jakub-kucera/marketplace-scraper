"""The cost surface.

Read-only by construction: an audit log that can be edited is not an audit log. Subclasses
`unfold.admin.ModelAdmin` because a stock one still renders 200 — the generic
`test_every_registered_changelist_renders` would not notice an unthemed page.
"""
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse
from unfold.decorators import action as unfold_action
from django.db.models import Sum
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from llm.models import LLMCall, LLMOutcome
from llm.services import month_to_date_cost


@admin.register(LLMCall)
class LLMCallAdmin(ModelAdmin):
    list_display = ("created", "prompt", "provider", "model", "outcome_badge",
                    "tokens", "cost_display", "latency_ms", "cached")
    list_filter = ("outcome", "provider", "prompt_name", "cached")
    search_fields = ("prompt_name", "model", "declined_reason")
    date_hierarchy = "created"
    ordering = ("-created",)

    @admin.display(description="Prompt", ordering="prompt_name")
    def prompt(self, obj: LLMCall) -> str:
        return f"{obj.prompt_name}@{obj.prompt_version}"

    @admin.display(description="Outcome", ordering="outcome")
    def outcome_badge(self, obj: LLMCall) -> str:
        colours: dict[str, str] = {
            LLMOutcome.OK.value: "#1a7f37",
            LLMOutcome.DECLINED.value: "#8a5a06",
            LLMOutcome.ERROR.value: "#b42318",
        }
        colour = colours.get(obj.outcome, "#69737d")
        return format_html('<b style="color:{}">{}</b>', colour, obj.get_outcome_display())

    @admin.display(description="Tokens")
    def tokens(self, obj: LLMCall) -> str:
        return f"{obj.tokens_in:,} → {obj.tokens_out:,}"

    @admin.display(description="Cost", ordering="cost_usd")
    def cost_display(self, obj: LLMCall) -> str:
        return f"${obj.cost_usd:.6f}"

    def changelist_view(self, request, extra_context=None):
        """Month-to-date spend in the title — the number the budget is checked against."""
        all_time = LLMCall.objects.aggregate(t=Sum("cost_usd"))["t"] or 0
        extra_context = {
            **(extra_context or {}),
            "title": (
                f"LLM calls — ${month_to_date_cost():.4f} this month, "
                f"${all_time:.4f} all time"
            ),
        }
        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# Wiring onto AdAdmin, from this side
# ---------------------------------------------------------------------------
#
# Appended here rather than declared in `bazos/admin.py`, for the reason `refprice/admin.py`
# gives: the dependency points inward, and deleting this app must break nothing in the
# pipeline. Admin modules load in INSTALLED_APPS order, and `llm` sits after `bazos`.

from django.contrib import messages  # noqa: E402
from django_q.tasks import async_task  # noqa: E402
from unfold.admin import TabularInline  # noqa: E402

from marketplace.admin import AdAdmin  # noqa: E402
from marketplace.models import Ad, AdSpecExtraction  # noqa: E402

from llm.jobs import EXTRACT_AD_SPECS  # noqa: E402


class AdSpecExtractionInline(TabularInline):
    model = AdSpecExtraction
    extra = 0
    can_delete = False
    fields = ("prompt_version", "specs", "provider", "model_name", "declined_reason", "created")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.action(description="Extract specs with the LLM")
def extract_ad_specs(modeladmin, request, queryset):
    """Queue one extraction per ad. Inert while LLM_PROVIDER is NULL.

    No filtering on "already extracted": a new prompt version is exactly when you would
    re-run this over ads that already have a row, and the unique key is (ad, prompt_version),
    so a re-run under the same version updates rather than duplicating.
    """
    pks = list(queryset.values_list("pk", flat=True))
    for pk in pks:
        async_task(EXTRACT_AD_SPECS, pk)
    modeladmin.message_user(
        request, f"Queued {len(pks)} spec extraction(s).", messages.INFO
    )


@unfold_action(description="Extract specs", icon="auto_awesome", url_path="extract-specs")
def extract_ad_specs_detail(self, request, object_id):
    """The changelist action, on the ad's own page. Appended to `AdAdmin.actions_detail`
    from here for the same reason `actions` is - `bazos` cannot import this app."""
    async_task(EXTRACT_AD_SPECS, int(object_id))
    self.message_user(request, "Queued a spec extraction.", messages.INFO)
    return HttpResponseRedirect(reverse("admin:bazos_ad_change", args=[object_id]))

AdAdmin.inlines = (*AdAdmin.inlines, AdSpecExtractionInline)  # type: ignore[assignment]
AdAdmin.actions = (*(AdAdmin.actions or ()), extract_ad_specs)
# `actions_detail` is resolved by NAME via getattr on the admin instance, unlike
# `actions`, which accepts a callable. So the function has to be attached to the
# class first and referenced as a string - appending the bare function raises
# "attribute name must be string" at import time.
AdAdmin.extract_ad_specs_detail = extract_ad_specs_detail
AdAdmin.actions_detail = (*AdAdmin.actions_detail, "extract_ad_specs_detail")
admin.site.unregister(Ad)
admin.site.register(Ad, AdAdmin)
