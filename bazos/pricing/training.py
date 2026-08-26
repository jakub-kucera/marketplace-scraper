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

from bazos.models import Ad, Marketplace, PriceType
from bazos.pricing.artifacts import ARTIFACT_ROOT
from bazos.pricing.estimators.macbook import MacbookPriceModel

logger = logging.getLogger(__name__)

#: Numeric features, with the fill used when a listing does not state them. The paired
#: `missing` indicator is what actually carries "this was not stated" -- filling alone would
#: tell the model a median-aged machine, which is why both are emitted.
NUMERIC = ("ram_log", "storage_log", "screen")
BOOLEAN = ("warranty", "new", "defect", "vat_dph", "top_word", "scratches", "box", "retina", "touchbar")
CATEGORICAL = ("chip_key", "family", "year_cat")


def training_rows(marketplace: str = Marketplace.BAZOS) -> list[dict[str, Any]]:
    """Feature dicts + target for every ad a model claims, straight from the DB.

    Ads with incomplete specs are KEPT. Their missingness is a feature, and dropping them
    biases the training set toward well-written listings -- which are not the ones the model
    struggles with.
    """
    model = MacbookPriceModel()
    rows = []
    qs = Ad.objects.filter(marketplace=marketplace, price_type=PriceType.EXACT, price__gt=0)
    for ad in qs.iterator(chunk_size=500):
        if not model.applies_to(ad):
            continue
        feats = model.extract(ad)
        feats["_price"] = ad.price
        feats["_seller"] = ad.email_publisher_id or f"anon-{ad.pk}"
        rows.append(feats)
    return rows


def _design(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[float]]]:
    """Build the manifest feature spec and the matching design matrix, in one pass.

    The spec and the matrix are produced together so they cannot drift: column *i* of the
    matrix is feature *i* of the spec, which is the invariant `artifacts.evaluate` relies on.
    """
    rows = list(rows)
    spec: list[dict[str, Any]] = []
    fills: dict[str, float] = {}
    for name in NUMERIC:
        vals = sorted(float(r[name]) for r in rows if r.get(name) is not None)
        fills[name] = vals[len(vals) // 2] if vals else 0.0
        spec.append({"kind": "num", "name": name, "fill": fills[name]})
        spec.append({"kind": "missing", "name": name})
    for name in BOOLEAN:
        spec.append({"kind": "bool", "name": name})
    for name in CATEGORICAL:
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


def fit(rows: list[dict[str, Any]], *, alpha: float = 1.0) -> dict[str, Any]:
    """Fit a ridge regression on log price and return a manifest dict."""
    import math

    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score
    from sklearn.model_selection import GroupKFold

    spec, matrix = _design(rows)
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

    return {
        "name": "macbook",
        "kind": "linear",
        "target": "log_price",
        "intercept": round(float(final.intercept_), 6),
        "features": spec,
        "residual_sigma": round(float(np.std(resid)), 4) if ok.sum() > 2 else 0.2,
        "seller_sigma_prior": sigma_prior,
        "seller_sigma_prior_n": prior_counts,
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
