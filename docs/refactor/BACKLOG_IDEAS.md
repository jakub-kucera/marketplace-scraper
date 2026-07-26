# Backlog Ideas — Not Yet in Any Stage

> Sourced from a full sweep of the GitHub issue tracker (57 issues, `jakub-kucera/marketplace-scrapper`),
> cross-checked against `PIPELINE_REFACTOR.md`, `STAGE8_VINTED_DESIGN.md`, and `docs/bazos-api/`.
> Everything here is either (a) not covered by any existing stage/doc, or (b) covered elsewhere
> but only partially — the gap is called out explicitly. Each idea is explored deeper than its
> originating issue, grounded in the current code, not just restated.
>
> Unlike the numbered `PIPELINE_REFACTOR.md` stages, these are **not sequenced** — they're
> independent candidates. Pick them up individually; none blocks another except where noted.

---

## Priority — effort vs. relevance

Ranked by effort vs. actual relevance to what this scraper does (find deals, notify fast, stay
under the radar), not by order of appearance above.

| # | Idea | Effort | Depends on | Priority |
|---|---|---|---|---|
| 6 | Posting-time-of-day → interval tuning | **S** (~half day) | nothing — data already collected | **Do first** |
| 7 | True AND/OR queries | **S** (probe: ~1hr; impl if real: trivial) | nothing | **Do first** (just to kill the unknown) |
| 3a | Thumbnail in Discord embed | **S/M** (~1-2 days) | nothing | **Do soon** |
| 1 | Cross-query `Ad`/`AdDelivery` split | **L** (bigger than any existing stage) | nothing, but gets worse the longer you wait | **Do before scaling queries** |
| 2 | asyncio scraping | **M/L**, but only as part of a scraper you haven't built yet | the API migration (not started) | **Not independently actionable** |
| 3b | Self-host image mirror | **L** (storage + serving + retention) | 3a | **Defer** |
| 4 | External price cross-referencing (Heureka) | **L**, high uncertainty | its own unresearched spike | **Defer** |
| 5 | Computer-vision item recognition | **L**, speculative | idea #3 (images) + vendor pick | **Defer, lowest** |
| 8 | Full-listing rescan flag (comprehensive price-drop detection) | **S** structurally (~1hr); **M** with the cap/throttle guardrail it needs | nothing, but must ship with a page cap/throttle | **Do soon, but scope narrowly** |

**Why this order:**

- **#6 and #7 are the obvious first picks** — both are small and self-contained, and don't wait on
  anything. #6 is pure analysis over data already collected; #7 isn't even a build decision yet,
  just an unresolved unknown that costs almost nothing to close (a couple of live curl probes, same
  style as the existing `BAZOS_HIDDEN_API_RESEARCH.md` work) — worth knowing whether it's real
  before it's worth a design.
- **#3a is the best "visible payoff" item** — Discord notifications get noticeably nicer for a
  bounded, well-understood cost. Doesn't need the API migration to start.
- **#1 (cross-query dedup) is the most architecturally important idea here, and the most
  expensive** — bigger than any single stage in `PIPELINE_REFACTOR.md`. Not urgent today because
  query overlap is rare in practice, but the discovery-pipeline doc's "fewer, broader
  category-scoped queries" pattern makes collisions much more likely. The real trigger for doing
  this isn't a calendar date — it's **before broadening query scope**, not after.
- **#2 (asyncio) isn't really a standalone task** — its own conclusion above is "don't retrofit
  onto the HTML scraper"; the actual payoff only exists once the Bazos API migration
  (`BAZOS_HIDDEN_API_RESEARCH.md` §8, not yet scheduled) is underway. Not worth active
  consideration until that migration is on the table.
- **#3b, #4, #5 are all "interesting but speculative"** — each has either an unresearched
  dependency (#4's Heureka endpoint, #5's vendor choice) or an unconfirmed benefit (#3b's
  click-tracking risk isn't observed to be a real problem yet). None block anything else — lowest
  urgency by construction.
- **#8 is cheap to build but easy to misuse** — the code change itself is a few lines, but enabling
  it on a broad category-scoped query multiplies request volume by orders of magnitude on *every*
  pass, not once (see its own section for the measured numbers). Worth doing soon since it's small
  and unblocks real price-drop detection, but only alongside a page cap/throttle guardrail and
  strictly as an opt-in for narrow queries — not a flag to flip broadly.

---

## 1. Cross-query `Ad` dedup (M:N `Ad`↔`Query`)

> **Referenced by** [`LLM_AD_REVIEW_DESIGN.md`](../refactor/LLM_AD_REVIEW_DESIGN.md) §3
> (2026-07-24) — LLM review/outreach opt-ins are properties of a *query's* interest in an ad,
> which today's single-`Ad`-row model can't represent per-query. Not a blocker for a first
> version of that proposal, but a reason to revisit this sooner if both move forward together.
>
> **Also referenced by** [`DISCORD_BOT_DESIGN.md`](../refactor/DISCORD_BOT_DESIGN.md) §3.1
> (2026-07-24) — per-ad Discord message-id tracking hits the same one-`Ad`-row-per-delivery
> assumption. Third independent proposal to want this; worth weighting accordingly.

**Source**: [#39](https://github.com/jakub-kucera/marketplace-scrapper/issues/39). Already flagged
as a TODO in code — `bazos/models.py:139` (`external_id` comment: "requires M:N to queries") and
`:161` ("TODO m:n relationship with Query (+ senders)") — but never designed.

### The actual problem

`Ad.query` is a single FK (`models.py:163`). `BazosQueryRunner._is_known` (`bazos_query_runner.py:31`)
scopes its existence check to `query=self.query` — so if two `Query` rows both match the same
real-world ad (e.g. a `text="macbook"` query and a `category=Apple` query), each discovers it
independently and creates **two separate `Ad` rows** with the same `(marketplace, external_id)`.
Consequences: duplicate Discord notifications (once per matching `Query`), duplicate
`load_full_description` fetches if both queries set that flag, and no single row that answers
"has this real-world ad ever been seen" — every downstream idea that wants global ad identity
(price history across all sightings, repost detection, the bazos-api discovery pipeline's
per-seller diffing) implicitly assumes one `Ad` = one real-world ad, which isn't true today.

### The design fork this creates

Status (`PENDING→APPROVED→SENT`) is currently a property of the **Ad row**. But delivery is
inherently a property of **(ad, query, sender)** — the same real-world ad matching two queries
with two different senders should notify both channels. Making `Ad` globally unique per
`(marketplace, external_id)` without addressing this would silently under-notify (the ad gets
sent once, to whichever query "won", and the second query's channel never hears about it) —
that's not a neutral simplification, it's a behavior regression.

### Options

**A — Do nothing structural, add a lightweight match-log.** Keep the first-discoverer `Ad` row
as-is; add `AdMatch(ad, query, matched_at)` purely for analytics/bookkeeping when a later query
rediscovers a known ad. Smallest change, but doesn't fix the under-notification problem above —
just documents that it happens.

**B — Split `Ad` (facts) from `AdDelivery` (per-query delivery state)** *(recommended)*.
`Ad` keeps only scraped facts (name, price, description, images) and becomes globally unique on
`(marketplace, external_id)` — updated in place on rediscovery rather than duplicated. A new
`AdDelivery(ad, query, status, filter_reason, sent_at, send_attempts)` row is created per
`(ad, query)` match and is what `run_filter`/`run_sender` actually operate on (`select_for_update`
against `AdDelivery`, not `Ad`). This is the shape the current architecture is already gesturing
at — "resource" and "notification of that resource" are different things — but it touches every
consumer of `Ad.status`/`filter_reason`/`sent_at`/`send_attempts`: `run_filter.py`, `run_sender.py`,
`bazos_query_runner.py`, `admin.py`, and all pipeline tests. This is a bigger migration than any
single stage in `PIPELINE_REFACTOR.md` so far — scope it as its own multi-step stage, not a quick
patch.

**Interaction with Stage 4 (`PriceChange`)**: worth doing *after* this split, not before — a price
change is a fact about the `Ad` (global), not about any one `(ad, query)` delivery, so `PriceChange`
keyed off a global `Ad` is strictly more correct than keying it off today's per-query `Ad` row.
Sequencing this idea before Stage 4 avoids re-deriving `PriceChange`'s FK target later.

**Recommendation**: B, but treat it as a standalone "Stage 10"-weight effort, not a drive-by fix.
Not urgent — duplicate notifications are a nuisance, not a correctness bug in today's single-query-
per-ad-in-practice usage — but worth doing before leaning further on cross-query features (broader
category-scoped queries per the discovery-pipeline doc make the collision more likely, since one ad
now more easily matches two overlapping queries).

---

## 2. Concurrent scraping (`asyncio`/`aiohttp`)

**Source**: [#62](https://github.com/jakub-kucera/marketplace-scrapper/issues/62).

### Where it would and wouldn't help, concretely

`BazosRunner.run()` (`bazos_runner.py:36`) loops over enabled queries **strictly sequentially**,
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
- **The future `BazosApiScraper`** (`BAZOS_HIDDEN_API_RESEARCH.md` §8) — biggest benefit by far.
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
> [`DISCORD_BOT_DESIGN.md`](../refactor/DISCORD_BOT_DESIGN.md) §1.4/§5 — that proposal
> independently needs the same move off plain-text `discord_notify` webhooks onto real
> embeds/components; worth building once rather than twice if both are ever picked up.

### 3a. Attach a thumbnail to the Discord message — cheap, low-risk, decoupled from 3b

The hidden API's listing response already includes `image_thumbnail` **at zero extra request
cost** over what discovery already pays (`BAZOS_HIDDEN_API_RESEARCH.md` §5.1); the detail endpoint
includes the full `images[]` array at the same per-ad cost `load_full_description` already pays
(§5.2). So once the API migration (`BAZOS_HIDDEN_API_RESEARCH.md` §8, Stage B) lands, this is
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

## 4. External price cross-referencing (Heureka / price-comparison APIs)

**Source**: [#36](https://github.com/jakub-kucera/marketplace-scrapper/issues/36) ("search product
name in Heureka / Price API"), [#56](https://github.com/jakub-kucera/marketplace-scrapper/issues/56)
(cheap Macbook/iPhone deal-finder), and the "EXTERNAL PRODUCT DB" node on the #54 whiteboard.

This is a different signal than the *internal* rolling price-baseline already designed in
`BAZOS_API_DISCOVERY_PIPELINE.md` §2 Stage 2 ("rolling median/percentile price per category from
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

### The price source itself is unresearched

Unlike the Bazos hidden API (fully probed in `BAZOS_HIDDEN_API_RESEARCH.md`), **no equivalent
research has been done for Heureka or any price-comparison source** — no confirmed endpoint, no
confirmed rate limits, nothing. This is a bigger unknown than anything else in this document; it
needs its own research spike before it's more than an idea.

**Recommendation**: if pursued, scope narrowly to Apple laptops/phones (matching #56's original
ask) rather than a general product-pricing system, and treat the Heureka-side research as a
separate, first prerequisite spike — don't design the `Query`/filter integration before that
endpoint even exists on paper.

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

**Source**: [#36](https://github.com/jakub-kucera/marketplace-scrapper/issues/36) ("analyse at what
hours are posts most posted and change the interval changing logic").

The cheapest idea in this document by far: `Ad.publish_date` (already captured for every ad,
`models.py:149`) plus `Ad.created` (free via `TimeStampedModel`) is already **enough data today** to
bucket posting/discovery volume by hour and weekday — zero new scraping, zero new model fields, zero
new API calls, just an aggregate query (`Ad.objects.annotate(hour=ExtractHour("publish_date"))...`)
over data already being collected.

This feeds directly into `bazos/scraping/interval_multiplier.py`'s `NightMultiplier` (referenced in
`CLAUDE.md`'s Environment section) — currently a flat day/night 2× split. A real hourly posting-
density curve could replace that blunt heuristic with one that tracks actual posting patterns:
poll more often during genuine peak-posting hours, back off harder than a flat 2× overnight if
volume is even lower than "night" currently assumes. `NightMultiplier` is already the right
extension point — this replaces its internals, not the interface `BazosRunner.get_next_interval`
calls.

**Recommendation**: good first pass at reducing wasted/late polls — no new dependencies, all data
already on hand, small and self-contained.

---

## 7. True AND/OR query support — unconfirmed, needs its own probe

> **Promoted to `PROMPTS.md` as P15** (2026-07-24) — ready-to-run probe steps there, this
> section remains the fuller rationale.

**Source**: [#52](https://github.com/jakub-kucera/marketplace-scrapper/issues/52) ("the BE support
AND and OR operator for search terms").

Cross-checked against `BAZOS_HIDDEN_API_RESEARCH.md` §4.1: the confirmed-live `query` param
behavior is full-text search across title+description, with a **confirmed** `-word` exclusion
suffix and quoted-phrase exact-match — but the research doc never tests or claims boolean AND/OR
operators. The original issue's claim was never verified against either the HTML search form or the
hidden API; treat it as **unconfirmed**, not as an existing capability waiting to be wired up.

If it's real, it would reduce `Query` row sprawl the same way the discovery-pipeline doc's "fewer,
broader queries" theme already argues for (§1: category-scoped over narrow keyword rows) — e.g. one
query for `"macbook" OR "imac" OR "ipad"` instead of three separate `Query` rows. But this needs a
small, targeted live probe (same methodology as `BAZOS_HIDDEN_API_RESEARCH.md` §7) before any model
change is designed around it.

---

## 8. Full-listing rescan flag — comprehensive price-drop detection

> **Related but distinct**: [`DISCORD_BOT_DESIGN.md`](../refactor/DISCORD_BOT_DESIGN.md) §2.1/§3.2
> (2026-07-24) already designs `AdWatch` — a per-ad "👁 Watch this ad" model plus a `run_ad_watch`
> poll loop — for the *same* underlying gap (an ad that scrolls out of a query's newest-first scan
> window never gets re-checked). `AdWatch` solves it for a user-curated set of *specific* ads, cheaply,
> via the bulk `ads.php?ad_id[]=` recheck (`BAZOS_HIDDEN_API_RESEARCH.md` §5.3, §8 Stage D) — up to 210
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

`run_existing_query` (`bazos_query_runner.py:71-95`) walks a query's results newest→oldest and stops
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
`Query.full_rescan` — that changes the branch at `bazos_query_runner.py:91-95`: instead of `break` on
a known non-TOP ad, `continue`, exactly like the existing TOP-ad case already does. Every known ad the
query has ever seen then gets its price compared on every pass, and on a drop gets the existing
`PriceChange`/`AdStatus.PRICE_CHANGED` treatment (`bazos_query_runner.py:78-89`) — no new pipeline
mechanics needed, `run_filter` and `PriceDropRule` already handle `PRICE_CHANGED` re-entry correctly.

### The real cost — quantified from `PROXY_ROTATION_RESEARCH.md`

`run_query` (`bazos_scraper.py:210-235`) is a lazy per-page generator with a sleep between every page
fetch (`BAZOS_PAGE_WAIT_TIME`) — breaking early is *why* per-pass cost is low today.
`PROXY_ROTATION_RESEARCH.md:179` measures this directly: "steady-state each category still resolves in
~1 request/pass (dedup breaks at the first known non-TOP id)." Flipping that off for a query changes
its cost from O(1) request/pass to O(listing size / `PAGE_SIZE`) requests **every single pass,
forever** — for the doc's own `auto` category example (49,372 active listings), that's hundreds of
requests per pass instead of one, at whatever cadence that query runs (240 passes/day at a 5-min
interval per the doc's model). It also serializes badly: queries run strictly sequentially, sharing
one Tor session (`BazosRunner.run()`, see idea #2 above), so one deep-rescan query would dominate
wall-clock and delay every other query's turn during its pass.

### Recommendation

Build it as a narrowly-scoped opt-in, not a general-purpose toggle:

- Per-query boolean, off by default, exactly like `load_full_description`.
- Document (and ideally guard in code/admin) that it should only be enabled on small/narrow queries —
  explicitly warn against combining it with the "broader category-scoped queries" direction
  `BAZOS_API_DISCOVERY_PIPELINE.md` pushes toward, since that's exactly where the cost multiplies
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

## Explicitly out of scope for this document

**[#60](https://github.com/jakub-kucera/marketplace-scrapper/issues/60) — using ChatGPT to write ad
copy for posts you're selling.** This is a *selling*-assistant feature, orthogonal to everything
else here (all of which is about discovering/monitoring/enriching ads as a buyer). Noted for
completeness, not pursued in this doc.
