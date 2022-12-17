from django.contrib import admin

from bazos.models import Query


@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "text",
        "category",
        "enabled",
        "sender",
    )
    list_filter = ("enabled", "category")
