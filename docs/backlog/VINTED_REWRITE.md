---
title: Vinted — rewrite the scraper on the catalog-page transport
status: active
updated: 2026-09-16
verified: 2026-09-16
---

# Vinted — rewrite the scraper on the catalog-page transport

> **Why now:** every Vinted query has failed since 2026-09-08 with
> `RuntimeError: Cannot perform API call to endpoint /api/v2/catalog/items, error code: 404`.
> Vinted withdrew the anonymous catalog API; `vinted-scraper` cannot be fixed by upgrading.
> The measured replacement is in [`VINTED.md`](../research/marketplaces/VINTED.md) — **read it
> first**, this document does not repeat its evidence and every "measured" claim below points
> back into it.
>
> The failure is contained to Vinted queries by the runner's per-query guard, which is why it ran
> for eight days unnoticed. Nothing else in the pipeline is affected.
>
> ## ✅ Status, 2026-09-17 — **done, deployed, and verified in production**
>
> | PR | Branch | State |
> |---|---|---|
> | 1 | `vinted/pr1-schema` | ✅ merged into the branch chain |
> | 2 | `vinted/pr2-catalogs` | ✅ seeds 2,920 nodes, verified live |
> | 3 | `vinted/pr3-scraper` | ✅ verified end to end against live vinted.cz |
> | 4 | `vinted/pr4-catalog-picker` | ✅ |
> | 5 | `vinted/pr5-fieldsets` | ✅ |
> | 6 | — | ✅ shipped in **v1.2.0** (2026-09-16), §7 worked through 2026-09-17 |
>
> Coverage of the Vinted modules is 100% of statements, 99% of branches.
>
> **What the rollout actually produced**, measured on the Pi 2026-09-17:
>
> - **The outage is over.** 12 Vinted query runs in 12 hours, **0 failures**, against 132 ok /
>   131 failed for Bazos over the same window (that ratio is the unrelated Tor block rate).
> - §7.2: `create_vinted_catalogs` → `2920 created, 0 updated`, exactly as predicted.
> - §7.3: query 13 converted to `{"catalog_ids": [3580], "brand_ids": [54661]}` with `text`
>   cleared. Both ids were checked before the change rather than trusted — `3580` resolves to
>   **Notebooky** in the seeded table, and the scraper logged no `_warn_on_param_mismatch`, so
>   Vinted honoured both.
> - §7.4: the quiet first pass produced **one** `SUPPRESSED` delivery, not a flood. Widening
>   from `search_text=macbook` to catalog+brand turned out to add almost nothing the text
>   search was already finding — worth knowing before converting the next query, because the
>   feared Discord flood is not the real risk here.
>
> §7.5, on 104 ads from the new transport, with two boxes left open honestly:
>
> | check | result |
> |---|---|
> | ads created, `QueryRun.success` true | ✅ 104 ads |
> | **`short_description` non-empty** (the §3.5.1 regression check) | ✅ **104/104** — and note this is a *change*: under the old scraper all 760 Vinted ads had it empty, so both keyword rules were silently disabled on Vinted and are now live |
> | `publish_date` / `view_count` null | ✅ 104/104 both |
> | `price` parsed | ✅ `price_raw` is `"10192 CZK"` → `price=10192`, `price_type=exact`. Note the checklist's wording "an integer string" describes `price`, not `price_raw`, which carries the currency suffix |
> | **`topped` set on some rows** | ⚠️ **0 of 104.** 40 Vinted ads are topped overall but the newest is 2026-09-13, i.e. all predate this transport. Either the catalog page does not expose a promoted flag or it is not being read. Low impact — `topped` only feeds `dedup_break_streak`, and under `newest_first` an eager break is correct anyway — but the box is not ticked |
> | `attributes` carries specs with `load_full_description=True` | ⏸ not checked; query 13 has the flag **off** |

---

## 1. Decisions already taken

Settled, not open for re-litigation during implementation:

1. **`Ad.price` stores `price` — the seller's asking price, excluding Buyer Protection.** Not
   `totalItemPrice`. This is a change from the shipped scraper. Rationale in §3.5; the short form
   is that the server-side `price_from`/`price_to` filter works on `price`, so storing anything
   else makes `price_range` reject rows the marketplace was asked to return.
2. **Vinted's taxonomy gets a lookup table, not a foreign key on `Query`.** `extra_params`
   stays the source of truth. Rationale in §2.1.
3. **Drop `vinted-scraper`.** The rewrite uses `requests` + the stdlib. No `httpx`.
4. **No Tor for Vinted**, unchanged. The scraper still accepts and ignores the session's proxy
   configuration — see §3.1.
5. **`Ad.attributes` (JSONB) captures marketplace-stated structured specs, stored raw.** Not
   normalised at write time, and not a child table. Rationale in §2.3.

## 2. Order of work

Six PRs. PRs 1–2 are inert and can land any time; PR 3 is what restores service. **PR 3 does not
depend on PR 2** — it reads `extra_params["catalog_ids"]`, which an operator can populate by hand
today. It *does* depend on PR 1 for `Ad.attributes`, which is one migration away. Land PR 1 + PR 3
first if the eight-day outage matters more than ergonomics.

⚠️ **PR 1 is the one with a deadline.** `attributes` can only ever be filled from a live page, so
every pass that runs without the column loses those specs permanently — there is nothing to
backfill from. Consuming them (§9) can wait; capturing them cannot.

| PR | Content | Restores Vinted? |
|---|---|---|
| **1** | `MarketplaceCategory` + `Ad.attributes` + migration `0043` (§2.1, §2.3) | No — inert |
| **2** | `manage.py create_vinted_catalogs` (§2.2) | No — seeds PR 1 |
| **3** | **The scraper rewrite** (§3) + tests | **Yes** |
| **4** | `QueryAdminForm` catalog picker (§4) | No — ergonomics |
| **5** | Per-marketplace fieldsets (§5) | No — ergonomics |
| **6** | Rollout (§7) | Operational |

### 2.1 PR 1 — `MarketplaceCategory`

New model in `bazos/models.py`. **Nothing points at it from `Query`** — no FK, no constraint
change, `not_section_or_not_category` untouched.

```python
class MarketplaceCategory(models.Model):
    """Marketplace taxonomy, as a lookup for the admin — NOT a Query FK.

    Deliberately not a ForeignKey from Query. Vinted's tree is ~2,920 nodes re-seeded from
    the live site; a PROTECT FK would make a re-seed fail whenever Vinted retires a node a
    Query points at, and SET_NULL would silently widen that Query to the whole site. With
    extra_params holding the ids, a retired node degrades to "returns nothing" and the
    re-seed can just warn. Bazos keeps Section/Category: those are URL builders
    (Section.full_url is a subdomain), not lookups, and migrating them buys nothing.
    """
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices)
    external_id = models.CharField(max_length=32)
    name        = models.CharField(max_length=120)
    slug        = models.CharField(max_length=160, blank=True)
    parent      = models.ForeignKey("self", null=True, blank=True,
                                    on_delete=models.CASCADE, related_name="children")

    class Meta:
        verbose_name_plural = "Marketplace categories"
        constraints = [
            models.UniqueConstraint(fields=("marketplace", "external_id"),
                                    name="unique_category_per_marketplace"),
        ]

    def __str__(self):
        return self.path

    @property
    def path(self) -> str:
        """`Elektronika › Počítače a příslušenství › Notebooky`.

        Not cosmetic: 205 Vinted titles are shared by more than one node — 575 of 2,920
        (20%) are ambiguous by name alone, and "Ostatní" appears 35 times. A flat picker
        is unusable. See VINTED.md §9.
        """
```

⚠️ `path` walks `parent` and will emit a query per level unless the caller prefetched. The admin
picker (§4) builds its labels **once** from a single `select_related("parent__parent__parent")` or
an in-memory pass over the whole table — never per-row in a loop. The tree is 4–5 deep.

⚠️ The `marketplace` column exists from day one on purpose. Sbazar already stores
`extra_params["category_id"]` and will want the same picker; naming this `VintedCategory` would
force a rename migration later for nothing.

**Migration: `0043`.** Verify with `ls bazos/migrations/` at write time — `0042_alter_category_options`
is current as of 2026-09-16.

Register it on `unfold.admin.ModelAdmin` (a stock `ModelAdmin` renders unthemed and
`test_every_registered_changelist_renders` will not catch it) and add a sidebar entry — a new model
does **not** appear in `UNFOLD["SIDEBAR"]["navigation"]` on its own.

### 2.2 PR 2 — `manage.py create_vinted_catalogs`

Mirrors `create_sections` / `create_categories`. One HTTP request, idempotent,
`update_or_create` keyed on `(marketplace, external_id)`.

- Fetch any catalog page (`/catalog?search_text=x`) with the §3.1 transport.
- The tree is nested in the flight payload under `"catalogs":[…]`; walk it recursively so
  `parent` is resolved from structure rather than guessed. ⚠️ `"catalogs":[` appears **17,312
  times** — the first match is a *subtree*, not the root. Either walk every match and union the
  results, or regex the whole payload for `"id":N,"title":"…","url":"/catalog/N-slug"` triples
  (2,920 unique nodes) and resolve parents in a second pass.
- **Report, never delete.** If a seeded id is absent from a fresh fetch, log a warning naming any
  `Query` whose `extra_params["catalog_ids"]` references it. Deleting would strand config; that is
  the whole reason this isn't an FK.

Add to CLAUDE.md's one-off tools block alongside `geocode_postal_codes`.

### 2.3 PR 1 — `Ad.attributes`

```python
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured specs as the marketplace stated them, verbatim: "
            '{"computer_ram": "16 GB", "computer_storage_capacity": "1 TB"}. '
            "Empty for marketplaces that publish none (Bazos, Sbazar today)."
        ),
    )
```

**On `Ad`, not a child table.** `PriceChange` and `AdPriceScore` are child tables because `Ad` is
re-read every pass — but both are **1:N** (a price history; one score per model). Attributes are
**1:1** with the listing, so that rationale does not transfer. `Ad` already carries
`full_description` as a `TextField`, which is far larger than a dozen short key/values.

⚠️ **Stored raw — never normalised at write time.** `{"computer_ram": "16 GB"}`, not
`{"ram_gb": 16}`. This is the same split as `price_raw` / `price`: keep the marketplace's own words
as the audit trail and derive the parse at read time. Normalising on write bakes in today's parser
and leaves nothing to re-derive from when it improves — the bind `rescore_ads` exists to work
around. Values stay strings; do not coerce types.

The seam this preserves: **`Ad.attributes` is what the marketplace said; `AdPriceScore.features` is
what a model made of it.** That keeps true the reason `features` is JSON at all — it is the model's
vocabulary, not the table's.

⚠️ **No index initially.** A `GinIndex` would make `attributes` queryable, but nothing queries it
yet and `django.contrib.postgres.indexes.GinIndex` is Postgres-only — verify it does not break the
`TEST_DB=sqlite` migration path (`contract-check.yml`) before adding one. Add it when a real query
pattern appears, not speculatively.

⚠️ **Only populated when `query.load_full_description=True`.** The specs are on the detail page; the
listing row carries brand, model and condition and nothing else. A Vinted query that wants price
scoring must enable the detail fetch, and that is a per-query cost of one paced request per new ad.

Generic on purpose: the column is marketplace-neutral, stays `{}` for Bazos and Sbazar, and is
ready for Aukro. Do **not** write regex-derived values into it from Bazos text — that would destroy
the stated-vs-derived distinction the column exists to keep.

## 3. PR 3 — the scraper

Rewrite `bazos/scraping/vinted/vinted_scraper.py` in place. The class name, module path and
`MarketplaceScraper` protocol conformance stay; `_build_scrapers` needs no change.

### 3.1 Transport

```python
def _get(self, url: str) -> str:
    response = self.session.get(url, headers={
        "User-Agent": VINTED_USER_AGENT,          # a browser UA is mandatory — see below
        "Accept": "text/x-component",
        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
        "RSC": "1",                                # returns the flight payload, no HTML wrapper
    }, timeout=VINTED_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text
```

- **Use the `session` the runner passes.** The old class ignored it because the library built its
  own `httpx` client; that reason is gone. It must still not egress through Tor — the runner hands
  every scraper `ip_changer.session`, so `VintedScraper.__init__` builds its **own**
  `requests.Session()` and keeps the passed one only for factory symmetry. Make that explicit in a
  comment; an accidental Tor egress here is the one change that could get the IP banned.
- **One `GET /` first**, per scraper instance, to obtain `access_token_web` (24 h) and `anon_id`.
  Cache it on the instance; `_build_scrapers` currently rebuilds per query, so this costs one extra
  request per query per pass. Acceptable; do not add a retry loop around it.
- ⚠️ **Without a browser `User-Agent` the request is served a DataDome interstitial.** With one, 10
  back-to-back fetches returned 200 with full results (VINTED.md §10).
- ⚠️ **Do not detect blocks by grepping for `datadome`** — the string is present on healthy pages.
  Detect a block as "the items array did not parse", nothing else.
- `Accept-Encoding: gzip` — `requests` handles this. Payload is ~803 KB wire, ~7.2 MB decompressed,
  ~1.2 s per page. That is the cost of this transport and there is no leaner variant (§3.6).

### 3.2 Parsing

The response is the raw RSC flight payload. Locate `"items":{"items"`, then **balanced-scan** from
the following `[` — tracking string state and escapes — and `json.loads` the slice.

⚠️ **Do not regex the item array out.** Titles contain `"`, `[`, `{` and backslashes routinely
(measured: `MacBook Pro 13" Retina (A1502)`, `Macbook Air 2018 | Ładowarka |`). A balanced scanner
that understands JSON strings is ~20 lines and is the only correct approach. Put it in a module
function with its own unit tests — it is the single most breakage-prone thing in this PR.

Also parse `"pagination"` (`current_page`, `per_page`, `total_entries`, `total_pages`) and
`"initialCatalogState"` → `filters`.

⚠️ **Assert the filter echo.** Unknown query params are silently dropped. After the first page,
compare `filters` against what was requested (`query`, `catalogIds`, `sortBy`, `priceFrom`/`priceTo`)
and log a WARNING on mismatch. This is the canary for Vinted renaming a param — without it, a
renamed `order` degrades to relevance sort and quietly breaks the dedup walk with no error anywhere.

### 3.3 Search parameters

```python
params: list[tuple[str, Any]] = [("order", "newest_first")]     # mandatory — see §3.4
if query.text:
    params.append(("search_text", query.text))
for cid in extra_params.pop("catalog_ids", []):
    params.append(("catalog[]", cid))
for bid in extra_params.pop("brand_ids", []):
    params.append(("brand_ids[]", bid))
for sid in extra_params.pop("status_ids", []):
    params.append(("status_ids[]", sid))
if query.price_lower:
    params += [("price_from", query.price_lower), ("currency", VINTED_CURRENCY)]
if query.price_upper:
    params += [("price_to", query.price_upper), ("currency", VINTED_CURRENCY)]
```

A list of pairs, not a dict — `catalog[]` repeats. `base_url` is popped first and selects the
domain (`.cz`/`.sk`/`.pl` all work, currency follows the domain — VINTED.md §6c).

⚠️ `per_page` is **no longer a parameter**; 96 is server-fixed. Keep `VINTED_PAGE_SIZE = 96` only as
the short-page sentinel.

⚠️ **`status_ids[]` values are not the ids item pages report.** Filter ids are
1/2/3/4/6/7; an item page's `status.id` for "Velmi dobrý" is `50`, and passing 50 returns zero rows.
Table in VINTED.md §3. Worth documenting in the `extra_params` help text, because this one fails
silently as "no results" rather than as an error.

**Relevance.** `search_text` alone is fuzzy — 22 of 96 results for `macbook` were unrelated
(Nike windbreakers, a handbag). `catalog[]` + `brand_ids[]` returned 96/96 correct. The
`extra_params` help text must say so, and §7 rollout should convert the existing Vinted queries to
structured filters rather than reinstating text search.

### 3.4 Pagination and dedup

- `page` starts at 1, increments; stop on a short page, an empty page, `page > total_pages`, or
  `VINTED_MAX_PAGES`.
- ⚠️ `total_entries` is **capped at 960 / 10 pages** for broad queries; a narrow one reports its
  true count. Treat 960 as "at least 960", never as a total.
- **`order=newest_first` is mandatory and verified chronological** (VINTED.md §7): position 0 was
  "před minutou", 50 was "včera", monotonic throughout for non-promoted rows.
- **Map `isPromoted` → `Ad.topped`.** Promoted rows sit far out of chronological order (positions 75
  and 95 were newer than position 50). The existing continue-on-topped walk handles them; do **not**
  write a Vinted-specific dedup variant.
- **Leave `dedup_break_streak` at the default 1.** The ordering premise it requires — everything
  below the first known ad is older — is measured true here.
- ⚠️ **Never use item id as a recency proxy.** 36 inversions among 88 non-promoted rows, max
  positional displacement 61. Ids are assigned at draft creation.

### 3.5 Field mapping

```python
Ad(
    external_id=item["id"],                        # BigIntegerField — ids exceed int4
    marketplace=Marketplace.VINTED.value,
    url=urljoin(base_url, item["url"]),            # url is RELATIVE now: "/items/1001…-slug"
    name=item["title"][:120],
    price_raw=f"{amount} {currency}",
    price=amount,                                  # int, ex-fee — see below
    price_type=PriceType.EXACT,
    short_description=f"{first_line} · {second_line}"[:300],   # §3.5.1
    location="",                                   # not served
    publish_date=None,                             # not served in ANY form
    view_count=None,                               # not served
    topped=bool(item["isPromoted"]),
    publisher_name="",                             # see §3.5.2
)
```

**Price.** `item["price"]["amount"]` is a **decimal string** (`"17999.00"`). Parse with `Decimal`,
round to int, format once.

```python
amount = int(Decimal(item["price"]["amount"]).quantize(0, ROUND_HALF_UP))
```

⚠️ Not `float`, and not `re.sub(r"\D", "", …)` — `parse_price` strips non-digits, so `"6307.5 CZK"`
becomes `63075`, a silent 10× error.

⚠️ **This is `price`, not `totalItemPrice` — a deliberate change from the shipped scraper.**
`price + serviceFee == totalItemPrice` holds on 96/96 rows, with `fee = 18 CZK + 5%` exactly. The
server filters on `price`, so storing the total made `price_to=5000` return rows whose stored price
was up to 5268 — which `price_range` then rejected. Store `price`; surface the all-in figure in the
Discord message instead, where `serviceFee` and `totalItemPrice` are free in the same row.

`price_type` is `EXACT` — Vinted has no placeholder price strings. ⚠️ If `amount == 0` ever appears,
map it to `PriceType.FREE`, not `EXACT` with a zero: that is the distinction
`docs/research/PRICE_PARSING.md` §3.3 exists for. No zero-price row was observed (minimum measured
35 CZK), so treat this as defensive.

⚠️ **FX.** 78% of `.cz` prices are converted from another currency (measured 71/91 non-round). Over
~1 h, **0 of 91 prices changed**, so Vinted pins the rate rather than re-quoting continuously.
Rounding to integer absorbs sub-koruna moves. Still, `run_existing_query` compares `price_raw` as a
**string**, so a genuine re-quote wave would write a `PriceChange` per affected ad and flip every
delivery to `PRICE_CHANGED`. Watch `PriceChange` volume on Vinted after rollout; if a wave appears,
that is the reason, not a bug in the walk.

#### 3.5.1 `short_description` — the real improvement

The shipped scraper stored `""`, which silently disabled `blocklist_keyword` and `required_keyword`
on Vinted (they match `name + short_description`). `productItem.itemBox` gives, at **96/96
coverage**, `firstLine` (Vinted-normalised brand + model, e.g. `Apple MacBook Pro 2019`) and
`secondLine` (condition). Store `f"{firstLine} · {secondLine}"`.

Do **not** store `accessibilityLabel` instead: it embeds both prices, so it would change whenever
the price does, and it duplicates the title. `firstLine · secondLine` is stable, descriptive and
non-duplicative. Cap at 300 defensively even though the measured max is well under it —
`short_description` is a `TextField`, but the habit is what the `varchar(300)` outage taught.

#### 3.5.2 Seller

`item["user"]` carries `{id, isBusiness}` — a stable, non-opaque seller id plus a dealer flag,
strictly better than Bazos's opaque pairs. `EmailPublisher`/`PhonePublisher` stay null, so
`publisher_blocklist` still cannot fire and `Ad.message` still renders "0 ads seen".

**Out of scope here** — capturing it needs a model and a GDPR retention decision
(`MONETIZATION.md` §6.1). Record the id in the research doc, don't build it in this PR.

### 3.6 `load_full_description`

```python
def load_full_description(self, ad: Ad) -> Ad:
```

Fetch `ad.url` with the §3.1 transport, extract the **JSON-LD** blob (`"jsonLd":{…}` → schema.org
`Product`) and read `description`. Present on **3/3** items probed, against the old OpenGraph
scrape's 5/8.

- Pace it: `sleep(uniform(*VINTED_DETAIL_WAIT_TIME))` **before** the request. A `new_query` backfill
  calls this up to `NEW_PRODUCT_LOAD_MAX = 50` times with no delay of its own.
- ⚠️ **Catch broadly and return `ad` unchanged on any failure.** `QueryRunner._handle_new_product`
  calls this with no try/except, and `_tolerating_one_bad_ad` catches only `DatabaseError` — so
  anything escaping here aborts the rest of that query's pass. A sold/deleted listing 404ing between
  the search and this call is routine on a resale marketplace, not exceptional.
- ⚠️ **Never write a price from the detail page.** JSON-LD `offers.price` is in the **seller's**
  currency — a `.cz` listing returned `2500 PLN` while its listing row showed converted CZK.
  Description only.
- Do **not** touch `short_description` here; §3.5.1 already filled it from the listing, and that
  runs even when `load_full_description` is off.

**Also write `Ad.attributes` here** (§2.3). The same detail page carries a typed attribute list:

```python
ad.attributes = {
    a["code"]: a["data"]["value"]
    for a in attributes_block
    if a.get("code") and isinstance(a.get("data"), dict) and a["data"].get("value")
}
```

Measured on one laptop: `computer_cpu_line`, `computer_ram`, `computer_storage_capacity`,
`computer_operating_system`, `laptop_display_size`, `laptop_charger_included`, `keyboard_layout`,
`brand`, `model_nav`, `status`, `upload_date`.

⚠️ **Store every code the page offers, verbatim — do not allow-list.** The set is
category-dependent (a phone carries different codes from a laptop) and unknown codes cost nothing,
whereas a filter drops data that cannot be recovered later.

⚠️ **Do not parse `upload_date` into `publish_date`.** It is relative display text
(`"před hodinou"`, `"včera"`) and belongs in `attributes` as the string it is. §3.5's
`publish_date=None` stands.

⚠️ `status` here is the **item-page** condition id (`50`), not the `status_ids[]` filter value
(`2`) — see §3.3. Storing the raw value is correct; just never feed it back as a filter.

This is the highest-value thing Vinted offers: `PRICE_MODEL_BENCHMARK.md` §3.1 names feature
*extraction*, not model class, as the measured weak point, and `bazos/pricing/features.py`'s own
docstring records two live defects it had to fix in regexing RAM and storage out of prose
(`16GB RAM / 512GB SSD` mislabelling 512 as RAM; `zaruka do 04/2027` parsing as 4 GB RAM and a
2027 GB disk). Typed fields do not improve that parser — they make it unnecessary on this
marketplace. **Consuming them is §9 and stays out of this PR**; capturing them is here because
nothing can backfill them.

### 3.7 `check_blacklisted`

`return False`. No block signal was observed (VINTED.md §10) and nothing in production calls it.

## 4. PR 4 — the admin picker

In `QueryAdminForm`, a **non-model** field, following the `filter_rule_names` pattern:

```python
vinted_catalogs = forms.ModelMultipleChoiceField(
    queryset=MarketplaceCategory.objects.filter(marketplace=Marketplace.VINTED),
    widget=UnfoldAdminCheckboxSelectMultipleWidget,   # or a filtered-select; name it explicitly
    required=False,
    label="Vinted categories",
    help_text="Writes to extra_params['catalog_ids']. Far more precise than text search.",
)
```

- `__init__` seeds `initial` from `instance.extra_params.get("catalog_ids")`.
- `clean()` writes the selected ids back into `cleaned_data["extra_params"]`, preserving every other
  key. ⚠️ `clean_extra_params` already coerces `None → {}`; order the two so the picker writes into
  the coerced dict, not the raw one.
- Labels come from `MarketplaceCategory.path`. ⚠️ Build them in one pass — see §2.1's note about
  `path` walking parents. 2,920 rows × 4 levels of lazy FK access would be ~12k queries on a form
  render.
- A checkbox list over 2,920 rows is unusable; prefer an autocomplete (`autocomplete_fields` needs a
  real FK, so use a `ModelMultipleChoiceField` with Unfold's searchable select, or gate the queryset
  to the electronics subtree) — decide at implementation time against what Unfold actually ships.

⚠️ `QueryAdmin` carries `QueryChangeInline`, so any test that POSTs the change form must include the
`config_history-*` management form or the view returns **200 with empty `form.errors`** — an
invalid formset reads exactly like a silent no-op. `valid_query_data` in `test_admin.py` already
handles this; reuse it.

## 5. PR 5 — per-marketplace fieldsets

Independent of everything above, and the change that actually removes the felt collision: a Bazos
query renders `extra_params`, a Vinted query renders `section`/`category`/`location_*`, and none of
it applies. Implement `QueryAdmin.get_fieldsets` to branch on `obj.marketplace`.

⚠️ Hide, don't remove: fields absent from the form are not submitted, so a hidden field must keep
its stored value. Prefer grouping into a collapsed "Not used by this marketplace" fieldset over
dropping fields outright — and note `marketplace` itself must stay editable, which means the form
for an unsaved `Query` (`obj is None`) has to show everything.

## 6. Constants and dependencies

`bazos/const.py`:

```python
VINTED_PAGE_SIZE      = 96          # server-fixed; now only the short-page sentinel
VINTED_MAX_PAGES      = 10          # was 20 — the server caps at 10 (VINTED.md §3)
VINTED_REQUEST_TIMEOUT = (10.0, 30.0)   # NEW — no Tor here, but 7 MB decompresses slowly
VINTED_USER_AGENT     = "Mozilla/5.0 (…) Chrome/140.0.0.0 Safari/537.36"   # NEW, mandatory
VINTED_CURRENCY       = "CZK"       # NEW — must accompany price_from/price_to
VINTED_DETAIL_WAIT_TIME = (0.5, 1.5)    # unchanged
```

Update `VINTED_PAGE_SIZE`'s comment: it is no longer a `per_page` request parameter.

`pyproject.toml`: **remove `vinted-scraper = "^4.0.0"`**. Check whether `httpx` disappears from the
lock as a result. Nothing else depends on it (`grep -rn vinted_scraper --include=*.py`).

## 7. Rollout — PR 6, the part that is not done

Everything above is code on local branches. None of it is deployed, and **Vinted is still
failing in production**. This section is the hand-off; it needs production access and a
deploy, neither of which happens from a development checkout.

### 7.1 Deploy

`deploy.yml` fires on a **`v*` tag** and that is the only deploy path:

```bash
git tag v1.2.3 && git push origin v1.2.3
```

Before tagging, merge the branch chain (`vinted/pr1-schema` → … → `vinted/pr5-fieldsets`) into
`main`. Two migrations ride along, `0043` (MarketplaceCategory + Ad.attributes) and `0044`
(the extra_params help text); both are additive and neither rewrites a row.

⚠️ `deploy.yml` checks out **before** it stops the containers, so a dependency change briefly
runs new code on the old image. This deploy *removes* `vinted-scraper`, so expect one spurious
import error in the logs during the window — it is the known behaviour of that ordering, not a
failed deploy.

### 7.2 Seed the taxonomy (once, after deploying)

```bash
docker compose exec marketplace_server python manage.py create_vinted_catalogs
```

~2,920 rows in one request. Idempotent, so re-run whenever the tree looks stale. Nothing else
depends on it — PR 3 reads `extra_params`, not this table — so a failure here delays only the
admin picker.

### 7.3 Convert the queries from text search to structured filters

This is the fix for the long-standing irrelevant-results complaint, and it is **config, not
code**. In the admin, for each Vinted query: pick the category under "Where to search" (or set
`extra_params` directly), add `brand_ids`, and keep `filter_required` as a backstop.

```json
{"catalog_ids": [3580], "brand_ids": [54661]}
```

Category ids: §9 of [`VINTED.md`](../research/marketplaces/VINTED.md), or read them straight out
of a `/catalog/<id>-<slug>` URL. Brand ids: the table in that same section.

Measured difference on `macbook`: text search returned 22 unrelated rows in 96 (Nike jackets, a
handbag); `catalog[]=3580&brand_ids[]=54661` returned 96/96 correct.

⚠️ Do **not** convert every query at once. Change one, watch a pass, then do the rest.

### 7.4 Backfill the first query quietly

Eight days of missed listings plus a 96-row first page is a Discord flood. On the **first**
query only, set `new_query=True` **and** `ignore_first_run=True`, let one pass run, then set
`ignore_first_run=False`.

### 7.5 Verify, in this order

In the admin, on ads from the new pass:

- [ ] ads are being created at all, and `QueryRun.success` is true for the Vinted query
- [ ] `price_raw` is an integer string and `price` is the **ex-fee** figure (cross-check one
      against the listing page: the site shows the ex-fee price in large type)
- [ ] **`short_description` is non-empty** — the regression check for §3.5.1; empty means
      `itemBox` changed shape and both keyword rules are silently disabled again
- [ ] `topped` is set on some rows
- [ ] `publish_date` and `view_count` are null (they must stay null — never synthesised)
- [ ] with `load_full_description=True`, `attributes` carries real specs

Then watch for a few passes:

- [ ] `QueryRun` failure rate for the Vinted query — an occasional failure is normal
- [ ] **`PriceChange` volume on Vinted.** 78% of `.cz` prices are FX-converted, and a re-quote
      wave would write a PriceChange per affected ad and flip every delivery to
      `PRICE_CHANGED`. Measured 0/91 drift over an hour, so this should stay quiet; a burst is
      the FX rate moving, not a bug in the walk.

### 7.6 The gap this leaves open

⚠️ The zero-rows canary counts rows across **all** queries in a pass, so a broken Vinted scraper
does not trip it while Bazos queries keep returning rows. That is precisely how this outage
lasted eight days. `contract-check.yml` now covers Vinted weekly, which shortens the blind
window but does not close it. **A per-query failure rate is the real fix and is not built** —
see §10.

## 8. Tests

`bazos/tests/test_vinted_scraper.py` is rewritten, not extended — every existing test mocks
`VintedApiClient`, which no longer exists. Capture **one real flight payload** as a fixture
(trim it: the 7 MB is mostly i18n) and drive the parser from it. Never hit the network.

| test | asserts |
|---|---|
| `test_balanced_scan_handles_quotes_and_brackets` | a title containing `"`, `[`, `\` parses — §3.2's main risk |
| `test_maps_listing_row_to_ad` | every field in §3.5 on one real row |
| `test_price_is_ex_fee_and_integer` | `"17999.00"` → `17999`, **not** `18916` and not `1799900` |
| `test_parse_price_roundtrip` | `parse_price(ad.price_raw) == ad.price` — pins the decimal trap |
| `test_short_description_from_item_box` | `firstLine · secondLine`, non-empty |
| `test_promoted_maps_to_topped` | `isPromoted: true` → `topped` |
| `test_relative_url_is_joined_to_base` | `/items/…` → absolute, per `base_url` |
| `test_publish_date_and_view_count_are_none` | no synthesised values |
| `test_big_external_id_survives_save` | `django_db`, id `10018454667` on Postgres |
| `test_catalog_and_brand_ids_repeat_in_query_string` | `catalog[]` appears twice for two ids |
| `test_price_bounds_omitted_when_zero` | `0/0` → no `price_from`/`price_to` |
| `test_filter_echo_mismatch_logs_warning` | §3.2's canary fires when `sortBy` comes back wrong |
| `test_pagination_stops_on_short_page` / `_empty_page` / `_max_pages` | loop termination |
| `test_load_full_description_reads_json_ld` | description extracted |
| `test_load_full_description_survives_http_error` | returns ad unchanged, nothing escapes |
| `test_load_full_description_never_overwrites_price` | ⚠️ JSON-LD `offers.price` in PLN is ignored |
| `test_attributes_captured_verbatim` | `computer_ram` → `"16 GB"` — a string, not `16` |
| `test_attributes_keeps_unknown_codes` | an invented code survives; no allow-list |
| `test_attributes_default_empty_for_bazos` | a Bazos ad round-trips `{}`, not null |
| `test_run_query_completes_when_one_detail_fetch_raises` | the regression that matters: 3 ads, 2nd raises → all 3 yielded |

Plus, for PRs 1–2: `test_marketplace_category_path_builds_breadcrumb`,
`test_create_vinted_catalogs_is_idempotent`, `test_reseed_warns_about_referenced_missing_node`.

**Extend `contract-check.yml`** to cover Vinted. The weekly live job is the mechanism that would
have caught this in a week instead of eight days, and it already runs on the Pi runner. A minimal
`@pytest.mark.live` test — fetch one catalog page, assert ≥1 item parses and `sortBy` echoes back —
is enough. ⚠️ It must not depend on Postgres; the live job runs with `TEST_DB=sqlite`.

## 9. The follow-up this unlocks (not in this plan)

Once `Ad.attributes` is populating, `MacBookEstimator` can prefer stated specs over regexed ones.
The integration point is a single method — `bazos/pricing/estimators/macbook.py::extract`, which
today is:

```python
feats = features.extract(ad.name, ad.short_description or "")
```

It becomes "take `ad.attributes` where present, fall back to the regex path" — so Bazos is
unaffected and Vinted stops guessing. Two things that also have to move, which is why this is its
own item and not a footnote:

- `applies_to` currently returns `False` for anything where `ad.marketplace != Marketplace.BAZOS`,
  so the model does not score Vinted ads at all today.
- The shipped artifact was trained on Bazos listings. Scoring Vinted inventory with it is a
  cross-marketplace transfer that `docs/research/CROSS_MARKETPLACE_MACBOOK.md` should be consulted
  on first — and Vinted prices are ex-fee and FX-converted, which is a second distribution shift.

Do not fold this into the rewrite. It needs its own measurement.

## 10. Out of scope

- Seller identity capture (`user.id`, `isBusiness`) — needs a model and a retention decision.
- Consuming `Ad.attributes` in the price model — §9. Capturing them is in scope; reading them is not.
- Images, though `photos[]` and `thumbnailUrls` are free in the listing row.
- Any change to `parse_price`; §3.5 works within its current behaviour deliberately.
- Migrating Bazos `Section`/`Category` into `MarketplaceCategory` — explicitly rejected, §2.1.
- Per-query failure-rate alerting (§7.6) — **needed, and the actual lesson of this outage**.
  The canary is pass-wide, so one dead marketplace hides behind the others. Wants a threshold on
  consecutive `QueryRun.success=False` per query, alerting to the `for_logging` channel.
