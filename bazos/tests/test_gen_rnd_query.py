
import pytest

from bazos.models import Section, Category, Query

# TODO use baker to create objects

@pytest.mark.django_db
def test_gen_url():
    section = Section.objects.create(name="PC", bazos_id="PC", url="pc")
    category1 = Category.objects.create(name="Notebooky", url="notebook", bazos_id=10, section=section)
    category2 = Category.objects.create(name="Klavesnice", url="klavesnice", bazos_id=99, section=section)
    queries = Query.generate_random_queries(1)
    assert queries[0].category in [category1, category2]
