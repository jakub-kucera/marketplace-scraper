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
        self._register_schedule()

    def _register_schedule(self) -> None:
        """Same seam, same reason: `bazos` must not have to know this app exists.

        Weekly. The series it refreshes is ~24 months of monthly points, so a daily job
        would re-fetch the same numbers six times before any of them moved.
        """
        from django_q.models import Schedule

        from bazos.jobs import ScheduleSpec, register_schedule
        from refprice.jobs import REFRESH_STALE_REFERENCE_PRICES

        register_schedule(
            "refresh-stale-reference-prices",
            ScheduleSpec(REFRESH_STALE_REFERENCE_PRICES, Schedule.WEEKLY),
        )
        self._register_jobs()

    def _register_jobs(self) -> None:
        """Offer both tasks on the admin's Run-a-job page."""
        from bazos.jobs import AD_PK, JobSpec, register_job
        from refprice.jobs import LOOKUP_REFERENCE_PRICE, REFRESH_STALE_REFERENCE_PRICES

        register_job(JobSpec(LOOKUP_REFERENCE_PRICE, "Look up an ad's reference price", AD_PK))
        register_job(JobSpec(REFRESH_STALE_REFERENCE_PRICES, "Refresh stale reference prices"))
