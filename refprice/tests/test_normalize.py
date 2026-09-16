"""Reducing a scruffy classified title to something `suggest` can match.

This is not a formality. Measured on the live API (`ZBOZI_API.md` §5): `Apple iPhone 13`
returns 15 candidates and **`Apple iPhone 13 128GB` returns zero**. Suggest is a typeahead
over catalogue titles, so spec noise is fatal — which means the cheapest rung of the
ladder is also the one without which the rung above it cannot work at all.

Conservative on purpose: strip what is measurably noise (capacity, condition, colour,
price, packaging) and cap the length. Anything cleverer risks removing the model code,
and losing that fails closed into a *wrong* match rather than no match.
"""
import pytest

from refprice.resolution.normalize import normalize_phrase


@pytest.mark.parametrize("title, expected", [
    # the measured killer: capacity suffixes empty the result set
    ("Apple iPhone 13 128GB", "Apple iPhone 13"),
    ("Apple iPhone 13 256 GB", "Apple iPhone 13"),
    ("Samsung Galaxy S21 512GB", "Samsung Galaxy S21"),
    # colours, Czech and English
    ("Apple iPhone 13 černý", "Apple iPhone 13"),
    ("Apple iPhone 13 black", "Apple iPhone 13"),
    ("Apple iPhone 13 vesmírně šedý", "Apple iPhone 13"),
    # condition grades and wear words
    ("Apple iPhone 13 stav A", "Apple iPhone 13"),
    ("Apple iPhone 13 zánovní", "Apple iPhone 13"),
    ("Apple iPhone 13 jako nový", "Apple iPhone 13"),
    ("Makita DHP484Z málo používaná", "Makita DHP484Z"),
    # price and sale noise
    ("Apple iPhone 13 - 5000 Kč", "Apple iPhone 13"),
    ("Apple iPhone 13 SLEVA", "Apple iPhone 13"),
    # packaging / paperwork
    ("Apple iPhone 13 v původním balení", "Apple iPhone 13"),
    ("Apple iPhone 13 se zárukou", "Apple iPhone 13"),
])
def test_strips_known_noise(title, expected):
    assert normalize_phrase(title) == expected


def test_keeps_the_model_code_intact():
    """`DHP484Z` is the entire signal. Losing it fails into a confident wrong match."""
    assert "DHP484Z" in normalize_phrase("Makita DHP484Z aku vrtačka 18V")


def test_truncates_at_the_model_code():
    """Measured live 2026-09-16, and the difference between working and not:
        "Makita DHP484Z aku vrtacka 18V"  ->  0 suggestions
        "Makita DHP484Z 18V"              -> 18 suggestions, none of them Makita
        "Makita DHP484Z"                  ->  8 suggestions, correct
    A voltage is a specification, not an identity."""
    assert normalize_phrase("Makita DHP484Z aku vrtačka 18V") == "Makita DHP484Z"


def test_keeps_the_product_line_before_the_code():
    """`GSB` is part of the name, and it sits *before* the code."""
    assert normalize_phrase("Bosch GSB 18-2-LI příklepová vrtačka") == "Bosch GSB 18-2-LI"


def test_a_voltage_is_not_treated_as_a_model_code():
    from refprice.resolution.normalize import is_model_code
    assert is_model_code("18V") is False
    assert is_model_code("K5") is False
    assert is_model_code("DHP484Z") is True
    assert is_model_code("18-2-LI") is True


def test_keeps_a_hyphenated_model_code():
    assert "GSB" in normalize_phrase("Bosch GSB 18-2-LI příklepová vrtačka")
    assert "18-2-LI" in normalize_phrase("Bosch GSB 18-2-LI příklepová vrtačka")


def test_keeps_a_model_year():
    """A year disambiguates a laptop generation; it is signal, not noise."""
    assert "2020" in normalize_phrase("Apple MacBook Pro 13 2020 i5")


def test_collapses_whitespace_and_punctuation():
    assert normalize_phrase("Apple   iPhone 13,,,  ") == "Apple iPhone 13"


def test_drops_emoji_and_decoration():
    assert normalize_phrase("🔥 Apple iPhone 13 🔥 TOP") == "Apple iPhone 13"


def test_caps_the_phrase_length():
    """Suggest is a prefix matcher; a sentence never matches."""
    long_title = "Prodám levně Apple iPhone 13 velmi pěkný kus bez škrábanců a s nabíječkou"
    assert len(normalize_phrase(long_title).split()) <= 6


def test_an_empty_title_normalises_to_empty():
    assert normalize_phrase("") == ""


def test_a_title_that_is_all_noise_normalises_to_empty():
    assert normalize_phrase("nový, se zárukou, 128GB, černý") == ""


def test_it_does_not_lowercase_the_result():
    """The phrase is shown to a human in the evidence, and brands read wrong in lowercase."""
    assert normalize_phrase("Apple iPhone 13 128GB") == "Apple iPhone 13"


def test_description_supplies_a_model_code_the_title_lacks():
    """Bazos titles are capped at 120 chars and sellers often put the code in the body."""
    phrase = normalize_phrase("Aku vrtačka Makita", description="Model DHP484Z, 18V, bez aku")
    assert "DHP484Z" in phrase


def test_the_description_never_overrides_the_title():
    phrase = normalize_phrase("Apple iPhone 13", description="taky mám Samsung Galaxy S21")
    assert phrase.startswith("Apple iPhone 13")
    assert "Samsung" not in phrase
