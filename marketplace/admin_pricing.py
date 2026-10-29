"""The admin's "Price model" page — what the scorer thinks, and what it is silent about.

`AdPriceScore` exists only as an inline on the ad it belongs to, which is backwards for a
model whose whole job is to surface ads you have *not* already found. This page is the
other direction: start from the model, end at the listings.

It answers four questions, and deliberately not a fifth:

1. **Is the artifact actually loaded?** Every uncertain path in `bazos/pricing/` returns
   neutral by design, so a missing or corrupt artifact is indistinguishable from "no
   opinion" anywhere else in the product. Here it is stated.
2. **What does it cover?** Measured on production 2026-09-20: 3 310 MacBook ads in the
   archive, 361 ever scored. The gap is ads that predate the feature — `rescore_ads` is
   what closes it, and the funnel is how you notice it needs running.
3. **Why is it silent?** A third of scoring attempts decline at a gate. Grouped by which
   gate, that is a work queue for the extractor — and extraction, not model class, is the
   measured weak point (`PRICE_MODEL_BENCHMARK.md` §3.1).
4. **What would it have alerted on?** `PRICE_MODEL_SHADOW_MODE` is on, so the flags go
   nowhere. Seeing them listed is the evidence needed to decide whether to turn it off,
   and the honest way to check the research's warning that 70% of a naive underpricing
   alert is damage, parse failures and price-floor artifacts.

**Not** a precision or accuracy figure. There are no outcomes (`AdOutcome` is empty), and
R² 0.87 measures agreement with *asking* prices — put that on a page like this and it will
be read as "87% right about deals", which is exactly the claim the research refuses to
make. The drift panel is the honest version: it shows the model moving relative to the
market without claiming to be right about either.
"""
import math
from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncWeek
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

#: Rows in the "would have alerted" and "declined" tables. Both are meant to be read, not
#: scrolled; the changelist is where you go when you want all of them.
TABLE_ROWS = 15

#: How far back the drift line looks. Weekly buckets, because a daily median over ~30
#: scores a day is noise wearing a trend's clothes.
DRIFT_WEEKS = 12

#: Which model the page opens on when `?model=` is absent. The first registered one, so a
#: bookmark keeps working and the page never renders empty just because a second model landed.
def _default_model_name(registry) -> str:
    return next(iter(registry), "")


def _percent(part, whole):
    return round(100 * part / whole) if whole else None


def price_model_view(request):
    from marketplace.models import Ad, AdDelivery, AdPriceScore, AdStatus, Marketplace
    from marketplace.pricing.registry import MODEL_REGISTRY

    if not request.user.is_staff:
        raise PermissionDenied

    # One page per model rather than one page: a model you cannot inspect is one you cannot
    # calibrate, and with the rule in shadow mode this page is the only place a score
    # surfaces at all. An unknown `?model=` falls back rather than 404ing, because the name
    # comes from a bookmark as often as from the selector.
    model_name = request.GET.get("model") or _default_model_name(MODEL_REGISTRY)
    if model_name not in MODEL_REGISTRY:
        model_name = _default_model_name(MODEL_REGISTRY)

    model = MODEL_REGISTRY.get(model_name)
    manifest = getattr(model, "manifest", None) if model else None

    scores = AdPriceScore.objects.filter(model_name=model_name)
    # The aliases must not be named after the columns their own filters reference: an
    # alias shadows the field inside the same aggregate() call, and `predicted=Count(...,
    # filter=Q(predicted__isnull=False))` fails with "predicted is an aggregate".
    totals = scores.aggregate(
        n_total=Count("id"),
        n_predicted=Count("id", filter=Q(predicted__isnull=False)),
        n_declined=Count("id", filter=Q(predicted__isnull=True)),
        n_deals=Count("id", filter=Q(z_score__lte=-2)),
    )
    # The denominator is intentionally a name match rather than `applies_to`: the real
    # predicate needs the ad object, and running it over the archive is a page load nobody
    # would forgive. It overcounts slightly (a "macbook" in a bundle listing), which is the
    # right direction for a coverage number — it must not flatter itself. Each model declares
    # its own term, because a denominator is a claim about what the model is *for* and only
    # the model knows that.
    term = getattr(model, "coverage_name_contains", model_name) if model else model_name
    candidates = Ad.objects.filter(
        marketplace__in=sorted(model.marketplaces) if model else [Marketplace.BAZOS],
        name__icontains=term,
    ).count()

    # The leg the funnel was missing. A flag that was notified anyway is one the existing
    # rules already caught; a flag that was *not* is what enabling the rule would add, and
    # that difference is the whole shadow-mode decision.
    flagged_ids = set(scores.filter(z_score__lte=-2).values_list("ad_id", flat=True))
    notified = set(
        AdDelivery.objects.filter(ad_id__in=flagged_ids, status=AdStatus.SENT)
        .values_list("ad_id", flat=True)
    ) if flagged_ids else set()

    declines = list(
        scores.filter(predicted__isnull=True)
        .values("declined_reason").annotate(n=Count("id")).order_by("-n")[:TABLE_ROWS]
    )

    # What shadow mode is suppressing. Ordered by z, not by discount: a flat percentage is
    # ~0.95 sigma for a first-time private seller and ~2.9 for a dealer, and the whole
    # point of the z-score is that those are not the same find.
    would_alert = list(
        scores.filter(z_score__lte=-2)
        .select_related("ad").order_by("z_score")[:TABLE_ROWS]
    )

    drift = [
        {
            "week": row["week"],
            "n": row["n"],
            "median_pct": None if row["avg_residual"] is None
            else round((math.exp(row["avg_residual"]) - 1) * 100, 1),
        }
        for row in (
            scores.filter(
                predicted__isnull=False,
                created__gte=timezone.now() - timedelta(weeks=DRIFT_WEEKS),
            )
            .annotate(week=TruncWeek("created")).values("week")
            .annotate(n=Count("id"), avg_residual=Avg("residual_log"))
            .order_by("week")
        )
    ]

    return render(request, "admin/price_model.html", {
        **admin.site.each_context(request),
        "title": "Price model",
        "model_name": model_name,
        "model_label": getattr(model, "label", model_name) if model else model_name,
        "models": [
            {"name": key, "label": getattr(m, "label", key), "selected": key == model_name}
            for key, m in MODEL_REGISTRY.items()
        ],
        "artifact": {
            "loaded": manifest is not None,
            "version": getattr(model, "version", "unavailable") if model else "not registered",
            # From `raw`, not an attribute: `Manifest` promotes only the fields inference
            # needs, and these are provenance. `n_train` is shown because
            # PRICE_MODEL_DEFECTS.md §1's complaint is that an artifact records nothing
            # about what it was trained on — it records this much, and it is worth seeing
            # next to a coverage number built from a corpus that has since grown.
            "trained_at": manifest.raw.get("trained_at") if manifest else None,
            "n_train": manifest.metrics.get("n_train") if manifest else None,
            "features": len(manifest.features) if manifest else None,
            "registered": model is not None,
        },
        "funnel": {
            "candidates": candidates,
            "scored": totals["n_total"],
            "scored_pct": _percent(totals["n_total"], candidates),
            "predicted": totals["n_predicted"],
            "declined": totals["n_declined"],
            "declined_pct": _percent(totals["n_declined"], totals["n_total"]),
            "deals": totals["n_deals"],
            "deals_notified": len(notified),
            "deals_unnotified": len(flagged_ids - notified),
        },
        "declines": declines,
        "would_alert": would_alert,
        "drift": drift,
        "shadow_mode": getattr(settings, "PRICE_MODEL_SHADOW_MODE", True),
        "scores_url": reverse("admin:bazos_ad_changelist"),
    })
