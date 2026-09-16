"""`manage.py llm_check` — is the configured LLM backend actually working?

The one thing you want when a key, a model name or a quota is in doubt. It makes a single
real call through `llm.services.complete`, so it exercises the same budget ceiling, cache
and audit row as production rather than a special path that proves nothing.

With `LLM_PROVIDER=NULL` (the shipped default) it reports a decline and costs nothing,
which is the correct answer rather than an error.
"""
from dataclasses import dataclass

from django.conf import settings
from django.core.management.base import BaseCommand

from llm.registry import get_provider
from llm.services import complete, month_to_date_cost


@dataclass(frozen=True)
class Ping:
    answer: str
    confidence: float


class Command(BaseCommand):
    help = "Make one real call to the configured LLM provider and report what happened."

    def add_arguments(self, parser):
        parser.add_argument("--models", action="store_true",
                            help="List the models this provider offers, if it can.")
        parser.add_argument("--model", help="Override LLM_MODEL for this call only.")
        parser.add_argument("--prompt",
                            default='Reply with JSON: {"answer": "pong", "confidence": 1.0}')

    def handle(self, *args, **options):
        if options["model"]:
            settings.LLM_MODEL = options["model"]

        self.stdout.write(f"provider   {settings.LLM_PROVIDER}")
        self.stdout.write(f"model      {settings.LLM_MODEL}")
        self.stdout.write(f"budget     ${month_to_date_cost():.4f} of "
                          f"${settings.LLM_MONTHLY_BUDGET_USD} this month")

        provider = get_provider()
        key = getattr(provider, "api_key", None)
        if key is not None:
            # Never print the key. Its length and last four are enough to tell "wrong key"
            # from "no key", which is the only question this line has to answer.
            self.stdout.write(
                f"key        {'set (…' + key[-4:] + ', ' + str(len(key)) + ' chars)' if key else 'NOT SET'}"
            )

        if options["models"]:
            self._list_models(provider)
            return

        self.stdout.write("")
        result = complete(prompt=options["prompt"], schema=Ping,
                          prompt_name="llm_check", prompt_version="v1",
                          max_output_tokens=100)

        if result.declined:
            self.stdout.write(self.style.WARNING(f"DECLINED   {result.declined_reason}"))
            if result.raw:
                self.stdout.write(f"raw        {result.raw[:300]!r}")
            return

        self.stdout.write(self.style.SUCCESS(f"OK         {result.value}"))
        self.stdout.write(f"tokens     {result.tokens_in} in / {result.tokens_out} out")
        self.stdout.write(f"cost       ${result.cost_usd:.6f}")
        self.stdout.write(f"latency    {result.latency_ms} ms")

    def _list_models(self, provider) -> None:
        """Optional capability, read with getattr — being a provider does not imply being
        able to enumerate models (the same call `Sendable`/`admin_url` makes)."""
        lister = getattr(provider, "list_models", None)
        if lister is None:
            self.stdout.write(self.style.WARNING(
                f"\n{provider.name} cannot list models."
            ))
            return
        models = lister()
        if not models:
            self.stdout.write(self.style.WARNING("\nNo models returned."))
            return
        self.stdout.write(f"\n{len(models)} models:")
        for model in models:
            self.stdout.write(f"  {model}")
