"""Tests for bazos/pricing/ — the feature extractor, the JSON artifact format, the
MacbookPriceModel gates, the scoring service, and PriceModelRule.

Design: docs/proposals/ML_PRICE_SCORING.md
"""
import json
import math

import pytest

from bazos.const import PRICE_MODEL_MIN_DISCOUNT_PCT, PRICE_MODEL_Z_THRESHOLD
from bazos.filters import DEFAULT_RULE_NAMES, RULE_REGISTRY, FilterResult, PriceModelRule
from bazos.models import Ad, AdDelivery, AdPriceScore, AdStatus, Marketplace, PriceType, Query
from bazos.pricing import artifacts, features
from bazos.pricing.artifacts import Manifest
from bazos.pricing.estimators.macbook import MacbookPriceModel
from bazos.pricing.scoring import score_ad

# ---------------------------------------------------------------------------
# Feature extraction (no DB)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,desc,expected",
    [
        # The two parsing traps that were live defects — MACBOOK_PRICE_MODEL.md §2.
        ("MacBook Pro 14 2021 / M1 Pro / 16GB RAM / 512GB SSD", "",
         {"ram_gb": 16, "ssd_gb": 512}),
        ("MacBook Air 13 M2 2022", "apple macbook air 8gb. 512gb ssd, zaruka do 04/2027",
         {"ram_gb": 8, "ssd_gb": 512, "year": 2022}),
        # M5 must parse: it was 25% of all chip-extraction failures before the widening.
        ("MacBook Pro 16 M5 Pro 48GB/1TB", "", {"chip_gen": 5, "chip_variant": "pro", "ssd_gb": 1000}),
        ("MacBook Pro 14 M3 Max 36GB/1TB", "", {"chip_gen": 3, "chip_variant": "max", "ram_gb": 36}),
    ],
)
def test_extractor_parses_specs(name, desc, expected):
    got = features.extract(name, desc)
    for key, value in expected.items():
        assert got[key] == value, f"{key}: {got[key]!r} != {value!r}"


def test_warranty_date_is_not_a_capacity():
    """`zaruka do 04/2027` must not become 4 GB RAM and a 2027 GB disk."""
    got = features.extract("MacBook Pro 14 M3 Max 36GB/1TB", "Zaruka do 04/2027.")
    assert got["ram_gb"] == 36
    assert got["ssd_gb"] == 1000


@pytest.mark.parametrize("name,ram,ssd", [
    ("MacBook Pro 13 2017 i5 128GB", None, 128),
    ("MacBook Air 2012 64GB", None, 64),
    ("MacBook Pro 16 M3 Max 128GB 4TB", 128, 4000),
    ("MacBook Pro 14 M3 Max 64GB RAM 1TB SSD", 64, 1000),
])
def test_ambiguous_capacity_needs_a_max_chip_to_be_ram(name, ram, ssd):
    """64 and 128 are both plausible capacities; only Apple's Max tier carries them as RAM."""
    got = features.extract(name, "")
    assert (got["ram_gb"], got["ssd_gb"]) == (ram, ssd)


def test_charge_cycles_from_nabijeno():
    assert features.extract("MacBook Pro", "Pouze 8x nabijeno.")["cycles"] == 8


def test_non_macbook_is_not_claimed():
    assert features.extract("Dell XPS 15 7590 i9 / 32GB", "")["kind"] != "macbook"


# ---------------------------------------------------------------------------
# Artifact format (no DB)
# ---------------------------------------------------------------------------


def _manifest(**over):
    data = dict(
        name="macbook", version="test", intercept=1.0,
        features=[
            {"kind": "num", "name": "year", "fill": 2020.0, "coef": 0.1},
            {"kind": "missing", "name": "year", "coef": -0.5},
            {"kind": "bool", "name": "warranty", "coef": 0.25},
            {"kind": "cat", "name": "chip_key", "value": "apple3_max", "coef": 2.0},
        ],
        residual_sigma=0.2,
        seller_sigma_prior={0: 0.30, 3: 0.17, 50: 0.07},
        raw={},
    )
    data.update(over)
    return Manifest(**data)


def test_evaluate_is_a_dot_product():
    m = _manifest()
    got = artifacts.evaluate(m, {"year": 2024.0, "warranty": True, "chip_key": "apple3_max"})
    assert got == pytest.approx(1.0 + 0.1 * 2024 + 0.25 + 2.0)


def test_evaluate_uses_fill_and_missing_indicator_together():
    m = _manifest()
    got = artifacts.evaluate(m, {"year": None, "warranty": False, "chip_key": None})
    assert got == pytest.approx(1.0 + 0.1 * 2020.0 - 0.5)


def test_sigma_prior_widens_for_unknown_sellers():
    """A first-time seller must get a wider sigma than an established dealer, or a flat
    threshold means different things for each — MACBOOK_PRICE_MODEL.md §5."""
    m = _manifest()
    assert m.sigma_for(0) == 0.30
    assert m.sigma_for(5) == 0.17
    assert m.sigma_for(200) == 0.07
    assert m.sigma_for(0) > m.sigma_for(200)


def test_unusable_artifact_returns_none_not_raises(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    (root / "macbook" / "v1").mkdir(parents=True)
    (root / "macbook" / "v1" / "manifest.json").write_text("{ not json")
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", root)
    assert artifacts.load_manifest("macbook", "v1") is None


def test_unknown_feature_kind_is_rejected(tmp_path, monkeypatch):
    """An artifact from a newer trainer must fail loudly, not score by silently ignoring
    features it does not understand."""
    root = tmp_path / "artifacts"
    (root / "macbook" / "v1").mkdir(parents=True)
    (root / "macbook" / "v1" / "manifest.json").write_text(json.dumps({
        "name": "macbook", "version": "v1", "intercept": 1.0,
        "features": [{"kind": "polynomial", "name": "year", "coef": 1.0}],
    }))
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", root)
    assert artifacts.load_manifest("macbook", "v1") is None


def test_pickle_artifacts_are_refused(tmp_path, monkeypatch):
    """`kind: joblib` must be refused while sklearn is not a runtime dependency."""
    root = tmp_path / "artifacts"
    (root / "macbook" / "v1").mkdir(parents=True)
    (root / "macbook" / "v1" / "manifest.json").write_text(json.dumps({
        "name": "macbook", "version": "v1", "intercept": 0.0, "kind": "joblib",
        "features": [{"kind": "num", "name": "year", "coef": 1.0}],
    }))
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", root)
    assert artifacts.load_manifest("macbook", "v1") is None


# ---------------------------------------------------------------------------
# Model + scoring (DB)
# ---------------------------------------------------------------------------


def _ad(**over):
    data = dict(
        external_id=1, marketplace=Marketplace.BAZOS, url="https://x/1",
        name="MacBook Pro 14 2023 / M3 Max / 36GB RAM / 1TB SSD",
        price_raw="45 000 Kc", price=45_000, price_type=PriceType.EXACT,
        location="Praha", short_description="Perfektni stav.", publisher_name="x",
    )
    data.update(over)
    return Ad.objects.create(**data)


@pytest.fixture
def model(monkeypatch):
    """A MacbookPriceModel with a deterministic in-memory artifact."""
    m = MacbookPriceModel()
    manifest = _manifest(
        intercept=math.log(50_000),
        features=[{"kind": "bool", "name": "warranty", "coef": 0.0}],
        seller_sigma_prior={0: 0.20},
        residual_sigma=0.20,
    )
    monkeypatch.setattr(type(m), "manifest", property(lambda self: manifest))
    return m


@pytest.mark.django_db
def test_model_claims_only_bazos_macbooks(model):
    assert model.applies_to(_ad()) is True
    assert model.applies_to(_ad(external_id=2, name="Dell XPS 15 i9 32GB")) is False
    assert model.applies_to(_ad(external_id=3, marketplace=Marketplace.VINTED)) is False


@pytest.mark.django_db
def test_predict_returns_residual_and_z(model):
    pred = model.predict(_ad())
    assert pred is not None
    assert pred.predicted == pytest.approx(50_000, abs=2)
    # 45000 vs 50000 -> ~10.5% below, and z = residual / 0.20
    assert pred.discount_pct == pytest.approx(10.0, abs=0.5)
    assert pred.z_score == pytest.approx(math.log(45_000 / 50_000) / 0.20, abs=1e-6)


@pytest.mark.django_db
@pytest.mark.parametrize("over,why", [
    (dict(name="MacBook Pro M3 Max"), "incomplete specs"),
    (dict(short_description="Displej je prasklý, nefunkcni."), "damage language"),
    (dict(price=None, price_type=PriceType.NEGOTIABLE), "no exact price"),
])
def test_model_declines_rather_than_guessing(model, over, why):
    assert model.predict(_ad(**over)) is None, why


@pytest.mark.django_db
def test_missing_artifact_declines(monkeypatch):
    m = MacbookPriceModel()
    monkeypatch.setattr(type(m), "manifest", property(lambda self: None))
    assert m.predict(_ad()) is None


@pytest.mark.django_db
def test_score_ad_persists_and_is_idempotent(model, monkeypatch):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    ad = _ad()
    first = score_ad(ad)
    assert first is not None and first.predicted == pytest.approx(50_000, abs=2)
    second = score_ad(ad)
    assert AdPriceScore.objects.filter(ad=ad).count() == 1
    assert second.pk == first.pk


@pytest.mark.django_db
def test_declined_score_is_still_recorded(model, monkeypatch):
    """"A model looked and had no opinion" must be distinguishable from "nothing looked"."""
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    score = score_ad(_ad(name="MacBook Pro M3 Max"))
    assert score is not None
    assert score.predicted is None
    assert score.declined_reason


@pytest.mark.django_db
def test_score_ad_returns_none_when_no_model_applies(model, monkeypatch):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    assert score_ad(_ad(name="Dell XPS 15 i9 32GB 1TB")) is None


# ---------------------------------------------------------------------------
# The filter rule
# ---------------------------------------------------------------------------


def _delivery(ad):
    q = Query.objects.create(text="macbook", price_lower=0, price_upper=0)
    return AdDelivery.objects.create(ad=ad, query=q, status=AdStatus.PENDING)


def test_price_model_is_not_a_default_rule():
    """It REJECTs anything that is not a deal, so switching it on by default would mute
    every existing query."""
    assert "price_model" in RULE_REGISTRY
    assert "price_model" not in DEFAULT_RULE_NAMES


@pytest.mark.django_db
def test_rule_passes_in_shadow_mode(model, monkeypatch, settings):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    settings.PRICE_MODEL_SHADOW_MODE = True
    ad = _ad(price=20_000)  # a huge discount — would reject if shadow mode were off
    result, _ = PriceModelRule().apply(_delivery(ad))
    assert result == FilterResult.PASS
    # ...but the score is still written, which is the point of shadow mode.
    assert AdPriceScore.objects.filter(ad=ad).exists()


@pytest.mark.django_db
def test_rule_rejects_a_non_deal_when_live(model, monkeypatch, settings):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    settings.PRICE_MODEL_SHADOW_MODE = False
    result, reason = PriceModelRule().apply(_delivery(_ad(price=49_500)))
    assert result == FilterResult.REJECT
    assert reason is not None and "not a deal" in reason


@pytest.mark.django_db
def test_rule_passes_a_real_deal_when_live(model, monkeypatch, settings):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    settings.PRICE_MODEL_SHADOW_MODE = False
    ad = _ad(price=25_000)  # ~-69% -> z well past -2.0
    score = score_ad(ad)
    assert float(score.z_score) <= PRICE_MODEL_Z_THRESHOLD
    assert float(score.discount_pct) >= PRICE_MODEL_MIN_DISCOUNT_PCT
    result, _ = PriceModelRule().apply(_delivery(ad))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_rule_passes_when_the_model_declines(model, monkeypatch, settings):
    """A model that cannot score must not silently drop everything."""
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": model})
    settings.PRICE_MODEL_SHADOW_MODE = False
    result, _ = PriceModelRule().apply(_delivery(_ad(name="MacBook Pro M3 Max")))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_rule_passes_when_scoring_raises(monkeypatch, settings):
    settings.PRICE_MODEL_SHADOW_MODE = False

    def boom(*a, **kw):
        raise RuntimeError("artifact exploded")

    monkeypatch.setattr("bazos.pricing.scoring.score_ad", boom)
    result, _ = PriceModelRule().apply(_delivery(_ad()))
    assert result == FilterResult.PASS
