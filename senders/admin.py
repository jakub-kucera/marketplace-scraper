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
    )
    list_filter = ("notify", "for_logging", "for_summary")
    search_fields = ("channel_name",)
