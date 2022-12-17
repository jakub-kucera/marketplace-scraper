from django.contrib import admin

from senders.models import Discord


@admin.register(Discord)
class SenderAdmin(admin.ModelAdmin):
    list_display = (
        "channel_name",
        "notify",
        "for_logging",
    )
    list_filter = ("notify", "for_logging")
