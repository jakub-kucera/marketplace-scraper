"""Re-run price predictions over ads that already have a score, and persist the result.

`score_ad` treats a score as fresh when its `model_version` matches the artifact's, so a
row scored before a code change keeps whatever that older code persisted — forever, no
matter how many times the pipeline sees the ad again. That is the right cache key for the
*artifact* (a new artifact means new numbers) and the wrong one for the *code* (a new
persisted field means new columns on the same numbers).

This is the tool for the second case. It is deliberately general rather than a one-off
backfill script: every future field added to `AdPriceScore` lands with exactly the same
gap, and the answer should not be another migration each time.

Do **not** reach for a version bump instead. `AdPriceScore.model_version` records which
artifact produced a row, and is what makes a bad model's output findable after the fact;
bumping it to trigger recomputation falsifies that, and has to be repeated on every code
change rather than once.

Cheap to run: `PriceModel.predict` is CPU-only by contract — no network, no pacing, no
block handling, unlike `geocode_postal_codes`.
"""
import logging

from django.core.management.base import BaseCommand

from marketplace.models import Ad, AdPriceScore
from marketplace.pricing.scoring import score_ad

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-predict and re-persist existing AdPriceScore rows (e.g. after adding a field)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default=None,
            help="Only rescore rows produced by this model (registry key, e.g. macbook).",
        )
        parser.add_argument(
            "--missing-features",
            action="store_true",
            help="Only rows with no features. Skips declined rows, whose features are "
                 "legitimately null, so this is the narrow backfill for a shipped field.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be rescored without writing anything.",
        )

    def _target_ad_ids(self, options) -> list[int]:
        rows = AdPriceScore.objects.all()
        if options["model"]:
            rows = rows.filter(model_name=options["model"])
        if options["missing_features"]:
            # `predicted__isnull=False` matters: a declined row has null features by
            # design, and rescoring it would decline again for the same reason.
            rows = rows.filter(features__isnull=True, predicted__isnull=False)
        # Materialised rather than streamed: score_ad writes to this same table, and a
        # server-side cursor iterating it while it is being updated is asking for trouble.
        return list(rows.values_list("ad_id", flat=True).distinct())

    def handle(self, *args, **options):
        ad_ids = self._target_ad_ids(options)
        self.stdout.write(f"{len(ad_ids)} ads to rescore")
        if options["dry_run"] or not ad_ids:
            return

        rescored = declined = failed = 0
        for ad in Ad.objects.filter(pk__in=ad_ids).iterator():
            try:
                score = score_ad(ad, refresh=True)
            except Exception:
                # One unusable ad must not end the run: this is a backfill over rows that
                # already exist, and the useful outcome is "as many as possible", not
                # all-or-nothing.
                logger.exception("Rescoring ad %s failed", ad.pk)
                failed += 1
                continue
            if score is None:
                # No registered model claims it any more — the row stays as it was.
                continue
            if score.declined_reason:
                declined += 1
            else:
                rescored += 1

        summary = f"Rescored {rescored} ads; {declined} now decline"
        if failed:
            summary += f"; {failed} failed (see the log)"
        self.stdout.write(
            self.style.WARNING(summary) if failed else self.style.SUCCESS(summary)
        )
