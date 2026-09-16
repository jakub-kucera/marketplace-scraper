from django.apps import AppConfig


class RefpriceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "refprice"
    verbose_name = "Reference prices"

    def ready(self) -> None:
        """Register the filter rule from here, not from `bazos/filters.py`.

        The dependency points inward: deleting this app must break nothing in the
        pipeline, so `bazos` never imports `refprice`. Registering at `ready()` is the
        standard Django seam for that, and it deliberately does **not** touch
        `DEFAULT_RULE_NAMES` — the rule is available to a query that names it and inert
        for every query that does not, which is how `price_model` already ships.
        """
        from bazos.filters import register_rule
        from refprice.rules import ReferencePriceRule

        register_rule(ReferencePriceRule(), opt_in=True)
