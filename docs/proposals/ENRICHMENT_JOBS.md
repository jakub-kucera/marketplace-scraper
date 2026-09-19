---
title: Enrichment jobs — on-demand lookups, triggered from the admin today and the bot later
status: shipped
shipped_in: bazos/jobs.py, bazos/enrichment.py, bazos/ratings.py, bazos/reposts.py, llm/extraction.py
updated: 2026-09-18
verified: 2026-09-18
---

# Enrichment jobs — on-demand lookups, triggered from the admin today and the bot later

> ✅ **Built, 2026-09-17 — this is now the spec the code was written from, not open work.**
> Every job below exists, with an admin action where one made sense and a schedule where the
> work is periodic. What actually shipped differs from the plan in three places, each noted
> inline: §4.3's watch flag was **not** built (the delisting sweep already does that work and
> nothing yet asks for a priority tier), §5 gained the housekeeping and canary jobs that were
> only mentioned in passing, and §7's build order was followed exactly.
>
> Written days after [`JOB_QUEUE.md`](JOB_QUEUE.md)'s decision landed. It answers one question
> — *what would "🔍 Check seller" actually be, as a job?* — and generalises the answer, because
> the same shape covers most of [`DISCORD_BOT.md`](DISCORD_BOT.md) §2's catalog plus several
> things that catalog never mentions.
>
> **Prerequisites**: `django-q2`, `bazos/jobs.py`, `ensure_schedules`, and the
> `marketplace_qcluster` service. Without a queue none of this is buildable without giving the
> caller its own Tor circuit — see §1.

---

## 1. The shape, and why it is the same for all of them

An enrichment job **takes an id, does network work, and writes a row**. It does not post
anywhere.

That last clause is the design. The obvious instinct is "button press → fetch → reply in
Discord", but that couples every job to a delivery channel **that does not exist yet**, and
throws the result away the moment the message scrolls. A row in the database is readable by
the admin today, by the bot when it exists, and by the next question nobody has asked yet.

```
trigger (admin action | bot button | schedule)
    -> async_task("bazos.jobs.<name>", pk)
        -> job: fetch, parse, persist
            -> admin renders the row;  later, the bot reads the same row
```

**Why a queue at all**, restated because it is the load-bearing reason: `JOB_QUEUE.md` §2 —
the shared `requests.Session` and its Tor circuit are not safe for concurrent callers. Most
jobs below need a Bazos request. Without the queue, an admin request or a bot process would
have to own its own circuit, doubling the fingerprint surface against a marketplace that 403s
roughly half our exits (49.8% measured over 5,293 attempts, 7 days to 2026-09-06). With it,
the caller enqueues and the single worker that already owns the session does the work.

### 1.1 Three conventions, each with a trap behind it

**Pass primitive ids, never model instances.** django-q2 pickles task arguments, so an `Ad`
handed to `async_task` is serialised as a *snapshot* — the worker then operates on a stale
copy and writes it back over whatever changed meanwhile. Pass `ad.pk` and re-fetch.

**Return a short string; let exceptions escape.** This is already `bazos/jobs.py`'s stated
rule: django-q2 records the return value on `Success` and the traceback on `Failure`, which is
what makes the admin a run log. A job that catches its own exception to "be safe" produces a
green row that lies.

**One job per object, not one job per selection.** An admin action over 50 rows enqueues 50
tasks, not one. One failure then loses one lookup rather than forty-nine, each gets its own
audit row, and the worker stays interruptible between them.

### 1.2 The constraint this inherits

`Q_CLUSTER["workers"] = 1`, and `settings.py` says why in as many words: raising it *requires*
the `requires_bazos_session` lock design first. So **every job serialises behind every other
job**, including the delisting sweep, which at full backfill is ~96 paced requests plus
rotations — the reason `timeout` is 30 minutes.

Consequence, and it is a real one: an admin-triggered lookup can sit behind a sweep for tens
of minutes. Two mitigations, in order of preference:

1. **Chunk the long jobs.** `sweep_delisted` should take bounded slices and re-enqueue rather
   than draining the whole backlog in one task, so the worker yields between slices. This also
   paces the `PRICE_CHANGED` fan-out the sweep produces, which is already the larger of the
   two producers.
2. Accept it, and show queue depth in the admin. django-q2's `OrmQ` table makes that trivial.

A second cluster is **not** a mitigation for the Bazos jobs — both clusters would touch Bazos,
which is exactly what the single worker exists to prevent. It *is* a legitimate option for the
three jobs in §5 that touch no Bazos session at all, if it ever matters.

---

## 2. Half the catalog needs no job at all

Going through `DISCORD_BOT.md` §2 with the code as it stands today, the useful split is not
Tier 0/1/2 — it is **"needs a request" vs "needs rendering"**:

| Catalog item | Needs a Bazos request? | Verdict |
|---|---|---|
| 📈 Price history | No — `PriceChange` rows exist | **Rendering.** Already an inline on `AdAdmin`. |
| 📊 Price context | No — `bazos/comparables.py` shipped | **Rendering.** `find_comparables` already returns it. |
| ❓ Why rejected | No — `AdDelivery.filter_reason` | **Rendering.** (The catalog says `ad.filter_reason`; that field moved to `AdDelivery` in migrations 0026–0028.) |
| 📍 Distance | No — `PostalCode` cache + `bazos/geo.py` | **Rendering.** `manage.py appraise` already prints it. |
| 🚫 Blocklist seller | No — it is a write | **Admin action**, no job. Already exists. |
| ⭐ Favorite / 🔇 Mute | No — local flags | **Admin action**, no job (needs the fields). |
| 🕵️ Repost check | No — reads our own archive | **Job**, but CPU-only; no session, no lock concern. |
| 🔍 **Check seller** | **Yes** — `ratings.php` | **Job.** §3. |
| 📦 **Seller's other listings** | **Yes** — `ads.php?email_id=` | **Job.** §4.1. |
| 📖 **Full description** | **Yes** — `ad-detail-2.php` | **Job.** §4.2. |
| 👁 **Watch this ad** | **Yes**, repeatedly | **Not a job.** §4.3. |

**Four of eleven need the network, and one of those four should not be a job.** The rest are
display problems whose data the pipeline already collects — worth knowing before anyone plans
a bot sprint around "fetching".

---

## 3. `fetch_seller_ratings` — the one worth doing first

`GET ratings.php?email_id=<id>` (or `phone_id=`) is **public, unauthenticated, and
unpaginated**: one request returns a seller's whole rating history
([`HIDDEN_API.md`](../research/bazos-api/HIDDEN_API.md) §6.4b, re-verified live with a worked
example). Every id it needs is already stored — `EmailPublisher.bazos_id` /
`PhonePublisher.bazos_id` hold exactly these values — so **the entire back catalogue can be
enriched with no discovery step**. Each entry carries `name`, `phone`, `message`, `type`
(`positive`/`negative`/`neutral`) and `from`.

### 3.1 The PII decision, which is the whole design

`ratings.php` returns **reviewers'** real, unmasked phone numbers — private individuals who
left feedback, not the seller. §6.2(5) flags this as *"a step up in what we'd be collecting
versus today's scraper"* and asks for *"a deliberate decision on whether/how to store this,
not just 'because the API returns it.'"* §6.4b then answers its own question in point 2:
store the aggregate, not the raw review list.

**This proposal adopts that recommendation.** Counts, not identities:

```
EmailPublisher / PhonePublisher  +=
    ratings_positive, ratings_negative, ratings_neutral   # ints, default 0
    ratings_first_at, ratings_last_at                     # dates — "is this reputation current"
    ratings_fetched_at                                    # null = never looked
```

**Not stored**: reviewer `name`, reviewer `phone`, reviewer `email_id`, `message`.

Three reasons, in the order they should be re-litigated if anyone wants to change it:

- **The counts answer the question.** "Does this seller have negative feedback, how much, how
  recent" is the decision input. A reviewer's name and number contribute nothing to it.
- **Backups already hold seller PII** — `BACKUPS.md` is why `./backups/` is gitignored.
  Adding *third-party* PII widens the blast radius of a leak to people who never transacted
  with us and have no relationship to this project at all.
- **`MONETIZATION.md` §6 (Legal analysis) outranks convenience here.** The reviewer data has
  no lawful basis that the seller ids do not already have, and §6.1's "fix before anything"
  tier is not the place to be adding new categories of personal data.

**On the publisher rows rather than a `SellerRatings` table**, because `PublisherBlocklistRule`
already reads `blocked` off the publisher and a future trust rule should not need a join to
read a sibling number. The cost is real and should be acknowledged: `PublisherMixin` is
explicitly *"a plain mixin, not an abstract model: it adds no fields, so it needs no
migration."* Six shared fields either get declared twice or that mixin becomes an abstract
base. Declaring twice mirrors `blocked`, which is already duplicated on both models; prefer
that to reshaping the mixin for this.

⚠️ **One open check before building, from §6.4b point 1**: does bazos.cz itself show reviewer
names and phones on a public profile page? If it does, the API is not exposing anything new,
only making it programmatic, and the calculus above is unchanged but better grounded. If it
does not, the case for storing counts only gets stronger. Five minutes with a browser settles
it and nobody has done it.

⚠️ The genuinely useful thing being given up is the **text of negative reviews** — "never
shipped", "arrived broken" is more actionable than `negative: 3`. If that turns out to matter,
the right move is a setting defaulting to off, mirroring `PRICE_MODEL_SHADOW_MODE` and
`LLM_PROVIDER=NULL`: ship the cautious default, make the other one a deliberate act. Do not
quietly start storing third-party free text because it was convenient.

### 3.2 What it buys, beyond a button

`PublisherBlocklistRule` already exists and already reads `blocked`. Ratings make that flag
**evidence-based rather than a hunch**: a seller with several recent negatives becomes a
blocklist candidate a human confirms in one click, instead of one discovered after wasting a
trip.

It also repairs a known weakness in `SellerAdCounts`, which counts *ads in this DB*, not the
seller's true Bazos total — `ad-detail-2.php` returns `user_ads_count` and `user_reviews_count`
as the real figures, and both come free on a detail call §4.2 sometimes already makes.
`user_ads_count` in the hundreds is the "private seller is actually a dealer" signal
`DISCOVERY_PIPELINE.md` §3.1 wanted.

---

## 4. The other three

### 4.1 `fetch_seller_listings(publisher_pk)`

`ads.php?email_id=` / `phone_id=` is confirmed working and undocumented-but-stable
(`HIDDEN_API.md` §6.4g). One request returns a seller's **entire current active inventory**,
thin payload, 210 rows per page.

It should write through the normal `_resolve_ad` path, so dedup, geocoding and scoring happen
for free. Two things to settle before building:

- **It creates `Ad` rows with no `AdDelivery`.** That is correct — no query asked for them —
  but it quietly changes what every ad count means, from "ads our queries found" to "ads we
  have". Give `Ad` an explicit provenance marker in the same change rather than discovering
  the ambiguity in six months' analysis.
- It is the missing input for **repost detection** (`DISCOVERY_PIPELINE.md` §3.3): a seller's
  past-vs-current inventory diff is exactly what catches the same item relisted under a new
  `external_id`. Which is why §5 lists `detect_reposts` as *blocked on this one*, not parallel
  to it.

### 4.2 `fetch_full_description(ad_pk)`

Wraps `scraper.load_full_description`. Useful because `Query.load_full_description` is a
*per-query* boolean, so today the choice is "every ad on this query pays a detail request, or
none do". A job makes it **per ad, on demand**, which is the right granularity for "this one
looks interesting".

Also the cheapest fix for a real gap: on the API path this call is the only source of
`email_id`/`phone_id`, so an on-demand fetch is what turns a thin ad from "seller unknown"
into a real identity — and therefore, per §3, into something that *has* ratings to fetch.

### 4.3 "👁 Watch this ad" — a priority flag, not a job

`DISCORD_BOT.md` §3.2 proposes an `AdWatch` model plus a `run_ad_watch` polling process. That
was written before the delisting sweep existed. The sweep now does that work:
`bazos/delisting.py` re-checks live ads on an age-decayed schedule, detects price changes, and
records removal.

Watching is therefore a **priority tier, not a new mechanism**.
`bazos/delisting.py::_priority_expression()` already exists and already promotes SENT and
scored ads to a faster band. A watch is one more `Q()` clause in that expression, backed by a
boolean or timestamp on `Ad`.

Prefer that to both alternatives: a fourth polling process duplicates machinery that works,
and a per-ad `Schedule` row would put thousands of rows in a table meant to hold a handful.
**`DISCORD_BOT.md` §2.1 and §3.2 should be marked superseded on this point** when someone next
touches that doc.

---

## 5. Jobs the bot catalog does not mention

| Job | Why | Needs the Bazos session? |
|---|---|---|
| `lookup_reference_price(ad_pk)` | **Was already an admin action, doing its HTTP inline in the request.** See §6; it was the first thing ported, not a new idea. | No — Zboží |
| `rescore_ads(...)` | `manage.py rescore_ads` exists; as a job, an artifact bump becomes a one-click admin action instead of an SSH session | No |
| `extract_specs_with_llm(ad_pk)` | `PRICE_MODEL_BENCHMARK.md` §3.1 is blunt: two extractor regexes were worth more R² than the entire model-class choice. `llm/` is built and inert (`LLM_PROVIDER=NULL`). | No — LLM API |
| `geocode_postal_code(code)` | Closes the window where a hand-typed query centre is unusable until the next scrape pass warms the cache | Yes |
| `sweep_delisted_chunk(...)` | §1.2 — chunking is what stops the sweep monopolising the single worker | Yes |
| `sync_vinted_catalogs()` | `create_vinted_catalogs` is already a command; scheduling it monthly catches taxonomy drift instead of waiting for a query to go quiet | No — Vinted |
| `detect_reposts(publisher_pk)` | CPU-only over our own archive. **Blocked on §4.1** — without an inventory pull there is nothing to diff against. | No |

The first three need **no Bazos session at all**, which is what makes them the safe candidates
if the single-worker constraint ever actually bites.

---

## 6. Triggering from the admin

The pattern — enqueue, return immediately:

```python
@admin.action(description="Fetch seller ratings")
def fetch_ratings(modeladmin, request, queryset):
    pks = list(queryset.exclude(bazos_id=None).values_list("pk", flat=True))
    for pk in pks:
        async_task("bazos.jobs.fetch_seller_ratings", pk)
    skipped = queryset.count() - len(pks)
    modeladmin.message_user(
        request, f"Queued {len(pks)} lookup(s); skipped {skipped} with no Bazos id", messages.INFO
    )
```

**The repo already had the counter-example, which is why §7 ports it first.**
`refprice/admin.py::look_up_reference_price` called `lookup_reference_price`
**synchronously, once per selected ad, inside the request**. Its posture was right — explicit
operator invocation, never on the scrape path — and it predated the queue, so this is not a
criticism of it. But select fifty ads and the admin request made fifty sequential HTTP calls to
Zboží while the browser waited. It now enqueues one task per ad and says "Queued", which was
the smallest possible proof that the pattern in this section works; it also needs no Bazos
session, so it could not be blocked behind a sweep.

Four things an enqueueing action must not do:

- **Must not do the work inline.** With Tor and `workers: 1`, a fifty-row selection is
  minutes. An admin request that blocks that long is a gateway timeout and a lost result.
- **Must not report success.** It queued something. Say "queued", not "fetched" — the
  `Success`/`Failure` rows are where the outcome lives, and the message should link to them.
- **Must not silently skip.** A publisher with no `bazos_id`, an ad on a marketplace with no
  ratings endpoint — filter them, then say how many were skipped and why. Same discipline as
  `geocode_postal_codes` reporting unparseable codes.
- **Must not be the only trigger.** Every job stays runnable as a management command. That is
  what makes it debuggable over SSH without clicking through a UI, and it is already how
  `sweep_delisted` is built — the job wraps the command rather than reimplementing it.

Where they live: ratings and seller-listings on `EmailPublisherAdmin` / `PhonePublisherAdmin`;
full-description, reference-price and rescore on `AdAdmin`. Results render as readonly panels
on the change page next to `comparables` and `seller_ad_counts`, which is already this
project's established shape for "computed context about this row".

### 6.0 …and a page for when all you have is an id

An action needs a row on screen. Sometimes you just have an id — from a log line, a
notification, a Discord message later — and finding the row to select it is the long way
round.

**Admin → Jobs → Run a job** is that: a dropdown built from `JOB_CATALOG` and one argument
field. It exists because the generic alternative is bad, not because a form is nice.
django-q2's Schedule admin already enqueues anything with `schedule_type=Once` — but the
dotted path is typed by hand, so a typo becomes a `Failure` row in a worker nobody is
watching (the exact trap `bazos/jobs.py` declares its constants to avoid); the id is not
checked either; and it leaves a stray schedule row behind.

So the path comes from the registry, and **the argument is resolved before anything is
queued**. An ad id that does not exist, an unusable postal code, or a seller given as a bare
number — a seller is a *pair* of ids across two tables, so `42` alone is ambiguous and
`email:42` is not — all fail on the page you are looking at.

### 6.1 The bot, later, changes nothing here

A bot button calls the same `async_task` with the same arguments. The only addition is telling
the user the answer arrived — a *notification* concern, and `senders/` already exists for that.
The job stays ignorant of who asked, which is the property that lets one job serve a schedule,
an admin click and a Discord button without branching.

---

## 7. The build order — followed as written

1. ✅ **`lookup_reference_price` ported first.** Existing action, existing tests, no new model
   or endpoint, and no Bazos session — so it could not be blocked behind a sweep while the
   conventions in §1.1 were being proved.
2. ✅ **The delisting sweep chunks** before any interactive Bazos job existed. `sweep_delisted`
   now works a slice, yields the single worker and re-enqueues itself, with two independent
   stops — a round budget, and "this chunk cleared nothing", the second being what stops a
   blocked sweep re-queueing itself against a marketplace that is refusing us.
3. ✅ **`fetch_seller_ratings` next**, and the PII decision in §3.1 was adopted unchanged.
   ⚠️ **The five-minute browser check in §3.1 was NOT done** — whether bazos.cz shows reviewer
   names and phones on a public profile page is still unknown. It does not change the
   recommendation either way, and the cautious option was taken regardless, so nothing is
   blocked on it. It would still be worth grounding.
4. ✅ **`Ad.source` shipped in the same change as §4.1**, so "ads we have" never silently
   stopped meaning "ads our queries found".

### 7.1 What shipped beyond the plan

- **A shared `bazos/scraping/session.py`.** Two commands already had their own copy of "pick
  the IPChanger, rotate on a 403"; four more callers made it a pattern. Exhaustion raises
  `AllCircuitsBlocked` rather than returning `None`, because callers here already use `None`
  for their own meanings and a third would be the conflation that wrote 180 false removals.
- **Housekeeping.** `StatusLog` and `QueryRun` were the only two tables growing with the
  clock rather than the market, and nothing pruned either.
- **`Ad.reposted_from`.** §5 listed `detect_reposts` with nowhere to put the answer; a
  nullable self-FK is one link per ad, visible on the ad page, and needs no new table.
- **`AdSpecExtraction`.** §5's `extract_specs_with_llm` needed a home, and `Ad.attributes`
  is explicitly not it — that column means "as the marketplace *stated* it".

### 7.2 What did not ship, and why

- **§4.3's watch flag.** The reasoning still holds — a watch is one `Q()` clause in
  `_priority_expression()`, not a fourth poller — but nothing yet asks for a priority tier,
  and the sweep already re-checks every live ad. Build it when something wants it.
- **A Discord path for any of this.** Out of scope by decision: results land in database rows,
  and the admin reads them. §6.1 still describes what changes when a bot exists — nothing.

## 8. Explicitly out of scope

Seller *outreach* — drafting or sending messages to sellers. `LLM_AD_REVIEW.md` §4 already
recommends against auto-sending and nothing here changes that assessment. An enrichment job
reads; it does not talk to anyone.
