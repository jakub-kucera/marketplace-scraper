from django.contrib import admin

from bazos.models import Query, Ad, Section, Category, EmailPublisher, PhonePublisher


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
        "randomly_generated",
        "sender",
    )
    list_filter = ("enabled", "randomly_generated", "section", "category")


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "topped",
        "price_raw",
        "url",
        "query",
        "created",
    )
    list_filter = ("query", )


@admin.register(EmailPublisher)
class EmailPublisherAdmin(admin.ModelAdmin):
    list_display = (
        "bazos_id",
        "email",
    )


@admin.register(PhonePublisher)
class PhonePublisherAdmin(admin.ModelAdmin):
    list_display = (
        "bazos_id",
        "phone",
    )