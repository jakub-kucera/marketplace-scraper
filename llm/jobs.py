"""The LLM backend canary, as a queued task.

Lives here rather than in `bazos/jobs.py` for the same reason `refprice/jobs.py` does: the
dependency points inward, and the schedule is contributed through
`bazos.jobs.register_schedule` at `AppConfig.ready()`.
"""
import logging
from io import StringIO

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)

LLM_CHECK = "llm.jobs.llm_check"


def llm_check() -> str:
    """One real call to the configured provider: is the key, the model and the quota alive?

    ⚠️ **Skips rather than calling when `LLM_PROVIDER` is `NULL`** — the shipped default.
    `NullProvider` declines every call and opens no socket, so a call here would prove
    nothing while filling the run log with a weekly row that always says the same thing.
    Silence about a backend nobody configured is correct; a green row implying a working
    backend is not.

    Everything that *can* go wrong with a configured provider is a decline, not an
    exception — a bad key, a model name the provider does not serve, an exhausted budget —
    so the outcome is in the return string rather than in whether this raises. The one thing
    that would raise is a broken `llm/` itself, which is what a Failure row should mean.

    Costs one call's tokens per run. Every call writes an `LLMCall` row regardless, so the
    spend is attributable rather than mysterious.
    """
    provider = (settings.LLM_PROVIDER or "NULL").upper()
    if provider == "NULL":
        logger.info("LLM check skipped: LLM_PROVIDER is NULL")
        return "skipped — LLM_PROVIDER is NULL, nothing to check"

    out = StringIO()
    call_command("llm_check", stdout=out)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("LLM check (%s): %s", provider, summary)
    return f"{provider}: {summary}"
