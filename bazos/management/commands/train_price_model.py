"""Management command: train_price_model

Fits a price model from the ads already in the database and writes a JSON artifact under
`bazos/pricing/artifacts/<name>/<version>/`. Offline only -- needs scikit-learn, which is
deliberately not a runtime dependency (docs/proposals/ML_PRICE_SCORING.md §4.1).

Usage:
    python manage.py train_price_model --model macbook    # version = today
    python manage.py train_price_model --model iphone --artifact-version 2026-10-15
    python manage.py train_price_model --model iphone --dry-run   # metrics only, write nothing

`--model` is a `MODEL_REGISTRY` key and is required: with more than one model registered,
defaulting it would retrain whichever happens to be first and write over its artifact.
"""
import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fit a price model from the DB and write a JSON artifact"

    def add_arguments(self, parser):
        parser.add_argument("--model", required=True,
                            help="Registry key of the model to train, e.g. macbook or iphone.")
        # not --version: BaseCommand already owns that, and argparse raises on the collision.
        parser.add_argument("--artifact-version", default=None, help="Artifact version (default: today's date).")
        parser.add_argument("--alpha", type=float, default=1.0, help="Ridge regularisation strength.")
        parser.add_argument("--dry-run", action="store_true", help="Report metrics without writing.")

    def handle(self, *args, **options):
        from bazos.pricing import training
        from bazos.pricing.registry import MODEL_REGISTRY

        model = MODEL_REGISTRY.get(options["model"])
        if model is None:
            raise CommandError(
                f"Unknown model {options['model']!r}; registered: {sorted(MODEL_REGISTRY)}"
            )

        rows = training.training_rows(model)
        if len(rows) < 50:
            raise CommandError(f"Only {len(rows)} usable ads; refusing to train on that.")
        try:
            manifest = training.fit(rows, model, alpha=options["alpha"])
        except ImportError as exc:
            raise CommandError(
                "Training needs scikit-learn, which is not a runtime dependency. "
                "Install it in your dev environment: pip install scikit-learn"
            ) from exc

        m = manifest["metrics"]
        self.stdout.write(f"{model.name}: trained on {m['n_train']} ads")
        self.stdout.write(f"  R2 (seller-grouped) : {m['r2_seller_grouped']}")
        self.stdout.write(f"  MedAPE              : {m['medape_pct']}")
        self.stdout.write(f"  features            : {len(manifest['features'])}")
        if manifest.get("sigma_by_completeness"):
            self.stdout.write(f"  sigma by completeness: {manifest['sigma_by_completeness']}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing written"))
            return
        path = training.write_artifact(manifest, options["artifact_version"])
        self.stdout.write(self.style.SUCCESS(f"wrote {path}"))
