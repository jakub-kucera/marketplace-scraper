"""The cost surface.

Read-only by construction: an audit log that can be edited is not an audit log. Subclasses
`unfold.admin.ModelAdmin` because a stock one still renders 200 — the generic
`test_every_registered_changelist_renders` would not notice an unthemed page.
"""
from django.contrib import admin
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
