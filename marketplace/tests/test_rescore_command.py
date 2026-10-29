"""Tests for `manage.py rescore_ads`.

The gap it closes: `score_ad` treats a row as fresh when its `model_version` matches the
artifact's, so a field added to `AdPriceScore` after a row was written stays null on that
row forever — the pipeline seeing the ad again changes nothing.
"""
from io import StringIO

import pytest
from django.core.management import call_command

from marketplace.models import AdPriceScore
from marketplace.pricing.scoring import score_ad
from marketplace.tests.test_pricing import _ad, model  # noqa: F401 — `model` is a fixture


@pytest.fixture
def registered(monkeypatch, model):  # noqa: F811
    monkeypatch.setattr("marketplace.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    return model


def _run(*args):
    out = StringIO()
    call_command("rescore_ads", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def _score_then_blank_features(ad):
    """The state this command exists for: a row written by code that had no `features`."""
    score = score_ad(ad)
    AdPriceScore.objects.filter(pk=score.pk).update(features=None)
    return score


@pytest.mark.django_db
def test_pipeline_alone_never_refills_features(registered):
    """The bug, pinned. Without this command the row stays null however often it is seen."""
    ad = _ad(price=40_000)
    score = _score_then_blank_features(ad)

    score_ad(ad)
    score_ad(ad)

    score.refresh_from_db()
    assert score.features is None


@pytest.mark.django_db
def test_rescore_refills_features(registered):
    ad = _ad(price=40_000)
    score = _score_then_blank_features(ad)

    output = _run()

    score.refresh_from_db()
    assert score.features is not None
    assert "Rescored 1 ads" in output


@pytest.mark.django_db
def test_dry_run_writes_nothing(registered):
    ad = _ad(price=40_000)
    score = _score_then_blank_features(ad)

    output = _run("--dry-run")

    score.refresh_from_db()
    assert score.features is None
    assert "1 ads to rescore" in output


@pytest.mark.django_db
def test_missing_features_skips_rows_that_already_have_them(registered):
    ad = _ad(price=40_000)
    score_ad(ad)  # written with features

    output = _run("--missing-features", "--dry-run")

    assert "0 ads to rescore" in output


@pytest.mark.django_db
def test_missing_features_skips_declined_rows(registered):
    """A declined row's null features are correct, not a gap — rescoring it would just
    decline again for the same reason."""
    score = score_ad(_ad(name="MacBook Pro M3 Max"))
    assert score.declined_reason and score.features is None

    output = _run("--missing-features", "--dry-run")

    assert "0 ads to rescore" in output


@pytest.mark.django_db
def test_model_filter_restricts_the_set(registered):
    ad = _ad(price=40_000)
    _score_then_blank_features(ad)

    assert "0 ads to rescore" in _run("--model", "not-a-model", "--dry-run")
    assert "1 ads to rescore" in _run("--model", "macbook", "--dry-run")


@pytest.mark.django_db
def test_one_broken_ad_does_not_end_the_run(registered, monkeypatch):
    """A backfill's useful outcome is "as many as possible", not all-or-nothing."""
    _score_then_blank_features(_ad(price=40_000, external_id=901))
    _score_then_blank_features(_ad(price=41_000, external_id=902))

    calls = {"n": 0}
    real = score_ad

    def flaky(ad, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("artifact exploded")
        return real(ad, **kwargs)

    monkeypatch.setattr("marketplace.management.commands.rescore_ads.score_ad", flaky)
    output = _run()

    assert "1 failed" in output
    assert AdPriceScore.objects.filter(features__isnull=False).count() == 1


@pytest.mark.django_db
def test_reports_a_row_that_now_declines(registered, monkeypatch):
    """Rescoring can legitimately change the verdict — say so rather than counting it as
    a success."""
    ad = _ad(price=40_000)
    _score_then_blank_features(ad)
    monkeypatch.setattr(type(registered), "predict", lambda self, ad: None)

    output = _run()

    assert "1 now decline" in output
