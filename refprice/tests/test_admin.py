"""The admin surface — which is the feature's actual UI.

CLAUDE.md calls the admin "a real operational surface, not scaffolding", and explicit
invocation is the whole posture: the confirm/reject buttons here are what produce the
labelled `(ad title -> product id)` corpus that would later justify automating any of it.

Two traps CLAUDE.md names and the generic changelist test cannot catch: a stock
`ModelAdmin` renders unthemed but still 200s, and the Unfold sidebar is hand-maintained.
"""
import pytest
from django.contrib import admin as dj_admin
from django.contrib.auth import get_user_model
from django.urls import reverse
from unfold.admin import ModelAdmin as UnfoldModelAdmin

from bazos.admin import AdAdmin
from bazos.models import Ad, Marketplace
from refprice.models import LookupStatus, RefLookup, RefProduct, RefProductLink

pytestmark = pytest.mark.django_db


@pytest.fixture()
def admin_client_logged_in(client):
    user = get_user_model().objects.create_superuser(
        username="ref-admin", email="a@test.local", password="password"
    )
    client.force_login(user)
    return client


@pytest.fixture()
def product():
    return RefProduct.objects.create(
        provider="zbozi", product_id="5325309", slug="makita-dhp484z-li-ion-18-v",
        name="Makita DHP484Z Li-ion 18 V", brand="Makita", median_czk=3813,
        min_czk=2870, max_czk=5391, shop_count=41, availability="in_stock",
    )


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=777, name="Makita DHP484Z",
        url="https://pc.bazos.cz/inzerat/777/x.php", price_raw="2 500 Kč", price=2500,
    )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", [RefProduct, RefProductLink, RefLookup])
def test_the_model_is_registered_on_the_themed_base(model):
    assert model in dj_admin.site._registry
    assert isinstance(dj_admin.site._registry[model], UnfoldModelAdmin)


@pytest.mark.parametrize("model", [RefProduct, RefProductLink, RefLookup])
def test_the_changelist_renders(admin_client_logged_in, model, product):
    opts = model._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
    assert admin_client_logged_in.get(url).status_code == 200


def test_the_new_models_are_in_the_hand_maintained_sidebar():
    from django.conf import settings
    sidebar: dict = settings.UNFOLD["SIDEBAR"]
    links = [str(item["link"]) for group in sidebar["navigation"] for item in group["items"]]
    assert str(reverse("admin:refprice_refproduct_changelist")) in links


# ---------------------------------------------------------------------------
# the wiring onto Ad — done from this app, so deleting refprice breaks nothing
# ---------------------------------------------------------------------------

def test_the_reference_inline_is_attached_to_the_ad_admin():
    from refprice.admin import ReferenceLinkInline
    assert ReferenceLinkInline in AdAdmin.inlines


def test_bazos_admin_does_not_import_refprice():
    """The dependency points inward. `bazos` must stay deletable-independent of this app,
    so the wiring lives here and mutates AdAdmin rather than the reverse."""
    from refprice.tests.import_direction import modules_imported_by

    assert "refprice" not in modules_imported_by("admin.py")


def test_the_lookup_action_is_available_on_the_ad_changelist():
    actions = dj_admin.site._registry[Ad].actions or ()
    assert "look_up_reference_price" in [getattr(a, "__name__", a) for a in actions]


def test_the_ad_change_page_still_renders_with_the_inline(admin_client_logged_in, ad):
    assert admin_client_logged_in.get(
        reverse("admin:bazos_ad_change", args=[ad.pk])
    ).status_code == 200


# ---------------------------------------------------------------------------
# read-only where it should be
# ---------------------------------------------------------------------------

def test_the_lookup_log_cannot_be_edited(admin_client_logged_in):
    opts = dj_admin.site._registry[RefLookup]
    request = admin_client_logged_in.request()  # type: ignore[call-arg]
    assert opts.has_add_permission(request) is False


def test_a_link_can_be_edited_because_confirming_is_the_point(ad, product):
    """`confirmed_by_human` is the payoff column, so this one is deliberately writable."""
    opts = dj_admin.site._registry[RefProductLink]
    assert "confirmed_by_human" in opts.list_editable


def test_the_link_changelist_shows_the_confirmation_state(admin_client_logged_in, ad, product):
    RefProductLink.objects.create(ad=ad, ad_title=ad.name, provider="zbozi",
                                  product=product, confidence=0.9)
    response = admin_client_logged_in.get(reverse("admin:refprice_refproductlink_changelist"))
    assert response.status_code == 200


def test_a_lookup_row_renders_in_the_changelist(admin_client_logged_in, ad):
    RefLookup.objects.create(ad=ad, provider="zbozi", phrase_used="Makita DHP484Z",
                             status=LookupStatus.MATCHED, http_requests=3)
    assert admin_client_logged_in.get(
        reverse("admin:refprice_reflookup_changelist")
    ).status_code == 200
