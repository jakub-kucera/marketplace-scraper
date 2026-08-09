"""Tests for the publisher admins' partner list (BACKLOG_IDEAS.md step 2).

A seller's Bazos identity is a *pair* of opaque ids (email_id, phone_id), and the same
person routinely posts under several pairings — one real email in the 2024-03 export pairs
with 69 distinct phones. These tests cover surfacing that pairing on the publisher admin.
"""
import pytest
from django.contrib.admin.sites import AdminSite

from bazos.admin import EmailPublisherAdmin, PhonePublisherAdmin, PublisherAdminBase
from bazos.models import Ad, EmailPublisher, PhonePublisher


@pytest.fixture
def email_admin():
    return EmailPublisherAdmin(EmailPublisher, AdminSite())


@pytest.fixture
def phone_admin():
    return PhonePublisherAdmin(PhonePublisher, AdminSite())


@pytest.fixture
def link_ad(query, make_ad):
    """Create a saved Ad joining an email publisher to a phone publisher."""
    counter = iter(range(1000, 100000))

    def _factory(email_pub=None, phone_pub=None):
        ad = make_ad(query, next(counter))
        ad.email_publisher = email_pub
        ad.phone_publisher = phone_pub
        ad.save()
        return ad

    return _factory


@pytest.mark.django_db
def test_lists_each_partner_once_with_shared_ad_count(email_admin, link_ad):
    """The recruiter pattern: one email, several phones, some used repeatedly."""
    email = EmailPublisher.objects.create(bazos_id=5998423)
    frequent = PhonePublisher.objects.create(bazos_id=1165)
    occasional = PhonePublisher.objects.create(bazos_id=1928)
    for _ in range(3):
        link_ad(email, frequent)
    link_ad(email, occasional)

    html = email_admin.partners(email)

    assert "1165" in html and "1928" in html
    assert "3 ads" in html
    assert "1 ad" in html
    # most-shared first
    assert html.index("1165") < html.index("1928")


@pytest.mark.django_db
def test_partner_links_point_at_the_other_admin(email_admin, phone_admin, link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    phone = PhonePublisher.objects.create(bazos_id=200)
    link_ad(email, phone)

    assert f"/phonepublisher/{phone.pk}/change/" in email_admin.partners(email)
    assert f"/emailpublisher/{email.pk}/change/" in phone_admin.partners(phone)


@pytest.mark.django_db
def test_reports_no_partners_rather_than_an_empty_list(email_admin, link_ad):
    """Post-sentinel-fix, an ad legitimately has no publisher of the other type."""
    email = EmailPublisher.objects.create(bazos_id=100)
    link_ad(email, None)

    assert email_admin.partners(email) == "— (no ads with a publisher of the other type)"


@pytest.mark.django_db
def test_unsaved_object_does_not_query(email_admin):
    """The add form renders readonly fields against an unsaved instance."""
    assert email_admin.partners(EmailPublisher(bazos_id=1)) == "—"


@pytest.mark.django_db
def test_partner_list_is_capped(email_admin, link_ad, monkeypatch):
    monkeypatch.setattr("bazos.admin.PARTNER_DISPLAY_LIMIT", 2)
    email = EmailPublisher.objects.create(bazos_id=100)
    for bazos_id in (1, 2, 3, 4):
        link_ad(email, PhonePublisher.objects.create(bazos_id=bazos_id))

    html = email_admin.partners(email)

    assert "more than 2" in html
    assert html.count("<li>") == 3  # 2 partners + the overflow notice


@pytest.mark.django_db
def test_blocked_partner_is_flagged(email_admin, link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    link_ad(email, PhonePublisher.objects.create(bazos_id=200, blocked=True))

    assert "blocked" in email_admin.partners(email)


@pytest.mark.django_db
def test_partner_and_ad_counts_come_from_one_annotated_query(email_admin, link_ad, rf, django_assert_num_queries):
    email = EmailPublisher.objects.create(bazos_id=100)
    other = EmailPublisher.objects.create(bazos_id=101)
    phone = PhonePublisher.objects.create(bazos_id=200)
    link_ad(email, phone)
    link_ad(email, PhonePublisher.objects.create(bazos_id=201))
    link_ad(other, phone)

    qs = email_admin.get_queryset(rf.get("/"))
    with django_assert_num_queries(1):
        counts = {row.bazos_id: (row.ad_count, row.partner_count) for row in qs}

    assert counts[100] == (2, 2)
    assert counts[101] == (1, 1)


@pytest.mark.django_db
def test_counts_ignore_the_other_publisher_type(phone_admin, link_ad, rf):
    """A phone shared by two emails has 2 partners, not 2 ads' worth of double-counting."""
    phone = PhonePublisher.objects.create(bazos_id=200)
    for bazos_id in (1, 2):
        link_ad(EmailPublisher.objects.create(bazos_id=bazos_id), phone)

    row = phone_admin.get_queryset(rf.get("/")).get(pk=phone.pk)

    assert (row.ad_count, row.partner_count) == (2, 2)


@pytest.mark.django_db
def test_ads_without_a_partner_do_not_inflate_partner_count(email_admin, link_ad, rf):
    email = EmailPublisher.objects.create(bazos_id=100)
    link_ad(email, PhonePublisher.objects.create(bazos_id=200))
    link_ad(email, None)

    row = email_admin.get_queryset(rf.get("/")).get(pk=email.pk)

    assert (row.ad_count, row.partner_count) == (2, 1)


def test_both_admins_declare_the_full_subclass_contract():
    """Guards against a third publisher admin being added with a field left unset."""
    for cls in (EmailPublisherAdmin, PhonePublisherAdmin):
        assert cls.own_ad_field and cls.partner_ad_field and cls.partner_model
        assert cls.own_ad_field != cls.partner_ad_field
        assert {cls.own_ad_field, cls.partner_ad_field} == {"email_publisher", "phone_publisher"}
        assert issubclass(cls, PublisherAdminBase)


def test_ad_model_actually_has_the_declared_fields():
    """The FK names are strings, so a model rename would silently break the admin."""
    field_names = {f.name for f in Ad._meta.get_fields()}
    for cls in (EmailPublisherAdmin, PhonePublisherAdmin):
        assert cls.own_ad_field in field_names
        assert cls.partner_ad_field in field_names


@pytest.mark.django_db
def test_change_page_renders_with_the_partner_list(admin_client, link_ad):
    """End-to-end: readonly_fields wiring, template rendering, and escaping."""
    email = EmailPublisher.objects.create(bazos_id=5998423)
    link_ad(email, PhonePublisher.objects.create(bazos_id=1165))

    response = admin_client.get(f"/admin/bazos/emailpublisher/{email.pk}/change/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Seen together with" in body
    assert "1165" in body
    assert "&lt;ul" not in body  # format_html output must not be double-escaped


@pytest.mark.django_db
def test_changelist_renders_with_the_annotated_columns(admin_client, link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    link_ad(email, PhonePublisher.objects.create(bazos_id=200))

    response = admin_client.get("/admin/bazos/emailpublisher/")

    assert response.status_code == 200
    assert "Partner ids" in response.content.decode()


# ---------------------------------------------------------------------------
# ads_link — browse a publisher's ads, newest first (step 3)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ads_link_reports_the_count_and_targets_the_ad_changelist(email_admin, link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    for _ in range(3):
        link_ad(email, None)

    html = email_admin.ads_link(email)

    assert "Browse 3 ads" in html
    assert f"/admin/bazos/ad/?email_publisher__id__exact={email.pk}" in html


@pytest.mark.django_db
def test_ads_link_singular_and_empty_cases(email_admin, link_ad):
    email = EmailPublisher.objects.create(bazos_id=100)
    assert email_admin.ads_link(email) == "— (no ads)"

    link_ad(email, None)
    assert "Browse 1 ad<" in email_admin.ads_link(email) + "<"


@pytest.mark.django_db
def test_ads_link_filters_on_the_right_side_for_phone_admin(phone_admin, link_ad):
    phone = PhonePublisher.objects.create(bazos_id=200)
    link_ad(None, phone)

    assert f"phone_publisher__id__exact={phone.pk}" in phone_admin.ads_link(phone)


@pytest.mark.django_db
def test_unsaved_object_has_no_ads_link(email_admin):
    assert email_admin.ads_link(EmailPublisher(bazos_id=1)) == "—"


@pytest.mark.django_db
def test_the_generated_url_is_an_allowed_lookup_and_filters_correctly(admin_client, link_ad, email_admin):
    """Django raises DisallowedModelAdminLookup for filters it doesn't permit, so the URL
    being well-formed is not enough — it has to actually load and filter.
    """
    mine = EmailPublisher.objects.create(bazos_id=100)
    theirs = EmailPublisher.objects.create(bazos_id=101)
    link_ad(mine, None)
    link_ad(mine, None)
    link_ad(theirs, None)

    response = admin_client.get(email_admin.ads_changelist_url(mine))

    assert response.status_code == 200
    assert response.context["cl"].result_count == 2


@pytest.mark.django_db
def test_ad_changelist_is_ordered_newest_first(admin_client, query, make_ad):
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    for offset, bazos_id in ((2, 1), (0, 2), (1, 3)):
        ad = make_ad(query, bazos_id)
        ad.publish_date = now - timedelta(days=offset)
        ad.save()

    response = admin_client.get("/admin/bazos/ad/")

    external_ids = [ad.external_id for ad in response.context["cl"].result_list]
    assert external_ids == [2, 3, 1]


@pytest.mark.django_db
def test_ad_count_column_links_to_the_filtered_list(email_admin, link_ad, rf):
    email = EmailPublisher.objects.create(bazos_id=100)
    link_ad(email, None)

    row = email_admin.get_queryset(rf.get("/")).get(pk=email.pk)

    assert f"email_publisher__id__exact={email.pk}" in email_admin.ad_count(row)


@pytest.mark.django_db
def test_ad_count_column_renders_zero_without_a_link(email_admin, rf):
    EmailPublisher.objects.create(bazos_id=100)
    row = email_admin.get_queryset(rf.get("/")).get(bazos_id=100)

    assert email_admin.ad_count(row) == 0
