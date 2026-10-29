"""iPhone price model for Bazos listings.

Estimates `ln(price)` from the model name, storage and condition, and reports how far the ask
sits below it. Research: `docs/research/IPHONE_PRICE_MODEL.md`, whose §8 assessment is
**register the artifact, do not enable the rule** — the model is the tightest fit in the
project on its own corpus and the alert built on it is the worst one measured, and those are
not in tension: a 150-ads/day feed turns a good model into 41 flags a week.

Three things differ from `MacbookPriceModel`, each because the research measured that they
must:

- **Generation is a live age in months, not one level per generation.** Frozen levels
  under-price a held-out generation by 73.8% and make it invisible to a −25% alert; the
  ordinal extrapolates (mean R² +0.404 against −7.18 with a whole generation held out, §3.1).
- **Sigma keys on spec completeness, not seller maturity.** The MacBook ladder does not
  replicate here — its 1–2 bucket is *wider* than the never-seen bucket and a quarter of the
  corpus sits in a wider one still. Borrowing a monotone ladder onto a non-monotone corpus is
  not conservative, it is arbitrary: on identical residuals it moves alert volume 32% in a
  direction nobody chose (§6).
- **The gates reject a listing class the MacBook model never meets**: resold pre-order
  reservations, whose ask is a deposit against a phone worth thirty times it.
"""
import logging
import math
from datetime import date
from typing import Any

from marketplace.models import Ad, Marketplace, PriceType
from marketplace.pricing import artifacts, features_iphone
from marketplace.pricing.artifacts import Manifest
from marketplace.pricing.base import PricePrediction

logger = logging.getLogger(__name__)

#: `product_kind` values that are not a whole iPhone offered for sale. Each is a different
#: quantity rather than a noisier one: a want-to-buy price is a **bid**, a parts price is for
#: a component, an accessory price is for a case. Contamination measured at 2.29% of the
#: category, of which want-to-buy is the class that matters most because those sit at the top
#: of the distribution and drag predictions up (research §3).
_NOT_A_PHONE = frozenset({"wtb", "accessory", "parts", "other_apple", "other_brand"})

#: Sanity bounds on the ask. Below the floor the listing is a deposit, a teaser or a part
#: that said nothing parts-like; above the ceiling it is a multi-unit lot.
_MIN_PRICE, _MAX_PRICE = 300, 80_000


class IPhonePriceModel:
    """Satisfies :class:`bazos.pricing.base.PriceModel` structurally."""

    name = "iphone"

    #: Bazos HTML only. The API scraper carries no `short_description` at all, which would
    #: silently halve this extractor's input, and Vinted prices are converted from PLN.
    marketplaces: frozenset[str] = frozenset({Marketplace.BAZOS})

    #: See `MacbookPriceModel.label` -- the admin page's name for this model and the
    #: `name__icontains` term behind its coverage denominator.
    label = "iPhone"
    coverage_name_contains = "iphone"

    #: What makes two listings "the same phone", for `bazos/comparables.py`. Generation and
    #: tier rather than the derived age, because a bucket label has to be readable; storage
    #: because it is the only remaining axis a buyer chooses along.
    comparable_keys = ("gen_label", "tier", "storage_gb")

    #: The feature groups `bazos/pricing/training.py` builds the design matrix from. Class
    #: attributes rather than module constants in the trainer so a second model does not have
    #: to edit the first one's list.
    #:
    #: `gen_age_m` carries the generation axis on its own: adding per-generation dummies on
    #: top costs ΔR² −0.005 and poisons the ordinal's coefficients out-of-generation
    #: (+0.241 against +0.404), so the 43 dummies would be pure manifest cost (§3.1).
    TRAINING_NUMERIC = ("gen_age_m", "storage_log2", "battery_pct")
    #: Tier is a small closed set that is always seen, so it has nothing to interpolate along
    #: and dummies beat an ordinal on it (0.464 against 0.423, §3.1). Encoded as a category
    #: for exactly that reason, which is why `tier_ord` is extracted but not trained on.
    TRAINING_CATEGORICAL = ("tier",)
    TRAINING_BOOLEAN = (
        "damage", "scratches", "mint_words", "sealed_new", "new_word", "warranty", "invoice",
        "vat_dph", "box", "icloud_clear", "locked", "cz_region", "battery_replaced",
        "dealer_pickup", "multi_unit", "bundle_other",
    )

    @staticmethod
    def describe_features(bucket: dict) -> str:
        """`{"gen_label": "15", "tier": "pro", ...}` -> `iPhone 15 Pro 256GB`."""
        label = str(bucket.get("gen_label") or "?")
        name = f"iPhone {label.upper() if label.isalpha() else label}"
        tier = str(bucket.get("tier") or "base")
        if tier not in ("base", "se"):
            name += " " + tier.title()
        if bucket.get("storage_gb"):
            gb = int(bucket["storage_gb"])
            name += f" {gb // 1024}TB" if gb >= 1024 else f" {gb}GB"
        return name

    def __init__(self, version: str | None = None) -> None:
        self._requested: str = version or artifacts.resolve_version(self.name)
        self._manifest: Manifest | None = None
        self._loaded = False

    # -- artifact ---------------------------------------------------------
    @property
    def manifest(self) -> Manifest | None:
        """Lazily loaded and cached for the process, same reasoning as the MacBook model."""
        if not self._loaded:
            self._manifest = artifacts.load_manifest(self.name, self._requested)
            self._loaded = True
        return self._manifest

    @property
    def version(self) -> str:
        m = self.manifest
        return m.version if m else "unavailable"

    # -- protocol ---------------------------------------------------------
    def applies_to(self, ad: Ad) -> bool:
        """Claims an ad whose subject is a whole iPhone.

        Mutually exclusive with the MacBook model by construction: `product_kind` returns
        `other_apple` the moment a title names a Mac without naming an iPhone, so the one
        measured double-claim class — a dealer's boilerplate listing both — lands on neither.
        That mattered less when the preview was 254 characters; in full text the cross-family
        token appears 20x more often (docs/backlog/PRICE_MODEL_DEFECTS.md §8.1), so this must
        hold before `load_full_description` is ever turned on for an iPhone query.
        """
        if ad.marketplace != Marketplace.BAZOS:
            return False
        title = features_iphone.norm(ad.name or "")
        blob = features_iphone.norm(f"{ad.name or ''} || {ad.short_description or ''}")
        gen, *_ = features_iphone.model(title)
        if gen is None:
            gen, *_ = features_iphone.model(blob)
        return features_iphone.product_kind(title, blob, gen) == "iphone"

    def predict(self, ad: Ad) -> PricePrediction | None:
        """Score the ad, or decline. Never raises, never touches the network."""
        manifest = self.manifest
        if manifest is None:
            return None
        if ad.price is None or ad.price <= 0 or ad.price_type != PriceType.EXACT:
            return None

        feats = self.extract(ad)
        if not self._gates_pass(feats, ad.price):
            return None

        try:
            predicted_log = artifacts.evaluate(manifest, feats)
            predicted = int(round(math.exp(predicted_log)))
        except (ValueError, OverflowError) as exc:
            logger.error("Price model %r failed on ad %s: %s", self.name, ad.pk, exc)
            return None
        if predicted <= 0:
            return None

        residual_log = math.log(ad.price) - predicted_log
        sigma = self.sigma_for(manifest, feats)
        return PricePrediction(
            predicted=predicted,
            residual_log=residual_log,
            z_score=residual_log / sigma if sigma > 0 else None,
            # Recorded because it is worth having in arrears, and deliberately NOT what picks
            # sigma here. See `sigma_for`.
            seller_prior_ads=self.seller_prior_ads(ad),
            features=feats,
        )

    # -- helpers ----------------------------------------------------------
    def extract(self, ad: Ad, today: date | None = None) -> dict[str, Any]:
        return features_iphone.extract(ad.name or "", ad.short_description or "", today=today)

    #: Residual sigma by how completely the listing states its specs, fitted on this corpus.
    #: The fallback when a manifest carries no table of its own; a manifest's
    #: `sigma_by_completeness` wins.
    #:
    #: ⚠️ **Three point estimates with overlapping intervals, not a calibrated ladder.** The
    #: 95% seller-cluster CIs are [0.157, 0.196], [0.180, 0.281] and [0.252, 0.456]; the
    #: bottom bucket is 37 rows and its interval places −25% anywhere from ordinary noise to
    #: mildly unusual (research §6). Read a z from here as an ordering, not a probability.
    SIGMA_BY_COMPLETENESS = {"full": 0.1755, "no_battery": 0.2316, "no_storage": 0.3708}

    @classmethod
    def trainable(cls, feats: dict[str, Any], price: int) -> bool:
        """Is this row an observation of *one phone's asking price*?

        Read by `bazos/pricing/training.py` with `getattr`, so a model that does not declare
        it trains on everything it claims — which is the MacBook model's behaviour and stays
        correct for it.

        Two classes are dropped and the reasons are different.

        **A price that is a different quantity**: a bid, a resold pre-order's deposit, a
        price for two phones, a price for the cheapest of four configurations. These are not
        noisier observations of an asking price, they are observations of something else.
        Including them measured R² 0.906 against 0.941.

        **A spec the serving gate requires.** Training on rows the model then refuses to
        score cannot improve those scores and does distort the coefficients it does use:
        residual sigma on the storage-less bucket is 0.638 against 0.223 on complete rows.
        Note the limit of that argument — a *battery* is missing on half the corpus and is
        **not** gated, so those rows stay, and the paired `missing` indicator is what carries
        them. "Missingness is a feature" is true of a feature the model serves without;
        storage is not one.
        """
        if feats.get("kind") in _NOT_A_PHONE or feats.get("gen_age_m") is None:
            return False
        if feats.get("reservation") or feats.get("marked_sold") or feats.get("multipack"):
            return False
        if feats.get("swap") or (feats.get("storage_variants") or 0) > 1:
            return False
        if feats.get("storage_gb") is None:
            return False
        return _MIN_PRICE <= price <= _MAX_PRICE

    @classmethod
    def completeness(cls, feats: dict[str, Any]) -> str:
        if feats.get("storage_gb") is None:
            return "no_storage"
        return "full" if feats.get("battery_pct") is not None else "no_battery"

    @classmethod
    def sigma_for(cls, manifest: Manifest, feats: dict[str, Any]) -> float:
        """Residual spread expected of a listing this complete.

        **Not `Manifest.sigma_for`**, which keys on `seller_prior_ads`. That ladder is the
        MacBook corpus's and does not replicate here: 80.3% of these sellers appear once, so
        this is the desktop situation rather than the MacBook one (research §6).
        """
        table = manifest.raw.get("sigma_by_completeness") or cls.SIGMA_BY_COMPLETENESS
        return float(table.get(cls.completeness(feats), manifest.residual_sigma))

    #: Order matters: first blocker wins, and the breakdown this feeds is an extractor work
    #: queue. Unlike the MacBook model's, most of these are *product* gates rather than
    #: missing-spec gates, because the measured problem here is what the ad is, not how well
    #: it is written.
    def explain_decline(self, ad: Ad) -> str:
        """Which gate refused this ad. Re-derives rather than being told, same as MacBook's."""
        if self.manifest is None:
            return "no artifact loaded"
        if ad.price is None or ad.price <= 0:
            return "no parsed price"
        if ad.price_type != PriceType.EXACT:
            return f"price type is {ad.price_type}"

        feats = self.extract(ad)
        if feats.get("kind") in _NOT_A_PHONE:
            return f"not a phone: {feats['kind']}"
        if feats.get("gen_age_m") is None:
            return "unknown generation"
        if feats.get("reservation"):
            return "pre-order reservation, price is a deposit"
        if feats.get("marked_sold"):
            return "marked sold"
        if feats.get("multipack"):
            return "several phones in one ad"
        if feats.get("swap"):
            return "swap, price is not an ask"
        if (feats.get("storage_variants") or 0) > 1:
            return "several storage variants in one ad"
        if feats.get("storage_gb") is None:
            return "missing storage"
        if ad.price < _MIN_PRICE:
            return f"ask below {_MIN_PRICE} Kc"
        if ad.price > _MAX_PRICE:
            return f"ask above {_MAX_PRICE} Kc"
        return "declined, gate not identified"

    def _gates_pass(self, feats: dict[str, Any], price: int) -> bool:
        """Refuse to score what is not one phone's asking price.

        The same predicate as `trainable`, and that is deliberate rather than a redundancy
        worth collapsing: **train the distribution you score.** The two names answer
        different questions — "is this a usable observation" and "will this get a number" —
        and they would diverge the moment either side gains a check the other should not
        have. Keeping them as one call means they cannot drift apart silently in the
        meantime, which is the failure that matters: a gate the training set does not share
        makes every coefficient an estimate for a population the model never meets.

        The reservation gate is the one worth stating: resold iPhone 18 pre-orders were the
        largest single defect on this corpus, 4.2% of the category, and because the ask is a
        deposit they poisoned the newest generation's level in *both* directions — genuine
        flagships then read as 2x overpriced.

        `damage` is deliberately **not** a gate. It is a trained feature instead, because the
        negation handling a damage gate needs cuts both ways and its measured false rate runs
        in both directions (docs/backlog/PRICE_MODEL_DEFECTS.md §13a): the shipped MacBook
        tuple rejects ads that say they are *undamaged*, and a naive negation passes cracked
        phones into the alert. A damaged phone with a stated discount is a real listing and
        pricing it is better than losing it. That gate is a prerequisite for enabling the
        *rule*, which this model does not ask for.
        """
        return self.trainable(feats, price)

    @staticmethod
    def seller_prior_ads(ad: Ad) -> int:
        """How many other ads this seller has in the DB. One indexed COUNT, not a join.

        Recorded on every prediction because the question is only ever asked in arrears, and
        **not** used to pick sigma — see `sigma_for`.
        """
        if ad.email_publisher_id is None:
            return 0
        return Ad.objects.filter(email_publisher_id=ad.email_publisher_id).exclude(pk=ad.pk).count()
