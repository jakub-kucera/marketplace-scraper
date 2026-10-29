"""Tests for `llm/extraction.py`.

Two things carry weight here. That an empty value is *absent* rather than stored as zero —
otherwise "the ad does not say" and "the ad says zero" become the same row, and something
downstream will eventually average them. And that a decline is still written down.
"""
from unittest.mock import patch

import pytest
from django.test import override_settings

from marketplace.models import Ad, AdSpecExtraction, Marketplace
from llm.base import LLMResult
from llm.extraction import AdSpecs, _present, extract_specs


@pytest.fixture
def ad(db):
    return Ad.objects.create(
        external_id=6001, marketplace=Marketplace.BAZOS,
        url="https://pc.bazos.cz/inzerat/6001/x.php",
        name="MacBook Pro 14 M1 Pro 16/512",
        price_raw="31 000 Kč", price=31000, location="Praha, 110 00",
        short_description="Pekny stav, koupeno 2022",
        publisher_name="Seller",
    )


def result(value=None, declined_reason=None, model="test-model"):
    return LLMResult(
        value=value, raw="", provider="TEST", model=model,
        tokens_in=10, tokens_out=5, cost_usd=0.0, latency_ms=12,
        declined_reason=declined_reason,
    )


# ---------------------------------------------------------------------------
# _present — the empty-vs-zero distinction
# ---------------------------------------------------------------------------

def test_absent_values_are_dropped_rather_than_stored_as_zero():
    """Storing the defaults would make "the ad does not say" indistinguishable from "the ad
    says zero", and an average taken over that is silently wrong."""
    kept = _present(AdSpecs(brand="apple", ram_gb=16, storage_gb=0, cpu=""))

    assert kept == {"brand": "apple", "ram_gb": 16}
    assert "storage_gb" not in kept and "cpu" not in kept


def test_a_listing_with_nothing_readable_yields_an_empty_dict():
    """The prompt's correct answer for a listing that is not hardware at all."""
    assert _present(AdSpecs()) == {}


# ---------------------------------------------------------------------------
# extract_specs — what reaches the database
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_specs_are_stored_against_the_prompt_version(ad):
    with patch("llm.extraction.complete", return_value=result(
        AdSpecs(brand="apple", model="MacBook Pro 14", ram_gb=16, storage_gb=512)
    )):
        row = extract_specs(ad)

    assert row.specs["ram_gb"] == 16
    assert row.prompt_version == "v1"
    assert row.declined_reason is None


@pytest.mark.django_db
def test_a_decline_is_still_written_down(ad):
    """"The model looked and had no opinion" is a different fact from "nothing looked" —
    the same call `AdPriceScore` makes, and the reason declines are persisted at all."""
    with patch("llm.extraction.complete", return_value=result(declined_reason="budget spent")):
        row = extract_specs(ad)

    assert row.specs == {}
    assert row.declined_reason == "budget spent"


@pytest.mark.django_db
def test_re_running_one_version_updates_rather_than_duplicating(ad):
    with patch("llm.extraction.complete", return_value=result(AdSpecs(ram_gb=16))):
        extract_specs(ad)
    with patch("llm.extraction.complete", return_value=result(AdSpecs(ram_gb=32))):
        extract_specs(ad)

    rows = AdSpecExtraction.objects.filter(ad=ad)
    assert rows.count() == 1
    assert rows.get().specs["ram_gb"] == 32


@pytest.mark.django_db
def test_the_full_description_is_preferred_over_the_snippet(ad):
    """The detail text is where the specs actually are; the listing snippet is truncated
    marketing."""
    ad.full_description = "16GB RAM, 512GB SSD, M1 Pro"
    ad.save(update_fields=["full_description"])

    with patch("llm.extraction.complete", return_value=result(AdSpecs())) as complete:
        extract_specs(ad)

    assert "512GB SSD" in complete.call_args.kwargs["prompt"]


@override_settings(LLM_PROVIDER="NULL")
@pytest.mark.django_db
def test_the_shipped_default_declines_and_opens_no_socket(ad):
    """`LLM_PROVIDER=NULL` is the default, so this must be a no-op that costs nothing and
    still leaves evidence that it ran."""
    row = extract_specs(ad)

    assert row.specs == {}
    assert row.declined_reason
    assert row.provider == "NULL"
