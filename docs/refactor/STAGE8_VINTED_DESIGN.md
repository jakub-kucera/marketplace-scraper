# Stage 8 Design Notes — VintedScraper & Multi-Marketplace Queries

> **Status**: Design / pre-implementation  
> **Referenced from**: [PIPELINE_REFACTOR.md](./PIPELINE_REFACTOR.md) — Stage 8

---

## 1. Library choice

**Package**: [`vinted-scraper`](https://pypi.org/project/vinted-scraper/) by Giglium  
**Version**: `3.1.1` (released May 2026, actively maintained)  
**Install**: `pip install vinted-scraper`

```python
from vinted_scraper import VintedScraper

scraper = VintedScraper("https://www.vinted.cz")
items = scraper.search({"search_text": "macbook", "price_from": 5000})
# → List[VintedItem]
```

The library manages session cookies automatically. No BeautifulSoup — the API returns JSON.

### Key VintedItem fields

| `VintedItem` field | maps to `Ad` field |
|---|---|
| `id` | `external_id` |
| `title` | `name` |
| `price` (float) + `currency` | `price_raw` (formatted string) |
| `url` | `url` |
| `description` | `short_description` |
| — | `publish_date` — not available in search results |
| — | `view_count` — not available |
| — | `publisher_email` / `publisher_phone` — not available (`EmailPublisher` / `PhonePublisher` FKs will be `null`) |

---

## 2. Behavioural differences from BazosScraper

| Concern | BazosScraper | VintedScraper |
|---|---|---|
| Transport | HTML + BeautifulSoup | REST JSON via `vinted-scraper` lib |
| Session management | Caller passes `requests.Session` | Library manages cookies internally |
| Tor / IP rotation | Required — Bazos bans IPs | **Must NOT use** — Vinted bans proxies/VPNs |
| `check_blacklisted()` | Real HTTP 403 probe | Always returns `False` (no equivalent) |
| `load_full_description()` | Fetches second detail page | No-op — description already in search results |
| Pagination | Manual URL construction, stop on empty page | `per_page` param, stop when fewer results than page size |
| Publisher tracking | `EmailPublisher` / `PhonePublisher` FKs | Both FKs will be `null` (Vinted does not expose contact info) |
| "topped" ads | `topped=True` if ad is promoted | No `topped` concept — all results chronological; always `topped=False` |

### Tor implications

`BazosRunner` passes `self.ip_changer.session` into `BazosQueryRunner`, which forwards it to `BazosScraper`.
For Vinted queries, `VintedScraper` constructs its own session — the passed `session` argument must be ignored.
The `_build_scrapers(session)` factory in `bazos_query_runner.py`:

```python
def _build_scrapers(session: requests.Session) -> dict[str, MarketplaceScraper]:
    return {
        "bazos": BazosScraper(session),
        "vinted": VintedScraper("https://www.vinted.cz"),  # session ignored intentionally
    }
```

---

## 3. The Query model problem

### The core issue

A single `Query` row does not cleanly serve both marketplaces. Field-by-field breakdown:

| `Query` field | Bazos | Vinted |
|---|---|---|
| `text` | keyword search | `search_text` — **same** ✅ |
| `section` FK → `Section` | Bazos subdomain (`pc.bazos.cz`) | **no equivalent** |
| `category` FK → `Category` | Bazos category ID + URL slug | **completely different taxonomy** — Vinted uses `catalog_ids` integers |
| `price_lower` / `price_upper` | CZK price range | `price_from` / `price_to` — **same semantics** ✅ |
| `location_center` / `location_radius` | Bazos PSČ + km | Vinted search API **does not support location filtering** |
| `url` property | computed from `section`/`category` | needs to return `https://www.vinted.cz` |
| `load_full_description` | triggers second page fetch | meaningless for Vinted |

#### The category problem in detail

- **Bazos `Category`**: `bazos_id` integer + `url` slug + `Section` FK. Fully Bazos-specific.
- **Vinted categories**: `catalog_ids` (e.g. `1194`, `1206`...) — completely different integer IDs with no Section equivalent. A separate `VintedCategory` model would be needed for proper admin lookup, and would need to be seeded from Vinted's API.

---

## 4. Options considered

### Option A — Single model, nullable cross-marketplace fields *(simplest)*

Keep one `Query`. Accept that `section` / `category` are `null` for Vinted queries.
Add `vinted_catalog_ids = JSONField(default=list)` for Vinted category filtering.
`location_*` fields are silently ignored by `VintedScraper`.
`url` property returns `https://www.vinted.cz` when `marketplace="vinted"`.

**Pros**: No model restructure. One small migration.  
**Cons**: Admin shows half-empty fields for Vinted queries. Bazos-specific constraints look wrong for Vinted rows.

---

### Option B — Abstract base + per-marketplace subclasses *(cleanest OOP)*

Make `Query` an abstract base. Add `BazosQuery` and `VintedQuery` subclasses using Django multi-table inheritance.

**Pros**: Perfect separation, no nullable mismatches.  
**Cons**: Large refactor, breaks all existing FK relations to `Query`, breaks admin, breaks runner dispatch. Not worth it for two marketplaces.

---

### Option C — Single model + `extra_params` JSONField *(recommended)*

Keep one `Query` table. Add a single `extra_params = JSONField(default=dict)`.
Each scraper reads what it needs from it:

```python
# BazosScraper reads nothing from extra_params (uses section/category FKs as before)

# VintedScraper builds its search params:
params = {
    "search_text": query.text,
    "price_from": query.price_lower or None,
    "price_to": query.price_upper or None,
    **query.extra_params,   # e.g. {"catalog_ids": [1194], "order": "newest_first"}
}
```

`section` / `category` FKs stay Bazos-only; they are simply `null` for Vinted queries.
The existing constraint `not_section_or_not_category` already allows both to be `null`,
so Vinted queries satisfy it naturally without any constraint changes.

`url` property gains a short override:

```python
@property
def url(self):
    if self.marketplace == "vinted":
        return "https://www.vinted.cz"
    if self.section:
        return self.section.full_url
    elif self.category:
        return self.category.full_url
    return BAZOS_BASE_URL
```

**Pros**: One migration (add `extra_params` JSONField). No model restructure. Admin stays usable. `extra_params` maps directly to `vinted-scraper`'s search dict.  
**Cons**: `extra_params` is untyped — callers must know valid keys per marketplace. Document in admin help_text.

---

## 5. Decision

**Proceed with Option C.**

Migration adds `extra_params = JSONField(default=dict, blank=True)` to `Query`.
A `VintedCategory` model can be added later as a proper lookup for admin autocomplete if needed.

---

## 6. Files to create / modify

| File | Change |
|---|---|
| `bazos/scraping/vinted/__init__.py` | [NEW] empty |
| `bazos/scraping/vinted/vinted_scraper.py` | [NEW] `VintedScraper` implementing `MarketplaceScraper` |
| `bazos/scraping/bazos_query_runner.py` | uncomment `"vinted"` in `_build_scrapers` |
| `bazos/models.py` | add `extra_params` to `Query`; update `url` property |
| `bazos/migrations/0019_query_extra_params.py` | [NEW] migration |
| `bazos/admin.py` | `QueryAdmin`: show `extra_params`, `marketplace` fields |
| `pyproject.toml` | add `vinted-scraper = "^3.1.1"` |
| `bazos/scraping/vinted/tests/test_vinted_scraper.py` | [NEW] tests (mock `vinted_scraper.VintedScraper.search`) |

---

## 7. Open questions

- [ ] **Czech vs Slovak domain**: `vinted.cz` vs `vinted.sk`? Should the domain be per-query (stored in `extra_params` as `"base_url"`) or a Django setting?
- [ ] **"Bumped" listings**: Vinted has promoted listings (`promoted` flag in API response) — does the stopping logic from `BazosQueryRunner.run_existing_query` (break on first non-topped known ad) need a Vinted-specific variant, or should Vinted always scan the full page?
- [ ] **Rate limiting**: Vinted's unofficial API rate-limits aggressively. Should `VintedScraper` have its own back-off delay, or rely on the existing runner sleep intervals?
