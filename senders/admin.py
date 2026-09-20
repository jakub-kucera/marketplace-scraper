from django.contrib import admin
from unfold.admin import ModelAdmin

from senders.models import Discord


@admin.register(Discord)
class SenderAdmin(ModelAdmin):
    list_display = (
        "channel_name",
        "notify",
        "for_logging",
        "for_summary",
        "for_daily_digest",
    )
    list_filter = ("notify", "for_logging", "for_summary", "for_daily_digest")
    search_fields = ("channel_name",)
