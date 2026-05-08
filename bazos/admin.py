from django.contrib import admin
from django.db.models import Max
from django.db.models.functions import Coalesce

from bazos.models import Query, Ad, Section, Category, EmailPublisher, PhonePublisher, QueryRun


class CategoryInline(admin.TabularInline):
    model = Category
    extra = 0
    readonly_fields = [
        "name",
        "url",
        "bazos_id",
    ]


class HasFullDescriptionFilter(admin.SimpleListFilter):
    title = 'has full description'
    parameter_name = 'has_full_description'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Has description'),
            ('no', 'No description'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(full_description__isnull=True).exclude(full_description='')
        if self.value() == 'no':
            return queryset.filter(full_description__isnull=True) | queryset.filter(full_description='')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "section",
        "bazos_id",
    )
    list_filter = ("section",)
    search_fields = ("name", "section__name")


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
    search_fields = ("name",)
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
        "last_run",
    )
    list_filter = ("enabled", "randomly_generated", "section", "category")
    actions = ["enable_queries", "disable_queries"]
    autocomplete_fields = ["category", "section", "sender"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # annotate last_run as the latest run_end if present, otherwise run_start
        return qs.annotate(last_run=Coalesce(Max('runs__run_end'), Max('runs__run_start')))

    def last_run(self, obj):
        return getattr(obj, 'last_run', None)

    last_run.admin_order_field = 'last_run'
    last_run.short_description = 'Last run'

    @admin.action(description="Enable selected queries")
    def enable_queries(self, request, queryset):
        updated = queryset.update(enabled=True)
        self.message_user(request, f"{updated} query(ies) enabled successfully.")

    @admin.action(description="Disable selected queries")
    def disable_queries(self, request, queryset):
        updated = queryset.update(enabled=False)
        self.message_user(request, f"{updated} query(ies) disabled successfully.")


@admin.register(QueryRun)
class QueryRunAdmin(admin.ModelAdmin):
    list_display = (
        "query",
        "run_start",
        "run_end",
        "new_ads_count",
    )
    list_filter = ("query", )


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
    list_filter = ("query", HasFullDescriptionFilter)


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
