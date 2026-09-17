from django.apps import AppConfig


class LLMConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "llm"
    verbose_name = "LLM"

    def ready(self) -> None:
        """Register the backend canary's schedule from here, not from `bazos/jobs.py`.

        The dependency points inward — deleting this app must break nothing in the pipeline
        — so `bazos` never imports `llm`. The same seam `refprice` uses for its filter rule
        and its own schedule.
        """
        from django_q.models import Schedule

        from bazos.jobs import ScheduleSpec, register_schedule
        from llm.jobs import LLM_CHECK

        # Weekly, and a no-op while LLM_PROVIDER is NULL (the shipped default), so this
        # costs nothing until a provider is actually configured.
        register_schedule("llm-check", ScheduleSpec(LLM_CHECK, Schedule.WEEKLY))
