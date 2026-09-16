"""Rung 1: reduce a classified title to brand + line + model code.

Free, and the rung above it does not work without it. Measured (`ZBOZI_API.md` §5):
`Apple iPhone 13` returns 15 candidates, `Apple iPhone 13 128GB` returns **zero** —
Zbozi's suggest is a typeahead over catalogue titles, not a search.

Deliberately conservative. Everything stripped here is measurably noise; anything
cleverer risks removing the model code, and losing that fails *closed into a wrong
match* rather than into no match, which is the worse of the two outcomes.
"""
import re
import unicodedata

#: Cap: suggest is a prefix matcher, so a sentence never matches.
MAX_TOKENS = 6

#: Capacity/size suffixes — the measured killer.
_CAPACITY = re.compile(r"\b\d+\s?(gb|tb|mb)\b", re.I)
#: Prices and sale words.
_PRICE = re.compile(r"\b\d[\d\s]*(kč|kc|czk)\b", re.I)
#: Condition grade, e.g. "stav A", "stav B".
_GRADE = re.compile(r"\bstav\s+[a-c]\b", re.I)
#: Anything that is not a letter, digit, hyphen or whitespace.
_PUNCT = re.compile(r"[^\w\s-]", re.UNICODE)

#: Single-token noise. Matched case- and diacritic-insensitively.
_NOISE_TOKENS = frozenset({
    # condition / wear
    "zanovni", "novy", "nova", "nove", "novy!", "pouzity", "pouzita", "pouzite",
    "pouzivana", "pouzivany", "pouzivane", "malo", "jako", "top", "perfektni",
    "nepouzity", "nepouzita", "zachovaly", "zachovala",
    # packaging / paperwork
    "zaruka", "zarukou", "se", "v", "puvodnim", "baleni", "originalni", "faktura",
    "doklad", "uctenka",
    # selling words
    "prodam", "prodej", "levne", "sleva", "akce", "nabizim", "cena", "dohodou",
    "spechá", "spicha", "kus", "velmi", "pekny", "pekna", "bez", "skrabancu",
    "a", "s", "nabijeckou", "i",
    # colours, cs + en
    "cerny", "cerna", "cerne", "bily", "bila", "bile", "modry", "modra", "modre",
    "cerveny", "cervena", "zeleny", "zelena", "sedy", "seda", "stribrny", "stribrna",
    "zlaty", "zlata", "ruzovy", "ruzova", "fialovy", "zluty", "vesmirne",
    "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold",
    "pink", "purple", "yellow", "midnight", "starlight",
    # Category nouns. Zbozi's catalogue names are "Makita DHP484Z Li-ion 18 V", never
    # "aku vrtacka" — so a Czech seller's category word matches nothing and, because
    # suggest is a typeahead, actively empties the result set. Measured live:
    # "Karcher K5 vysokotlaky cistic" resolved to a Smoby toy, "Karcher K5" to the
    # pressure washer. Scoped to this project's four target categories rather than
    # attempting a Czech dictionary.
    "aku", "akumulatorova", "akumulatorovy", "vrtacka", "vrtacku", "vrtacky",
    "sroubovak", "bruska", "brusku", "pila", "pilu", "kladivo", "kotoucova",
    "prikleporva", "priklepova", "utahovak", "frezka", "hoblik", "kompresor",
    "cistic", "cistic!", "vysokotlaky", "vysokotlaka", "sekacka", "sekacku",
    "notebook", "notebooku", "pocitac", "telefon", "telefonu", "mobil", "mobilni",
    "monitor", "tablet!", "kolo", "jizdni", "horske", "naradi",
})


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, for matching only — never for output."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_model_code(token: str) -> bool:
    """A manufacturer model code: `DHP484Z`, `DCD796`, `18-2-LI`.

    The length and letter floors exist to keep *specifications* out. `18V` and `K5` read
    as codes under a looser rule, and treating a voltage as the product's identity is how
    "Makita DHP484Z 18V" ends up suggesting Merrell shoes (measured live 2026-09-16).
    """
    stripped = _fold(token).replace("-", "")
    return (len(stripped) >= 4
            and any(c.isdigit() for c in stripped)
            and sum(c.isalpha() for c in stripped) >= 2)


def _looks_like_a_model_code(token: str) -> bool:
    folded = _fold(token)
    return any(c.isdigit() for c in folded) and any(c.isalpha() for c in folded)


def _truncate_at_the_model_code(tokens: list[str]) -> list[str]:
    """A model code is the identity; everything after it is the seller's prose or specs.

    Measured live 2026-09-16, and not cosmetic — suggest is a typeahead, so what follows
    the code is fatal rather than merely noisy:

        "Makita DHP484Z aku vrtacka 18V"  ->  0 suggestions
        "Makita DHP484Z 18V"              -> 18 suggestions, none of them Makita
        "Makita DHP484Z"                  ->  8 suggestions, correct

    Tokens *before* the code are the product line (`Bosch **GSB** 18-2-LI`) and are kept.
    """
    first_code = next((i for i, t in enumerate(tokens) if is_model_code(t)), None)
    if first_code is None:
        return tokens
    return tokens[:first_code + 1]


def _clean(text: str) -> list[str]:
    text = _CAPACITY.sub(" ", text)
    text = _PRICE.sub(" ", text)
    text = _GRADE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    # Hyphens survive `_PUNCT` so that `18-2-LI` stays one token — which leaves bare
    # separators ("iPhone 13 - 5000 Kc") behind once the price is stripped.
    return [t for t in text.split() if any(c.isalnum() for c in t)]


def normalize_phrase(title: str, description: str = "") -> str:
    """Return a phrase suitable for `ReferenceProvider.suggest`, or "" if nothing survives."""
    kept: list[str] = []
    for token in _clean(title or ""):
        if _fold(token) in _NOISE_TOKENS:
            continue
        if _fold(token).isdigit() and len(token) > 4:
            # A bare 5+ digit run in a title is a price or a phone number, not a model.
            continue
        kept.append(token)
        if len(kept) >= MAX_TOKENS:
            break

    # Bazos titles cap at 120 chars and sellers routinely put the model code in the body.
    # Only a model code is taken, and only to extend — never to override the title.
    if description and len(kept) < MAX_TOKENS:
        have = {_fold(t) for t in kept}
        for token in _clean(description):
            if not _looks_like_a_model_code(token) or _fold(token) in have:
                continue
            kept.append(token)
            break

    return " ".join(_truncate_at_the_model_code(kept))
