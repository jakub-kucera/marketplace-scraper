"""`lookup_reference_price` — the whole public surface, end to end.

Shape and status vocabulary: `PRICE_REFERENCE_SERVICE.md` §4. The rule these tests exist
to hold is **never return a bare number**: the measured failure modes are confident and
wrong (a 2020 MacBook baselined at 47 370 Kc from a 2025 M5; a Dell XPS at 262 Kc from a
backpack), so a caller must always be able to see what was matched and decline to believe it.
"""
import datetime as dt

import pytest

from marketplace.models import Ad, Marketplace
from refprice.models import LookupStatus, RefLookup, RefPricePoint, RefProduct, RefProductLink
from refprice.providers.base import Candidate, PricePoint, RefProductFacts
from refprice.results import ReferenceRequest
from refprice.services import assess_deal, lookup_reference_price

pytestmark = pytest.mark.django_db


def product(name="Makita DHP484Z Li-ion 18 V", *, shops=41, median=3813, pid="5325309"):
    return RefProductFacts(
        provider="zbozi", product_id=pid, slug="makita-dhp484z-li-ion-18-v", name=name,
        brand="Makita", category_id=2543, product_no=None, min_czk=2870,
        median_czk=median, max_czk=5391, shop_count=shops, availability="in_stock",
        release_date=dt.date(2017, 6, 14), url="/vyrobek/makita-dhp484z-li-ion-18-v/",
    )


class StubProvider:
    """A provider whose answers the test dictates, counting what it was asked."""

    name = "zbozi"

    def __init__(self, candidates=None, facts=None, history=None):
        self.candidates = candidates if candidates is not None else [
            Candidate(slug="makita-dhp484z-li-ion-18-v", name="Makita DHP484Z Li-ion 18 V")
        ]
        self._facts = facts if facts is not None else {"makita-dhp484z-li-ion-18-v": product()}
        self._history = history if history is not None else [
            PricePoint(date=dt.date(2025, 9, 1), min_czk=3190, median_czk=4150, max_czk=5000),
            PricePoint(date=dt.date(2026, 6, 1), min_czk=2790, median_czk=3891, max_czk=5390),
            PricePoint(date=dt.date(2026, 9, 1), min_czk=2870, median_czk=3813, max_czk=5391),
        ]
        self.suggest_calls, self.fetch_calls, self.history_calls = 0, 0, 0

    def suggest(self, phrase):
        self.suggest_calls += 1
        return list(self.candidates)

    def fetch(self, slug):
        self.fetch_calls += 1
        return self._facts.get(slug)

    def history(self, product_id, months_back=13):
        self.history_calls += 1
        return list(self._history)

    def search(self, phrase, *, allow_disallowed=False):
        return []


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=999,
        name="Makita DHP484Z aku vrtačka 18V", url="https://pc.bazos.cz/inzerat/999/x.php",
        price_raw="2 500 Kč", price=2500,
    )


def request_for(title="Makita DHP484Z aku vrtačka 18V", **over):
    return ReferenceRequest(title=title, **over)


# ---------------------------------------------------------------------------
# the matched path
# ---------------------------------------------------------------------------

def test_a_good_match_is_reported_as_matched(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.status == LookupStatus.MATCHED


def test_the_headline_number_is_the_median(ad):
    """Not min: mis-pairing poisons the bottom of the range (ZBOZI_API.md §6)."""
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.pricing.median_czk == 3813


def test_it_names_the_product_it_matched(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.product.name == "Makita DHP484Z Li-ion 18 V"
    assert result.product.product_id == "5325309"


def test_it_reports_the_phrase_it_actually_searched(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert "DHP484Z" in result.match.phrase_used
    assert "aku" not in result.match.phrase_used.lower()


def test_it_records_which_candidates_it_considered(ad):
    """"Why did it think this" has to be answerable after the fact."""
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.match.candidates_considered


def test_it_reports_a_robots_allowed_path(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.match.robots_allowed_path is True


def test_it_counts_what_the_lookup_cost(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.cost.http_requests >= 2
    assert result.cost.llm_calls == 0


# ---------------------------------------------------------------------------
# the history
# ---------------------------------------------------------------------------

def test_it_returns_the_price_series(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert len(result.history.points) == 3


def test_it_summarises_the_trend(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.history.median_now == 3813
    assert result.history.trend in {"falling", "stable", "rising"}


def test_a_depreciating_product_reports_a_falling_trend(ad):
    """The iPhone 13 shape: -38% over 13 months."""
    falling = [
        PricePoint(date=dt.date(2025, 9, 1), min_czk=10486, median_czk=10728, max_czk=11000),
        PricePoint(date=dt.date(2026, 9, 1), min_czk=6499, median_czk=7240, max_czk=10950),
    ]
    result = lookup_reference_price(request_for(), ad=ad,
                                    provider=StubProvider(history=falling))
    assert result.history.trend == "falling"
    depreciation = result.history.depreciation_pct_per_year
    assert depreciation is not None and depreciation > 20


def test_a_stable_product_is_not_reported_as_falling(ad):
    """The Makita shape: -8% over 13 months. The distinction is the whole point of
    keeping the series — it is what makes '70% of new' mean different things."""
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.history.trend == "stable"


def test_it_reports_the_lowest_price_the_market_has_actually_seen(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.history.min_ever_czk == 2790


# ---------------------------------------------------------------------------
# the declining paths — each means something different
# ---------------------------------------------------------------------------

def test_nothing_suggested_is_no_match(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider(candidates=[]))
    assert result.status == LookupStatus.NO_MATCH
    assert result.pricing is None


def test_a_thin_market_is_no_market_not_no_match(ad):
    """A discontinued product with one stale offer. That is information about the ad."""
    stub = StubProvider(facts={"makita-dhp484z-li-ion-18-v": product(shops=1)})
    result = lookup_reference_price(request_for(), ad=ad, provider=stub)
    assert result.status == LookupStatus.NO_MARKET


def test_no_market_still_names_the_product_it_found(ad):
    stub = StubProvider(facts={"makita-dhp484z-li-ion-18-v": product(shops=1)})
    result = lookup_reference_price(request_for(), ad=ad, provider=stub)
    assert result.product is not None


def test_an_unusable_title_is_declined_without_calling_out(ad):
    stub = StubProvider()
    result = lookup_reference_price(request_for(title="nové, se zárukou, 128GB"),
                                    ad=ad, provider=stub)
    assert result.status == LookupStatus.DECLINED
    assert stub.suggest_calls == 0


def test_every_rejected_candidate_carries_its_reason(ad):
    wrong = RefProductFacts(
        provider="zbozi", product_id="1", slug="dewalt-kit",
        name="DeWalt DCK266P2T sada aku DCD796 + DCF887", brand="DeWalt",
        category_id=2543, product_no=None, min_czk=7000, median_czk=7785, max_czk=9000,
        shop_count=31, availability="in_stock", release_date=None,
    )
    stub = StubProvider(
        candidates=[Candidate(slug="dewalt-kit", name="DeWalt DCK266P2T sada")],
        facts={"dewalt-kit": wrong},
    )
    result = lookup_reference_price(request_for(title="DeWalt DCD796"), ad=ad, provider=stub)
    assert result.status == LookupStatus.NO_MATCH
    assert any("bundle" in c.reason.lower() for c in result.match.candidates_considered)


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_it_persists_the_product(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert RefProduct.objects.filter(provider="zbozi", product_id="5325309").exists()


def test_it_persists_the_price_series(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert RefPricePoint.objects.count() == 3


def test_it_links_the_ad_to_the_product(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    link = RefProductLink.objects.get()
    assert link.ad == ad
    assert link.product.product_id == "5325309"
    assert link.confirmed_by_human is False


def test_the_link_snapshots_the_ad_title(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert RefProductLink.objects.get().ad_title == ad.name


def test_it_writes_a_lookup_row_on_success(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert RefLookup.objects.get().status == LookupStatus.MATCHED


def test_it_writes_a_lookup_row_on_failure_too(ad):
    """QueryRun's rule. "Tried and found nothing" is not "never tried"."""
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(candidates=[]))
    assert RefLookup.objects.get().status == LookupStatus.NO_MATCH


def test_a_second_lookup_updates_the_link_rather_than_duplicating(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    assert RefProductLink.objects.count() == 1


def test_re_fetching_merges_the_series_rather_than_duplicating(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    assert RefPricePoint.objects.count() == 3


def test_a_human_confirmation_is_not_overwritten_by_a_rerun(ad):
    """The labelled corpus is the payoff; a routine refresh must not erase it."""
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    RefProductLink.objects.update(confirmed_by_human=True)
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider(), use_cache=False)
    assert RefProductLink.objects.get().confirmed_by_human is True


# ---------------------------------------------------------------------------
# rung 0 — the cache
# ---------------------------------------------------------------------------

def test_a_repeat_lookup_does_not_call_the_provider(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    second = StubProvider()
    lookup_reference_price(request_for(), ad=ad, provider=second)
    assert second.suggest_calls == 0


def test_a_cached_result_is_labelled_as_cached(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.match.method == "CACHED"


def test_a_cached_result_still_carries_the_numbers(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert result.pricing.median_czk == 3813
    assert result.history.points


def test_cache_can_be_bypassed(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    second = StubProvider()
    lookup_reference_price(request_for(), ad=ad, provider=second, use_cache=False)
    assert second.suggest_calls == 1


def test_a_stale_product_is_refetched(ad):
    lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    RefProduct.objects.update(fetched_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
    second = StubProvider()
    lookup_reference_price(request_for(), ad=ad, provider=second)
    assert second.suggest_calls == 1


# ---------------------------------------------------------------------------
# the deal verdict — a separate question, deliberately a separate object
# ---------------------------------------------------------------------------

def test_a_cheap_ad_reads_as_a_bargain(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    deal = assess_deal(ad_price_czk=1500, reference=result)
    assert deal.verdict == "bargain"
    assert deal.discount_pct is not None and deal.discount_pct > 50


def test_an_expensive_ad_reads_as_overpriced(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider())
    assert assess_deal(ad_price_czk=5200, reference=result).verdict == "overpriced"


def test_a_deal_cannot_be_assessed_without_a_reference(ad):
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider(candidates=[]))
    assert assess_deal(ad_price_czk=1500, reference=result).verdict == "unknown"


def test_a_thin_reference_is_flagged_as_a_caveat(ad):
    stub = StubProvider(facts={"makita-dhp484z-li-ion-18-v": product(shops=2)})
    result = lookup_reference_price(request_for(), ad=ad, provider=stub)
    deal = assess_deal(ad_price_czk=1500, reference=result)
    assert any("merchant" in c for c in deal.caveats)


def test_a_falling_reference_is_flagged_as_a_caveat(ad):
    """A 38%/yr depreciation means today's new price is not tomorrow's, and a used
    listing should be judged against the curve rather than against one day."""
    falling = [
        PricePoint(date=dt.date(2025, 9, 1), min_czk=10486, median_czk=10728, max_czk=11000),
        PricePoint(date=dt.date(2026, 9, 1), min_czk=6499, median_czk=7240, max_czk=10950),
    ]
    result = lookup_reference_price(request_for(), ad=ad, provider=StubProvider(history=falling))
    deal = assess_deal(ad_price_czk=3000, reference=result)
    assert any("depreciat" in c.lower() for c in deal.caveats)
