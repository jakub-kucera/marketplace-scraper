from django.contrib import admin
from unfold.admin import ModelAdmin

from facebook.models import FBUser


@admin.register(FBUser)
class BookingAdmin(ModelAdmin):
    list_display = ("first_name", "last_name", "municipality_of_residence", "phone_number", "email")
    list_filter = ("gender", "relationship_status", )
    search_fields = ("first_name", "last_name", "phone_number", "email")
    readonly_fields = ("facebook_id", )
