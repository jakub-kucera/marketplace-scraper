"""The audit log for every LLM call this project makes.

One row per *attempt*, written on success, decline and error alike — `QueryRun`'s rule,
for the same reason: "it was tried and failed" is a different fact from "it was never
tried", and only the first explains a gap in the results.

Without this table two questions have no answer after the fact: what did this cost, and
did changing the prompt help. Both are asked in arrears, which is exactly when the data
would otherwise be gone.
"""
from django.db import models


class LLMOutcome(models.TextChoices):
    OK = "OK", "OK"
    DECLINED = "DECLINED", "Declined"
    ERROR = "ERROR", "Error"


class LLMCall(models.Model):
    #: Which prompt, at which version. Prompts are versioned files rather than inline
    #: strings precisely so this pair can attribute a result to the text that produced it.
    prompt_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=20)

    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=120)

    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    #: Decimal, not float: these are fractions of a cent that get summed against a budget.
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cached = models.BooleanField(default=False)

    outcome = models.CharField(max_length=16, choices=LLMOutcome.choices, default=LLMOutcome.OK)
    declined_reason = models.TextField(blank=True, default="")

    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created",)
        indexes = [models.Index(fields=["prompt_name", "-created"])]

    def __str__(self) -> str:
        return f"{self.prompt_name}@{self.prompt_version} {self.provider} {self.outcome}"
