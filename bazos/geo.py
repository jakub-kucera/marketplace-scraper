"""Postal-code geography: parse a PSČ out of a listing, resolve it to coordinates, measure.

Two separate concerns live here, and keeping them apart is the point:

- **Resolution** (`ensure_postal_code`) talks to Bazos's `zip.php` geocoder and writes a
  `PostalCode` row. It runs in the *scraper*, which already owns a Tor session, pacing and
  block handling, and it runs once per code ever — the CZ postal-code space the queries
  actually touch is a few hundred entries and stops growing.
- **Measurement** (`distance_between_codes`) is pure arithmetic over the cache, with no
  network at all. That is what `LocationDistanceRule` calls, so `run_filter` stays the
  DB-only stage it has always been.

A code that cannot be resolved is not an error here — every caller degrades to "no opinion".
See `LocationDistanceRule` for why that has to be true.
"""
import json
import logging
import re
from math import asin, cos, radians, sin, sqrt
from random import uniform
from time import sleep

import requests

from bazos.const import (
    BAZOS_REQUEST_TIMEOUT,
    BAZOS_ZIP_API_URL,
    GEOCODE_WAIT_TIME,
)
from bazos.exceptions import MarketplaceBlockedError
from bazos.models import PostalCode
from bazos.scraping.bazos.user_agent import default_user_agent

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0

#: CZ and SK postal codes are both `NNN NN`, written with or without the space. The
#: `\b` on the left is what keeps the house number in "Praha 10, 106 00" from being read
#: as the start of a code.
_POSTAL_CODE_RE = re.compile(r"\b(\d{3})\s?(\d{2})\b")


def normalize_postal_code(value: str | None) -> str | None:
    """`"110 00"`, `"11000"` -> `"11000"`. None when the string holds no code."""
    if not value:
        return None
    match = _POSTAL_CODE_RE.search(value.strip())
    if match is None:
        return None
    return match.group(1) + match.group(2)


def parse_postal_code(location: str | None) -> str | None:
    """Pull the PSČ out of a scraped `Ad.location`, e.g. `"Pelhřimov, 394 03"`.

    The **last** match wins: Bazos renders the code after the locality, and a locality
    can itself be numeric ("Praha 4"). Returns None for the marketplaces whose location
    string carries no code at all — Sbazar ships district/region names, Vinted ships an
    empty string — which is what makes the distance rule Bazos-only without it having to
    branch on `marketplace`.
    """
    if not location:
        return None
    matches = _POSTAL_CODE_RE.findall(location)
    if not matches:
        return None
    head, tail = matches[-1]
    return head + tail


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Straight-line, not driving distance."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def distance_between_codes(code_a: str, code_b: str) -> float | None:
    """Km between two postal codes, or None if either is missing from the cache."""
    if code_a == code_b:
        return 0.0
    rows = {row.code: row for row in PostalCode.objects.filter(code__in=(code_a, code_b))}
    a, b = rows.get(code_a), rows.get(code_b)
    if a is None or b is None:
        return None
    return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)


def _parse_zip_response(payload: str, code: str) -> dict | None:
    """Pick the entry matching `code` out of a `zip.php` response.

    The endpoint is a prefix search over both codes and city names, so a lookup for
    "11000" can come back with several post offices, and a lookup for a code that does
    not exist comes back with unrelated neighbours rather than an empty list. Matching
    the code exactly is what makes "not found" distinguishable from "found something".
    """
    try:
        entries = json.loads(payload)
    except ValueError:
        logger.warning("zip.php returned non-JSON for %s", code)
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if normalize_postal_code(entry.get("zip_code")) != code:
            continue
        try:
            latitude = float(entry["latitude"])
            longitude = float(entry["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        return {"latitude": latitude, "longitude": longitude, "city": entry.get("city") or ""}
    return None


def geocode_postal_code(
    code: str, session: requests.Session, *, pace: bool = False, raise_on_block: bool = False
) -> PostalCode | None:
    """Resolve `code` via `zip.php` and cache it. None on any failure.

    `raise_on_block` is the one thing that can make this raise, and it exists because the
    two callers want opposite things from a 403. The **scraper** wants silence: its query
    already succeeded, and a blocked coordinate lookup is not worth retrying a whole walk
    for — the next pass gets it free. The **backfill command** wants the block, because a
    Tor exit is blocked for every code equally, so without rotating on the first 403 the
    remaining hundreds of lookups are guaranteed to fail identically (measured
    2026-08-30: 0/40 on one circuit).

    Otherwise it never raises. Its default caller is inside the scrape walk, whose guard
    catches `DatabaseError` and nothing wider, so anything escaping here would abort the
    query for the whole pass.
    """
    if pace:
        sleep(uniform(*GEOCODE_WAIT_TIME))
    try:
        response = session.get(
            BAZOS_ZIP_API_URL,
            params={"query": code},
            headers={"User-Agent": default_user_agent()},
            timeout=BAZOS_REQUEST_TIMEOUT,
        )
        if response.status_code == 403:
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("Geocoding %s returned HTTP %s", code, response.status_code)
            return None
        parsed = _parse_zip_response(response.text, code)
        if parsed is None:
            logger.info("zip.php knows no postal code %s", code)
            return None
        row, _ = PostalCode.objects.update_or_create(code=code, defaults=parsed)
    except MarketplaceBlockedError:
        if raise_on_block:
            raise
        logger.warning("Geocoding %s: this circuit's exit IP is blocked", code)
        return None
    # `Exception`, not just `requests.RequestException`. See the docstring: an enhancement
    # must not be able to break the thing it enhances. Same call `PriceModelRule` makes
    # about a scoring failure.
    except Exception as e:
        logger.warning("Geocoding %s failed: %s", code, e)
        return None
    logger.info("Geocoded %s -> %s (%.5f, %.5f)", code, row.city, row.latitude, row.longitude)
    return row


def ensure_postal_code(
    code: str | None,
    session: requests.Session,
    *,
    pace: bool = False,
    raise_on_block: bool = False,
) -> PostalCode | None:
    """Cache lookup, falling back to one `zip.php` call. None if it stays unresolved."""
    if not code:
        return None
    existing = PostalCode.objects.filter(code=code).first()
    if existing is not None:
        return existing
    return geocode_postal_code(code, session, pace=pace, raise_on_block=raise_on_block)
