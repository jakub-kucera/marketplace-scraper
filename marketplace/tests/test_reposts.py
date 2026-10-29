"""Tests for `bazos/reposts.py`.

The cost of being wrong here is asymmetric: a false link makes one item look unsellable and
hides a real second one, while a missed link leaves things exactly as they are today. So most
of these pin the cases that must *not* link.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from marketplace.models import Ad, EmailPublisher, Marketplace
from marketplace.reposts import detect_reposts, title_key


@pytest.fixture
def seller(db):
    return EmailPublisher.objects.create(bazos_id=4788860)


@pytest.fixture
def make_listing(seller):
    counter = {"n": 8000}

    def _factory(name, *, days_ago, removed_days_ago=None, publisher=None):
        counter["n"] += 1
        ad = Ad.objects.create(
            external_id=counter["n"], marketplace=Marketplace.BAZOS,
            url=f"https://pc.bazos.cz/inzerat/{counter['n']}/x.php",
            name=name, price_raw="1 500 Kč", price=1500,
            location="Praha 10", short_description="", publisher_name="",
            email_publisher=publisher if publisher is not None else seller,
        )
        # `created` is auto_now_add, so it can only be moved afterwards.
        Ad.objects.filter(pk=ad.pk).update(
            created=timezone.now() - timedelta(days=days_ago),
            removed_at=(
                timezone.now() - timedelta(days=removed_days_ago)
                if removed_days_ago is not None else None
            ),
        )
        ad.refresh_from_db()
        return ad
    return _factory


# ---------------------------------------------------------------------------
# title_key
# ---------------------------------------------------------------------------

def test_diacritics_and_punctuation_are_folded():
    """The same seller writes "Vrtačka" and "vrtacka" across relists."""
    assert title_key("Vrtačka Makita DHP484Z!") == title_key("vrtacka makita  dhp484z")


def test_a_too_generic_title_never_groups(make_listing):
    """"iphone" would chain every listing a seller ever made."""
    make_listing("iPhone", days_ago=60, removed_days_ago=40)
    later = make_listing("iPhone", days_ago=10)

    detect_reposts(later.email_publisher)

    later.refresh_from_db()
    assert later.reposted_from is None


# ---------------------------------------------------------------------------
# what links
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_a_relist_after_the_original_disappeared_links(make_listing, seller):
    original = make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40)
    relist = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)

    assert detect_reposts(seller) == 1

    relist.refresh_from_db()
    assert relist.reposted_from == original


@pytest.mark.django_db
def test_a_price_change_does_not_prevent_a_link(make_listing, seller):
    """Deliberately not a condition. A relist at a lower price is the most interesting case
    — a seller discovering the market — so requiring price equality would filter out the
    finding this exists to surface."""
    original = make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40)
    relist = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)
    Ad.objects.filter(pk=relist.pk).update(price=900, price_raw="900 Kč")

    detect_reposts(seller)

    relist.refresh_from_db()
    assert relist.reposted_from == original


@pytest.mark.django_db
def test_a_chain_links_to_its_immediate_predecessor(make_listing, seller):
    """Not a star topology pointing at the original: the gap between consecutive attempts is
    the interesting quantity, and linking everything to the first listing loses it."""
    first = make_listing("Makita DHP484Z aku vrtacka", days_ago=90, removed_days_ago=70)
    second = make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40)
    third = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)

    detect_reposts(seller)

    second.refresh_from_db()
    third.refresh_from_db()
    assert second.reposted_from == first
    assert third.reposted_from == second


# ---------------------------------------------------------------------------
# what must NOT link — the expensive direction
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_two_identical_items_listed_at_once_are_two_items(make_listing, seller):
    """The load-bearing rule. Without it a dealer with four identical monitors on sale
    simultaneously becomes one much-relisted item, and their asking prices stop being four
    independent observations."""
    make_listing("Dell U2415 monitor 24 palcu", days_ago=30)
    second = make_listing("Dell U2415 monitor 24 palcu", days_ago=29)

    assert detect_reposts(seller) == 0

    second.refresh_from_db()
    assert second.reposted_from is None


@pytest.mark.django_db
def test_a_still_listed_original_does_not_link(make_listing, seller):
    """`removed_at` is None — as far as we know it is still for sale, so the later listing
    is a second unit, not a relist."""
    make_listing("Makita DHP484Z aku vrtacka", days_ago=60)
    relist = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)

    assert detect_reposts(seller) == 0

    relist.refresh_from_db()
    assert relist.reposted_from is None


@pytest.mark.django_db
def test_a_different_seller_is_never_a_relist(make_listing, seller):
    """Two people listing the same phone is a coincidence."""
    other = EmailPublisher.objects.create(bazos_id=999)
    make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40,
                 publisher=other)
    mine = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)

    assert detect_reposts(seller) == 0

    mine.refresh_from_db()
    assert mine.reposted_from is None


# ---------------------------------------------------------------------------
# idempotence
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_running_twice_links_nothing_new(make_listing, seller):
    make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40)
    make_listing("Makita DHP484Z aku vrtacka", days_ago=10)

    assert detect_reposts(seller) == 1
    assert detect_reposts(seller) == 0


@pytest.mark.django_db
def test_deleting_the_original_does_not_delete_the_relist(make_listing, seller):
    """SET_NULL, not CASCADE: the older listing is gone from the marketplace, and the one
    still for sale must survive tidying it away."""
    original = make_listing("Makita DHP484Z aku vrtacka", days_ago=60, removed_days_ago=40)
    relist = make_listing("Makita DHP484Z aku vrtacka", days_ago=10)
    detect_reposts(seller)

    original.delete()

    relist.refresh_from_db()
    assert relist.reposted_from is None
