"""Has this seller listed this same item before, under a different id?

Pure analysis over rows we already hold — no network, no marketplace, no cost beyond a
couple of indexed queries. `DISCOVERY_PIPELINE.md` §3.3 designed this and nothing ever built
it, largely because it had no input: a seller's *past* inventory only exists in this database
if our queries happened to find it. `fetch_seller_listings` is what changed that.

**Why a repost is worth knowing.** A listing that has been posted three times and removed
twice is not a listing that sold twice — it is one that did not sell, and whose asking price
is therefore evidence about the market rather than about the item. It is also the one thing
that breaks `Ad.removed_at` as a proxy for selling, which is the only outcome signal the
project has.

⚠️ **This infers, and the cost of a false link is asymmetric.** Wrongly chaining two
different units makes one look unsellable and hides a real second item; missing a link
merely leaves things as they are today. Every rule below is therefore conservative, and the
one that does the real work is temporal: the candidates must not have been listed at the
same time. Two identical drills on sale simultaneously are two drills.
"""
import logging
import re
import unicodedata

from marketplace.models import Ad

logger = logging.getLogger(__name__)

#: Below this many characters a normalised title is too generic to identify anything —
#: "iphone" or "kolo" would chain every listing a seller ever made.
MIN_TITLE_KEY_LENGTH = 12

_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")


def title_key(name: str) -> str:
    """A title reduced to something two listings of one item plausibly share.

    Diacritics are folded because the same seller writes "Vrtačka" and "vrtacka" across
    relists; everything else is lowercased and punctuation-collapsed. Deliberately *not*
    fuzzy — an edit-distance match would trade the asymmetry in this module's docstring the
    wrong way round.
    """
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return _NON_ALPHANUMERIC.sub(" ", folded.lower()).strip()


def detect_reposts(publisher) -> int:
    """Link each of this seller's ads to the earlier listing it appears to relist.

    Returns how many links were newly made. Idempotent: an ad already linked is left alone,
    so re-running after an inventory pull only adds what the new rows revealed.

    Three conditions, all required:

    1. **Same seller.** Two people listing the same phone is a coincidence, not a relist.
    2. **Same normalised title**, at least `MIN_TITLE_KEY_LENGTH` characters of it.
    3. **The earlier listing was gone before the later one appeared.** This is the load-
       bearing one. Without it, a dealer with four identical monitors on sale at once gets
       chained into a single much-relisted item, and their asking prices stop being four
       independent observations.

    Note what is deliberately *not* a condition: **price**. A relist at a lower price is the
    single most interesting case here — it is a seller discovering the market — so requiring
    price equality would filter out the finding.
    """
    ads = list(
        Ad.objects.filter(
            publisher_filter(publisher)
        ).order_by("created").only(
            "pk", "name", "created", "removed_at", "reposted_from_id"
        )
    )

    groups: dict[str, list[Ad]] = {}
    for ad in ads:
        key = title_key(ad.name)
        if len(key) >= MIN_TITLE_KEY_LENGTH:
            groups.setdefault(key, []).append(ad)

    linked = 0
    for key, group in groups.items():
        if len(group) < 2:
            continue
        for index, ad in enumerate(group[1:], start=1):
            if ad.reposted_from_id is not None:
                continue
            predecessor = _latest_finished_before(group[:index], ad)
            if predecessor is None:
                continue
            ad.reposted_from = predecessor
            ad.save(update_fields=["reposted_from"])
            linked += 1
            logger.info("Ad %s looks like a relist of %s (%r)", ad.pk, predecessor.pk, key)

    return linked


def _latest_finished_before(earlier: list[Ad], ad: Ad) -> Ad | None:
    """The most recent candidate that had already disappeared when `ad` was posted.

    Walks backwards so a chain of relists links to its immediate predecessor rather than to
    the original — the gap between consecutive attempts is the interesting quantity, and a
    star topology pointing at the first listing would lose it.
    """
    for candidate in reversed(earlier):
        if candidate.removed_at is not None and candidate.removed_at <= ad.created:
            return candidate
    return None


def publisher_filter(publisher):
    """Ads belonging to this publisher, on whichever of the two FKs it lives.

    A seller is a *pair* of opaque ids; a publisher row is only ever one of them, so which
    column to filter is a property of the object, not of the caller.
    """
    from django.db.models import Q

    field = "email_publisher" if publisher.ratings_param == "email_id" else "phone_publisher"
    return Q(**{field: publisher})
