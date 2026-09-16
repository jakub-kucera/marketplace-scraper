"""What a lookup returns. Plain dataclasses — no Django objects cross this boundary.

That is the extraction seam from `PRICE_REFERENCE_SERVICE.md` §1: `ReferenceRequest`
carries strings and ints, never an `Ad`, so the day this becomes a separate service the
entry point becomes an HTTP client with the same signature and nothing above it changes.

**The core rule is that no consumer ever receives a bare number.** The measured failure
modes are confident and wrong — a 2020 MacBook baselined at 47 370 Kc from a 2025 M5, a
Dell XPS at 262 Kc from a laptop bag — so every result carries the evidence needed to
disbelieve it.
"""
import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceRequest:
    title: str
    description: str = ""
    category_hint: int | None = None
    months_back: int = 13
    #: Rung 5. Off by default; the `?q=` route is robots-disallowed (ZBOZI_API.md §4).
    allow_disallowed_search: bool = False
    #: Rungs 3-4. Off by default; requires a configured LLM provider.
    use_llm: bool = False


@dataclass(frozen=True)
class MatchedProduct:
    provider: str
    product_id: str
    slug: str
    name: str
    brand: str | None
    category_id: int | None
    product_no: str | None
    url: str | None


@dataclass(frozen=True)
class PriceSnapshot:
    #: The headline. Not `min` — see ZBOZI_API.md §6.
    median_czk: int | None
    min_czk: int | None
    max_czk: int | None
    shop_count: int
    availability: str


@dataclass(frozen=True)
class SeriesPoint:
    date: dt.date
    min_czk: int | None
    median_czk: int | None
    max_czk: int | None


@dataclass(frozen=True)
class PriceHistory:
    points: list[SeriesPoint]
    median_now: int | None
    median_365d_ago: int | None
    change_365d_pct: float | None
    trend: str
    #: The field that earns the series. Measured: the iPhone 13 lost 38% of its median in
    #: 13 months while the Makita DHP484Z moved -8%. "70% of new" is a great deal on one
    #: and a poor one on the other, and only the curve separates them.
    depreciation_pct_per_year: float | None
    #: What the market has actually cleared at — a far better floor than one day's minimum.
    min_ever_czk: int | None


@dataclass(frozen=True)
class CandidateTrace:
    slug: str
    name: str
    accepted: bool
    reason: str


@dataclass(frozen=True)
class MatchEvidence:
    method: str
    confidence: float
    phrase_used: str
    candidates_considered: list[CandidateTrace] = field(default_factory=list)
    #: False when rung 5 (the robots-disallowed search) was used. Travels with the number
    #: so how it was obtained is never separable from it.
    robots_allowed_path: bool = True


@dataclass(frozen=True)
class LookupCost:
    http_requests: int = 0
    llm_calls: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    usd: float = 0.0


@dataclass(frozen=True)
class ReferenceResult:
    status: str
    match: MatchEvidence
    cost: LookupCost
    fetched_at: dt.datetime
    product: MatchedProduct | None = None
    pricing: PriceSnapshot | None = None
    history: PriceHistory | None = None
    detail: str = ""


@dataclass(frozen=True)
class DealAssessment:
    """A separate object because it is a separate question, with a separate input."""
    ad_price_czk: int
    reference_median_czk: int | None
    ratio: float | None
    discount_pct: float | None
    verdict: str
    #: Populated, not cosmetic. "reference drawn from 2 merchants", "product is
    #: depreciating fast" — the things that make a ratio mean less than it looks.
    caveats: list[str] = field(default_factory=list)
