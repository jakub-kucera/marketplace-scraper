"""MacBook price model for Bazos listings.

Estimates `ln(price)` from specs parsed out of the listing text, then reports how far the
asking price sits below that — both as a percentage and as a seller-aware z-score.

The z-score is the part that makes a threshold meaningful. A flat "25% below predicted" is
~0.95 sigma for a first-time private seller but ~2.9 sigma for a high-volume dealer, so the
same rule means "ordinary noise" for one and "genuinely exceptional" for the other
(docs/research/MACBOOK_PRICE_MODEL.md §5). Dividing by a sigma that depends on seller
maturity puts both on a comparable evidence scale.
"""
import logging
import math
from typing import Any

from bazos.models import Ad, Marketplace, PriceType
from bazos.pricing import artifacts, features
from bazos.pricing.artifacts import Manifest
from bazos.pricing.base import PricePrediction

logger = logging.getLogger(__name__)

#: Damage vocabulary that disqualifies a listing from being scored at all. Deliberately does
#: NOT include terms with a common negated form -- `bez poskozeni` ("without damage")
#: contains `poskozen`, so blocking that word rejects the ads that say they are undamaged.
#: See docs/QUERY_COMPOSITION.md §3.2.
_DAMAGE = (
    "nefunk", "praskl", "prakl", "rozbit", "rozibt", "ko lcd",
    "na dily", "nahradni dily", "k oprave", "nekompletni",
)


class MacbookPriceModel:
    """Satisfies :class:`bazos.pricing.base.PriceModel` structurally."""

    name = "macbook"

    #: Fitted on Bazos HTML listings only. `applies_to` keeps its own check as well: it is
    #: called directly by training and by tests, where no registry gate runs ahead of it.
    marketplaces: frozenset[str] = frozenset({Marketplace.BAZOS})

    #: How the admin's Price model page names this model, and the `name__icontains` term it
    #: counts its coverage denominator with. The term belongs to the model because a
    #: denominator is a claim about what the model is *for*.
    label = "MacBook"
    coverage_name_contains = "macbook"

    #: The features that make two listings "the same machine", for `bazos/comparables.py`.
    #: An optional attribute, not a `PriceModel` protocol member — the same call as
    #: `dedup_break_streak` on the scraper protocol. Chip, memory, storage and screen size
    #: are what a buyer chooses between; year is deliberately absent, because it is implied
    #: by the chip and is the field listings most often omit (it is the gate that declines
    #: most M4 ads, measured 2026-09-15).
    comparable_keys = ("chip_key", "ram_gb", "ssd_gb", "screen")

    #: The feature groups `bazos/pricing/training.py` builds the design matrix from. Moved
    #: here from module constants in the trainer when the second model landed, so adding a
    #: model does not mean editing this one's list. The paired `missing` indicator on each
    #: numeric is what carries "this was not stated" -- filling alone would tell the model a
    #: median-aged machine.
    TRAINING_NUMERIC = ("ram_log", "storage_log", "screen")
    TRAINING_BOOLEAN = ("warranty", "new", "defect", "vat_dph", "top_word", "scratches",
                        "box", "retina", "touchbar")
    TRAINING_CATEGORICAL = ("chip_key", "family", "year_cat")

    @staticmethod
    def describe_features(bucket: dict) -> str:
        """`{"chip_key": "apple4_max", ...}` -> `M4 Max 36GB/1TB 14"`."""
        chip = str(bucket.get("chip_key") or "")
        if chip.startswith("apple"):
            gen, _, variant = chip[len("apple"):].partition("_")
            chip_label = f"M{gen}" + ("" if variant == "base" else f" {variant.title()}")
        else:
            chip_label = chip or "?"
        size = []
        if bucket.get("ram_gb"):
            size.append(f"{int(bucket['ram_gb'])}GB")
        if bucket.get("ssd_gb"):
            ssd = int(bucket["ssd_gb"])
            size.append(f"{ssd // 1000}TB" if ssd >= 1000 else f"{ssd}GB")
        out = chip_label + (" " + "/".join(size) if size else "")
        if bucket.get("screen"):
            out += f' {bucket["screen"]:g}"'
        return out

    def __init__(self, version: str | None = None) -> None:
        self._requested: str = version or artifacts.resolve_version(self.name)
        self._manifest: Manifest | None = None
        self._loaded = False

    # -- artifact ---------------------------------------------------------
    @property
    def manifest(self) -> Manifest | None:
        """Lazily loaded and cached for the process.

        Loading is deferred rather than done at import so a broken artifact cannot stop the
        app booting, and cached so `run_filter` pays the read once, not once per ad.
        """
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
        if ad.marketplace != Marketplace.BAZOS:
            return False
        text = features.norm(f"{ad.name} || {ad.short_description or ''}")
        return features.product_kind(text) == "macbook"

    def predict(self, ad: Ad) -> PricePrediction | None:
        """Score the ad, or decline. Never raises, never touches the network."""
        manifest = self.manifest
        if manifest is None:
            return None
        if ad.price is None or ad.price <= 0 or ad.price_type != PriceType.EXACT:
            return None

        feats = self.extract(ad)
        if not self._gates_pass(ad, feats):
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
        prior_ads = self.seller_prior_ads(ad)
        sigma = manifest.sigma_for(prior_ads)
        z = residual_log / sigma if sigma > 0 else None
        return PricePrediction(
            predicted=predicted,
            residual_log=residual_log,
            z_score=z,
            seller_prior_ads=prior_ads,
            features=feats,
        )

    # -- helpers ----------------------------------------------------------
    def extract(self, ad: Ad) -> dict[str, Any]:
        feats = features.extract(ad.name, ad.short_description or "")
        gen, variant = feats.get("chip_gen"), feats.get("chip_variant")
        feats["chip_key"] = (
            f"{feats['chip_brand']}{gen}_{variant}" if feats.get("chip_brand") else None
        )
        year = feats.get("year")
        feats["age"] = None if year is None else max(0, features._MAX_MODEL_YEAR - 1 - int(year))
        # one level per model year, "na" included: depreciation is not linear in time --
        # a chip generation lands and the whole cohort steps. Worth 1.35pp of MedAPE over a
        # single slope (docs/research/PRICE_MODEL_BENCHMARK.md).
        feats["year_cat"] = "na" if year is None else str(int(year))
        for src, dst in (("ram_gb", "ram_log"), ("ssd_gb", "storage_log")):
            v = feats.get(src)
            feats[dst] = math.log(v) if v else None
        return feats

    #: Order matters: the gates are reported one at a time, first blocker wins. Listing
    #: every missing field would fragment the breakdown ("missing year, ram" is a
    #: different group from "missing year") and answer a question nobody asks — an ad
    #: whose year *and* ram are missing is not unlocked by finding the ram. The question
    #: this column exists to answer is "which extractor would unlock the most ads", and
    #: that is the first blocker, counted.
    _REQUIRED_FEATURES = (("year", "year"), ("chip_key", "chip"), ("ram_gb", "ram"),
                          ("ssd_gb", "storage"))

    def explain_decline(self, ad: Ad) -> str:
        """Which gate refused this ad. Re-derives rather than being told.

        Deliberately **not** a `PriceModel` protocol member — the same call as
        `comparable_keys` above and `dedup_break_streak` on the scraper protocol: a model
        that cannot explain itself is still a model, and `score_ad` reads this with
        `getattr`. Cheap enough to re-run (regex over two short strings, no DB, no
        network) that threading the reason back out of `predict` would cost more in
        protocol surface than it saves in work.

        Extraction, not model class, is the measured weak point
        (`docs/research/PRICE_MODEL_BENCHMARK.md` §3.1: two extractor regexes were worth
        more R² than the entire choice of estimator), so the breakdown this feeds is how
        you choose which regex to write next.
        """
        if self.manifest is None:
            return "no artifact loaded"
        if ad.price is None or ad.price <= 0:
            return "no parsed price"
        if ad.price_type != PriceType.EXACT:
            return f"price type is {ad.price_type}"

        feats = self.extract(ad)
        for key, label in self._REQUIRED_FEATURES:
            if feats.get(key) is None:
                return f"missing {label}"

        haystack = features.norm(f"{ad.name} {ad.short_description or ''}")
        for term in _DAMAGE:
            if term in haystack:
                return f"damage word: {term}"
        return "declined, gate not identified"

    def _gates_pass(self, ad: Ad, feats: dict[str, Any]) -> bool:
        """Refuse to score what the model is measurably bad at.

        Complete specs take median error from 12.3% to 4.7%, damage words are 3.3x enriched
        in the underpriced tail, and ads sitting exactly on a query's price floor are 9.2x
        enriched -- so scoring any of them mostly manufactures false deals
        (docs/research/MACBOOK_PRICE_MODEL.md §4).
        """
        if any(feats.get(k) is None for k in ("year", "chip_key", "ram_gb", "ssd_gb")):
            return False
        haystack = features.norm(f"{ad.name} {ad.short_description or ''}")
        return not any(term in haystack for term in _DAMAGE)

    @staticmethod
    def seller_prior_ads(ad: Ad) -> int:
        """How many other ads this seller has in the DB.

        One indexed COUNT (`bazos_ad_email_publisher_id`), not a join, because this runs per
        ad inside `run_filter`'s transaction. Returns 0 when the seller is unidentified,
        which maps onto the widest sigma -- the right default for an unknown seller.
        """
        if ad.email_publisher_id is None:
            return 0
        return Ad.objects.filter(email_publisher_id=ad.email_publisher_id).exclude(pk=ad.pk).count()
