---
title: Backlog Ideas — Not Yet in Any Stage
status: active
updated: 2026-09-17
verified: 2026-09-17
---

# Backlog Ideas — Not Yet in Any Stage

> Sourced from a full sweep of the GitHub issue tracker (57 issues, `jakub-kucera/marketplace-scrapper`),
> cross-checked against `PIPELINE_REFACTOR.md`, `VINTED_SCRAPER_DESIGN.md`, and `docs/research/bazos-api/`.
> Everything here is either (a) not covered by any existing stage/doc, or (b) covered elsewhere
> but only partially — the gap is called out explicitly. Each idea is explored deeper than its
> originating issue, grounded in the current code, not just restated.
>
> Unlike the numbered `PIPELINE_REFACTOR.md` stages, these are **not sequenced** — they're
> independent candidates. Pick them up individually; none blocks another except where noted.
>
> **Numbers are stable and never reused.** #1, #4, #7, #9 and #11 have shipped and are
> collapsed to a stub pointing at [`SHIPPED.md`](../SHIPPED.md) — the numbers stay so the cross-references to
> them from other docs still land.

---

## Priority — effort vs. relevance

Ranked by effort vs. actual relevance to what this scraper does (find deals, notify fast, stay
under the radar), not by order of appearance below.

> **⚠️ Re-ranked 2026-08-23, pruned 2026-09-17.** Rows that used to sit at the top of this table
> have **shipped** — database backups, the `Ad`/`AdDelivery` split (#1), #7's AND/OR probe, #11's
> seller identity, then **#4 (as `refprice/`) and #9 (`AdOutcome`) on 2026-09-16/17**. The last
> two are gone from the table below; their sections survive as stubs. What has *not* changed in
> any of those revisions is the thing that governs the order:
>
> **Detection latency is still the binding constraint on the whole "find deals" goal.** The
> interval is still 15–45 min, i.e. a **~15 minute median**, while competing services poll every
> 60 s and good listings are gone in minutes. See [`MONETIZATION.md`](../MONETIZATION.md)
> **§7.1** for the argument and the numbers; the executable fix is [`PROMPTS.md`](PROMPTS.md)
> **P21a**, whose free half (the guard collapse) landed but whose latency half has not.
> Everything in this table is downstream of that — a better filter delivered 15 minutes late is
> worth nothing.
>
> Shipped work is recorded in [`SHIPPED.md`](../SHIPPED.md) and is not repeated here.

| # | Idea | Effort | Depends on | Priority |
|---|---|---|---|---|
| — | **IP guards can still raise** — no request timeouts in `ip_changer/`, two unguarded call sites | **XS** (~1 hr) | nothing | **⚠️ Do first — [`PROMPTS.md`](PROMPTS.md) P20.** One dropped socket still costs a whole pass. |
| — | **Latency, the half that's left** — tunable API page size + production cutover + interval to ~10 min | **S/M** (~1–2 days) | nothing; designed in `../research/proxies/` + `../research/bazos-api/`, scraper already built | **⚠️ Do first — [`PROMPTS.md`](PROMPTS.md) P21a Parts 1 + 4a.** ~3× latency win at *unchanged* Bazos request volume, no cost. |
| — | **Rotating proxy** — replace Tor | **M** (~1–2 days + ~$3–6/mo) | P21a, plus a benchmark never yet run | **[`PROMPTS.md`](PROMPTS.md) P21b.** The only part needing money and an unvalidated assumption — and the durable fix for Tor's ongoing failures. |
| 3a | Thumbnail in Discord embed | **S/M** (~1-2 days) | nothing | **Do soon** — and see #10, which wants the same notification rework |
| 10 | Distance / travel-cost-aware scoring | **M** (~1-2 days) | nothing (`zip.php` already probed) | 🟡 radius **shipped**; travel-cost scoring still open, and now blocked on a margin estimate |
| 8 | Full-listing rescan flag (comprehensive price-drop detection) | **S** structurally (~1hr); **M** with the cap/throttle guardrail it needs | nothing, but must ship with a page cap/throttle | **Do soon, but scope narrowly** |
| 6 | Posting-time-of-day → interval tuning | **S** (~half day) *once unblocked* | ⚠️ **blocked** — needs second-resolution timestamps (see §6) | **Blocked, and superseded in value by the latency chain** |
| 2 | asyncio scraping | **M/L**, but only as part of a scraper you haven't built yet | the API cutover | **Still not independently actionable** — and *less* attractive after P21a (see §2 note) |
| 3b | Self-host image mirror | **L** (storage + serving + retention) | 3a | **Defer** |
| 5 | Computer-vision item recognition | **L**, speculative | idea #3 (images) + vendor pick | **Defer, lowest** |

**Why this order:**

- **The three "—" rows outrank everything numbered**, because they're not feature bets — one is
  the difference between arriving first and arriving 15 minutes late (the entire premise of "find
  deals"), and the other is the difference between a dropped socket costing one query and costing
  an entire pass. Both are execution of work already designed elsewhere, not new design.
- **#9 was the cheapest thing in this document and the only one that creates ground truth. It
  shipped 2026-09-17** — and the constraint it existed to remove has *changed shape rather than
  gone*: no threshold in #5 or `PROMPTS.md` P23 can be tuned until the logbook and the delisting
  sweep have accumulated some history. The wait is now for data, not for code.
- **#3a is still the best "visible payoff" item** — Discord notifications get noticeably nicer for
  a bounded, well-understood cost. Doesn't need the API cutover to start. Worth building
  together with **#10**, since both rewrite the same notification-formatting path.
- **#6 wants an hourly posting-density curve** from `Ad.publish_date`, but `BazosScraper.extract_date`
  parses only `[29.7.2026]` and **discards the time**, so `ExtractHour("publish_date")` returns
  all-zeros today. It's blocked on data that doesn't exist yet, and even unblocked it makes a
  15–45 min interval *smarter* where P21 makes it **~2 minutes** — the wrong term to optimise.
  Keep it, but after the API cutover supplies real timestamps.
- **#2 (asyncio) isn't really a standalone task, and P21a weakens the case further** — its own
  conclusion below is "don't retrofit onto the HTML scraper", and the payoff was always going to
  come with the API cutover. P21a's steady-state shape is **one ~1.1 KB request per query per
  pass** (a `limit≈10` dedup probe), so there is very little left to parallelise in the common
  case; the remaining fan-out candidates are `load_full_description` batches on first discovery
  and the bulk enrichment workflows. Re-read §2 with that in mind before spending effort here.
- **#4 moved back from "don't" to "reconsider"** — the 2026-08-22 research that downgraded it was
  re-probed on 2026-09-16 and three of its four blocking findings did not survive: the join path is
  robots-allowed, `productNo` is a real identifier, and there is a price-history endpoint. The
  remaining honest limit is coverage (current-production goods yes, discontinued electronics no),
  not access. See §4 and [`PRICE_REFERENCE_SERVICE.md`](../proposals/PRICE_REFERENCE_SERVICE.md).
- **#3b and #5 remain speculative** — each has either an unconfirmed benefit (#3b's
  click-tracking risk isn't observed to be a real problem) or an unresolved vendor choice (#5).
  Neither blocks anything else — lowest urgency by construction.
- **#8 is cheap to build but easy to misuse** — the code change is a few lines, but enabling it on
  a broad category-scoped query multiplies request volume by orders of magnitude on *every* pass,
  not once (see its own section for the measured numbers). Worth doing soon since it's small and
  unblocks real price-drop detection, but only alongside a page cap/throttle guardrail and
  strictly as an opt-in for narrow queries — not a flag to flip broadly.

---

## 1. Cross-query `Ad` dedup (M:N `Ad`↔`Query`) — ✅ **shipped 2026-08-22/23**

> Option B was chosen, spec'd in [`AD_DELIVERY_SPLIT.md`](../archive/shipped/AD_DELIVERY_SPLIT.md), and
> **all four stages landed** (migrations `0026`–`0028`, `0031`). `Ad` now holds scraped facts and
> is globally unique on `(marketplace, external_id)`; `AdDelivery` holds per-`(ad, query)`
> pipeline state. `Ad.status`/`filter_reason`/`sent_at`/`send_attempts`/`query` no longer exist.
> Details in [`SHIPPED.md`](../SHIPPED.md); deferred review follow-ups in
> [`PROMPTS.md`](PROMPTS.md) P26.
>
> The number is kept so the several cross-references to "`BACKLOG_IDEAS.md` #1" still land. The
> option analysis that used to live here is preserved in the spec's §1–§3.


## 2. Concurrent scraping (`asyncio`/`aiohttp`)

**Source**: [#62](https://github.com/jakub-kucera/marketplace-scrapper/issues/62).

### Where it would and wouldn't help, concretely

`ScrapeRunner.run()` (`runner.py:36`) loops over enabled queries **strictly sequentially**,
in random order, sharing **one** `requests.Session` bound to **one** Tor circuit for the entire
pass (`self.ip_changer.session`, created once in `__init__`). `DiscordSender._send` already carries
a `# TODO make thread safe` comment (`discord_sender.py:41`) — concurrency here has been anticipated
but never built.

- **Within one query's pagination** — no benefit. `BazosScraper.run_query` walks pages in order and
  stops on the first known non-topped ad; that dedup logic is inherently sequential, not something
  async parallelizes.
- **`load_full_description` fan-out for newly discovered ads** — real benefit. A new query's first
  run can trigger up to `NEW_PRODUCT_LOAD_MAX` (50) sequential detail-page fetches
  (`_handle_new_product` → `load_full_description`), and those fetches are independent of each
  other — a natural concurrent batch today, HTML scraper or not.
- **Across queries** — limited benefit *today*, because every query in a pass shares the same Tor
  circuit; running them concurrently doesn't multiply IP diversity, just wall-clock speed. Still
  useful once query count grows (broader category-scoped queries per the discovery-pipeline doc, or
  Vinted queries running alongside Bazos ones).
- **The future `BazosApiScraper`** (`HIDDEN_API.md` §8) — biggest benefit by far.
  Every workflow that doc describes (bulk `ad_id[]=` re-checks, per-ad `ad-detail-2.php` calls,
  `ratings.php` lookups) is a swarm of small, independent JSON GETs with no ordering constraint —
  exactly what `asyncio` + `aiohttp` (and an `asyncio.Semaphore` cap, as the issue itself suggested)
  is for. Bulk-by-id in particular has no ranking/ordering to preserve at all (§6.4f of the research
  doc), unlike the HTML scraper's dedup walk.

### Real constraints, not just "add async"

- `IPChanger`/blacklist-check (`check_bazos_blacklisted`, `renew_ip_bazos_ok`) is synchronous,
  single-shared-instance, and not designed for concurrent callers — needs either a lock around IP
  rotation or a "stop the world, rotate, resume" checkpoint model, not concurrent races on the same
  circuit change.
- Django 4.1 (current `pyproject.toml` pin) has native async ORM methods (`afilter`, `acreate`,
  etc.), so wrapping in `sync_to_async` shouldn't be necessary for new async code — but the codebase
  uses none of this today, so it's new territory, not an incremental tweak.
- `requests.Session` (sync) would need an `aiohttp.ClientSession`/`httpx.AsyncClient` equivalent for
  actual transport — a parallel implementation, not a drop-in swap, for whichever scraper adopts it.

**Recommendation**: don't retrofit `asyncio` onto the current HTML scraper — the win there is small
and the dedup-ordering assumptions make it awkward. Build the eventual `BazosApiScraper`
async-native from the start instead; that's where the real payoff is, and where "many small
independent calls" is the dominant shape rather than the exception.

---

## 3. Ad images — two genuinely different features

**Source**: [#40](https://github.com/jakub-kucera/marketplace-scrapper/issues/40),
[#43](https://github.com/jakub-kucera/marketplace-scrapper/issues/43) (blocked by #40).

`Ad` has **no** image field today, and the HTML scraper (`bazos_scraper.py`) doesn't parse a
thumbnail URL at all — issue #40's original plan (rewrite `smth/1t/smth` → `smth/1/smth` in the
thumbnail URL for full-res) would require adding that parsing first. `DiscordSender` sends plain
text only (`discord_notify.Notifier.send(message)`, `discord_sender.py`) — no embed support exists.

Both issues bundle two different problems together; worth separating explicitly:

> **Promoted to `PROMPTS.md` as P16** (2026-07-24) — ready-to-run steps there, this section
> remains the fuller rationale. **Also converges with**
> [`DISCORD_BOT.md`](../proposals/DISCORD_BOT.md) §1.4/§5 — that proposal
> independently needs the same move off plain-text `discord_notify` webhooks onto real
> embeds/components; worth building once rather than twice if both are ever picked up.

### 3a. Attach a thumbnail to the Discord message — cheap, low-risk, decoupled from 3b

The hidden API's listing response already includes `image_thumbnail` **at zero extra request
cost** over what discovery already pays (`HIDDEN_API.md` §5.1); the detail endpoint
includes the full `images[]` array at the same per-ad cost `load_full_description` already pays
(§5.2). So once the API migration (`HIDDEN_API.md` §8, Stage B) lands, this is
nearly free. Until then, it needs its own small HTML-scraper addition (a BeautifulSoup selector for
the listing thumbnail `<img>`), independent of waiting on the API work.

Sending it needs an actual Discord **embed**, not a text webhook post — `discord_notify` may not
support this (needs checking); the `discord-webhook` package the issue's own comment linked
(`pypi.org/project/discord-webhook`) does. Discord's own servers fetch the embed image server-side
to render the preview — **the scraper's IP is not the one requesting the image from Bazos in this
path**, so this doesn't carry the "IP could be linked to scraper" risk #40 raised. That risk is
specific to a human clicking through to the ad *page* (3b below), not to an embedded thumbnail.

### 3b. Mirror/self-host the ad page or images — the actual concern behind #40, bigger

The real motivation in #40 is avoiding anyone hitting Bazos directly through a scraper-adjacent
access pattern — blocked source IP, cookie tracking, or a suspicious-looking ad-open pattern getting
linked back to the scraper's own IP/session. That needs storage (a volume or object store) plus a
serving mechanism (`marketplace_server`'s existing `runserver` process is the natural place to add
a view), a decision on scope (thumbnail only vs. all of `images[]`), and a retention policy — mirrored
files accumulate forever without one.

**Recommendation**: do 3a whenever thumbnails are wanted — it's cheap and carries none of 3b's risk.
Treat 3b as speculative until the click-tracking risk is actually observed to matter — concrete
storage/serving cost against an unconfirmed benefit.

---

## 4. External price cross-referencing (Heureka / price-comparison APIs) — ✅ **shipped 2026-09-16**

> **Built as `refprice/`.** The ladder this section argued toward — normalise → suggest →
> validate every candidate → optional LLM adjudication — shipped on 2026-09-16 with four
> tables, an admin action, an inline and `manage.py lookup_reference_price`, over the
> `/api/v3` surface measured in [`ZBOZI_API.md`](../research/marketplaces/ZBOZI_API.md).
> It is **invoked explicitly** — nothing on the scrape/filter/send path calls it — and the
> `reference_price` rule reads only persisted links, never the network. Details in
> [`SHIPPED.md`](../SHIPPED.md); design in
> [`PRICE_REFERENCE_SERVICE.md`](../proposals/PRICE_REFERENCE_SERVICE.md).
>
> The section below is kept **as the record of how the verdict moved** — REJECT on
> 2026-08-22, superseded on three of four points on 2026-09-16, built the same day. That
> sequence is the useful part: the first probe's blocker ("no identifier to join on") was a
> grep that missed `productNo` on spelling, and its second ("needs per-ad LLM extraction")
> was answered by making the LLM adjudicate a closed set rather than extract from free text.
> ⚠️ What did **not** move: eBay is still unavailable to a non-partner, Heureka.cz is still
> Cloudflare-blocked, and coverage is still uneven — current-production goods resolve well,
> discontinued electronics do not.

**Source**: [#36](https://github.com/jakub-kucera/marketplace-scrapper/issues/36) ("search product
name in Heureka / Price API"), [#56](https://github.com/jakub-kucera/marketplace-scrapper/issues/56)
(cheap Macbook/iPhone deal-finder), and the "EXTERNAL PRODUCT DB" node on the #54 whiteboard.

This is a different signal than the *internal* rolling price-baseline already designed in
`DISCOVERY_PIPELINE.md` §2 Stage 2 ("rolling median/percentile price per category from
your own accumulated discovery history") — that answers "cheap relative to other Bazos listings
like it"; this idea answers "cheap relative to what this exact model actually costs new/refurbished"
— which only works for standardized, model-identifiable products (Apple hardware, GPUs — exactly
what #56 and the already-closed #49 scoped themselves to), not one-off or hand-me-down items.

### The hard part is identification, not pricing

A free-text title like "Macbook Pro 13 2020 i5 16GB" has to resolve to a canonical
product/SKU before any reference-price lookup means anything. Options, roughly cheapest-first:

- **Regex/keyword extraction per category** (model year, storage, chip) — cheap, but brittle and
  needs hand-maintenance per product line. Realistically only worth it for a handful of
  high-value, well-standardized categories — which is exactly the scope #56/#49 already chose, not
  "any product."
- **LLM-based extraction** (title/description → structured attributes) — more robust to phrasing
  variance, but a real per-ad cost and a new external dependency; naturally a category-gated
  Stage-9-style filter rule, not something run for every scraped ad.

### The price source was researched — ✅ 2026-08-22, re-probed 2026-09-16

The spike this section used to call for **was run**:
[`HEUREKA_ZBOZI.md`](../research/marketplaces/HEUREKA_ZBOZI.md) assessed
Heureka.cz and Zboží.cz live, 15 requests, and
[`EBAY.md`](../research/marketplaces/EBAY.md) did the same for
eBay sold listings. There is now a confirmed endpoint and a measured rate-limit shape. **Verdict:
REJECT**, and it fails on the near side rather than the far side:

- **Heureka.cz** is behind a Cloudflare managed challenge on everything except `robots.txt`.
- **Zboží.cz** is wide open (Next.js, three usable layers) and its payload is genuinely rich for
  tools and electronics — so the *source* is not the problem.
- **The join is.** Neither site exposes EAN/GTIN, and more importantly **`Ad` carries no
  brand/model field to join *from*** — only free-text `name` + `short_description`. Every route
  therefore needs a per-ad LLM extraction step first, which is a different (and much larger)
  project than "call a price API".
- **eBay** has no route at all for a non-partner: `findCompletedItems` was decommissioned
  2025-02-05 and the Insights API is invitation-only. Its 90-day history window would also be too
  short for this project's thesis.

**⚠️ The 2026-08-22 REJECT above is superseded on three of its four points.** A re-probe on
2026-09-16 ([`ZBOZI_API.md`](../research/marketplaces/ZBOZI_API.md)) found a documented JSON API the
first pass never located:

- **The join is robots-*allowed*.** `/suggestV2?phrase=` → `/api/v3/product/<slug>/` — verified with a
  real `RobotFileParser`. Only the `?q=` search the first pass happened to find is disallowed.
- **There is an identifier**: `productNo` carries the manufacturer part number. The first pass
  grepped for `mpn`/`partNumber`/`sku` and missed it on spelling.
- **There is price history**: `POST /api/v3/pricetrend/product-v3/<id>` returns ~24 months of
  min/median/max, unauthenticated.
- **The "per-ad LLM extraction" blocker does not apply.** The LLM's job is *closed-set adjudication*
  over candidates the catalogue already returned (~340 tokens), not blind extraction of an identity
  from free text. That is the argument §4d rejected, and it is not this one.

What survives: eBay is still unavailable, Heureka.cz is still Cloudflare-blocked, and coverage is
still uneven — current-production goods resolve well (tools best), discontinued electronics do not.

**Recommendation: build it explicitly, not automatically** — design in
[`PRICE_REFERENCE_SERVICE.md`](../proposals/PRICE_REFERENCE_SERVICE.md). The *internal* rolling price
baseline (`PROMPTS.md` P23's `PriceAnomalyRule`, now possible because P22 gave `Ad` a real integer
price) is still the cheaper win and should not be displaced by this.

*(That recommendation was followed on 2026-09-16 — see the banner at the top of this section. The
internal baseline it defers to, P23, is **still open**.)*

---

## 5. Computer-vision item recognition

**Source**: [#36](https://github.com/jakub-kucera/marketplace-scrapper/issues/36) ("for stuff like
office chairs use Computer vision APIs to recognise them (bikes)"), and the #54 whiteboard's
`SUBQUERY.CLASS_PATH ← OPENCV/NLP` node — envisioned years ago as a post-filter classifier chained
after a base query, which maps directly onto the `FilterRule`/`RuleEngine` abstraction already
built in Stage 3c (`bazos/filters.py`): a `ClassifierRule.apply(ad) -> (FilterResult, reason)` that
calls an image-classification API on `ad.images` and rejects/passes on a label or confidence
threshold.

**Hard dependency**: this needs image data on `Ad` to exist at all first — sequenced after idea #3
above, and after there's at least one real image URL to classify. Thumbnail is probably enough for
a coarse category check; full images only matter for finer distinctions.

**Why this is the concrete use case, not a generic one**: it targets exactly the case
keyword/price filtering can't handle — a category-ambiguous or badly-titled listing (an "office
chair" that's actually a valuable mid-century design piece, or the reverse) where the *photo* is
the only reliable signal. Not useful as a blanket policy — mirroring the discovery pipeline's own
"filter before enrich" principle, this should run only on ads that already passed cheap
price/keyword filters, since it's a real per-call cost (vision API), not free.

**Open**: no vision API has been evaluated (OpenAI vision, Google Vision, a self-hosted model — each
with different cost/accuracy/ops tradeoffs). This is a research spike with no chosen implementation
yet, unlike the Bazos-API-grounded ideas above which build on already-confirmed endpoints.

---

## 6. Posting-time-of-day analysis → interval tuning

> **Promoted to `PROMPTS.md` as P14** (2026-07-24) — ready-to-run steps there, this section
> remains the fuller rationale.
>
> **⚠️ BLOCKED — correction 2026-07-29.** The claim below that the data is "already enough today"
> is **wrong**, and P14's step 1 will silently produce garbage. `BazosScraper.extract_date`
> (`bazos_scraper.py`) slices the `[d.m.yyyy]` substring out of the listing and builds a
> `datetime(day, month, year)` — **the time component is discarded entirely**, so every stored
> `publish_date` sits at midnight and `ExtractHour("publish_date")` returns **0 for every row**.
> `Ad.created` (discovery time, not posting time) has real resolution but is quantised to the
> pass interval, so at a 15–45 min cadence it can't resolve posting hour cleanly either.
>
> **Unblocked by:** the API cutover ([`PROMPTS.md`](PROMPTS.md) **P21a** — the free half; the
> paid proxy work in P21b is not required for this). The API's listing payload
> carries `"from": "2026-07-19 09:45:51"` — **second resolution** (`HIDDEN_API.md`
> §5.1). One caveat when it lands: for **topped** ads that `from` value is *not* the real posting
> time (§4.3 of the same doc — topped ads share a `from` equal to the request timestamp), so
> filter `topped=False` before building any density curve.
>
> **Also note:** even once unblocked, this tunes *when* a 15–45 min interval fires, whereas P21a
> makes it ~10 minutes and P21b ~2. Lower value than the table previously implied — and note the
> value keeps *falling* as cadence rises, since a tighter loop cares less when it fires.

**Source**: [#36](https://github.com/jakub-kucera/marketplace-scrapper/issues/36) ("analyse at what
hours are posts most posted and change the interval changing logic").

Cheap in *implementation* terms — no new scraping, no new API calls, just an aggregate query
(`Ad.objects.annotate(hour=ExtractHour("publish_date"))...`) plus a lookup table feeding
`interval_multiplier.py`. But **not** cheap in prerequisites, per the correction above: the
hour-of-day signal it needs is not in the database today.

This feeds directly into `bazos/scraping/interval_multiplier.py`'s `NightMultiplier` (referenced in
`CLAUDE.md`'s Environment section) — currently a flat day/night 2× split. A real hourly posting-
density curve could replace that blunt heuristic with one that tracks actual posting patterns:
poll more often during genuine peak-posting hours, back off harder than a flat 2× overnight if
volume is even lower than "night" currently assumes. `NightMultiplier` is already the right
extension point — this replaces its internals, not the interface `ScrapeRunner.get_next_interval`
calls.

**Recommendation**: good first pass at reducing wasted/late polls — no new dependencies, all data
already on hand, small and self-contained.

---

## 7. True AND/OR query support — ✅ **resolved 2026-07-26** (OR real, AND fake)

> Probed live as `PROMPTS.md` P15. **`OR` is a genuine boolean union**; **`AND` is not an
> operator** — it is matched as an ordinary literal word on top of the implicit AND of
> space-separated terms, which is why `macbook AND pro` returns 15× fewer results than
> `macbook pro`. Full probe evidence in
> [`HIDDEN_API.md`](../research/bazos-api/HIDDEN_API.md)
> §4.1a–4.1b; the mechanism (plain SQL substring `LIKE`, not FULLTEXT boolean mode) is §4.1b.
>
> **The remaining follow-up is not a code change.** Consolidating existing narrow `Query` rows
> into `macbook OR imac OR ipad` works today with the production HTML scraper, no API migration
> — it just has not been done to the real rows.


## 8. Full-listing rescan flag — comprehensive price-drop detection

> **Related but distinct**: [`DISCORD_BOT.md`](../proposals/DISCORD_BOT.md) §2.1/§3.2
> (2026-07-24) already designs `AdWatch` — a per-ad "👁 Watch this ad" model plus a `run_ad_watch`
> poll loop — for the *same* underlying gap (an ad that scrolls out of a query's newest-first scan
> window never gets re-checked). `AdWatch` solves it for a user-curated set of *specific* ads, cheaply,
> via the bulk `ads.php?ad_id[]=` recheck (`HIDDEN_API.md` §5.3, §8 Stage D) — up to 210
> known ids per call, no listing pagination at all. This idea (#8) solves the broader case — catching a
> drop on *any* ad in a query's full result set, not just ones a human already flagged — at
> proportionally higher cost (§ below). Pick #8 only when the ads worth watching aren't known in
> advance; reach for `AdWatch` first when they are, since it's the same payoff for far less request
> volume.

**Source**: internal design discussion (2026-07-26) — not from the GitHub issue tracker. A proposed
extension to the existing-query dedup logic, motivated by wanting `PriceDropRule` (Stage 9, already
built — see `PROMPTS.md` P5) to actually see price drops on old listings, instead of only whatever
ad happens to sit at a given pass's dedup boundary.

### The actual problem: price-change detection today is incidental, not comprehensive

`run_existing_query` (`query_runner.py:71-95`) walks a query's results newest→oldest and stops
at the first known non-TOP ad, assuming (correctly) that everything older was already seen — this is
the "Existing-query dedup" behavior noted in `CLAUDE.md`. But that means price is only ever re-checked
for two kinds of ad per pass: known TOP ads encountered before the break (they don't trigger it), and
the single known ad that causes the break. Every other older known ad is never revisited after its
first discovery — if its seller drops the price six weeks later, buried on page 9 of the listing,
nothing will ever notice. `PriceDropRule` (`filters.py:120`) already exists specifically to reject
non-drop `PRICE_CHANGED` re-notifications, but it's starved of data past the boundary ad — it can only
ever act on the one ad each pass happens to stop at.

### The proposed mechanism

A per-query opt-in boolean (same pattern as `load_full_description`/`ignore_first_run`) — e.g.
`Query.full_rescan` — that changes the branch at `query_runner.py:91-95`: instead of `break` on
a known non-TOP ad, `continue`, exactly like the existing TOP-ad case already does. Every known ad the
query has ever seen then gets its price compared on every pass, and on a drop gets the existing
`PriceChange`/`AdStatus.PRICE_CHANGED` treatment (`query_runner.py:78-89`) — no new pipeline
mechanics needed, `run_filter` and `PriceDropRule` already handle `PRICE_CHANGED` re-entry correctly.

### The real cost — quantified from `PROXY_ROTATION.md`

`run_query` (`bazos_scraper.py:210-235`) is a lazy per-page generator with a sleep between every page
fetch (`BAZOS_PAGE_WAIT_TIME`) — breaking early is *why* per-pass cost is low today.
`PROXY_ROTATION.md:179` measures this directly: "steady-state each category still resolves in
~1 request/pass (dedup breaks at the first known non-TOP id)." Flipping that off for a query changes
its cost from O(1) request/pass to O(listing size / `PAGE_SIZE`) requests **every single pass,
forever** — for the doc's own `auto` category example (49,372 active listings), that's hundreds of
requests per pass instead of one, at whatever cadence that query runs (240 passes/day at a 5-min
interval per the doc's model). It also serializes badly: queries run strictly sequentially, sharing
one Tor session (`ScrapeRunner.run()`, see idea #2 above), so one deep-rescan query would dominate
wall-clock and delay every other query's turn during its pass.

### Recommendation

Build it as a narrowly-scoped opt-in, not a general-purpose toggle:

- Per-query boolean, off by default, exactly like `load_full_description`.
- Document (and ideally guard in code/admin) that it should only be enabled on small/narrow queries —
  explicitly warn against combining it with the "broader category-scoped queries" direction
  `DISCOVERY_PIPELINE.md` pushes toward, since that's exactly where the cost multiplies
  worst.
- Add a hard page cap or a "only every Nth pass" throttle so the recurring cost is bounded rather than
  paid on every interval forever — a full walk doesn't need to happen every 15–45 minutes to still
  catch a price drop days later.
- Pairs naturally with idea #6 (interval tuning) if that's ever built — a full-rescan query is a good
  candidate for its own, much longer interval, independent of the rest of the fleet.
- Before reaching for this, check whether `AdWatch` (see the cross-reference above) already covers the
  actual need — if the ads worth tracking are a small, known set, watching them individually is
  strictly cheaper than rescanning the whole query on their behalf.

---

## 9. `AdOutcome` — record what you actually did about an ad — ✅ **shipped 2026-09-17**

> Shipped alongside P24's delisting sweep, in one change, because neither is worth much without
> the other: `Ad.removed_at` measures *time to disappear*, which is a confounded proxy — expiry
> looks identical to a sale — and this table is the only thing that can calibrate it. Entry point
> is an **editable inline on the `Ad` page plus a cross-ad changelist**, since the questions it
> answers are aggregate. Details in [`SHIPPED.md`](../SHIPPED.md).
>
> ⚠️ **The shipped shape is narrower than the one proposed here, deliberately.** This section
> argued for an append-only log — one row per state change, `(action, price_paid, price_sold,
> sold_at, note)` — so the *timeline* survives and time-from-notification-to-contact becomes
> measurable. What shipped is **one row per ad**: `OneToOneField`, `kind`, a single
> `realised_price`, `note`. The argument for the timeline is not wrong and is preserved in this
> file's history; it lost to the caveat in this section's own Recommendation — *a logbook nobody
> writes to is worse than none, because it looks like data* — and a form asking for one verdict
> gets filled in where a form asking for a sequence does not. If the logbook does get used, the
> append-only version is the natural second version, and `AdDelivery.sent_at` still pins the
> start of the latency interval.
>
> Two details worth keeping: `realised_price` stays **null unless a price was genuinely agreed,
> including for `BOUGHT`** — an asking price copied in would poison the one table meant to hold
> truth; and `LOST_TO_OTHER_BUYER` survived as its own value rather than folding into
> `NO_REPLY`, because it is the direct evidence of whether latency is still costing deals.
>
> The number is kept so cross-references to "`BACKLOG_IDEAS.md` #9" still land.

---

## 10. Distance / travel-cost-aware scoring — 🟡 **radius shipped 2026-08-30, economics still open**

> **Shipped since this was written:** the "cheap first version" below, in a better form than it
> proposed. `Query.filter_location_center`/`filter_location_radius` + the `location_distance`
> filter rule reject an ad whose PSČ is further than N km from a centre, *after* the scrape — so
> the "search wide, notify near" split this section asks for now exists. The PSČ-prefix
> approximation turned out to be unnecessary: `Ad.location` already carries the full code
> (`"Pelhřimov, 394 03"`), and `zip.php` geocodes it into the `PostalCode` cache, so real
> coordinates were cheaper than the approximation. See [`SHIPPED.md`](../SHIPPED.md).
>
> **What is still open here, and it is the more valuable half:** ranking within the radius, and
> the radius as a function of value rather than a per-query constant — i.e. steps 4's
> `TravelCostRule` (`estimated_margin − 2 × distance_km × cost_per_km`), which needs an estimated
> margin and therefore the price model. Steps 1-3 (GPS columns on `Ad`, a stored distance column)
> are **not** needed for that: the cached postal-code coordinates already answer "how far", and a
> few km of post-office imprecision is far below the noise in any margin estimate.


> **Source**: internal analysis 2026-07-29, prompted by [`MONETIZATION.md`](../MONETIZATION.md)
> §4.2's per-flip P&L, where travel is a real line item against a ~1,200 CZK margin.

### What exists today, and why it isn't enough

`Query.location_center` (a PSČ) and `Query.location_radius` are passed straight through to Bazos
as `hlokalita`/`humkreis` (`bazos_scraper.py::get_query_url_dict`), so filtering is **server-side
and binary** — inside the radius or not in the results at all. `Ad.location` is then stored as
free text (`"Praha 10"`), never parsed.

Two consequences:

- **No ranking within the radius.** A 25 km radius treats a 3 km pickup and a 24 km pickup
  identically, when the second may erase a third of the margin.
- **The radius is a per-query constant, not a function of value.** The right radius for a 1,500 CZK
  drill is not the right radius for a 40,000 CZK e-bike, but one `Query` row can only express one.
  Today you either miss distant high-value deals or drown in distant low-value ones.

### Mechanism

The pieces are already probed. `api/v1/zip.php` geocodes both directions (`query` → coordinates,
or `latitude`+`longitude` → locality) and is confirmed live (`HIDDEN_API.md` §3.1),
and the detail endpoint returns real GPS per ad (§5.2). So:

1. Store `latitude`/`longitude` on `Ad` — already on the Stage D additive-column list
   (`HIDDEN_API.md` §8 Stage D), so no new model design needed.
2. Add a home coordinate to settings (one geocode call, cached — not per ad).
3. Compute haversine distance on save; store it as a column so it's filterable/sortable.
4. Express the actual decision as a `FilterRule` — the abstraction already exists:
   `TravelCostRule` rejects when `estimated_margin − (2 × distance_km × cost_per_km)` falls below
   a floor. That turns "is it close enough" into "is it worth the drive", which is the question
   that actually matters.

**Cheap first version, no new columns at all:** distance can be approximated from the PSČ prefix
or the locality string against a static CZ municipality table, no geocoding and no API dependency.
Worth doing that first to find out whether the ranking changes any decisions before paying for
GPS plumbing.

### Interactions

- **Depends on a numeric price** to compute margin at all — so it lands after the
  `price`/`price_type` split ([`PROMPTS.md`](PROMPTS.md) P22).
- **Wants the same notification rework as #3a** — distance and price-vs-comparable are exactly the
  fields that belong in a Discord embed next to the thumbnail. Build the two together; the
  notification path shouldn't be rewritten twice.
- **Is the wrong tool for GPS-less marketplaces** — Vinted (Stage 8) is shipped, not collected, so
  gate the rule on `marketplace` rather than assuming every `Ad` has a location worth scoring.

### Recommendation

Do the cheap PSČ-prefix version soon if flipping is the goal — it is the second-largest lever on
realised margin after latency, and it needs no new external dependency. Defer the GPS/`zip.php`
version until Stage D columns land anyway.

---

## 11. Seller identity & history in the admin — ✅ **done 2026-08-10**

> Shipped: transitive `(email_id, phone_id)` resolution to a fixpoint (`SellerAdCounts`, bounded
> by `MAX_IDENTITY_ROUNDS=5`), three-way counts (`by_email` / `by_phone` / `combined` — their
> *disagreement* is the signal), per-seller counts in the admin and embedded in the Discord
> message, and publisher partner tables with block/unblock actions. Migration `0025` removed the
> `bazos_id=0` sentinel that had merged 6.7% of ads into one fake seller.
>
> Details in [`SHIPPED.md`](../SHIPPED.md) and CLAUDE.md's *Seller identity* section. This is
> the local, zero-API precursor to
> [`DISCOVERY_PIPELINE.md`](../research/bazos-api/DISCOVERY_PIPELINE.md)
> §3.1 (reseller/dealer detection).
>
> ⚠️ **One caveat worth keeping**: `Ad.message` embeds `seller_ad_counts().summary`, so rendering
> an ad for Discord fires several `COUNT` queries — never call `.message` in a loop over a large
> queryset.


## Explicitly out of scope for this document

**[#60](https://github.com/jakub-kucera/marketplace-scrapper/issues/60) — using ChatGPT to write ad
copy for posts you're selling.** This is a *selling*-assistant feature, orthogonal to everything
else here (all of which is about discovering/monitoring/enriching ads as a buyer). Noted for
completeness, not pursued in this doc.
