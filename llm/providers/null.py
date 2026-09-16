"""The default provider: answers nothing, costs nothing, touches no network.

`DummyIPChanger`'s role, for the same reason — it makes "no backend configured" a state
the code actually runs in rather than an untested branch. The whole test suite and any
fresh checkout exercise every caller's decline path through this class.
"""
from llm.base import LLMResult

DECLINED_REASON = "NULL provider: no LLM backend is configured (set LLM_PROVIDER)"


class NullProvider:
    name = "NULL"

    def complete(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: type | None,
        max_output_tokens: int,
        temperature: float,
    ) -> LLMResult:
        return LLMResult(
            value=None,
            raw="",
            provider=self.name,
            model="none",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            declined_reason=DECLINED_REASON,
        )
