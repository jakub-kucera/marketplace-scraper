"""Fit a price model and export it as a JSON artifact.

Runs offline, never in production. scikit-learn is imported lazily and is **not** a runtime
dependency -- the whole point of the JSON artifact format is that serving needs no numeric
stack (docs/proposals/ML_PRICE_SCORING.md §4.1). Install it in a dev environment to train:

    pip install scikit-learn

Validation is grouped by seller, never random: 56% of the MacBook corpus comes from ten
dealers relisting the same inventory, so a random split scores the same listing in train and
test and reports a model that does not exist (R^2 0.925 leaky vs 0.873 honest).
"""
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from marketplace.models import Ad, PriceType
from marketplace.pricing.artifacts import ARTIFACT_ROOT
from marketplace.pricing.base import PriceModel

logger = logging.getLogger(__name__)


def _groups(model: PriceModel) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The model's own feature groups.

    Each estimator declares `TRAINING_NUMERIC` / `TRAINING_BOOLEAN` / `TRAINING_CATEGORICAL`.
    They are optional attributes read with `getattr`, the same call as `comparable_keys` and
    `dedup_break_streak`: a model that cannot be trained by this trainer is still a model --
    an artifact fitted elsewhere and committed by hand serves exactly the same way.
    """
    return (
        tuple(getattr(model, "TRAINING_NUMERIC", ())),
        tuple(getattr(model, "TRAINING_BOOLEAN", ())),
        tuple(getattr(model, "TRAINING_CATEGORICAL", ())),
    )


def training_rows(model: PriceModel, marketplace: str | None = None) -> list[dict[str, Any]]:
    """Feature dicts + target for every ad this model claims, straight from the DB.

    Ads with incomplete specs are KEPT. Their missingness is a feature, and dropping them
    biases the training set toward well-written listings -- which are not the ones the model
    struggles with.

    **An ad whose price is a different quantity is NOT kept**, and the distinction is the one
    that matters: a want-to-buy price is a bid, a resold pre-order's price is a deposit, a
    two-phone lot's price is for two phones. Those are not noisier observations of an asking
    price, they are observations of something else, and a model declaring `trainable()` says
    so. Measured on iPhone: including them costs R2 0.795 against 0.946, because 4.2% of that
    category was ~1 000 CZK deposits against ~35 000 CZK phones, which dragged the newest
    generation's level down until genuine flagships read as 2x overpriced.

    The marketplace filter defaults to the model's own `marketplaces`, so a model fitted on
    one site cannot silently train on another's price semantics -- Vinted's are converted
    from PLN, and the Bazos API carries no `short_description` for the extractor to read.
    """
    marketplaces = [marketplace] if marketplace else sorted(model.marketplaces)
    trainable = getattr(model, "trainable", None)
    rows = []
    qs = Ad.objects.filter(marketplace__in=marketplaces, price_type=PriceType.EXACT, price__gt=0)
    for ad in qs.iterator(chunk_size=500):
        if not model.applies_to(ad):
            continue
        feats = model.extract(ad)
        if trainable is not None and not trainable(feats, ad.price):
            continue
        feats["_price"] = ad.price
        feats["_seller"] = ad.email_publisher_id or f"anon-{ad.pk}"
        rows.append(feats)
    return rows


def _design(rows: Iterable[dict[str, Any]],
            model: PriceModel) -> tuple[list[dict[str, Any]], list[list[float]]]:
    """Build the manifest feature spec and the matching design matrix, in one pass.

    The spec and the matrix are produced together so they cannot drift: column *i* of the
    matrix is feature *i* of the spec, which is the invariant `artifacts.evaluate` relies on.
    """
    rows = list(rows)
    numeric, boolean, categorical = _groups(model)
    spec: list[dict[str, Any]] = []
    fills: dict[str, float] = {}
    for name in numeric:
        vals = sorted(float(r[name]) for r in rows if r.get(name) is not None)
        fills[name] = vals[len(vals) // 2] if vals else 0.0
        spec.append({"kind": "num", "name": name, "fill": fills[name]})
        spec.append({"kind": "missing", "name": name})
    for name in boolean:
        spec.append({"kind": "bool", "name": name})
    for name in categorical:
        seen = sorted({str(r[name]) for r in rows if r.get(name) is not None})
        for value in seen:
            spec.append({"kind": "cat", "name": name, "value": value})

    matrix = []
    for r in rows:
        vec: list[float] = []
        for feat in spec:
            name, kind = feat["name"], feat["kind"]
            v = r.get(name)
            if kind == "num":
                vec.append(float(v) if v is not None else float(feat["fill"]))
            elif kind == "missing":
                vec.append(1.0 if v is None else 0.0)
            elif kind == "bool":
                vec.append(1.0 if bool(v) else 0.0)
            else:
                vec.append(1.0 if v is not None and str(v) == feat["value"] else 0.0)
        matrix.append(vec)
    return spec, matrix


def fit(rows: list[dict[str, Any]], model: PriceModel, *, alpha: float = 1.0) -> dict[str, Any]:
    """Fit a ridge regression on log price and return a manifest dict."""
    import math

    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score
    from sklearn.model_selection import GroupKFold

    spec, matrix = _design(rows, model)
    X = np.asarray(matrix, dtype=float)
    y = np.asarray([math.log(r["_price"]) for r in rows], dtype=float)
    groups = np.asarray([str(r["_seller"]) for r in rows])

    n_splits = min(5, len(set(groups.tolist())))
    oof = np.full(len(y), np.nan)
    if n_splits >= 2:
        for tr, te in GroupKFold(n_splits).split(X, y, groups):
            m = Ridge(alpha=alpha).fit(X[tr], y[tr])
            oof[te] = m.predict(X[te])
    ok = ~np.isnan(oof)
    resid = y[ok] - oof[ok]
    metrics = {
        "n_train": int(len(y)),
        "r2_seller_grouped": float(r2_score(y[ok], oof[ok])) if ok.sum() > 2 else None,
        "medape_pct": float(np.median(np.abs(np.exp(oof[ok]) - np.exp(y[ok])) / np.exp(y[ok])) * 100)
        if ok.sum() > 2 else None,
    }

    final = Ridge(alpha=alpha).fit(X, y)
    for feat, coef in zip(spec, final.coef_):
        feat["coef"] = round(float(coef), 6)

    # Residual sigma by seller maturity -- the prior that makes the z-score comparable across
    # seller types. Bucket lower bounds match `Manifest.sigma_for`.
    prior_counts: dict[str, int] = {}
    sigma_prior: dict[str, float] = {}
    for lower, upper in ((0, 0), (1, 2), (3, 9), (10, 49), (50, 10**9)):
        idx = []
        seen: dict[str, int] = {}
        for i, g in enumerate(groups):
            n_before = seen.get(g, 0)
            seen[g] = n_before + 1
            if ok[i] and lower <= n_before <= upper:
                idx.append(i)
        if len(idx) >= 15:
            sigma_prior[str(lower)] = round(float(np.std(y[idx] - oof[idx])), 4)
            prior_counts[str(lower)] = len(idx)

    # And by whatever else the model says its sigma depends on. A model declaring
    # `completeness()` gets its own table, because the seller-maturity ladder above is a
    # property of the MacBook corpus and does not replicate everywhere: on iPhone the 1-2
    # bucket is wider than the never-seen bucket, so borrowing a monotone ladder would move
    # alert volume 32% in a direction nobody chose
    # (docs/research/IPHONE_PRICE_MODEL.md §6).
    completeness = getattr(model, "completeness", None)
    sigma_completeness: dict[str, float] = {}
    completeness_counts: dict[str, int] = {}
    if completeness is not None:
        buckets: dict[str, list[int]] = {}
        for i, row in enumerate(rows):
            if ok[i]:
                buckets.setdefault(completeness(row), []).append(i)
        for bucket, idx in sorted(buckets.items()):
            if len(idx) >= 15:
                sigma_completeness[bucket] = round(float(np.std(y[idx] - oof[idx])), 4)
                completeness_counts[bucket] = len(idx)

    return {
        "name": model.name,
        "kind": "linear",
        "target": "log_price",
        "intercept": round(float(final.intercept_), 6),
        "features": spec,
        "residual_sigma": round(float(np.std(resid)), 4) if ok.sum() > 2 else 0.2,
        "seller_sigma_prior": sigma_prior,
        "seller_sigma_prior_n": prior_counts,
        "sigma_by_completeness": sigma_completeness,
        "sigma_by_completeness_n": completeness_counts,
        "metrics": metrics,
        "estimator": f"Ridge(alpha={alpha})",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_artifact(manifest: dict[str, Any], version: str | None = None) -> Path:
    version = version or date.today().isoformat()
    manifest["version"] = version
    out = ARTIFACT_ROOT / manifest["name"] / version
    out.mkdir(parents=True, exist_ok=True)
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
