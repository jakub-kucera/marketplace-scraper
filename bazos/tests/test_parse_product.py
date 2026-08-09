"""Tests for BazosScraper._parse_product (pure HTML parsing, no DB)
and _resolve_publishers (DB side-effects).
"""
from textwrap import dedent

import pytest
from bs4 import BeautifulSoup

from bazos.scraping.bazos.bazos_scraper import BazosScraper


# ---------------------------------------------------------------------------
# Minimal but structurally correct fixture HTML for a single ad element.
# Produced by inspecting the CSS classes consumed by _parse_product.
# ---------------------------------------------------------------------------

def make_product_html(
    *,
    bazos_id: int = 12345678,
    name: str = "MacBook Pro 15 2019",
    price: str = "35 000 Kč",
    location: str = "Praha 2",
    date_str: str = "31.3.2024",
    view_count: str = "42",
    short_desc: str = "Prodám MacBook Pro.",
    topped: bool = False,
    publisher_email_id: int = 100,
    publisher_phone_id: int = 200,
    publisher_name: str = "Prodavač",
) -> str:
    date_cell = f"TOP [{date_str}]" if topped else f"[{date_str}]"
    return dedent(f"""
        <div class="inzeraty">
          <div class="inzeratynadpis">
            <div class="nadpis">
              <a href="/inzerat/{bazos_id}/macbook-pro-15.php">{name}</a>
            </div>
            <div class="velikost10">{date_cell}</div>
            <div class="popis">{short_desc}</div>
          </div>
          <div class="inzeratycena">{price}</div>
          <div class="inzeratylok">Praha<br/>Praha 2</div>
          <div class="inzeratyview">{view_count} x</div>
          <div class="inzeratyakce">
            <span onclick="reportAd(1,'{bazos_id}','token')">Označit špatný inzerát</span>
            <span onclick="rateUser(1,'{publisher_email_id}','{publisher_phone_id}','{publisher_name}')">Ohodnotit uživatele</span>
          </div>
        </div>
    """)


def parse_element(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find(class_="inzeraty")


# ---------------------------------------------------------------------------
# _parse_product — no DB marker needed
# ---------------------------------------------------------------------------

class TestParseProduct:
    def _parsed(self, **kwargs) -> dict:
        return BazosScraper._parse_product(parse_element(make_product_html(**kwargs)))

    def test_name_is_extracted_and_whitespace_normalised(self):
        result = self._parsed(name="  MacBook   Pro  ")
        assert result["name"] == "MacBook Pro"

    def test_url_is_relative_href(self):
        result = self._parsed(bazos_id=12345678)
        assert result["url"] == "/inzerat/12345678/macbook-pro-15.php"

    def test_bazos_id_matches_url_segment(self):
        result = self._parsed(bazos_id=12345678)
        assert result["external_id"] == "12345678"

    def test_price_raw_stripped(self):
        result = self._parsed(price="  35 000 Kč  ")
        assert result["price_raw"] == "35 000 Kč"

    def test_view_count_is_first_token(self):
        result = self._parsed(view_count="42")
        assert result["view_count"] == "42"

    def test_short_description_stripped(self):
        result = self._parsed(short_desc="  Prodám laptop.  ")
        assert result["short_description"] == "Prodám laptop."

    def test_topped_false_when_no_top_in_date(self):
        result = self._parsed(topped=False)
        assert result["topped"] is False

    def test_topped_true_when_top_in_date(self):
        result = self._parsed(topped=True)
        assert result["topped"] is True

    def test_location_merges_br_with_comma(self):
        result = self._parsed(location="Praha 2")
        # br is replaced with ", " so we get "Praha, Praha 2"
        assert "," in result["location"]

    def test_publish_date_is_timezone_aware(self):
        from django.utils import timezone as tz
        result = self._parsed(date_str="31.3.2024")
        assert tz.is_aware(result["publish_date"])

    def test_publish_date_day_month_year(self):
        result = self._parsed(date_str="15.6.2023")
        d = result["publish_date"]
        assert (d.day, d.month, d.year) == (15, 6, 2023)

    def test_publisher_email_id_is_int(self):
        result = self._parsed(publisher_email_id=999)
        assert result["publisher_email"] == 999

    def test_publisher_phone_id_is_int(self):
        result = self._parsed(publisher_phone_id=888)
        assert result["publisher_phone"] == 888

    def test_publisher_name_is_string(self):
        result = self._parsed(publisher_name="JanNovak")
        assert result["publisher_name"] == "JanNovak"


# ---------------------------------------------------------------------------
# _resolve_publishers — needs DB
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_resolve_publishers_creates_records():
    from bazos.models import EmailPublisher, PhonePublisher

    email_pub, phone_pub = BazosScraper._resolve_publishers(100, 200)

    assert EmailPublisher.objects.filter(bazos_id=100).exists()
    assert PhonePublisher.objects.filter(bazos_id=200).exists()
    assert email_pub.bazos_id == 100
    assert phone_pub.bazos_id == 200


@pytest.mark.django_db
def test_resolve_publishers_is_idempotent():
    from bazos.models import EmailPublisher, PhonePublisher

    BazosScraper._resolve_publishers(100, 200)
    BazosScraper._resolve_publishers(100, 200)

    assert EmailPublisher.objects.filter(bazos_id=100).count() == 1
    assert PhonePublisher.objects.filter(bazos_id=200).count() == 1


@pytest.mark.django_db
def test_resolve_publishers_stores_zero_email_id_as_null():
    """`0` is Bazos's "no publisher" marker, not an identity — it must not become a row.

    A shared bazos_id=0 row acts as a hub joining unrelated sellers: measured at 1137 ads
    across 671 distinct phones on the 2024-03 export.
    """
    from bazos.models import EmailPublisher

    email_pub, phone_pub = BazosScraper._resolve_publishers(0, 200)

    assert email_pub is None
    assert phone_pub.bazos_id == 200
    assert not EmailPublisher.objects.filter(bazos_id=0).exists()


@pytest.mark.django_db
def test_resolve_publishers_stores_zero_phone_id_as_null():
    from bazos.models import PhonePublisher

    email_pub, phone_pub = BazosScraper._resolve_publishers(100, 0)

    assert phone_pub is None
    assert email_pub.bazos_id == 100
    assert not PhonePublisher.objects.filter(bazos_id=0).exists()


@pytest.mark.django_db
def test_resolve_publishers_handles_both_ids_zero():
    from bazos.models import EmailPublisher, PhonePublisher

    assert BazosScraper._resolve_publishers(0, 0) == (None, None)
    assert not EmailPublisher.objects.exists()
    assert not PhonePublisher.objects.exists()


@pytest.mark.django_db
def test_zero_publisher_ids_do_not_link_unrelated_ads():
    """Two ads that both lack an email publisher must not end up sharing one.

    This is the regression the sentinel caused: `get_or_create(bazos_id=0)` returned the
    same row for every such ad, so grouping by publisher merged them into one seller.
    """
    ad_a = BazosScraper.extract_product(
        parse_element(make_product_html(bazos_id=1, publisher_email_id=0, publisher_phone_id=11))
    )
    ad_b = BazosScraper.extract_product(
        parse_element(make_product_html(bazos_id=2, publisher_email_id=0, publisher_phone_id=22))
    )

    assert ad_a.email_publisher is None
    assert ad_b.email_publisher is None
    assert ad_a.phone_publisher.bazos_id != ad_b.phone_publisher.bazos_id


# ---------------------------------------------------------------------------
# extract_product (integration: pure parse + DB resolve)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_extract_product_returns_ad_with_correct_name():
    from bazos.models import Ad

    element = parse_element(make_product_html(name="Test Laptop"))
    ad = BazosScraper.extract_product(element)

    assert isinstance(ad, Ad)
    assert ad.name == "Test Laptop"


@pytest.mark.django_db
def test_extract_product_links_publisher_records():
    element = parse_element(make_product_html(publisher_email_id=55, publisher_phone_id=66))
    ad = BazosScraper.extract_product(element)

    assert ad.email_publisher.bazos_id == 55
    assert ad.phone_publisher.bazos_id == 66
