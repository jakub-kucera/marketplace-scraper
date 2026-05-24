from unittest.mock import MagicMock, patch

import pytest

from bazos.models import Ad, Query
from bazos.scraping.bazos_query_runner import BazosQueryRunner


def make_runner(query):
    return BazosQueryRunner(query, MagicMock())


# --- run_existing_query ---

@pytest.mark.django_db
def test_existing_query_saves_new_ad(query, make_ad):
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()
    assert Ad.objects.filter(query=query, bazos_id=111).exists()


@pytest.mark.django_db
def test_existing_query_counts_new_ads(query, make_ad):
    products = [make_ad(query, bazos_id=i) for i in [111, 222]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert runner.new_product_counter == 2


@pytest.mark.django_db
def test_existing_query_stops_on_known_non_topped_ad(query, make_ad):
    make_ad(query, bazos_id=111).save()
    products = [
        make_ad(query, bazos_id=111, topped=False),  # known, not TOP → stop
        make_ad(query, bazos_id=222, topped=False),  # would be new, but never reached
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert not Ad.objects.filter(query=query, bazos_id=222).exists()
    assert runner.new_product_counter == 0


@pytest.mark.django_db
def test_existing_query_does_not_stop_on_known_topped_ad(query, make_ad):
    make_ad(query, bazos_id=111).save()
    products = [
        make_ad(query, bazos_id=111, topped=True),   # known but TOP → continue
        make_ad(query, bazos_id=222, topped=False),  # new → should be saved
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert Ad.objects.filter(query=query, bazos_id=222).exists()
    assert runner.new_product_counter == 1


@pytest.mark.django_db
def test_existing_query_does_not_save_duplicate(query, make_ad):
    make_ad(query, bazos_id=111).save()
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([make_ad(query, bazos_id=111, topped=True)])):
        runner.run_existing_query()
    assert Ad.objects.filter(query=query, bazos_id=111).count() == 1


# --- run_new_query ---

@pytest.mark.django_db
def test_new_query_sets_new_query_false(query, make_ad):
    query.new_query = True
    query.save()
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([])):
        runner.run_new_query()
    assert query.new_query is False


@pytest.mark.django_db
def test_new_query_with_ignore_first_run_saves_but_does_not_count(query, make_ad):
    query.ignore_first_run = True
    query.save()
    products = [make_ad(query, bazos_id=i) for i in [1, 2, 3]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert Ad.objects.filter(query=query).count() == 3
    assert runner.new_product_counter == 0


@pytest.mark.django_db
def test_new_query_without_ignore_first_run_counts_new_products(query, make_ad):
    query.ignore_first_run = False
    query.save()
    products = [make_ad(query, bazos_id=i) for i in [1, 2, 3]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert runner.new_product_counter == 3


@pytest.mark.django_db
def test_new_query_stops_before_max_non_topped_ads(query, make_ad, monkeypatch):
    import bazos.scraping.bazos_query_runner as qr_module
    monkeypatch.setattr(qr_module, "NEW_PRODUCT_LOAD_MAX", 3)

    # 5 non-topped products; with limit=3 the 3rd triggers break before being saved
    products = [make_ad(query, bazos_id=i, topped=False) for i in range(1, 6)]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    # products 1 and 2 are saved; product 3 causes break (saved as per loop logic? let's check)
    # The break fires after counter reaches limit, BEFORE save() for that product
    assert Ad.objects.filter(query=query).count() == 2


@pytest.mark.django_db
def test_new_query_topped_ads_do_not_count_toward_limit(query, make_ad, monkeypatch):
    import bazos.scraping.bazos_query_runner as qr_module
    monkeypatch.setattr(qr_module, "NEW_PRODUCT_LOAD_MAX", 2)

    products = [
        make_ad(query, bazos_id=1, topped=True),   # doesn't count
        make_ad(query, bazos_id=2, topped=True),   # doesn't count
        make_ad(query, bazos_id=3, topped=False),  # counter=1
        make_ad(query, bazos_id=4, topped=False),  # counter=2 → break, not saved
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert Ad.objects.filter(query=query, bazos_id=1).exists()
    assert Ad.objects.filter(query=query, bazos_id=2).exists()
    assert Ad.objects.filter(query=query, bazos_id=3).exists()
    assert not Ad.objects.filter(query=query, bazos_id=4).exists()
