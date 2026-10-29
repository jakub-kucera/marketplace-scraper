"""Everything known about one listing, on one screen.

The question this answers — *"I am looking at this ad; what is it worth and where does it
sit?"* — was being assembled by hand from five places: the ad row, the price score and why it
declined, comparable listings, the distance from home, and the price history. Each already
existed; none of them was in the same place as the others.

Read-only. It makes no HTTP requests and writes nothing, so it is safe to run against
production while the pipeline is live.
"""
import re

from django.core.management.base import BaseCommand, CommandError

from marketplace.comparables import find_comparables
from marketplace.geo import distance_between_codes, normalize_postal_code, parse_postal_code
from marketplace.models import Ad
from marketplace.pricing.registry import get_price_model

#: `https://pc.bazos.cz/inzerat/223724249/slug.php` -> 223724249. Also accepts a bare id.
_AD_ID = re.compile(r"/inzerat/(\d+)/|^(\d+)$")


def parse_target(value: str) -> int:
    match = _AD_ID.search(value.strip())
    if match is None:
        raise CommandError(
            f"{value!r} is neither a Bazos ad URL nor an ad id "
            f"(expected .../inzerat/<id>/... or a bare number)"
        )
    return int(match.group(1) or match.group(2))


class Command(BaseCommand):
    help = "Report specs, comparables, distance, price history and the model's view of one ad."

    def add_arguments(self, parser):
        parser.add_argument("target", help="Bazos ad URL, or the numeric external_id")
        parser.add_argument(
            "--from",
            dest="origin",
            default=None,
            help="Postal code to measure distance from (default: the query centre that found it)",
        )

    def handle(self, *args, **options):
        external_id = parse_target(options["target"])
        ad = (
            Ad.objects
            .filter(external_id=external_id)
            .prefetch_related("deliveries__query", "price_history")
            .first()
        )
        if ad is None:
            raise CommandError(
                f"No ad with external_id={external_id} in the database. Only scraped ads can "
                f"be appraised — this command makes no network requests."
            )

        self._facts(ad, options["origin"])
        self._history(ad)
        self._deliveries(ad)
        self._model(ad)
        self._comparables(ad)

    # -- sections ---------------------------------------------------------

    def _facts(self, ad: Ad, origin: str | None) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{ad.name}"))
        self.stdout.write(f"  {ad.url}")
        self.stdout.write(f"  price     {ad.price_raw}  ({ad.price_type})")
        self.stdout.write(f"  location  {ad.location}{self._distance(ad, origin)}")
        self.stdout.write(
            f"  posted    {ad.publish_date:%Y-%m-%d} | {ad.view_count} views at discovery"
            if ad.publish_date else f"  posted    unknown | {ad.view_count} views at discovery"
        )
        self.stdout.write(f"  seller    {ad.seller_ad_counts().summary}")

    def _distance(self, ad: Ad, origin: str | None) -> str:
        """Distance is a property of a *pair*, so the origin has to come from somewhere.

        Preference order: what the operator asked for, else the first distance filter any
        query watching this ad configured — which is the origin that actually decided
        whether it was delivered.
        """
        code = parse_postal_code(ad.location)
        if code is None:
            return ""
        centre = normalize_postal_code(origin) if origin else None
        if centre is None:
            for delivery in ad.deliveries.all():
                centre = normalize_postal_code(delivery.query.filter_location_center)
                if centre:
                    break
        if centre is None:
            return ""
        km = distance_between_codes(centre, code)
        if km is None:
            return f"  (not geocoded: {code} or {centre} missing from the cache)"
        return f"  — {km:.0f} km from {centre}"

    def _history(self, ad: Ad) -> None:
        changes = list(ad.price_history.all())
        if not changes:
            self.stdout.write("  history   unchanged since discovery")
            return
        self.stdout.write(f"  history   {len(changes)} price change(s):")
        for change in changes:
            self.stdout.write(
                f"              {change.created:%Y-%m-%d}  {change.old_price} -> {change.new_price}"
            )

    def _deliveries(self, ad: Ad) -> None:
        self.stdout.write("  queries")
        for delivery in ad.deliveries.all():
            reason = f"  ({delivery.filter_reason})" if delivery.filter_reason else ""
            self.stdout.write(f"              q{delivery.query_id} {delivery.status}{reason}")

    def _model(self, ad: Ad) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("\n  model"))
        model = get_price_model(ad)
        if model is None:
            self.stdout.write("    no registered model claims this ad")
            return
        # The newest score of ANY kind, not `Ad.current_price_score()` — that one excludes
        # declines because a notification has nothing to say about them, but "the model
        # looked and refused, and here is why" is precisely what this report exists for.
        score = ad.price_scores.order_by("-created").first()
        if score is None:
            self.stdout.write(f"    {model.name}: claimed but never scored")
        elif score.predicted is None:
            self.stdout.write(f"    {model.name}: DECLINED — {score.declined_reason}")
        else:
            self.stdout.write(
                f"    {model.name} {score.model_version}: predicted {score.predicted} Kč"
                f" | {score.discount_pct:+.1f}% | z {score.z_score:+.2f}"
            )
        # The parsed specs even when the model declined — that is usually *why* it declined,
        # and a null here is a listing that did not state something, not a parser failure.
        features = getattr(score, "features", None) or {}
        if not features and hasattr(model, "extract"):
            features = model.extract(ad)
        keys = getattr(model, "comparable_keys", ()) or ()
        shown = {k: features.get(k) for k in (*keys, "year")} if features else {}
        if shown:
            self.stdout.write("    parsed  " + "  ".join(f"{k}={v!r}" for k, v in shown.items()))

    def _comparables(self, ad: Ad) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("\n  comparables"))
        found = find_comparables(ad)
        if found is None:
            self.stdout.write(
                "    none — needs a scored ad whose model defines comparable_keys, and a "
                "complete spec bucket"
            )
            return
        self.stdout.write(
            f"    {found.label}: {found.count} listed in the last 90 days, "
            f"median {found.median} Kč"
        )
        for row in found.rows:
            marker = self.style.SUCCESS(" <- this ad") if row.is_subject else ""
            self.stdout.write(f"      {row.price:>7}  {row.name[:52]}{marker}")
        rank = found.subject_rank
        if rank is not None:
            self.stdout.write(f"    rank {rank} of {found.count} by price (cheapest first)")
        self.stdout.write(
            self.style.WARNING(
                "    asking prices, not sold — and a relisted item counts once per listing"
            )
        )
