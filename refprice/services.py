"""`lookup_reference_price` — the entire public surface of this app.

Everything outside this module talks to one function with plain dataclasses in and out
(`PRICE_REFERENCE_SERVICE.md` §1). This layer adds what `resolution.ladder` deliberately
has not got: rung 0's cache, and persistence.

**This must never be called from a filter rule.** It performs network I/O, and
`run_filter` holds `select_for_update` locks while rules run — the same prohibition
`PriceModel.predict` carries. Reference lookup is explicit-only for that reason.
"""
import datetime as dt
import logging
import time

from django.db import transaction
from django.utils import timezone

from refprice.models import (
    LookupStatus,
    MatchMethod,
    RefLookup,
    RefPricePoint,
    RefProduct,
    RefProductLink,
)
from refprice.providers.base import ReferenceProvider, get_provider
from refprice.resolution import ladder
from refprice.resolution.llm_rungs import adjudicate, suggest_phrase
from refprice.results import (
    DealAssessment,
    LookupCost,
    MatchEvidence,
    ReferenceRequest,
    ReferenceResult,
)

logger = logging.getLogger(__name__)

#: How long a cached product is trusted before it is re-fetched.
DEFAULT_TTL = dt.timedelta(days=7)

#: Deal thresholds. Deliberately coarse — precision here is not measurable yet, the same
#: reason `PRICE_MODEL_SHADOW_MODE` defaults on.
BARGAIN_RATIO = 0.6
OVERPRICED_RATIO = 1.0
#: Below this many merchants the median is thin enough to say so out loud.
THIN_MARKET_SHOPS = 3


def lookup_reference_price(
    request: ReferenceRequest,
    *,
    ad=None,
    provider: ReferenceProvider | None = None,
    provider_name: str = "zbozi",
    use_cache: bool = True,
    persist: bool = True,
    ttl: dt.timedelta = DEFAULT_TTL,
) -> ReferenceResult:
    """Resolve one listing to a reference price. Never raises.

    `persist=False` makes the whole call read-only — no product, no series, no link, no
    audit row. That is the separation `PRICE_REFERENCE_SERVICE.md` §1 asks for: the
    resolution itself is pure, and storing it is the caller's decision.
    """
    started = time.monotonic()
    impl = provider if provider is not None else get_provider(provider_name)
    name = getattr(impl, "name", provider_name)

    phrase = ladder.normalise(request.title, request.description)

    if use_cache and ad is not None:
        cached = _from_cache(ad, name, ttl)
        if cached is not None:
            return cached

    llm_cost = LookupCost()
    if not phrase and request.use_llm:
        # Rung 3. The rule normaliser found nothing searchable; ask for a phrase before
        # giving up. Inert under the shipped LLM_PROVIDER=NULL.
        suggestion = suggest_phrase(request.title, request.description)
        phrase = suggestion.phrase

    if not phrase:
        return _finish(
            persist=persist,
            ad=ad, provider=name, phrase="", status=LookupStatus.DECLINED,
            evidence=MatchEvidence(method=MatchMethod.RULE, confidence=0.0, phrase_used=""),
            cost=LookupCost(), started=started,
            detail="nothing searchable left after normalising the title",
        )

    robots_allowed = True
    try:
        resolution, http_requests = ladder.resolve(
            phrase, impl, category_hint=request.category_hint
        )
        if resolution.facts is None and request.allow_disallowed_search:
            # Rung 5. Measured: `Bosch GSB 18-2-LI` returns 33 canonical products through
            # the ?q= search and zero through suggest. That route is robots-disallowed,
            # so it is off by default, opted into per call, and recorded on the result --
            # how a number was obtained travels with the number.
            resolution, extra = ladder.escalate(
                phrase, impl, resolution, category_hint=request.category_hint
            )
            http_requests += extra
            robots_allowed = False
    except Exception as exc:  # noqa: BLE001 — a broken transport is not the caller's problem
        logger.exception("Reference lookup failed for %r", phrase)
        return _finish(
            persist=persist,
            ad=ad, provider=name, phrase=phrase, status=LookupStatus.ERROR,
            evidence=MatchEvidence(method=MatchMethod.RULE, confidence=0.0,
                                   phrase_used=phrase),
            cost=LookupCost(), started=started, detail=f"{type(exc).__name__}: {exc}",
        )

    evidence = MatchEvidence(
        method=MatchMethod.RULE, confidence=resolution.confidence, phrase_used=phrase,
        candidates_considered=resolution.traces, robots_allowed_path=robots_allowed,
    )

    method = MatchMethod.RULE
    if resolution.facts is None and request.use_llm and resolution.considered:
        # Rung 4. The rules rejected everything, but the right answer is often *in* the
        # list — measured: the Samsung S10 at rank 3, a real MacBook at rank 6. Closed-set
        # adjudication over what the catalogue actually returned, with an explicit decline.
        choice = adjudicate(request.title, resolution.considered)
        llm_cost = LookupCost(llm_calls=1 if choice.called else 0,
                              llm_tokens_in=choice.tokens_in,
                              llm_tokens_out=choice.tokens_out, usd=choice.cost_usd)
        if choice.facts is not None:
            resolution.facts = choice.facts
            resolution.confidence = choice.confidence
            resolution.no_market = not choice.facts.shop_count >= 2
            method = MatchMethod.LLM
            evidence = MatchEvidence(
                method=method, confidence=choice.confidence, phrase_used=phrase,
                candidates_considered=resolution.traces,
                robots_allowed_path=robots_allowed,
            )

    cost = LookupCost(
        http_requests=http_requests, llm_calls=llm_cost.llm_calls,
        llm_tokens_in=llm_cost.llm_tokens_in, llm_tokens_out=llm_cost.llm_tokens_out,
        usd=llm_cost.usd,
    )

    if resolution.facts is None:
        return _finish(persist=persist, ad=ad, provider=name, phrase=phrase,
                       status=LookupStatus.NO_MATCH, evidence=evidence,
                       cost=cost, started=started)

    facts = resolution.facts
    points = impl.history(facts.product_id, request.months_back)

    cost = LookupCost(
        http_requests=http_requests + 1, llm_calls=cost.llm_calls,
        llm_tokens_in=cost.llm_tokens_in, llm_tokens_out=cost.llm_tokens_out,
        usd=cost.usd,
    )
    status = LookupStatus.NO_MARKET if resolution.no_market else LookupStatus.MATCHED
    if persist:
        stored = _persist(facts, points)
        if ad is not None:
            _link(ad, name, stored, resolution.confidence, method, phrase, evidence)

    return _finish(
        persist=persist,
        ad=ad, provider=name, phrase=phrase, status=status, evidence=evidence,
        cost=cost, started=started,
        product=ladder.to_matched_product(facts),
        pricing=ladder.to_snapshot(facts),
        history=ladder.summarise_history(points),
    )


# ---------------------------------------------------------------------------
# rung 0
# ---------------------------------------------------------------------------

def _from_cache(ad, provider: str, ttl: dt.timedelta) -> ReferenceResult | None:
    link = (
        RefProductLink.objects.filter(ad=ad, provider=provider)
        .select_related("product").first()
    )
    if link is None or link.product is None or not link.product.is_fresh(ttl):
        return None

    product = link.product
    # Rows, not provider PricePoints — same three fields, and `summarise_history` reads
    # them structurally rather than by type.
    points = list(product.price_points.all())
    facts = _facts_from_row(product)
    return ReferenceResult(
        status=(LookupStatus.MATCHED if product.has_market else LookupStatus.NO_MARKET),
        match=MatchEvidence(method=MatchMethod.CACHED, confidence=link.confidence,
                            phrase_used=link.phrase_used,
                            candidates_considered=[], robots_allowed_path=True),
        cost=LookupCost(),
        fetched_at=product.fetched_at,
        product=ladder.to_matched_product(facts),
        pricing=ladder.to_snapshot(facts),
        history=ladder.summarise_history(points),
    )


def _facts_from_row(product: RefProduct):
    from refprice.providers.base import RefProductFacts
    return RefProductFacts(
        provider=product.provider, product_id=product.product_id, slug=product.slug,
        name=product.name, brand=product.brand or None, category_id=product.category_id,
        product_no=product.product_no or None, min_czk=product.min_czk,
        median_czk=product.median_czk, max_czk=product.max_czk,
        shop_count=product.shop_count, availability=product.availability,
        release_date=product.release_date, url=product.url or None,
    )


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

@transaction.atomic
def _persist(facts, points) -> RefProduct:
    product, _ = RefProduct.objects.update_or_create(
        provider=facts.provider, product_id=facts.product_id,
        defaults={
            "slug": facts.slug, "name": facts.name, "brand": facts.brand or "",
            "category_id": facts.category_id, "product_no": facts.product_no or "",
            "min_czk": facts.min_czk, "median_czk": facts.median_czk,
            "max_czk": facts.max_czk, "shop_count": facts.shop_count,
            "availability": facts.availability, "release_date": facts.release_date,
            "url": facts.url or "", "fetched_at": timezone.now(),
        },
    )
    for point in points:
        # update_or_create, not bulk insert: the newest point is today's and its value
        # moves during the day, so a re-fetch must merge rather than collide.
        RefPricePoint.objects.update_or_create(
            product=product, date=point.date,
            defaults={"min_czk": point.min_czk, "median_czk": point.median_czk,
                      "max_czk": point.max_czk},
        )
    return product


def _link(ad, provider: str, product: RefProduct, confidence: float, method: str,
          phrase: str, evidence: MatchEvidence) -> None:
    existing = RefProductLink.objects.filter(ad=ad, provider=provider).first()
    if existing is not None and existing.confirmed_by_human:
        # A person vouched for this. A routine refresh must not quietly overwrite the
        # labelled corpus that explicit invocation exists to produce.
        return
    RefProductLink.objects.update_or_create(
        ad=ad, provider=provider,
        defaults={
            "ad_title": ad.name, "product": product, "confidence": confidence,
            "method": method, "phrase_used": phrase,
            "evidence": {
                "candidates": [
                    {"slug": c.slug, "name": c.name, "accepted": c.accepted,
                     "reason": c.reason}
                    for c in evidence.candidates_considered
                ]
            },
        },
    )


def _finish(*, ad, provider, phrase, status, evidence, cost, started, product=None,
            pricing=None, history=None, detail="", persist=True) -> ReferenceResult:
    duration_ms = int((time.monotonic() - started) * 1000)
    if persist:
        RefLookup.objects.create(
            ad=ad, provider=provider, phrase_used=phrase, status=status, detail=detail,
            http_requests=cost.http_requests, llm_calls=cost.llm_calls,
            llm_tokens_in=cost.llm_tokens_in, llm_tokens_out=cost.llm_tokens_out,
            cost_usd=cost.usd, duration_ms=duration_ms,
        )
    return ReferenceResult(
        status=status, match=evidence, cost=cost, fetched_at=timezone.now(),
        product=product, pricing=pricing, history=history, detail=detail,
    )


# ---------------------------------------------------------------------------
# the deal verdict
# ---------------------------------------------------------------------------

def assess_deal(*, ad_price_czk: int, reference: ReferenceResult) -> DealAssessment:
    """Compare an asking price to a reference. A separate question from the lookup."""
    median = reference.pricing.median_czk if reference.pricing else None
    if not median or reference.status not in {LookupStatus.MATCHED, LookupStatus.NO_MARKET}:
        return DealAssessment(
            ad_price_czk=ad_price_czk, reference_median_czk=None, ratio=None,
            discount_pct=None, verdict="unknown",
            caveats=["no usable reference price"],
        )

    ratio = ad_price_czk / median
    caveats: list[str] = []

    if reference.status == LookupStatus.NO_MARKET:
        caveats.append("product is discontinued; a new price is not a fair comparison")
    if reference.pricing and reference.pricing.shop_count < THIN_MARKET_SHOPS:
        caveats.append(
            f"reference drawn from {reference.pricing.shop_count} merchant(s)"
        )
    if reference.match.method == MatchMethod.LLM:
        caveats.append("matched by LLM, not confirmed by a human")
    if not reference.match.robots_allowed_path:
        caveats.append("resolved via the robots-disallowed search route")
    history = reference.history
    if history and history.depreciation_pct_per_year and history.depreciation_pct_per_year > 15:
        caveats.append(
            f"reference is depreciating ~{history.depreciation_pct_per_year:.0f}%/year — "
            f"judge against the curve, not one day"
        )

    verdict = ("bargain" if ratio <= BARGAIN_RATIO
               else "overpriced" if ratio >= OVERPRICED_RATIO else "fair")
    return DealAssessment(
        ad_price_czk=ad_price_czk, reference_median_czk=median, ratio=round(ratio, 3),
        discount_pct=round((1 - ratio) * 100, 1), verdict=verdict, caveats=caveats,
    )
