"""Loading and validating model artifacts.

An artifact is one `manifest.json` under ``artifacts/<name>/<version>/``. It carries the
feature specification and the coefficients as plain numbers, so inference needs no numeric
dependencies — see docs/proposals/ML_PRICE_SCORING.md §4, which explains why that is a hard
constraint rather than a preference (there is no numpy/sklearn in the production image).

A malformed or unreadable artifact makes the model **decline to score** rather than raise:
the rule then PASSes and the pipeline runs untouched. A model that cannot load must not be
able to wedge the filter stage.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_ROOT = Path(__file__).resolve().parent / "artifacts"

#: Feature kinds the pure-Python evaluator understands. `kind` is validated against this so
#: an artifact exported by a newer trainer fails loudly here rather than scoring silently
#: wrong by ignoring features it does not recognise.
_FEATURE_KINDS = {"num", "missing", "cat", "bool"}


class ArtifactError(Exception):
    """Raised only inside `load_manifest`, which converts it into a None return."""


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    intercept: float
    features: list[dict[str, Any]]
    residual_sigma: float
    seller_sigma_prior: dict[int, float]
    raw: dict[str, Any]

    @property
    def metrics(self) -> dict[str, Any]:
        return self.raw.get("metrics", {})

    def sigma_for(self, prior_ads: int) -> float:
        """Residual sigma expected of a seller with this many prior listings.

        A first-time seller is ~4.5x noisier than a 50-ad dealer, so one global sigma makes
        `z <= -2` mean wildly different things depending on who posted — see
        docs/research/MACBOOK_PRICE_MODEL.md §5. Keys are lower bounds; the highest key not
        above `prior_ads` wins.
        """
        best = self.residual_sigma
        for lower in sorted(self.seller_sigma_prior):
            if prior_ads >= lower:
                best = self.seller_sigma_prior[lower]
        return best


def available_versions(name: str) -> list[str]:
    """Version directories present for a model, oldest first by plain string sort."""
    root = ARTIFACT_ROOT / name
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file())


def _validate(data: dict[str, Any], path: Path) -> None:
    for key in ("name", "version", "intercept", "features"):
        if key not in data:
            raise ArtifactError(f"{path}: missing required key {key!r}")
    if data.get("kind", "linear") != "linear":
        # The joblib/pickle path is a deliberate non-feature today: it would require numpy,
        # scipy and scikit-learn in the ARM64 production image. See the spec's §4.3.
        raise ArtifactError(f"{path}: kind={data['kind']!r} is not supported; only 'linear' ships today")
    if not isinstance(data["features"], list) or not data["features"]:
        raise ArtifactError(f"{path}: 'features' must be a non-empty list")
    for i, feat in enumerate(data["features"]):
        kind = feat.get("kind")
        if kind not in _FEATURE_KINDS:
            raise ArtifactError(f"{path}: feature {i} has unknown kind {kind!r}")
        if "coef" not in feat or "name" not in feat:
            raise ArtifactError(f"{path}: feature {i} needs 'name' and 'coef'")
        float(feat["coef"])  # raises if unparseable


def load_manifest(name: str, version: str = "latest") -> Manifest | None:
    """Load one artifact, or return None (logged) if it is absent or unusable."""
    versions = available_versions(name)
    if not versions:
        logger.warning("Price model %r has no artifacts under %s", name, ARTIFACT_ROOT / name)
        return None
    resolved = versions[-1] if version == "latest" else version
    path = ARTIFACT_ROOT / name / resolved / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate(data, path)
    except (OSError, json.JSONDecodeError, ArtifactError, TypeError, ValueError) as exc:
        # Deliberately broad: any unusable artifact must degrade to "no score", never to an
        # exception escaping into run_filter's transaction.
        logger.error("Price model %r artifact %s unusable: %s", name, resolved, exc)
        return None

    prior = {int(k): float(v) for k, v in (data.get("seller_sigma_prior") or {}).items()}
    return Manifest(
        name=data["name"],
        version=data["version"],
        intercept=float(data["intercept"]),
        features=data["features"],
        residual_sigma=float(data.get("residual_sigma", 0.2)),
        seller_sigma_prior=prior,
        raw=data,
    )


def evaluate(manifest: Manifest, feats: dict[str, Any]) -> float:
    """`intercept + sum(coef * value)` over the manifest's feature specs.

    Pure Python on purpose (§4.1). Unknown feature names contribute 0 rather than raising:
    a listing missing a field is normal, and the `missing` indicator features are how the
    model is told about it.
    """
    total = manifest.intercept
    for feat in manifest.features:
        kind, name, coef = feat["kind"], feat["name"], float(feat["coef"])
        value = feats.get(name)
        if kind == "num":
            total += coef * (float(value) if value is not None else float(feat.get("fill", 0.0)))
        elif kind == "missing":
            total += coef * (1.0 if value is None else 0.0)
        elif kind == "cat":
            total += coef * (1.0 if value is not None and str(value) == feat.get("value") else 0.0)
        elif kind == "bool":
            total += coef * (1.0 if bool(value) else 0.0)
    return total
