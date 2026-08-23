"""Backfill Ad.price/price_type and PriceChange.*_amount from the existing price_raw /
old_price / new_price strings.

Pure re-derivation from the still-present raw strings, so this migration is re-runnable:
running it twice produces the same result, and if the parsing rules below ever need a fix,
re-running this migration (or its `backfill_price` function directly) catches existing rows
up without needing a new one.

Parsing logic is a self-contained copy of `bazos.filters.parse_price_and_type` — not
imported, to keep this migration isolated from the live module the way migration 0025's
docstring explains: `bazos.filters` will keep changing after this migration is history, and
importing it here would let a future edit silently change what an old migration does.

Grammar and the placeholder vocabulary are measured against the full 2024-03 Bazos export
(16,981 ads) — see docs/refactor/PRICE_PARSING_RESEARCH.md §3. Note the corpus-wide
non-numeric rate (~49%) is a `Práce` (job ads) artifact — goods categories measure 0-10%
(§3.2) — so don't expect a flat ratio when eyeballing the printed counts; segment by query
if that matters.

Reports via print(), not the `logging` module — see migration 0027's docstring for why
(django_db_logger's own table may not exist yet when this migration runs).
"""
import re

from django.db import migrations

#: Mirrors bazos.models.PriceType's string values — duplicated rather than imported for the
#: same isolation reason as the parsing function itself.
_PLACEHOLDER_TYPES = {
    "Dohodou": "negotiable",
    "V textu": "in_text",
    "Nabídněte": "make_offer",
    "Nerozhoduje": "indifferent",
}

_BATCH_SIZE = 500


def _parse(price_raw):
    stripped = price_raw.strip()
    if stripped == "Zdarma":
        return 0, "free"
    if stripped in _PLACEHOLDER_TYPES:
        return None, _PLACEHOLDER_TYPES[stripped]
    digits = re.sub(r"\D", "", stripped)
    if digits:
        return int(digits), "exact"
    return None, "unknown"


def backfill_price(apps, schema_editor):
    Ad = apps.get_model("bazos", "Ad")
    PriceChange = apps.get_model("bazos", "PriceChange")

    type_counts: dict[str, int] = {}
    batch = []
    for ad in Ad.objects.iterator():
        ad.price, ad.price_type = _parse(ad.price_raw)
        type_counts[ad.price_type] = type_counts.get(ad.price_type, 0) + 1
        batch.append(ad)
        if len(batch) >= _BATCH_SIZE:
            Ad.objects.bulk_update(batch, ["price", "price_type"])
            batch = []
    if batch:
        Ad.objects.bulk_update(batch, ["price", "price_type"])

    change_batch = []
    for change in PriceChange.objects.iterator():
        change.old_price_amount, _ = _parse(change.old_price)
        change.new_price_amount, _ = _parse(change.new_price)
        change_batch.append(change)
        if len(change_batch) >= _BATCH_SIZE:
            PriceChange.objects.bulk_update(change_batch, ["old_price_amount", "new_price_amount"])
            change_batch = []
    if change_batch:
        PriceChange.objects.bulk_update(change_batch, ["old_price_amount", "new_price_amount"])

    print(f"P22 price backfill: Ad.price_type counts = {type_counts}")


def noop_reverse(apps, schema_editor):
    """Irreversible in substance, permitted in form — see migration 0025's docstring.

    price/price_type/*_amount are pure re-derivations of the still-present raw strings, so
    nothing is lost by leaving them populated on a rollback, and no later migration depends
    on them being NULL again.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('bazos', '0032_price_amount_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_price, noop_reverse),
    ]
