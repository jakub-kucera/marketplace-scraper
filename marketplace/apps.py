from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketplace"
    #: Frozen at the pre-rename package name on purpose. The label, not `name`, is what
    #: every table name, django_migrations row, ContentType/Permission row and
    #: `to="bazos.Ad"`-style FK string already key on - changing it means renaming 16 live
    #: tables on production and re-pointing every cross-app FK and migration dependency.
    #: Only `name` (the import path) needed to change for the package to stop being called
    #: `bazos`; nothing downstream of the app registry has to know that happened.
    label = "bazos"
