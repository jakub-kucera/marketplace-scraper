"""Registry, artifact-version and read-path semantics once more than one model is registered.

Every test here pins something that is harmless at N=1 and silently wrong at N=2, and all four
are the prerequisites `docs/backlog/PRICE_MODEL_DEFECTS.md` §13 names by number as the condition
for registering a second model:

- **§8** — `marketplaces` gates `applies_to`, and no two models claim the same ad. Registry order
  used to decide that silently: reordering a dict literal re-labelled ads with no log line.
- **§7** — one artifact version per model. A single global string meant pinning `macbook` resolved
  `iphone` against a directory that does not exist, which declines, which on a deals-only query
  APPROVEs everything.
- **§9** — both `AdPriceScore` read paths filter on `model_name`. `-created` otherwise surfaces
  whichever model scored an ad *later*, which need not be the one that governed the decision.
- **§11** — the shipped artifact is loaded from disk, and every feature it names is producible by
  the model's own `extract()`. Catches a retrain that renamed a feature.
"""
import pytest

from bazos.models import Ad, AdPriceScore, Marketplace, PriceType
from bazos.pricing import artifacts
from bazos.pricing.registry import MODEL_REGISTRY, get_price_model


def _ad(n, name, marketplace=Marketplace.BAZOS, price=20_000, desc=""):
    return Ad.objects.create(
        external_id=n, marketplace=marketplace, url=f"https://x/{n}", name=name,
        price_raw=f"{price} Kc", price=price, price_type=PriceType.EXACT,
        location="Praha 1, 110 00", short_description=desc, publisher_name="x",
    )


# --------------------------------------------------------------------- §8
def test_every_registered_model_declares_its_marketplaces():
    """A protocol member, not a convention: `get_price_model` consults it before `applies_to`."""
    for name, model in MODEL_REGISTRY.items():
        assert isinstance(getattr(model, "marketplaces", None), frozenset), (
            f"{name} must declare `marketplaces` as a frozenset"
        )
        assert model.marketplaces, f"{name} declares an empty marketplace set, so it claims nothing"
        unknown = model.marketplaces - set(Marketplace.values)
        assert not unknown, f"{name} names marketplaces that do not exist: {sorted(unknown)}"


def test_registry_keys_match_the_models_own_names():
    """`AdPriceScore.model_name` is written from `model.name`; a mismatched key orphans rows."""
    for key, model in MODEL_REGISTRY.items():
        assert model.name == key


@pytest.mark.django_db
@pytest.mark.parametrize("name,desc,expected", [
    ("Apple iPhone 15 Pro 256GB", "Stav pekny, baterie 92 %.", "iphone"),
    ("MacBook Pro 14 2023 M3 Max 36GB 1TB", "Zaruka do 2027.", "macbook"),
    # ⚠️ An iPad accessory, claimed by `macbook` because its *description* names a MacBook.
    # This pins a **known pre-existing defect**, not desired behaviour: `MacbookPriceModel`
    # has no product gate, so dealer boilerplate in `short_description` pulls accessories and
    # bare parts into its claim set (measured 22 ads, 0.7%; the live example in
    # docs/backlog/PRICE_MODEL_DEFECTS.md §8 is a bare logic board that scores and fires).
    # It is not a mutual-exclusivity failure -- exactly one model claims it -- so it does not
    # block a second model, and fixing it changes which production ads get scored. When that
    # gate is built, this expectation becomes None and the change is visible here.
    ("Apple iPad Magic Keyboard pro iPad Pro", "Kompatibilni s iPhone i MacBook.", "macbook"),
])
def test_exactly_one_model_claims_an_unambiguous_ad(name, desc, expected):
    ad = _ad(1, name, desc=desc)

    claimants = [
        key for key, model in MODEL_REGISTRY.items()
        if ad.marketplace in model.marketplaces and model.applies_to(ad)
    ]

    assert claimants == ([expected] if expected else [])


@pytest.mark.django_db
def test_an_ad_two_models_claim_is_claimed_by_neither():
    """Order cannot express "neither of us should claim this", which is what §8.1 asks for.

    A title naming two product families is not a tie to be broken by dict order: neither
    model is fitted on it, and a confident number from the wrong coefficients is worse than
    no number. This is the one real overlap class the corpus contains.
    """
    ad = _ad(2, "Prodam iPhone 13, k nemu pridam i MacBook Air obal", desc="Na iPhone je zaruka.")

    claimants = [
        key for key, model in MODEL_REGISTRY.items()
        if ad.marketplace in model.marketplaces and model.applies_to(ad)
    ]

    assert len(claimants) > 1, "fixture no longer exercises the overlap; find another"
    assert get_price_model(ad) is None


@pytest.mark.django_db
def test_marketplaces_is_checked_before_applies_to(monkeypatch):
    """The cheap gate runs first, so a model never has to defend itself against another site."""
    def explode(self, ad):
        raise AssertionError("applies_to must not be reached for a marketplace it does not claim")

    for model in MODEL_REGISTRY.values():
        monkeypatch.setattr(type(model), "marketplaces", frozenset({Marketplace.SBAZAR}), raising=False)
        monkeypatch.setattr(type(model), "applies_to", explode)

    assert get_price_model(_ad(3, "Apple iPhone 15 Pro 256GB")) is None


# --------------------------------------------------------------------- §7
def test_each_model_resolves_its_own_artifact_version(settings):
    """Pinning one model must not disable another — the failure direction that APPROVEs everything."""
    names = list(MODEL_REGISTRY)
    assert len(names) >= 2, "this is the N=2 guarantee; it is vacuous with one model"

    settings.PRICE_MODEL_VERSIONS = {names[0]: "does-not-exist"}

    pinned = type(MODEL_REGISTRY[names[0]])()
    others = [type(MODEL_REGISTRY[n])() for n in names[1:]]

    assert pinned.manifest is None, "the pinned model should resolve to a version that is absent"
    for model in others:
        assert model.manifest is not None, (
            f"{model.name} lost its artifact because {names[0]} was pinned"
        )


def test_a_global_version_pin_still_works_for_a_single_model(settings):
    """`PRICE_MODEL_VERSION` predates the dict and is still the documented rollback lever."""
    name = next(iter(MODEL_REGISTRY))
    versions = artifacts.available_versions(name)
    assert versions, f"{name} ships no artifact"

    settings.PRICE_MODEL_VERSIONS = {}
    settings.PRICE_MODEL_VERSION = versions[-1]

    assert type(MODEL_REGISTRY[name])().version == versions[-1]


def test_the_per_model_dict_beats_the_global_string(settings):
    name = next(iter(MODEL_REGISTRY))
    settings.PRICE_MODEL_VERSION = "does-not-exist"
    settings.PRICE_MODEL_VERSIONS = {name: "latest"}

    assert type(MODEL_REGISTRY[name])().manifest is not None


# --------------------------------------------------------------------- §11
@pytest.mark.parametrize("name", sorted(MODEL_REGISTRY))
def test_the_shipped_artifact_loads_from_disk(name):
    """Not a tmp_path fixture. A corrupt committed artifact reaches production as a silent decline."""
    manifest = artifacts.load_manifest(name)

    assert manifest is not None, f"bazos/pricing/artifacts/{name}/ has no loadable artifact"
    assert manifest.name == name
    assert manifest.features


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(MODEL_REGISTRY))
def test_every_artifact_feature_is_producible_by_the_extractor(name):
    """The "retrained with a renamed feature" skew: it scores, and it scores wrong."""
    model = MODEL_REGISTRY[name]
    manifest = artifacts.load_manifest(name)
    produced = set(model.extract(_ad(3, "Apple iPhone 15 Pro 256GB 92% baterie zaruka")))

    named = {feat["name"] for feat in manifest.features}
    missing = named - produced

    assert not missing, f"{name}'s artifact names features its extract() never emits: {sorted(missing)}"


# --------------------------------------------------------------------- §9
@pytest.mark.django_db
def test_current_price_score_is_keyed_by_model_name():
    """Two rows, and `-created` alone surfaces whichever model scored the ad later."""
    ad = _ad(4, "Apple iPhone 15 Pro 256GB")
    AdPriceScore.objects.create(ad=ad, model_name="iphone", model_version="t",
                                predicted=18_000, residual_log=0.1, z_score=-0.5)
    AdPriceScore.objects.create(ad=ad, model_name="macbook", model_version="t",
                                predicted=99_000, residual_log=-1.6, z_score=-7.0)

    score = ad.current_price_score()

    assert score is not None
    assert score.model_name == "iphone", "the score must come from the model that claims the ad"


@pytest.mark.django_db
def test_a_score_from_an_unregistered_model_is_not_read_back():
    """Nothing deletes an `AdPriceScore`, so a rename leaves stale rows behind forever."""
    ad = _ad(5, "Apple iPhone 15 Pro 256GB")
    AdPriceScore.objects.create(ad=ad, model_name="iphone_v0_retired", model_version="t",
                                predicted=1_000, residual_log=-2.9, z_score=-9.0)

    assert ad.current_price_score() is None


def _changelist_row(admin_client, ad):
    from django.contrib.admin.sites import site
    from django.urls import reverse

    from bazos.admin import AdAdmin

    request = admin_client.get(reverse("admin:bazos_ad_changelist")).wsgi_request
    return AdAdmin(Ad, site).get_queryset(request).get(pk=ad.pk)


@pytest.mark.django_db
def test_changelist_ignores_scores_from_unregistered_models(admin_client):
    """Nothing deletes an `AdPriceScore`, so a rename leaves stale rows with stale numbers."""
    ad = _ad(6, "Apple iPhone 15 Pro 256GB")
    AdPriceScore.objects.create(ad=ad, model_name="iphone_v0_retired", model_version="t",
                                predicted=1_000, residual_log=-2.9, discount_pct=94.5, z_score=-9.0)

    assert _changelist_row(admin_client, ad).price_z is None


@pytest.mark.django_db
def test_changelist_tiebreak_is_registry_order_not_write_order(admin_client):
    """Two non-declined rows can only come from a registry change, and `-created` is not a rule.

    SQL cannot run `applies_to`, so the changelist cannot pick *the claiming* model the way
    `Ad.current_price_score()` does. What it can do is be deterministic: registry order, so
    the column does not change meaning because a later pass happened to write second.
    """
    ad = _ad(7, "Apple iPhone 15 Pro 256GB")
    first = list(MODEL_REGISTRY)[0]
    second = list(MODEL_REGISTRY)[1]
    # written in reverse registry order, so `-created` alone would surface `second`
    AdPriceScore.objects.create(ad=ad, model_name=first, model_version="t",
                                predicted=99_000, residual_log=-1.6, discount_pct=79.8, z_score=-7.0)
    AdPriceScore.objects.create(ad=ad, model_name=second, model_version="t",
                                predicted=18_000, residual_log=0.1, discount_pct=-10.0, z_score=-0.5)

    assert _changelist_row(admin_client, ad).price_z == pytest.approx(-7.0)
