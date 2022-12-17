from django.contrib import admin

from bazos.models import Query, Ad


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


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "price_raw",
        "url",
        "topped"
    )
    # list_filter = ("enabled", "category")
