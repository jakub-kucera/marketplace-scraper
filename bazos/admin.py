from django.contrib import admin

from bazos.models import Query, Ad, Section, Category


class CategoryInline(admin.TabularInline):
    model = Category
    extra = 0
    readonly_fields = [
        "name",
        "url",
        "bazos_id",
    ]


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
    inlines = (CategoryInline,)


@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "text",
        "category",
        "section",
        "enabled",
        "sender",
    )
    list_filter = ("enabled", "category", "section")


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "price_raw",
        "url",
        "topped"
    )
    # list_filter = ("enabled", "category")
