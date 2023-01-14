from urllib.parse import urlparse

import pytest

from bazos.models import Section, Category, Query


@pytest.mark.django_db
def test_gen_url():
    section = Section.objects.create(name="PC", bazos_id="PC", url="pc")
    category = Category.objects.create(name="Notebooky", url="notebook", bazos_id=10, section=section)
    query = Query.objects.create(text="macbook", category=category, location_center="12345", location_radius=25, price_lower=0, price_upper=100)
    assert urlparse(query.url) == urlparse("https://pc.bazos.cz/notebook/")
    # assert query.url == "https://pc.bazos.cz/notebook/"
    # assert query.url == "https://www.bazos.cz/pc/notebook/?hledani=macbook&hledani=12345&hledani=25&hledani=0&hledani=100"
    assert 1 == 1
