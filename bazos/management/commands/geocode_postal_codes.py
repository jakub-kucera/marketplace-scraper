"""Warm the `PostalCode` cache from Bazos's `zip.php` geocoder.

The scraper geocodes each ad's postal code as it creates the ad, so in steady state this
command has nothing to do. It exists for the two cases that path cannot cover:

- **Ads scraped before the distance filter existed** — their codes were never resolved, and
  `LocationDistanceRule` PASSes on a code it cannot place, so those ads bypass the filter
  until this has run once.
- **A query centre nobody has an ad for** — `Query.filter_location_center` is typed by hand
  in the admin and may name a postal code no listing has ever come from. Without its
  coordinates the filter is silently inactive for that whole query, so it is geocoded first.
"""
import logging

from django.core.management.base import BaseCommand

from bazos.geo import ensure_postal_code, normalize_postal_code, parse_postal_code
from bazos.models import Ad, PostalCode, Query
from bazos.scraping.session import AllCircuitsBlocked, build_ip_changer, with_rotation
from ip_changer.ip_changer import IPChanger

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Geocode postal codes seen in ads and query centres into the PostalCode cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codes",
            nargs="+",
            default=None,
            help="Geocode only these codes (e.g. 11000 60200) instead of scanning the DB.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what is missing from the cache without making any requests.",
        )

    def _ip_changer(self) -> IPChanger:
        # zip.php is a bazos.cz path, so it is subject to the same exit-IP blocking as
        # every other request the project makes.
        return build_ip_changer()

    def _geocode_with_rotation(self, code: str, changer: IPChanger) -> bool:
        """One code, rotating the circuit on a 403.

        A block is a property of the exit IP, not of the code: without this the first
        blocked circuit fails every remaining lookup identically (0/40, measured
        2026-08-30).
        """
        try:
            return with_rotation(
                changer,
                lambda session: ensure_postal_code(
                    code, session, pace=True, raise_on_block=True
                ),
                what=f"Geocoding {code}",
            ) is not None
        except AllCircuitsBlocked:
            return False

    def _wanted_codes(self, options) -> list[str]:
        if options["codes"]:
            codes = [normalize_postal_code(c) for c in options["codes"]]
            unusable = [c for c, n in zip(options["codes"], codes) if n is None]
            if unusable:
                self.stderr.write(f"Ignoring unparseable codes: {', '.join(unusable)}")
            return sorted({c for c in codes if c})

        # Centres first and separately: a missing centre disables its query's filter
        # entirely, where a missing ad code only lets one ad through.
        centres = {
            normalize_postal_code(value)
            for value in Query.objects.exclude(filter_location_center="")
            .values_list("filter_location_center", flat=True)
        }
        ad_codes = {
            parse_postal_code(location)
            for location in Ad.objects.exclude(location="")
            .values_list("location", flat=True)
            .iterator()
        }
        return sorted({c for c in centres if c}) + sorted({c for c in ad_codes - centres if c})

    def handle(self, *args, **options):
        wanted = self._wanted_codes(options)
        cached = set(PostalCode.objects.filter(code__in=wanted).values_list("code", flat=True))
        missing = [code for code in wanted if code not in cached]

        self.stdout.write(f"{len(wanted)} codes referenced, {len(missing)} not yet geocoded")
        if options["dry_run"] or not missing:
            for code in missing:
                self.stdout.write(f"  missing: {code}")
            return

        changer = self._ip_changer()
        # Paced inside ensure_postal_code: this walks hundreds of lookups back to back,
        # which is exactly the burst shape the QueryRun history correlates with 403s.
        resolved = sum(self._geocode_with_rotation(code, changer) for code in missing)

        self.stdout.write(
            self.style.SUCCESS(f"Geocoded {resolved}/{len(missing)} codes")
            if resolved == len(missing)
            else self.style.WARNING(
                f"Geocoded {resolved}/{len(missing)} codes; the rest stay unresolved "
                f"(unknown to zip.php, or the request was blocked) and are treated as "
                f"'no opinion' by the distance filter"
            )
        )
