"""Tests for `MarketplaceCategory` and `Ad.attributes` — the PR 1 schema.

Both are inert at this point: nothing reads either one. What is worth pinning now is the
shape they must keep, because both encode a decision that is easy to quietly undo later —
the taxonomy is a lookup rather than a `Query` FK, and `attributes` holds what the
marketplace said rather than what a parser made of it. See docs/backlog/VINTED_REWRITE.md
§2.1 and §2.3.
"""
import pytest
from django.db import IntegrityError

from bazos.models import Marketplace, MarketplaceCategory


@pytest.fixture
def vinted_tree(db):
    """Elektronika > Počítače a příslušenství > Notebooky — the real spine, real ids."""
    electronics = MarketplaceCategory.objects.create(
        marketplace=Marketplace.VINTED, external_id="2994",
        name="Elektronika", slug="2994-electronics",
    )
    computers = MarketplaceCategory.objects.create(
        marketplace=Marketplace.VINTED, external_id="3564",
        name="Počítače a příslušenství", slug="3564-computers-and-accessories",
        parent=electronics,
    )
    laptops = MarketplaceCategory.objects.create(
        marketplace=Marketplace.VINTED, external_id="3580",
        name="Notebooky", slug="3580-laptops", parent=computers,
    )
    return electronics, computers, laptops


def test_path_builds_a_breadcrumb(vinted_tree):
    _, _, laptops = vinted_tree
    assert laptops.path == "Elektronika > Počítače a příslušenství > Notebooky"


def test_path_of_a_root_is_just_its_name(vinted_tree):
    electronics, _, _ = vinted_tree
    assert electronics.path == "Elektronika"


def test_path_map_matches_path_without_walking_parents(vinted_tree, django_assert_num_queries):
    """The bulk path builder is the one the admin uses; it must agree with the property.

    Also pins the query count: `path` costs one query per level, so a changelist that
    used it per row would be thousands. `path_map` is a fixed two regardless of depth.
    """
    with django_assert_num_queries(1):
        paths = MarketplaceCategory.path_map(Marketplace.VINTED)

    for node in vinted_tree:
        assert paths[node.pk] == node.path


def test_path_map_is_scoped_to_one_marketplace(vinted_tree):
    other = MarketplaceCategory.objects.create(
        marketplace=Marketplace.SBAZAR, external_id="3580", name="Nářadí",
    )
    paths = MarketplaceCategory.path_map(Marketplace.VINTED)
    assert other.pk not in paths


def test_same_external_id_allowed_across_marketplaces(vinted_tree):
    """Identity is (marketplace, external_id) — the same pairing `Ad` uses. Vinted's 3580
    and some other marketplace's 3580 are unrelated and must coexist."""
    MarketplaceCategory.objects.create(
        marketplace=Marketplace.SBAZAR, external_id="3580", name="Nářadí",
    )
    assert MarketplaceCategory.objects.filter(external_id="3580").count() == 2


def test_duplicate_external_id_within_a_marketplace_is_rejected(vinted_tree):
    with pytest.raises(IntegrityError):
        MarketplaceCategory.objects.create(
            marketplace=Marketplace.VINTED, external_id="3580", name="Notebooky again",
        )


def test_path_survives_a_parent_cycle(db):
    """A cycle is not reachable through the seeder, but `path` must not hang the admin
    if one is ever created by hand — the loop is guarded, so assert it terminates."""
    a = MarketplaceCategory.objects.create(marketplace=Marketplace.VINTED, external_id="1", name="A")
    b = MarketplaceCategory.objects.create(marketplace=Marketplace.VINTED, external_id="2", name="B", parent=a)
    a.parent = b
    a.save(update_fields=["parent"])

    assert a.path              # terminates rather than recursing forever
    assert MarketplaceCategory.path_map(Marketplace.VINTED)[a.pk]


def test_deleting_a_parent_cascades(vinted_tree):
    """CASCADE is safe precisely because nothing outside this table references a row —
    no Query FK. If that ever changes, this test is the one that should start hurting."""
    electronics, _, _ = vinted_tree
    electronics.delete()
    assert MarketplaceCategory.objects.filter(marketplace=Marketplace.VINTED).count() == 0


def test_nothing_on_query_points_at_the_taxonomy():
    """The decision this whole model rests on: the ids live in `Query.extra_params`, so a
    re-seed can retire a node without either blocking (PROTECT) or silently widening a
    query to the whole marketplace (SET_NULL). A future FK would make this fail."""
    from bazos.models import Query

    pointing = [
        f.name for f in Query._meta.get_fields()
        if getattr(f, "related_model", None) is MarketplaceCategory
    ]
    assert pointing == [], f"Query gained a link to MarketplaceCategory: {pointing}"


# --------------------------------------------------------------------------- attributes

def test_attributes_defaults_to_empty_dict(make_ad, query, db):
    """Empty dict, never null — a marketplace publishing no specs is `{}`, and callers
    should never have to guard for None."""
    ad = make_ad(query, 1)
    ad.save()
    ad.refresh_from_db()
    assert ad.attributes == {}


def test_attributes_stores_values_verbatim(make_ad, query, db):
    """The point of the column: `"16 GB"` as the marketplace wrote it, not `16`.

    Storing the parsed number here would bake in today's parser and leave nothing to
    re-derive from when it improves — the same reason `price_raw` sits beside `price`.
    """
    ad = make_ad(query, 2)
    ad.attributes = {
        "computer_ram": "16 GB",
        "computer_storage_capacity": "1 TB",
        "computer_cpu_line": "Intel Core Ultra 9",
        "laptop_display_size": "16″–17,9″ (40–44 cm)",
    }
    ad.save()
    ad.refresh_from_db()

    assert ad.attributes["computer_ram"] == "16 GB"
    assert isinstance(ad.attributes["computer_ram"], str)
    assert ad.attributes["laptop_display_size"] == "16″–17,9″ (40–44 cm)"


def test_attributes_keeps_unknown_codes(make_ad, query, db):
    """No allow-list. The code set is category-dependent — a phone carries different codes
    from a laptop — and an unknown code costs nothing, whereas filtering drops data that
    cannot be recovered later."""
    ad = make_ad(query, 3)
    ad.attributes = {"some_code_invented_next_year": "value"}
    ad.save()
    ad.refresh_from_db()
    assert ad.attributes == {"some_code_invented_next_year": "value"}
