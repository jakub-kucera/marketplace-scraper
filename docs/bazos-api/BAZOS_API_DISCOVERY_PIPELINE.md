# Bazos API-Driven Discovery Pipeline — Design & Workflow Ideas

Builds on `BAZOS_HIDDEN_API_RESEARCH.md` (endpoint reference, live-verified facts).
This doc is about **what to build with it**: a broader discovery pipeline than
today's narrow per-`Query` polling, plus a set of downstream enrichment/analysis
workflows the API newly makes cheap. Where a claim is live-verified I say so;
where it's a design idea, I flag it as unverified/speculative.

---

## 1. The proposed flow, validated stage by stage

```
┌──────────────┐   ┌───────────────┐   ┌────────────────┐   ┌───────────────────┐
│ 1. Broad      │──▶│ 2. Cheap      │──▶│ 3. Selective    │──▶│ 4. Seller/author  │
│    discovery  │   │    filter     │   │    detail fetch │   │    enrichment     │
│ (category/    │   │ (price/loc/   │   │ (ad-detail-2)   │   │ (ratings.php +    │
│  section API  │   │  ML anomaly)  │   │                 │   │  seller-inventory │
│  search)      │   │               │   │                 │   │  pull)            │
└──────────────┘   └───────────────┘   └────────────────┘   └───────────────────┘
                                              │                        │
                                              ▼                        ▼
                                         send to Discord      store contacts,
                                         (thin+detail)         expand discovery
```

### Stage 1 — Broad discovery (category/section-scoped, not keyword-narrow)

Use `ads.php` scoped by `category`/`section` rather than today's narrow
`Query.text` keyword rows — e.g. "everything under Škoda" instead of "iphone 13
pro". Paginate `limit=210`, `sort=date`, existing dedup (stop at first known
non-topped id). Per §4.3 of the research doc, the topped-ad run for a
*category*-scoped query is bounded (confirmed ~126-132 deep for a real category),
so this still resolves within one or two pages — the pathological case was
whole-*section* browsing with no category, which this design avoids by staying
category-scoped.

**Why broader is actually cheaper to maintain, not just to run:** fewer, wider
`Query` rows (one per category of interest) replace many narrow keyword rows,
and category comes for free — you already know it from the query you issued, no
need to look it up per-ad. Section is also free from the listing `url`'s
subdomain (confirmed live, research doc §5.1 correction) if you ever do a mixed
discovery pass.

### Stage 2 — Cheap filter pass — **zero extra API calls**

Runs entirely on the thin fields already in hand from stage 1: `price_formatted`
(parse to a number), `locality`, `title`. No detail call needed yet — this is the
key economic point that makes "filter before enrich" actually free, not just a
nice ordering:

- **Simple rules:** price under some threshold, or a locality allowlist/radius
  (locality is a free-text string in thin data — good enough for exact-city
  filters; true radius/distance needs `zip_code`, which is detail-only, or the
  search-level `distance`+`latitude`/`longitude` params applied at stage 1 instead).
- **Statistical/ML anomaly detection:** since category is already known (it's the
  query scope) and price is in thin data, you can maintain a rolling
  median/percentile price per category from your own accumulated discovery
  history and flag large negative residuals ("this is priced well below what
  similar recent listings in this category go for") — a real, cheap
  deal-finder. No description/detail data needed for a first-pass filter based on
  price + category + rough title-keyword matching.

### Stage 3 — Selective detail fetch — only for filter-passed candidates

`GET ad-detail-2.php` for the reduced candidate set only. This is the "1 call per
ad, unavoidable" cost already established in the research doc (§5.3) — the
win here is that you're now paying it for a small filtered subset, not every
discovered ad. Gets full description, images, GPS, `price_type`,
`email_id`/`phone_id`, section/category objects, and the undocumented
`user_ads_count`/`user_reviews_count` bonus fields — all in the same call, no
extra cost.

**Branch point:** send immediately, or continue to stage 4 enrichment first (or
both — enrich in the background, send now).

### Stage 4 — Seller/author enrichment — confirmed capability, bigger than expected

`GET ratings.php?email_id=<id>` — public, unauthenticated, gets the seller's full
review history: reviewer names, **phone numbers** (often present), sentiment
(`positive`/`negative`/`neutral`), dates. Store harvested reviewer phone numbers
— this is exactly the "maybe useful for some other workflow" the request called
out, and it now has one: see §3.3 below.

**New this round, live-confirmed and significant:** `ads.php` accepts
**`email_id=`/`phone_id=` as filter parameters, and they genuinely work** — not
silently ignored like the topped-bypass guesses were. Verified all 10/10 results
for a real dealer's `email_id` actually belonged to that dealer (checked via
detail lookup on every result), and it composes with other filters
(`email_id=X&category=93` correctly narrowed to that seller's cars only). One
quirk: no `x-total-count` header on this filter mode (unlike normal search) —
paginate with `offset` until empty, or trust `user_ads_count` from the detail
call as the expected total.

**This means you can pull any seller's entire current active inventory in one
cheap paginated call**, not just their ad count. That's the building block for
several of the workflows below.

---

## 2. "Suggest more if relevant" — concrete mechanisms

The request floated this loosely; here's what it can actually mean:

- **Seller-graph expansion.** Once a seller is flagged interesting (a great
  deal, a scam-risk profile, or a prolific dealer), immediately pull their full
  current inventory via the new `email_id=`/`phone_id=` filter — cheap, and
  often surfaces more relevant listings than the category sweep alone would
  (a private seller might list a matching item under a category your broad
  discovery doesn't cover).
- **Reviewer-graph expansion.** A harvested reviewer phone/email id becomes a new
  seed: check whether *they* also currently have active listings via the same
  filter. Turns passive phone-number harvesting into an active discovery
  channel — "follow the contact graph," not just "follow categories."
- **Keyword/category expansion via `suggestionsnew.php`.** When an interesting
  ad's title contains terms not covered by current discovery scope, use the
  suggestions endpoint to find the matching category id and consider adding it.
- **Sibling-category expansion via `categories.php?section=X`.** If one category
  in a section is proving fruitful, consider broadening to its siblings.

---

## 3. Additional workflows

### 3.1 Reseller / dealer detection

> **A local precursor shipped 2026-08-10** — see
> [`../refactor/BACKLOG_IDEAS.md`](../refactor/BACKLOG_IDEAS.md) #11. It resolves seller
> identity from the `(email_id, phone_id)` pairs already in the DB (transitively — the two
> ids are not 1:1; 4.7% of emails pair with several phones) and surfaces per-seller ad
> counts in the admin and in Discord notifications. Two things it does **not** do, both
> relevant here: it counts only ads *we* scraped, not the seller's true total, and it
> classifies nobody. The threshold below is what turns it into actual dealer detection, and
> it needs `user_ads_count` — i.e. the API scraper in production first.
>
> One finding from that work worth carrying into any threshold: a `bazos_id=0` publisher id
> is Bazos's "no publisher of this kind" marker, and it was being stored as a real row —
> 1,137 ads (6.7%) attached to one fake seller spanning 671 phones. Fixed, but the general
> lesson holds: **validate that a seller id is a real identity before aggregating on it.**

- Primary signal (free, already in every detail call): `user_ads_count`. A
  threshold (e.g. >20-30) flags "professional."
- **New:** with the seller-inventory pull, you get the *actual* current listing
  set for a suspected dealer, not just the count — enabling category/brand-mix
  analysis. E.g. "80 near-identical iPhone listings" (flipper/reseller) reads
  very differently from "80 ads spread across unrelated categories" (general
  dealer/pawn-shop-style account) or "80 ads all in Reality" (realtor/agency).
- Secondary signal: `user_reviews_count` relative to `user_ads_count` — a
  legitimate high-volume dealer accumulates reviews roughly proportional to
  sales; a high-ad-count account with near-zero reviews is a different risk
  profile (spam/bot vs. real business).

### 3.2 Scammer detection

- Base signal: `ratings.php` sentiment history + recency + volume → a basic
  trust score per seller.
- **New — identity-reuse cross-referencing.** Because `ratings.php` exposes
  *reviewer* phone/email ids and `ads.php` now supports filtering by those same
  ids, you can ask: does a phone number that shows up as a **reviewer** on one
  seller's page also show up as a **seller** elsewhere? Fake-review farms
  commonly reuse a small pool of accounts as both buyers and sellers — this is a
  real, checkable pattern here.
- **New — "throwaway seller" profile.** Very low `user_ads_count` (1-2) + near-zero
  `user_reviews_count` + a price flagged as anomalous by the stage-2 filter is
  the classic combination for a scam listing (disposable identity, too-good-to-
  be-true pricing). This is a concrete example of composing the price-anomaly
  filter's output with the seller-enrichment output — the pipeline stages feed
  each other, not just run in sequence.
- **New — negative-review clustering.** If the same reviewer identity leaves
  negative reviews across many different sellers in a short window, weight that
  reviewer's negativity down in your trust scoring (could be an unreliable
  serial complainer rather than signal about the seller) — a data-quality check
  on the trust score itself.
- **Speculative, not verified:** cross-referencing the same *real* phone number
  across different `email_id`/seller-name combinations (using the full number
  when it leaks in ad descriptions, per the research doc's §6.4b note) to catch
  one person running multiple seller identities. Only works when the full
  number happens to be in the description text — not guaranteed in general, only
  confirmed for one sample so far.

### 3.3 Find reposted ads

Two genuinely different cases, worth tagging separately rather than treating
"repost" as one bucket:

- **Same-seller repost (data hygiene, not fraud).** A legitimate seller's ad
  expires and they repost it under a new id. Detection is now cheap and precise:
  pull the seller's current inventory (§1 stage 4 capability) and diff it
  against your own historical archive of that same seller's past ads (matched
  by `email_id`/`phone_id`, which you're already accumulating) for near-duplicate
  title/price/locality. Purpose: avoid re-notifying the user about literally the
  same item, and building an "ad lifespan" signal (how long a listing typically
  stays up before being reposted or removed).
- **Cross-seller duplicate (potential fraud signal).** The same underlying item
  or photo posted under *different* identities — could be a scammer copying a
  legitimate listing's photos/description to run a fake competing ad at a lower
  price, or just a household posting the same item from two accounts. Detection,
  cheapest-first:
  1. **Text similarity** — normalize/hash or fuzzy-match title+description across
     your accumulated archive regardless of seller. Cheap, no extra requests
     (uses data you already fetched at stage 3).
  2. **Combined cheap signal** — same rough price + same locality + high title
     similarity, as a pre-filter before spending any budget on images.
  3. **Image similarity (real cost, use sparingly)** — `images[]` URLs are always
     ad-id-specific (`/img/{n}/{id}.jpg`), so you cannot compare URLs directly
     across different ads even when the underlying photo is identical; you'd need
     to download and perceptually hash (pHash/dHash) images to catch reused
     photos. Reserve this for candidates that already passed the cheaper
     text/price/locality pre-filter, not as a blanket policy — it's the one piece
     of this whole design with a real, non-trivial per-check cost (image
     downloads), unlike everything else here which reuses data already fetched.

### 3.4 Further ideas beyond what was floated

- **Market price-curve tracking.** Combine the cheap bulk `ad_id[]=` price
  refresh (already in the research doc's §6.4a `PRICE_CHANGED` workflow) with
  category-scoped discovery to build a continuously-updated price curve per
  (category, rough model/keyword) instead of a static baseline — makes the
  stage-2 anomaly filter more accurate over time as more data accumulates.
- **Seller watchlist — hybrid discovery model.** Once a seller is flagged
  (dealer, scam-risk, or consistently good deals), add them to a persistent
  watchlist and periodically re-poll their inventory directly via the
  `email_id=`/`phone_id=` filter (cheap, ~1-2 requests per watched seller),
  independent of and in addition to the broad category sweep.
- **Category/keyword drift / adaptive scope.** Track which categories are
  yielding the most flagged-interesting results over time and shift discovery
  budget toward the more fruitful ones — an active-learning-style resource
  allocation loop, feeding back into stage 1's scope.
- **Deal-velocity as a model-quality feedback loop.** For flagged "great deal"
  ads specifically (not the whole discovery stream — keep this targeted), track
  how fast they get removed/sold (bulk `ad_id[]=` re-check, or the `410 deleted`
  detail signal). Genuinely underpriced items should disappear fast; if flagged
  deals *aren't* selling quickly, that's feedback that the anomaly model's
  precision needs work.
- **Cross-country dealer presence — speculative, unverified.** A dealer chain
  might operate across `.cz`/`.sk`, but whether the same person's contact
  identity/ids carry across country sites hasn't been tested. Flag as an idea
  to check, not a claim.

---

## 4. Data model implications (light touch, additive)

Following the existing "nullable, additive columns" pattern from the research
doc's Stage D:

- Reviewer contact storage: either extend `PhonePublisher`/`EmailPublisher` with
  review-harvested numbers + sentiment history, or a new lightweight table —
  per the research doc's §6.4b recommendation, default to storing an **aggregate**
  trust signal (counts by sentiment type) rather than raw review text/PII unless
  there's a specific, justified need for the raw data.
- A `SellerWatchlist`-style table: `email_id`/`phone_id`, why flagged, last-polled
  timestamp — backs the hybrid discovery model above.
- A self-referential `Ad.reposted_from`/`duplicate_of` (nullable FK) once
  repost/duplicate detection identifies a match — keep same-seller reposts and
  cross-seller duplicates distinguishable (different `reason` values), since
  they mean different things downstream.
- Price-anomaly baseline: start with a rolling-stats query over the existing
  `Ad` table filtered by category+recency rather than standing up a real ML
  service — upgrade later only if the simple baseline proves insufficient.

---

## 5. Worth deciding deliberately before building this out

This pipeline is a real step up in scope from the current scraper — it moves
from "track new ads matching my declared interests" to "build a seller/reviewer
identity graph and actively hunt for suspicious patterns across ordinary
marketplace users, many of whom only ever left a review, not a listing." The
technical capability is confirmed; the scope decision is not automatically
justified by the API allowing it. Worth an explicit call on:

- How much raw reviewer PII to persist vs. aggregate-only (§6.4b in the research
  doc, restated here because this pipeline is where it'd actually get used).
- Whether "scammer detection" output is for personal risk-avoidance (don't buy
  from this seller) or something with a wider blast radius (e.g. surfaced to
  other users) — the two have very different privacy/liability profiles.
- Whether image-hash-based duplicate detection (the one real per-check cost in
  this design) is worth its cost for your actual goal, or whether the cheaper
  text/price/locality signal is sufficient in practice.
