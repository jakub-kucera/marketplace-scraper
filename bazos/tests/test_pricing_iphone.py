"""The iPhone extractor and price model.

Most of these pin a defect that was measured on a real corpus rather than imagined, and the
parametrised extractor cases are organised by the six traps that took a first fit from
R² 0.78 to 0.93. Research: `docs/research/IPHONE_PRICE_MODEL.md`.

The gates matter more here than on MacBook, and for a different reason: the MacBook model
declines what is written badly, this one declines what *is not an asking price for one
phone*. A resold pre-order is a deposit, a want-to-buy is a bid, a two-phone lot is two
phones. Each produces a confident number from a quantity the model does not model.
"""
import math
from datetime import date

import pytest

from bazos.models import Ad, Marketplace, PriceType
from bazos.pricing import artifacts, features_iphone as fx
from bazos.pricing.estimators.iphone import IPhonePriceModel

TODAY = date(2026, 10, 15)


def _ad(name, desc="", price=15_000, marketplace=Marketplace.BAZOS, price_type=PriceType.EXACT):
    return Ad(
        external_id=1, marketplace=marketplace, url="https://x/1", name=name,
        price_raw=f"{price} Kc", price=price, price_type=price_type,
        location="Praha 1, 110 00", short_description=desc, publisher_name="x",
    )


# ------------------------------------------------------------------ model phrase
@pytest.mark.parametrize("title,gen_label,tier,storage", [
    ("Apple iPhone 15 Pro 256GB", "15", "pro", 256),
    ("iPhone 16 Pro Max 1TB", "16", "pro max", 1024),
    ("iPhone 13 mini 128 GB", "13", "mini", 128),
    ("Apple iPhone 14 Plus 256GB", "14", "plus", 256),
    # The `e` line only when glued to the digits -- `16 e` is not an iPhone 16e.
    ("Apple iPhone 16e 128GB Black", "16e", "e", 128),
    ("IPhone Apple 16e", "16e", "e", None),
    # Trap 3: a whole product line the naive pattern misses entirely.
    ("Apple iPhone Air 256GB cerny", "17", "air", 256),
    ("iPhone Air", "17", "air", None),
    # Lettered generations are not numbers.
    ("iPhone XS Max 64 GB Gold", "xs", "max", 64),
    ("Apple iPhone XR 64GB cerny", "xr", "base", 64),
    ("iPhone X 64GB", "x", "base", 64),
    # SE is placed by its chip, which is what the market prices.
    ("Apple iPhone SE 2020 64gb", "se11", "se", 64),
    ("iPhone SE (2022) 64GB Starlight", "se13", "se", 64),
    # No `iPhone` token at all: `apple` is an accepted anchor.
    ("Apple 17 Pro 256Gb", "17", "pro", 256),
    # Unspaced.
    ("iphone16pro128 gb", "16", "pro", 128),
])
def test_model_phrase_and_storage(title, gen_label, tier, storage):
    feats = fx.extract(title, today=TODAY)

    assert feats["gen_label"] == gen_label
    assert feats["tier"] == tier
    assert feats["storage_gb"] == storage


@pytest.mark.parametrize("title", [
    # Trap 2, and the bug that created phantom model tiers: `strip_diacritics` turns the
    # Czech colour words into `cerny` / `salvejove`, and a suffix alternation allowing the
    # 5s/5c forms ate their leading letter -- model key `17_c`, `17_s`.
    "iPhone 17 cerny 256GB",
    "Iphone 17 salvejove zelena 256GB",
    "iPhone 17 strieborny, 256 GB",
])
def test_a_czech_colour_word_is_not_a_model_variant(title):
    feats = fx.extract(title, today=TODAY)

    assert feats["gen_label"] == "17"
    assert feats["tier"] == "base"


def test_a_tier_word_separated_by_a_capacity_is_deliberately_not_consumed():
    """`iPhone 18 512GB pro` reads as a base 18, and the miss is the cheaper mistake.

    Consuming a tier word across a capacity token needs the search to leave the position
    straight after the generation, and in Czech `pro` is also the preposition "for". Measured
    on 7 323 titles: **one** has a tier word after a capacity (this one) and none has the
    preposition there -- but the corpus not containing a hazard is not the same as the hazard
    not existing, and the two errors are not symmetric. Missing a Pro under-prices one
    listing; reading `128GB pro nenarocneho uzivatele` as a Pro over-predicts ~30%, which
    turns a fair ask into a deal. Pinned so nobody "fixes" it without re-measuring both.
    """
    feats = fx.extract("iPhone 18 512GB pro", today=TODAY)

    assert (feats["gen_label"], feats["tier"]) == ("18", "base")


def test_pro_max_is_never_read_as_pro():
    assert fx.extract("iPhone 15 Pro Max 256GB", today=TODAY)["tier"] == "pro max"


def test_the_first_model_phrase_wins():
    """Sellers state the product first and a trade-in offer or comparison second."""
    feats = fx.extract("iPhone 13 Pro 256GB", "Vykupujeme i iPhone 16 Pro Max.", today=TODAY)

    assert feats["gen_label"] == "13"


# ------------------------------------------------------------------ the live generation axis
def test_a_generation_newer_than_the_artifact_still_prices():
    """The launch-day failure: frozen levels collapse to the intercept on a new generation.

    An ordinal read off the digits extrapolates, which is the whole structural bet (§3.1:
    mean R² +0.404 against −7.18 with a generation held out).
    """
    feats = fx.extract("Apple iPhone 19 Pro Max 512GB", today=date(2027, 10, 1))

    assert feats["gen_label"] == "19"
    assert feats["gen_age_m"] == 1.0, "September 2027 release, read one month later"


@pytest.mark.parametrize("label,expected_months", [
    ("18", 1.0),    # September 2026
    ("17", 13.0),   # September 2025
    ("13", 61.0),   # September 2021
    ("x", 107.0),   # November 2017
    ("se11", 85.0),  # placed on the 11's release, by chip
])
def test_generation_age_in_months(label, expected_months):
    assert fx.gen_age_months(label, today=TODAY) == expected_months


def test_a_pre_release_generation_gets_age_zero_not_a_negative():
    assert fx.gen_age_months("19", today=TODAY) == 0.0


def test_an_unparseable_generation_has_no_age():
    assert fx.gen_age_months(None) is None
    assert fx.gen_age_months("nonsense") is None


# ------------------------------------------------------------------ the gated classes
@pytest.mark.parametrize("title,desc,kind", [
    ("Koupim iPhone 15 Pro", "", "wtb"),
    ("Apple iPhone VYKUPP", "", "wtb"),
    ("Obal na iPhone 17 Pro", "", "accessory"),
    ("Tvrzene sklo pro iPhone 13", "", "accessory"),
    ("iPhone 11 na dily", "", "parts"),
    ("IPhone displeje=X,XR,11,11Pro", "", "parts"),
    ("Apple iPad Magic Keyboard", "Pro iPad Pro.", "other_apple"),
    ("Samsung Galaxy S24", "", "other_brand"),
    # A phone with a case thrown in is still a phone.
    ("iPhone 13 Pro 128gb cerny a kryt", "Jeden kryt soucasti.", "iphone"),
])
def test_product_kind(title, desc, kind):
    feats = fx.extract(title, desc, today=TODAY)

    assert feats["kind"] == kind


@pytest.mark.parametrize("title,desc", [
    # Trap 1, the largest single defect: a resold place in the pre-order queue. The ask is a
    # deposit of ~1 000 CZK against a ~35 000 CZK phone.
    ("Prenechani rezervace iPhone 18 Pro Max 512 GB", ""),
    ("iPhone 18 Pro Max 256 GB k vyzvednuti od 26. 9. 2026", ""),
    ("Objednavka iPhone 18 Pro 256 GB", ""),
    ("iPhone 18 Pro 256GB", "Prodam rezervaci, zaloha 1000 Kc."),
])
def test_a_resold_preorder_is_recognised(title, desc):
    assert fx.extract(title, desc, today=TODAY)["reservation"] is True


def test_a_multi_variant_dealer_ad_is_recognised():
    """Trap 4: the ask is the cheapest configuration and the parsed capacity is another one."""
    feats = fx.extract("iPhone 18 Pro Max 256GB/512GB/1TB", today=TODAY)

    assert feats["storage_variants"] == 3


def test_a_single_capacity_repeated_is_not_a_multi_variant_ad():
    feats = fx.extract("iPhone 15 Pro 256GB", "Pamet 256 GB, cerna.", today=TODAY)

    assert feats["storage_variants"] == 1


@pytest.mark.parametrize("title,flag", [
    ("PRODANO iPhone 12 PRO, 512GB", "marked_sold"),
    ("2x iPhone 11 64 gb", "multipack"),
])
def test_stale_and_lot_listings_are_flagged(title, flag):
    assert fx.extract(title, today=TODAY)[flag] is True


# ------------------------------------------------------------------ negation
def test_a_denial_of_damage_does_not_set_the_damage_flag():
    assert fx.extract("iPhone 13", "Zadne skrabance, bez poskozeni.", today=TODAY)["scratches"] is False


def test_a_cracked_back_glass_is_damage_despite_the_collapsed_diacritic():
    """The defect `experiments/.../ipfeat.py` leaves in on purpose, fixed here.

    `strip_diacritics` collapses `zadny` ("none") onto `zadni` ("rear"), so a cracked back
    glass read as a denial. Measured: 6 of 26 crack-word rows missed, and 2 of 25 gated alert
    flags were cracked phones. The disambiguator is the intervening copula.
    """
    assert fx.extract("iPhone 13", "Zadni sklo je prasklé.", today=TODAY)["damage"] is True


def test_a_negated_copula_is_still_a_denial():
    """`displej ani zadni sklo nejsou prasklé` needs both readings at once."""
    feats = fx.extract("iPhone 13", "Displej ani zadni sklo nejsou prasklé.", today=TODAY)

    assert feats["damage"] is False


def test_the_ne_prefix_negates_but_nefunkcni_is_still_damage():
    assert fx.extract("iPhone 13", "Telefon je neposkozeny.", today=TODAY)["damage"] is False
    assert fx.extract("iPhone 13", "Nefunkcni, nezapina.", today=TODAY)["damage"] is True


def test_an_unlocked_phone_is_not_flagged_as_locked():
    assert fx.extract("iPhone 13", "Neblokovany na operatora.", today=TODAY)["locked"] is False
    assert fx.extract("iPhone 13", "Blokovany na operatora.", today=TODAY)["locked"] is True


# ------------------------------------------------------------------ battery and warranty
def test_battery_health_from_several_phrasings():
    for desc in ("Baterie 89 %.", "Kapacita baterie: 89%", "89 % kondice baterie", "zdravi 89 %"):
        assert fx.extract("iPhone 13 128GB", desc, today=TODAY)["battery_pct"] == 89


def test_a_bare_percentage_counts_only_in_the_title_and_not_when_it_qualifies_something_else():
    assert fx.extract("iPhone 13 - 256GB - 100% - 12M ZARUKA", today=TODAY)["battery_pct"] == 100
    assert fx.extract("iPhone 13 256GB 100% funkcni", today=TODAY)["battery_pct"] is None


def test_a_warranty_date_is_not_a_capacity_or_a_battery_level():
    """The trap `features.py` documents for MacBook, re-tested on this extractor's regexes."""
    feats = fx.extract("iPhone 15 Pro 256GB", "Zaruka do 04/2027.", today=TODAY)

    assert feats["storage_gb"] == 256
    assert feats["battery_pct"] is None


def test_warranty_months():
    assert fx.extract("iPhone 15", "Zaruka 12 mesicu.", today=TODAY)["warranty_months"] == 12
    assert fx.extract("iPhone 15", "2 roky zaruka.", today=TODAY)["warranty_months"] == 24


def test_storage_is_log2_so_a_unit_step_is_one_doubling():
    feats = fx.extract("iPhone 15 Pro 256GB", today=TODAY)

    assert feats["storage_log2"] == pytest.approx(8.0)


# ------------------------------------------------------------------ the model
@pytest.fixture
def model():
    return IPhonePriceModel()


def test_the_shipped_artifact_is_loadable(model):
    assert model.manifest is not None
    assert model.version != "unavailable"


@pytest.mark.django_db
def test_claims_a_bazos_iphone_and_nothing_else(model):
    assert model.applies_to(_ad("Apple iPhone 15 Pro 256GB")) is True
    assert model.applies_to(_ad("MacBook Pro 14 M3 Max")) is False
    assert model.applies_to(_ad("Obal na iPhone 15 Pro")) is False
    assert model.applies_to(_ad("Apple iPhone 15 Pro", marketplace=Marketplace.SBAZAR)) is False


@pytest.mark.django_db
def test_predict_returns_a_residual_and_a_z(model):
    prediction = model.predict(_ad("Apple iPhone 15 Pro 256GB", "Baterie 95 %, zaruka.", price=13_000))

    assert prediction is not None
    assert prediction.predicted > 0
    # `predicted` is rounded to whole CZK, so this is the rounding tolerance, not a fudge.
    assert prediction.residual_log == pytest.approx(math.log(13_000 / prediction.predicted), abs=1e-3)
    assert prediction.z_score is not None


@pytest.mark.django_db
def test_a_cheap_listing_scores_as_a_discount_and_a_dear_one_does_not(model):
    cheap = model.predict(_ad("Apple iPhone 15 Pro 256GB", "Baterie 95 %.", price=6_000))
    dear = model.predict(_ad("Apple iPhone 15 Pro 256GB", "Baterie 95 %.", price=28_000))

    assert cheap.discount_pct > 0 and cheap.z_score < 0
    assert dear.discount_pct < 0 and dear.z_score > 0


@pytest.mark.django_db
@pytest.mark.parametrize("ad_kwargs,why", [
    (dict(name="Koupim iPhone 15 Pro 256GB"), "a bid is not an ask"),
    (dict(name="Obal na iPhone 15 Pro"), "an accessory is not a phone"),
    (dict(name="iPhone 15 Pro 256GB na dily"), "parts are not a phone"),
    (dict(name="Prenechani rezervace iPhone 18 Pro Max 512GB", price=1_000), "a deposit is not an ask"),
    (dict(name="2x iPhone 11 64GB", price=6_500), "two phones for one price"),
    (dict(name="PRODANO iPhone 12 Pro 512GB"), "already sold, price may be stale"),
    (dict(name="iPhone 18 Pro Max 256GB/512GB/1TB", price=30_000), "several configurations, one price"),
    (dict(name="Apple iPhone Pro 256GB"), "no generation stated"),
    (dict(name="Apple iPhone 15 Pro"), "no storage stated"),
    (dict(name="Apple iPhone 15 Pro 256GB", price=100), "ask below the floor"),
    (dict(name="Apple iPhone 15 Pro 256GB", price=120_000), "ask above the ceiling"),
    (dict(name="Apple iPhone 15 Pro 256GB", price_type=PriceType.NEGOTIABLE), "no parsed price"),
])
def test_declines_rather_than_guessing(model, ad_kwargs, why):
    assert model.predict(_ad(**ad_kwargs)) is None, why


@pytest.mark.django_db
def test_a_damaged_phone_is_priced_rather_than_declined(model):
    """Damage is a trained feature here, not a gate -- and it must move the prediction down."""
    clean = model.predict(_ad("Apple iPhone 15 Pro 256GB", "Bez poskozeni.", price=13_000))
    broken = model.predict(_ad("Apple iPhone 15 Pro 256GB", "Prasklé zadni sklo.", price=13_000))

    assert broken is not None
    assert broken.predicted < clean.predicted


@pytest.mark.django_db
def test_decline_reasons_name_the_gate_that_fired(model):
    assert "not a phone" in model.explain_decline(_ad("Koupim iPhone 15 Pro"))
    assert model.explain_decline(_ad("Prenechani rezervace iPhone 18 Pro 256GB")) == (
        "pre-order reservation, price is a deposit"
    )
    assert model.explain_decline(_ad("Apple iPhone 15 Pro")) == "missing storage"
    assert model.explain_decline(_ad("Apple iPhone Pro 256GB")) == "unknown generation"


@pytest.mark.django_db
def test_a_missing_artifact_declines_rather_than_raising(monkeypatch):
    monkeypatch.setattr(type(IPhonePriceModel()), "manifest", property(lambda self: None))

    assert IPhonePriceModel().predict(_ad("Apple iPhone 15 Pro 256GB")) is None
    assert IPhonePriceModel().explain_decline(_ad("Apple iPhone 15 Pro 256GB")) == "no artifact loaded"


# ------------------------------------------------------------------ sigma
def test_sigma_keys_on_spec_completeness_not_on_seller_maturity():
    """The MacBook ladder does not replicate: its 1-2 bucket is wider than its never-seen one.

    Borrowing a monotone ladder onto a non-monotone corpus moves alert volume 32% in a
    direction nobody chose (research §6), so this model must not read `Manifest.sigma_for`.
    """
    manifest = artifacts.load_manifest("iphone")
    stated = IPhonePriceModel.sigma_for(manifest, {"storage_gb": 256, "battery_pct": 92})
    unstated = IPhonePriceModel.sigma_for(manifest, {"storage_gb": 256, "battery_pct": None})

    assert stated < unstated, "a listing that states its battery is the better-behaved one"
    # and it must not be the MacBook ladder's value for a first-time seller
    assert stated != pytest.approx(manifest.seller_sigma_prior.get(0, -1))


def test_completeness_buckets():
    assert IPhonePriceModel.completeness({"storage_gb": 256, "battery_pct": 90}) == "full"
    assert IPhonePriceModel.completeness({"storage_gb": 256, "battery_pct": None}) == "no_battery"
    assert IPhonePriceModel.completeness({"storage_gb": None, "battery_pct": 90}) == "no_storage"


def test_the_artifact_records_its_sigma_table_and_its_n():
    """A shipped manifest has to say the ladder is three estimates with overlapping CIs."""
    raw = artifacts.load_manifest("iphone").raw

    assert raw["sigma_by_completeness"], "the model reads this, not seller_sigma_prior"
    assert raw["sigma_by_completeness_n"], "without n, an overlapping CI cannot be read back"


# ------------------------------------------------------------------ comparables
@pytest.mark.parametrize("bucket,expected", [
    ({"gen_label": "15", "tier": "pro", "storage_gb": 256}, "iPhone 15 Pro 256GB"),
    ({"gen_label": "16", "tier": "pro max", "storage_gb": 1024}, "iPhone 16 Pro Max 1TB"),
    ({"gen_label": "13", "tier": "base", "storage_gb": 128}, "iPhone 13 128GB"),
    ({"gen_label": "xr", "tier": "base", "storage_gb": 64}, "iPhone XR 64GB"),
])
def test_describe_features_reads_as_a_product_name(bucket, expected):
    assert IPhonePriceModel.describe_features(bucket) == expected


def test_comparable_keys_are_all_produced_by_the_extractor():
    produced = set(fx.extract("Apple iPhone 15 Pro 256GB", today=TODAY))

    assert set(IPhonePriceModel.comparable_keys) <= produced


def test_a_capacity_written_in_mb_is_read_as_gb():
    """`iPhone 17 Pro 256 MB` states a capacity in the only unit it can mean.

    No iPhone has 256 MB of storage, and `PLAUS_GB` admits only the eight real capacities,
    so this cannot turn a genuine small number into a disk. It matters because the
    alternative is a decline, and a declined ad PASSes `PriceModelRule` — on a deals-only
    query that means it gets sent.
    """
    assert fx.extract("iphone 17 pro, 512 mb, skvely stav", today=TODAY)["storage_gb"] == 512
    assert fx.extract("Apple iPhone 17 Pro oranzovy zaruka 256 MB", today=TODAY)["storage_gb"] == 256


def test_an_implausible_mb_number_is_still_not_a_capacity():
    assert fx.extract("iPhone 13 128GB, fotky 300 mb", today=TODAY)["storage_gb"] == 128
