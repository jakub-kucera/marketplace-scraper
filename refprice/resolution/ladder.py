"""Rungs 1-2: phrase -> candidates -> one validated product. No database, no LLM.

`PRICE_REFERENCE_SERVICE.md` §5. Each rung can decline, and nothing below a rung runs if
a cheaper one already answered. This module is the network-and-arithmetic half; the
database-aware wrapper is `refprice.services`.
"""
import datetime as dt
import logging
from collections.abc import Sequence
from typing import Any

from refprice.providers.base import RefProductFacts, ReferenceProvider
from refprice.resolution.normalize import normalize_phrase
from refprice.resolution.validate import spec_from_phrase, validate
from refprice.results import (
    CandidateTrace,
    MatchedProduct,
    PriceHistory,
    PriceSnapshot,
    SeriesPoint,
)

logger = logging.getLogger(__name__)

#: Beyond ~10%/year, today's new price is a poor proxy for next month's and a used
#: listing has to be judged against the curve. Calibrated against the two measured
#: series: the iPhone 13 fell 38%/yr (falling), the Makita DHP484Z 8%/yr (stable).
FALLING_PCT = 10.0


class Resolution:
    """The outcome of rungs 1-2, before anything is persisted."""

    def __init__(self, facts=None, traces=None, confidence=0.0, no_market=False,
                 considered=None):
        self.facts: RefProductFacts | None = facts
        self.traces: list[CandidateTrace] = traces or []
        self.confidence = confidence
        self.no_market = no_market
        #: Every candidate that was successfully fetched, in suggest order. Kept so rung 4
        #: can adjudicate over the real catalogue rows without fetching them again.
        self.considered: list[RefProductFacts] = considered or []


def resolve(
    phrase: str,
    provider: ReferenceProvider,
    *,
    category_hint: int | None = None,
    max_candidates: int = 8,
) -> tuple[Resolution, int]:
    """Return (resolution, http_requests_made)."""
    spec = spec_from_phrase(phrase, category_id=category_hint)
    candidates = provider.suggest(phrase)
    requests_made = 1
    if not candidates:
        return Resolution(), requests_made

    traces: list[CandidateTrace] = []
    considered: list[RefProductFacts] = []
    near_miss: RefProductFacts | None = None

    for candidate in candidates[:max_candidates]:
        facts = provider.fetch(candidate.slug)
        requests_made += 1
        if facts is None:
            traces.append(CandidateTrace(candidate.slug, candidate.name, False,
                                         "could not be fetched"))
            continue
        considered.append(facts)

        verdict = validate(facts, spec)
        traces.append(CandidateTrace(candidate.slug, facts.name, verdict.accepted,
                                     verdict.reason))
        if verdict.accepted:
            return Resolution(facts=facts, traces=traces, considered=considered,
                              confidence=verdict.confidence), requests_made
        if verdict.no_market and near_miss is None:
            # The right product with too few merchants. Remembered so the caller can say
            # "this is old" rather than "no idea" — a different answer for the user.
            near_miss = facts

    if near_miss is not None:
        return Resolution(facts=near_miss, traces=traces, considered=considered,
                          no_market=True), requests_made
    return Resolution(traces=traces, considered=considered), requests_made


def to_matched_product(facts: RefProductFacts) -> MatchedProduct:
    return MatchedProduct(
        provider=facts.provider, product_id=facts.product_id, slug=facts.slug,
        name=facts.name, brand=facts.brand, category_id=facts.category_id,
        product_no=facts.product_no, url=facts.url,
    )


def to_snapshot(facts: RefProductFacts) -> PriceSnapshot:
    return PriceSnapshot(
        median_czk=facts.median_czk, min_czk=facts.min_czk, max_czk=facts.max_czk,
        shop_count=facts.shop_count, availability=facts.availability,
    )


def summarise_history(points: Sequence[Any]) -> PriceHistory | None:
    """Turn a series into the three numbers a consumer actually reasons with.

    Accepts anything carrying `date`/`min_czk`/`median_czk`/`max_czk` — provider
    `PricePoint`s on a fresh lookup, `RefPricePoint` rows on a cached one.
    """
    series = [
        SeriesPoint(date=p.date, min_czk=p.min_czk, median_czk=p.median_czk,
                    max_czk=p.max_czk)
        for p in points
    ]
    if not series:
        return None

    with_median = [p for p in series if p.median_czk]
    median_now = with_median[-1].median_czk if with_median else None
    mins = [p.min_czk for p in series if p.min_czk]

    median_365 = None
    change_pct = None
    depreciation = None
    trend = "unknown"

    if with_median and median_now:
        newest = with_median[-1].date
        older = [p for p in with_median if (newest - p.date).days >= 300]
        reference = older[-1] if older else with_median[0]
        span_days = (newest - reference.date).days
        if span_days >= 60 and reference.median_czk:
            median_365 = reference.median_czk if older else None
            change = (median_now - reference.median_czk) / reference.median_czk * 100
            # Annualised linearly. The series is ~2 years at most, so a compounding model
            # would imply a precision the data does not carry.
            depreciation = round(-change * 365 / span_days, 1)
            change_pct = round(change, 1) if older else None
            trend = ("falling" if depreciation > FALLING_PCT
                     else "rising" if depreciation < -FALLING_PCT else "stable")

    return PriceHistory(
        points=series, median_now=median_now, median_365d_ago=median_365,
        change_365d_pct=change_pct, trend=trend,
        depreciation_pct_per_year=depreciation,
        min_ever_czk=min(mins) if mins else None,
    )


def normalise(title: str, description: str = "") -> str:
    phrase = normalize_phrase(title, description)
    if not phrase:
        logger.info("Nothing searchable left after normalising %r", title[:80])
    return phrase


__all__ = [
    "Resolution", "resolve", "normalise", "summarise_history",
    "to_matched_product", "to_snapshot", "dt",
]
