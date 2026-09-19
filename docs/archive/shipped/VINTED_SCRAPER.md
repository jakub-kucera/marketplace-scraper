---
title: "Stage 8 — `VintedScraper`: implementation spec"
status: shipped
updated: 2026-09-18
verified: 2026-09-18
shipped_in: 0029
---

# Stage 8 — `VintedScraper`: implementation spec

> ## ⛔ DO NOT USE §4 AS A TRAP LIST. THE TRANSPORT IT DESCRIBES NO LONGER EXISTS.
>
> **Audited 2026-09-18.** Vinted withdrew the anonymous `/api/v2/catalog/items` endpoint around
> 2026-09-08 and every Vinted query failed until the scraper was rebuilt on the catalog page's
> Next.js RSC payload (commit `4cf35ec`, 2026-09-16). The `vinted-scraper` PyPI package and
> `httpx` that this whole document is written against are **gone from `pyproject.toml`**; the
> scraper now uses `bazos/scraping/vinted/client.py` + `flight.py` over plain `requests`.
>
> **The live trap list for Vinted is [`VINTED.md`](../../research/marketplaces/VINTED.md)**
> (measured 2026-09-16) with the implementation plan in
> [`VINTED_REWRITE.md`](../../backlog/VINTED_REWRITE.md). Read those before touching
> `bazos/scraping/vinted/vinted_scraper.py`. Three §4 instructions here are now **inverted** by
> the current code, each for a measured reason recorded in the module's docstrings:
>
> | This doc says | The code does, deliberately |
> |---|---|
> | §4.5 use `total_item_price`, not `price` | uses `price` (ex-fee). Vinted's own `price_from`/`price_to` filter keys on `price`, so storing the all-in figure made a `price_upper=5000` query return rows stored at up to 5268, which `price_range` then rejected |
> | §4.4/§4.6 leave `short_description` empty | fills it from `itemBox` (`firstLine · secondLine`). Empty silently disabled `blocklist_keyword` and `required_keyword` on Vinted, since both match `name + short_description` |
> | §4.3 send `per_page` | never sends it. `per_page` was retired with the v2 API; the page is fixed at 96, and the walk is bounded by `VINTED_MAX_PAGES=10` |
>
> What is still true and still worth reading: **§2** (the schema widenings, all still in the
> model), **§4.4's `topped`/`publish_date`/`view_count` decisions**, and **§7**. The mapper now
> additionally sets `Ad.price`/`price_type` (P22, migration `0032`) and `Ad.attributes`
> (migration `0043`), neither of which existed when this was written.
>
> **✅ Built 2026-08-22** — `Marketplace.VINTED` is live, migration `0029_vinted_support`. See
> [`SHIPPED.md`](../../SHIPPED.md).
>
> Executable expansion of [`VINTED_SCRAPER_DESIGN.md`](VINTED_SCRAPER_DESIGN.md) and the old
> `PROMPTS.md` P3 + P4, which it superseded and which have since been retired from that file —
> they predated the live probe and were wrong in nine ways that crash rather than degrade.
>
> Field names and API behaviour come from a **live probe of `vinted-scraper` 4.0.0 against
> `vinted.cz` on 2026-08-21** — see the design doc §1a and §8. They were measured, not assumed,
> and they described a transport that has since been withdrawn.
>
> Class and file names have moved too (2026-08-23, commit `0a91b9a`): `BazosRunner` is now
> `ScrapeRunner` in `bazos/scraping/runner.py`, and `BazosQueryRunner` is now `QueryRunner` in
> `bazos/scraping/query_runner.py`. Read the old names below as the new ones.

---

## 1. Order of work

Four PRs. Do not collapse them — PR 1 is a schema change that must be deployed and verified
before any Vinted row exists.

| PR | Content | Ships behaviour? |
|---|---|---|
| **1** | Model changes + migration (§2, §3) | No — inert |
| **2** | `VintedScraper` class + tests (§4, §5) | No — not registered yet |
| **3** | Register in `_build_scrapers`, uncomment `Marketplace.VINTED`, admin (§6) | Yes |
| **4** | Create one real Vinted `Query` and watch it (§8) | Yes — operational |

---

## 2. ⚠️ Two blockers that must be fixed first, or every Vinted ad fails to save

Both were missed by the design doc, and **P4 step 2 actively instructs the first one**.

### 2.1 `Ad.external_id` overflows on Postgres

`Ad.external_id` is `models.IntegerField(db_index=True)`. Postgres `integer` maxes at
**2,147,483,647**. Measured live Vinted ids:

```
9734229070   →  4.5x over int4 max
```

Every Vinted ad would raise `psycopg2.errors.NumericValueOutOfRange` on `save()`. **The test
suite would not catch this** — `conftest.py` runs everything on SQLite, which has no fixed
integer width and accepts the value silently.

**Fix:** change to `models.BigIntegerField(db_index=True)`. Bazos ids are far below the
threshold, so this is a widening with no data impact.

### 2.2 `publish_date` and `view_count` are NOT NULL with no default

```python
view_count   = models.IntegerField(help_text="View count at the time of discovery")
publish_date = models.DateTimeField()
```

The Vinted search payload has **no date field at all**, and `view_count` is `0` on every row.
Django leaves unset `IntegerField`/`DateTimeField` attributes as `None`, so `save()` raises
`IntegrityError`.

**Fix:** make both `null=True, blank=True`.

**Do NOT synthesise values.** P4 step 2 says `publish_date=None, view_count=None` (which
crashes today); the temptation is to "fix" it with `publish_date=timezone.now()`. Do not. A
synthesised timestamp is exactly the failure that made `BazosScraper.extract_date` produce
all-midnight dates and blocked P14 for months — a fake date is worse than a null one because
nothing downstream can tell it is fake.

Store `view_count=None` rather than `0` for the same reason: `0` asserts "nobody viewed this",
which is false; `None` says "unknown", which is true.

### 2.3 Fields that are fine (do not change them)

`location`, `publisher_name`, `short_description` are `CharField`s. Django defaults an unset
`CharField` to `''`, which satisfies NOT NULL. Leave them; set `location=""` explicitly in the
mapper so the intent is visible.

### 2.4 The migration

One migration covering all three field changes.

**Migration number: `0028`.** Resolved 2026-08-21 — the `Ad`/`AdDelivery` split landed first and
took `0026_addelivery.py` and `0027_merge_duplicate_ads.py`. Still run `ls bazos/migrations/` to
confirm nothing else has landed since.

> **Correction to an earlier draft of this spec.** It claimed Vinted *had* to land before the
> split's Stage C, on the grounds that merging duplicate ads keyed on `(marketplace, external_id)`
> while the column was too narrow for Vinted ids would "bake in a broken identity". **That was
> overcautious and is now moot.** The merge only ever grouped existing Bazos rows, whose ids fit
> in `int4` comfortably, and widening the column afterwards leaves those merged rows untouched.
> There was no dependency. The order simply resolved itself.

⚠️ **One real consequence of the split landing first:** `0027` added a
`UniqueConstraint(fields=("marketplace", "external_id"), name="unique_ad_per_marketplace")`.
Widening `external_id` to `BigIntegerField` therefore alters a column that participates in a
unique index, so Postgres rebuilds that index and takes a lock for the duration. Harmless at this
table size, but it is a schema change to run during the normal deploy stop, not against a live
process — which `deploy.yml` already guarantees (`down` → `migrate` → `up -d`).

The constraint is otherwise **good news for Vinted**: global `(marketplace, external_id)` identity
is now enforced at the DB level, so a Vinted id can never collide with a Bazos one and
rediscovery across queries is handled by the split rather than by this scraper.

## 3. `Query.extra_params` (this is P3)

Add to `Query` in `bazos/models.py`:

```python
    extra_params = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Marketplace-specific search params. Ignored by Bazos. Vinted: "
            '{"base_url": "https://www.vinted.sk", "catalog_ids": [1194]}. '
            "Vinted text search is fuzzy — a 'macbook' search returns unrelated items — so "
            "setting filter_required is strongly recommended on Vinted queries."
        ),
    )
```

Update the `url` property (currently has no marketplace branch):

```python
    @property
    def url(self):
        if self.marketplace == Marketplace.VINTED:
            return self.extra_params.get("base_url", VINTED_BASE_URL)
        if self.section:
            return self.section.full_url
        elif self.category:
            return self.category.full_url
        return BAZOS_BASE_URL
```

Add to `bazos/const.py`:

```python
VINTED_BASE_URL: Final[str] = "https://www.vinted.cz"
VINTED_PAGE_SIZE: Final[int] = 96   # server-enforced cap, measured: asked 200, got 96
```

The existing `not_section_or_not_category` constraint already permits both FKs being null, so
Vinted queries satisfy it with **no constraint change**.

---

## 4. The scraper

**File:** `bazos/scraping/vinted/vinted_scraper.py` (plus an empty `__init__.py`).

> **⛔ §4.1, §4.2 and §4.6 describe the `vinted-scraper` library and are now history.** There is
> no `VintedApiClient` to alias, no session-cookie bootstrap that intermittently raises
> `RuntimeError`, and no OpenGraph scrape with a 5/8 success rate. The package directory is now
> `vinted_scraper.py` + `client.py` + `flight.py`, and `load_full_description` reads the
> schema.org `Product` JSON-LD (3/3 on probe) behind a bare `except Exception`. The *principle*
> §4.6 states is the durable part and still holds: a detail fetch escaping here aborts the rest
> of that query's pass, so everything must be caught.

### 4.1 ⚠️ The name collision — alias the library class

The library's class is *also* called `VintedScraper`. P4 and the design doc are ambiguous about
which one is which. Mandatory convention:

```python
from vinted_scraper import VintedScraper as VintedApiClient   # the library
...
class VintedScraper:                                          # ours, implements MarketplaceScraper
```

Our class takes **no constructor arguments** beyond the ignored session, and builds the client
per query (the base URL is per-query, from `extra_params`).

### 4.2 Class shape

```python
class VintedScraper:
    """MarketplaceScraper for Vinted, backed by the `vinted-scraper` package.

    Deliberately ignores the `session` the runner passes in: the library builds its own
    httpx client, and Vinted bans proxy/VPN traffic, so Vinted requests egress from the
    host's real IP rather than through Tor. See VINTED_SCRAPER_DESIGN.md §2.
    """
    marketplace = Marketplace.VINTED.value

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session          # accepted for factory symmetry, intentionally unused
        self._clients: dict[str, VintedApiClient] = {}
```

Cache one client per base URL — the library fetches a session cookie on construction, so
rebuilding it per query would double the request count.

⚠️ **Client construction can raise `RuntimeError`.** The constructor fetches a session cookie
from the site root; Vinted sits behind Cloudflare + DataDome and this **intermittently fails**:

```
RuntimeError: Cannot fetch session cookie from https://www.vinted.cz
```

Observed live once during the probe, succeeding immediately on retry. The library already
retries internally (3 attempts) — **do not add another retry layer**. Let this one propagate:
"cannot reach Vinted at all" is a genuine query failure and P18 records it on `QueryRun`
(`success=False` + `error`). This is deliberately different from §4.6's per-ad failures, which
must never abort a pass. Because of it, expect occasional failed `QueryRun` rows on Vinted
queries that are not bugs — see §8.

### 4.3 `run_query`

```python
    def run_query(self, query: Query) -> Iterator[Ad]:
```

- Build params:
  ```python
  params = {
      "search_text": query.text,
      "order": "newest_first",
      "per_page": VINTED_PAGE_SIZE,
      **query.extra_params,
  }
  if query.price_lower:
      params["price_from"] = query.price_lower
  if query.price_upper:
      params["price_to"] = query.price_upper
  ```
  ⚠️ **`order: "newest_first"` is mandatory.** Vinted's default order is *relevance*. The
  dedup walk in `run_existing_query` assumes newest-first and will break at an arbitrary point
  without it. Confirmed working live.

  ⚠️ Strip `base_url` out of `params` before passing them to `search()` — it selects the client,
  it is not a search parameter.

  Note `price_lower`/`price_upper` use the `0 == no filter` convention (P7), hence the
  truthiness checks. Confirmed live that `price_from`/`price_to` are honoured.

- Paginate with `page`, starting at 1, incrementing until a page returns fewer than
  `per_page` items or zero. Pagination via `page` is confirmed working (no overlap between
  pages 1 and 2). Add a hard page cap (`MAX_ATTEMPTS`-style, e.g. 20) so a misbehaving
  response cannot loop forever.

- Yield an `Ad` per item, mapped per §4.4.

### 4.4 The field mapping — exact

> **⛔ Partly superseded 2026-09-16 (`4cf35ec`).** The RSC payload names these fields differently
> (`productItem.id` / `.title` / `.url` / `.price.amount` / `.isPromoted` / `.itemBox`), and
> `short_description` is no longer `""`. The `topped`, `publish_date=None` and `view_count=None`
> decisions below survived the rewrite unchanged and are still the reason those columns are null
> on Vinted.

```python
        Ad(
            external_id=item.id,
            marketplace=self.marketplace,
            url=item.url,
            name=item.title[:120],
            price_raw=self._format_price(item),
            location="",
            view_count=None,
            publish_date=None,
            topped=bool(item.promoted),
            short_description="",
            publisher_name="",
        )
```

⚠️ **`name` must be truncated to 120** — `Ad.name` is `CharField(max_length=120)` and the very
first measured live title was 78 characters with plenty of headroom above it. Postgres raises
`DataError` on overflow; SQLite does not, so the tests will not catch it.

⚠️ **`topped=bool(item.promoted)`** — `promoted` is real and behaves like Bazos's topped ads,
appearing out of chronological order even under `newest_first`. Mapping it correctly is what
lets `run_existing_query`'s existing `continue`-on-topped / `break`-on-known logic work
unchanged. **Do not write a Vinted-specific dedup variant.**

### 4.5 ⚠️ `_format_price` — the decimal trap

> **⛔ REVERSED 2026-09-16 (`4cf35ec`).** The decimal trap below is still real and the current
> `_price()` still guards it. The **choice of field is not**: read `price`, not
> `total_item_price`. See the banner at the top of this file for the measured reason.

`parse_price` in `bazos/filters.py` does `re.sub(r"\D", "", price_raw)`. A price string of
`"6307.5 CZK"` therefore parses to **63075** — a silent 10× error that would wreck
`PriceRangeRule` and `PriceDropRule`.

Vinted prices *are* decimals, because most `vinted.cz` results are FX-converted from PLN
(measured: `1385.41`, `107.44`, `197.92`).

```python
    @staticmethod
    def _format_price(item) -> str:
        """Integer CZK only — `parse_price` strips non-digits, so a decimal point would
        silently multiply the parsed value by 10. See VINTED_SCRAPER.md §4.5."""
        amount = item.total_item_price if item.total_item_price is not None else item.price
        return f"{round(amount)} {item.currency}"
```

**Use `total_item_price`, not `price`.** Measured `5990.0` vs `6307.5` — the difference is
Vinted's buyer-protection fee, which the buyer actually pays. For a deal-hunting pipeline the
all-in number is the honest one. `Ad.price_raw` is `max_length=30`; the formatted string is
well under that.

### 4.6 `load_full_description` — must tolerate BOTH failure modes

```python
    def load_full_description(self, ad: Ad) -> Ad:
```

⚠️ **This is NOT a no-op.** The design doc originally said the description arrives with the
search results; measured, `description` is `None` on every search result.

There are **two distinct failure modes**, and they are easy to conflate. Both are normal.

**(a) HTTP 200, unparseable head → a sparse `{'id'}`-only response.** The library streams the
item page and extracts OpenGraph meta tags; when they are not found it returns a dict
containing only `id`. **Measured success rate: 5 of 8.** No exception is raised.

**(b) Non-200 → `RuntimeError`.** Confirmed live:

```
>>> client.item("1")
RuntimeError: Cannot perform API call to endpoint /items/1, error code: 404
```

`VintedWrapper.item()` calls `_raise_curl_error` on any non-200. **On a resale marketplace this
is a routine event** — an item sold or was deleted between the search response and the detail
fetch — not an exceptional one.

⚠️ **Mode (b) is the one that bites**, because `_handle_new_product` calls this with no
try/except (`bazos/scraping/bazos_query_runner.py`):

```python
        if self.query.load_full_description:
            self.scraper.load_full_description(product)
            product.save()
```

An uncaught `RuntimeError` propagates out through `run_new_query` / `run_existing_query` into
`BazosRunner.run`'s per-query `except Exception`. That is not a process crash — P18 catches it
and records `QueryRun.success=False` — but it **aborts the rest of that query's pass mid-loop**,
losing every ad after the one that happened to be sold. One deleted listing would silently
truncate a scrape.

Both existing scrapers already handle their equivalent: `BazosScraper.load_full_description`
returns the ad unchanged on a failed/`None` response, and `BazosApiScraper.load_full_description`
explicitly handles 410 and non-200. **Match that pattern.**

```python
    def load_full_description(self, ad: Ad) -> Ad:
        client = self._client_for(ad_base_url)
        try:
            detail = client.item(str(ad.external_id))
        except RuntimeError as e:
            # Non-200 from the item page — normally a listing sold or deleted between the
            # search response and this call. Routine on a resale marketplace; never fatal.
            logger.info("Vinted detail fetch failed for ad %s: %s", ad.external_id, e)
            return ad
        description = getattr(detail, "description", None)
        if not description:
            # HTTP 200 but no OpenGraph tags in the head — measured ~3/8. Also normal.
            logger.debug("Vinted detail for ad %s carried no description", ad.external_id)
            return ad
        ad.full_description = description
        return ad
```

- Leave `short_description` empty — the only source is this call, and that text belongs in
  `full_description`. A truncated duplicate buys nothing.
- Do **not** retry either mode in a loop, and do **not** treat either as a blacklist signal.

### 4.7 `check_blacklisted`

```python
    def check_blacklisted(self) -> bool:
        return False
```

Vinted has no equivalent probe. Note the signature takes **no `url` argument** — the protocol
changed in `2fb37f8`; older docs show `check_blacklisted(url="")`.

---

## 5. Tests

**File:** `bazos/tests/test_vinted_scraper.py` — flat path, matching the other 20 test files.
**Not** `bazos/scraping/vinted/tests/`, which the design doc's file table wrongly specified.

Mock `VintedApiClient.search` / `.item`; never hit the network in tests. Build fake items with a
small factory mirroring the measured shape (`id`, `title`, `price`, `total_item_price`,
`currency`, `promoted`, `description=None`, `url`).

Required tests:

| Test | Asserts |
|---|---|
| `test_maps_search_result_to_ad` | every field in §4.4, on one realistic item |
| `test_price_uses_total_item_price_and_is_integer` | `"6308 CZK"` from `total_item_price=6307.5` — and `parse_price` of it returns `6308`, **not** `63075` |
| `test_price_falls_back_to_price_when_total_missing` | `total_item_price=None` → uses `price` |
| `test_promoted_maps_to_topped` | `promoted=True` → `topped=True` |
| `test_long_title_is_truncated_to_120_chars` | a 200-char title does not exceed the column |
| `test_publish_date_and_view_count_are_none` | pins §2.2 — no synthesised values |
| `test_big_external_id_survives_save` | `@pytest.mark.django_db`, id `9734229070`, saves and reloads equal |
| `test_search_params_include_newest_first_order` | asserts `order == "newest_first"` reaches `search()` |
| `test_base_url_is_stripped_from_search_params` | `extra_params={"base_url": ...}` selects the client and is absent from `search()` params |
| `test_price_bounds_omitted_when_zero` | `price_lower=0, price_upper=0` → no `price_from`/`price_to` keys |
| `test_pagination_stops_on_short_page` | page 1 full, page 2 short → 2 calls, all items yielded |
| `test_pagination_stops_on_empty_page` | page 2 empty → no extra call |
| `test_load_full_description_sets_full_description` | detail returns a description → stored |
| `test_load_full_description_tolerates_id_only_response` | detail returns `{'id'}` → returns ad unchanged, **no exception** (mode a) |
| `test_load_full_description_survives_runtime_error` | ⚠️ `client.item` raises `RuntimeError` (sold/deleted listing, 404) → returns ad unchanged, **no exception escapes** (mode b) |
| `test_run_query_completes_when_one_detail_fetch_raises` | ⚠️ the regression that matters: 3 ads, the 2nd raises `RuntimeError` on detail → **all 3 still yielded**, pass not truncated |
| `test_check_blacklisted_always_false` | trivial, but pins the protocol |

---

## 6. Registration (PR 3)

- `bazos/models.py`: uncomment `VINTED = "vinted", "Vinted"` in `Marketplace`.
- `bazos/scraping/bazos_query_runner.py`: uncomment the `Marketplace.VINTED.value` line in
  `_build_scrapers`. Note it passes `session` — our class accepts and ignores it (§4.2), so the
  factory signature stays uniform.
- `bazos/admin.py`: **no change needed.** `QueryAdminForm.Meta.fields = "__all__"`, so
  `extra_params` appears on the form automatically once it exists on the model, and
  `marketplace` is already in `list_display` and `list_filter`. (An earlier draft of this spec
  said to add the field by hand — that was busywork.) The operator-facing guidance lives in the
  field's own `help_text`, set in §3.
- `pyproject.toml`: `vinted-scraper = "^4.0.0"`. ⚠️ **Not `^3.1.1`** — that constraint resolves
  below 4.0.0 and does not get the probed API. It pulls in `httpx` as a new transitive dep.
- **No new docker-compose service.** `run_scraper` already iterates all enabled queries and
  dispatches on `query.marketplace`; P4 step 5's "or confirm the existing scraper handles all
  marketplaces" resolves to *confirmed*.

---

## 7. Interactions to be aware of (do not fix here)

- **`Ad.message` renders "0 ads seen"** for every Vinted ad — both publisher FKs are null and
  `SellerAdCounts.for_ad` short-circuits to zeros. Not a crash; it is noise in every Discord
  notification. That is P11's job.
- **Keyword rules match on the title alone** on Vinted, since `short_description` is empty.
  Combined with Vinted's fuzzy text search (a `macbook` query returned a Mango handbag),
  `filter_required` matters much more here than on Bazos.
- **Seller identity exists and is better than Bazos's** — `item.user` carries a stable id,
  login, and a `business` dealer flag. Capturing it needs a new model and a GDPR retention
  decision (`MONETIZATION.md` §6.1). Out of scope; record it, do not build it.
- **Cross-border inventory.** Most `vinted.cz` results for tech are Polish sellers with
  FX-converted prices. Distance/travel-cost scoring (`BACKLOG_IDEAS.md` #10) must stay gated on
  `marketplace`, as that idea already says.
- **`Ad`/`AdDelivery` split** ([`AD_DELIVERY_SPLIT.md`](AD_DELIVERY_SPLIT.md)) —
  ⚠️ **landed 2026-08-21** (`0026`, `0027`), so write this scraper against the post-split world.
  In practice the scraper is unaffected: `run_query` still yields plain `Ad` objects and
  `BazosQueryRunner` owns persistence, including creating the `AdDelivery` row. **Do not set
  `Ad.status` in the scraper** — that column has moved. If you are working from an older copy of
  this spec or of `PROMPTS.md`, check `bazos/models.py` before assuming where pipeline state
  lives.

---

## 8. Rollout (PR 4)

1. Create **one** Vinted `Query` with `new_query=True` and `ignore_first_run=True`, so the first
   pass backfills silently instead of dumping up to 50 notifications into Discord.
2. Check the admin: ads created, `topped` populated, `price_raw` an integer string,
   `publish_date` null.
3. Flip `ignore_first_run=False` and watch one real notification arrive.
4. Only then add more Vinted queries.

Note the P19 canary counts rows across *all* queries in a pass, so a broken Vinted scraper will
not by itself trip the zero-rows alert while Bazos queries keep returning rows. Watch
`QueryRun.success` for the Vinted query specifically during rollout.

⚠️ **Expect occasional `success=False` rows on Vinted that are not bugs** — the session-cookie
bootstrap intermittently fails behind Cloudflare/DataDome (§4.2). A steady trickle is normal;
a run of consecutive failures is not. If you find yourself unable to tell those apart, that is
the argument for tracking a per-query failure rate rather than eyeballing the list.

---

## 9. Explicitly out of scope

- ~~`VintedCategory` lookup model — `extra_params["catalog_ids"]` is enough for a first version.~~
  **Shipped 2026-09-16** as the marketplace-agnostic `MarketplaceCategory` (migration `0043`,
  commits `8edfaa1` seeding the tree and `511436a` making the admin pick from it instead of
  typing ids). `extra_params["catalog_ids"]` is still what the scraper reads.
- Capturing `item.user` / seller identity (§7).
- Images (`photo`/`photos` are in the payload for free) — that is P16.
- Async (`AsyncVintedScraper` exists) — that is `BACKLOG_IDEAS.md` #2.
- Any change to `parse_price` — §4.5 works within its current behaviour deliberately.
- Bespoke rate-limit backoff — 6 rapid searches measured clean at ~0.30s each, no 429.
