"""The `ReferenceProvider` protocol and the plain types that cross the app boundary.

Design: `docs/proposals/PRICE_REFERENCE_SERVICE.md` §3. Measurements:
`docs/research/marketplaces/ZBOZI_API.md`.

Two deliberate shapes:

- **`search` is a separate protocol member from `suggest`** because they have different
  compliance postures, not different mechanics. `suggest` is robots-allowed; `search` is
  the `?q=` route that is not. Keeping them apart puts that distinction in the type rather
  than in a flag buried inside one method, which is what lets the resolution ladder gate
  one and not the other.
- **Every price here is whole CZK.** Providers convert at their own edge, exactly once.
  Zbozi reports hundredths under two spellings (`minPrice`, `minPriceHa`), and
  `parse_price` in `bazos/filters.py` strips non-digits — an unconverted value lands 100x
  too large.
"""
import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class NotPermitted(Exception):
    """Raised for a route the caller has not explicitly opted into (see `search`)."""


@dataclass(frozen=True)
class Candidate:
    """One suggestion. `slug` is what `fetch` takes."""
    slug: str
    name: str
    image_url: str | None = None


@dataclass(frozen=True)
class RefProductFacts:
    """What a provider knows about one catalogue product, right now."""
    provider: str
    product_id: str
    slug: str
    name: str
    brand: str | None
    category_id: int | None
    #: Manufacturer part number. Present on roughly half of catalogued products, and the
    #: only stable identifier either site exposes — no EAN/GTIN anywhere.
    product_no: str | None
    min_czk: int | None
    #: The headline. NOT `min`: mis-pairing puts a different product's cheaper offer at the
    #: bottom of the range (ZBOZI_API.md §6), and it poisons min, not median.
    median_czk: int | None
    max_czk: int | None
    #: `<= 1` means one merchant's opinion, not a market.
    shop_count: int
    availability: str
    release_date: dt.date | None
    url: str | None = None


@dataclass(frozen=True)
class PricePoint:
    date: dt.date
    min_czk: int | None
    median_czk: int | None
    max_czk: int | None


@runtime_checkable
class ReferenceProvider(Protocol):
    name: str

    def suggest(self, phrase: str) -> list[Candidate]:
        """Resolve a phrase to candidate products. Returns [] rather than raising."""
        ...

    def fetch(self, slug: str) -> RefProductFacts | None:
        """Fetch one product, or None when it does not exist or cannot be reached."""
        ...

    def history(self, product_id: str, months_back: int) -> list[PricePoint]:
        """Price series, oldest first. Returns [] rather than raising."""
        ...

    def search(self, phrase: str, *, allow_disallowed: bool = False) -> list[Candidate]:
        """Full-text search. Raises `NotPermitted` unless explicitly opted into."""
        ...


#: Implemented providers only. `heureka` is absent on purpose: its content surface has
#: never rendered to a plain client from any of three egress types (ZBOZI_API.md §2).
PROVIDER_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    PROVIDER_REGISTRY[getattr(cls, "name")] = cls
    return cls


def get_provider(name: str = "zbozi") -> ReferenceProvider:
    try:
        return PROVIDER_REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown reference provider {name!r}. Implemented: {sorted(PROVIDER_REGISTRY)}"
        ) from None
