"""Tests for SellerAdCounts — the three seller-history numbers (BACKLOG_IDEAS.md step 4).

A seller's Bazos identity is a *pair* of opaque ids, and the same person routinely posts
under several pairings. `combined` therefore walks the identity graph transitively rather
than counting a single id; on the 2024-03 export 13.7% of ads get a different answer that
way than under `max(by_email, by_phone)`.
"""
import pytest

from marketplace.models import Ad, EmailPublisher, PhonePublisher, SellerAdCounts


@pytest.fixture
def link_ad(query, make_ad):
    counter = iter(range(1000, 100000))

    def _factory(email_pub=None, phone_pub=None):
        ad = make_ad(query, next(counter))
        ad.email_publisher = email_pub
        ad.phone_publisher = phone_pub
        ad.save()
        return ad

    return _factory


@pytest.mark.django_db
def test_single_identity_agrees_across_all_three(link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    phone = PhonePublisher.objects.create(bazos_id=200)
    for _ in range(3):
        ad = link_ad(email, phone)

    assert ad.seller_ad_counts() == SellerAdCounts(by_email=3, by_phone=3, combined=3)


@pytest.mark.django_db
def test_rotating_phone_numbers_shows_up_as_disagreement(link_ad):
    """The recruiter pattern: one email, several phones. by_phone understates the seller."""
    email = EmailPublisher.objects.create(bazos_id=5998423)
    for bazos_id in (1165, 1928, 5565):
        link_ad(email, PhonePublisher.objects.create(bazos_id=bazos_id))
    ad = Ad.objects.filter(phone_publisher__bazos_id=1165).first()

    counts = ad.seller_ad_counts()

    assert counts == SellerAdCounts(by_email=3, by_phone=1, combined=3)
    assert counts.has_split_identity


@pytest.mark.django_db
def test_combined_walks_the_graph_transitively(link_ad):
    """(A,X) (B,X) (B,Z): from A, one hop reaches only X's ads — the walk must reach Z too.

    This is the 13.7% case: max(by_email, by_phone) would say 1, the truth is 3.
    """
    a = EmailPublisher.objects.create(bazos_id=1)
    b = EmailPublisher.objects.create(bazos_id=2)
    x = PhonePublisher.objects.create(bazos_id=10)
    z = PhonePublisher.objects.create(bazos_id=20)
    first = link_ad(a, x)
    link_ad(b, x)
    link_ad(b, z)

    counts = first.seller_ad_counts()

    assert (counts.by_email, counts.by_phone) == (1, 2)
    assert counts.combined == 3
    assert counts.has_split_identity


@pytest.mark.django_db
def test_unrelated_sellers_are_not_merged(link_ad):
    mine = link_ad(EmailPublisher.objects.create(bazos_id=1), PhonePublisher.objects.create(bazos_id=10))
    link_ad(EmailPublisher.objects.create(bazos_id=2), PhonePublisher.objects.create(bazos_id=20))

    assert mine.seller_ad_counts() == SellerAdCounts(by_email=1, by_phone=1, combined=1)


@pytest.mark.django_db
def test_ad_with_no_publishers_reports_zero(link_ad):
    """Post-sentinel-fix an ad can legitimately have neither side."""
    ad = link_ad(None, None)

    counts = ad.seller_ad_counts()

    assert counts == SellerAdCounts(0, 0, 0)
    assert not counts.has_split_identity
    assert counts.summary == "Seller: unknown"


@pytest.mark.django_db
def test_ad_with_only_a_phone_still_counts(link_ad):
    phone = PhonePublisher.objects.create(bazos_id=200)
    link_ad(None, phone)
    ad = link_ad(None, phone)

    assert ad.seller_ad_counts() == SellerAdCounts(by_email=0, by_phone=2, combined=2)


@pytest.mark.django_db
def test_null_publishers_do_not_join_unrelated_ads(link_ad):
    """The regression the bazos_id=0 sentinel caused, now guarded at the counting layer."""
    phone = PhonePublisher.objects.create(bazos_id=200)
    ad = link_ad(None, phone)
    link_ad(None, PhonePublisher.objects.create(bazos_id=201))
    link_ad(None, None)

    assert ad.seller_ad_counts().combined == 1


@pytest.mark.django_db
def test_walk_terminates_on_a_long_chain(link_ad):
    """A chain longer than MAX_IDENTITY_ROUNDS must stop, not hang or recurse."""
    emails = [EmailPublisher.objects.create(bazos_id=i) for i in range(1, 12)]
    phones = [PhonePublisher.objects.create(bazos_id=100 + i) for i in range(1, 12)]
    first = link_ad(emails[0], phones[0])
    for i in range(1, 11):
        link_ad(emails[i - 1], phones[i])
        link_ad(emails[i], phones[i])

    counts = first.seller_ad_counts()

    assert counts.combined >= 3
    assert counts.combined <= Ad.objects.count()


# ---------------------------------------------------------------------------
# summary — the line that reaches Discord
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "counts,expected",
    [
        (SellerAdCounts(0, 0, 0), "Seller: unknown"),
        (SellerAdCounts(1, 1, 1), "Seller: 1 ad seen"),
        (SellerAdCounts(4, 4, 4), "Seller: 4 ads seen"),
        (SellerAdCounts(3, 1, 3), "Seller: 3 ads seen (email 3 / phone 1)"),
        (SellerAdCounts(1, 2, 3), "Seller: 3 ads seen (email 1 / phone 2)"),
    ],
)
def test_summary_wording(counts, expected):
    assert counts.summary == expected


@pytest.mark.parametrize(
    "counts,expected,case",
    [
        (SellerAdCounts(3, 3, 3), False, "one stable email/phone pairing"),
        (SellerAdCounts(3, 1, 3), True, "one email, several phones — combined == by_email"),
        (SellerAdCounts(1, 3, 3), True, "one phone, several emails"),
        (SellerAdCounts(1, 2, 3), True, "both sides vary"),
        (SellerAdCounts(0, 2, 2), False, "no email publisher at all — missing, not split"),
        (SellerAdCounts(2, 0, 2), False, "no phone publisher at all"),
        (SellerAdCounts(0, 0, 0), False, "no publishers at all"),
    ],
)
def test_has_split_identity(counts, expected, case):
    assert counts.has_split_identity is expected, case


# ---------------------------------------------------------------------------
# Ad.message — what run_sender actually posts to Discord
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_message_includes_the_seller_line(link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    phone = PhonePublisher.objects.create(bazos_id=200)
    link_ad(email, phone)
    ad = link_ad(email, phone)

    assert ad.message.splitlines()[-1] == "Seller: 2 ads seen"


@pytest.mark.django_db
def test_message_keeps_the_original_fields_and_order(link_ad):
    ad = link_ad(None, None)

    lines = ad.message.splitlines()

    assert lines[:4] == [ad.name, ad.price_raw, ad.location, ad.short_description]
    assert lines[4].startswith("Seller: ")


@pytest.mark.django_db
def test_message_query_cost_is_bounded(link_ad, django_assert_num_queries):
    """`Ad.message` runs per ad in run_sender's batch — pin its cost so a future change to
    the identity walk can't quietly turn a 50-ad batch into thousands of queries.

    5 = five for the seller identity (by_email + by_phone + one graph round (2) + the
    combined count; the walk settles on the first round for the common single-pairing
    seller). The fixture's ad name is claimed by no price model, so `price_score_summary`
    adds **no** query — `current_price_score` resolves the claiming model first, which is
    regex with no DB. A MacBook or iPhone ad pays one more; `test_comparables.py` pins both
    sides of that.
    """
    email = EmailPublisher.objects.create(bazos_id=100)
    phone = PhonePublisher.objects.create(bazos_id=200)
    ad = link_ad(email, phone)

    with django_assert_num_queries(5):
        ad.message
