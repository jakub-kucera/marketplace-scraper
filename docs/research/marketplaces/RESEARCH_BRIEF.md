---
title: Research brief — which Czech marketplace to implement next
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Research brief — which Czech marketplace to implement next

> **You are being asked to research, not to implement.** No code changes. The deliverable is one
> markdown file per marketplace you assess, plus a ranked recommendation.
>
> **Written 2026-08-22**, against a codebase that just finished becoming genuinely
> multi-marketplace (three scrapers registered, the `Ad`/`AdDelivery` split landed, `Ad` columns
> widened and made nullable). That work is *why* this question is worth asking now.

---

## 0. What to deliver

For each marketplace you assess:

```
docs/research/marketplaces/<NAME>.md          e.g. AUKRO.md
```

Following the structure in §7. Plus one summary file:

```
RECOMMENDATION.md   ranked, with a clear "build this one first" and why
```

Match the house style of the existing research docs — read
[`HIDDEN_API.md`](../bazos-api/HIDDEN_API.md) first.
It is the standard to hit: every claim either **live-measured with the command that produced it**,
or explicitly flagged as unverified. That doc's §7 (raw probe log) is the model.

**The single most important rule: mark every claim as measured or assumed.** A previous design
doc in this repo (`VINTED_SCRAPER_DESIGN.md`) asserted a library's field mapping from its README
without running it. Four of the claims were wrong, including the one the whole design rested on,
and it was only caught when someone finally ran a probe — after the prompts derived from it had
already been written. Do not repeat that.

---

## 1. Ground rules

**Work in two passes, not candidate-by-candidate.** Do not research one marketplace to
completion and then start the next — you will spend the whole budget on candidate #1.

| Pass | Scope | Per-site budget |
|---|---|---|
| **Pass 1 — triage** | The scale test (§2b) on **every** candidate, plus a 60-second existence check | **≤ 5 requests** per site, hard cap |
| **Pass 2 — workup** | Legal (§3), transport (§4), schema fit (§5), workflows (§6) on the **top 3 only** | **≤ 30 requests** per site, hard cap |

Rank after Pass 1 and write the ranking down *before* starting Pass 2, so the cut is made on
measured scale rather than on whichever site turned out to be the most interesting to poke at.

Everything not in the top 3 gets a three-paragraph file: what it is, the measured scale, why it
was cut. That is a complete and useful deliverable — do not apologise for it or pad it.

**If a budget forces you to stop mid-assessment, stop and say so** in §9 of that file. A file
that says "transport undetermined, budget exhausted after 30 requests" is honest and actionable.
A file that fills the gap with plausible guesses is the exact failure this brief was written to
prevent.

**Measure, don't recall.** Listing counts, API shapes, field names, rate limits — all of it must
come from a request you actually made, with the command recorded. Your training data about Czech
marketplaces may be stale or wrong. Treat it as a hypothesis generator only.

**Be honest about failure.** "I could not find a hidden API for Sbazar" is a valuable, publishable
finding. Inventing a plausible-looking endpoint is worse than useless.

**Do not scrape at volume.** You are characterising, not harvesting. A handful of requests per
site, spaced out. Never run a paginated crawl. If a site returns 403/429, record it as a finding
and stop — do not rotate IPs to get around it during research.

---

## 2. Phase 1 — candidates and scale triage

### 2a. Seed list

These are **hypotheses, not a curated list.** Verify each still exists and is active before
spending time. Add anything you find; drop anything dead.

| Candidate | Why it's on the list | Prior work in this repo |
|---|---|---|
| **Sbazar.cz** | Seznam-owned, the most direct Bazos competitor in the same general-classifieds categories | **Zero mentions anywhere in this repo** |
| **Aukro.cz** | Auction format — see §5a, this is the interesting one | **Zero mentions anywhere in this repo** |
| **Facebook Marketplace** | Large, but see §3d before spending any time | Mentioned once in `MONETIZATION.md` as a Bright Data dataset example. Note the `facebook/` Django app is unrelated — a leaked-profile PII importer, not Marketplace |
| **bazos.sk / .at / .pl** | Same hidden API, different base URL and currency | Documented in `HIDDEN_API.md` — see §6, this is the cheap one |
| Mimibazar, Hyperinzerce, Annonce.cz, Avizo | General classifieds, unknown current scale | none |
| Vertical sites (TipCars, Sauto, Sreality, Bezrealitky…) | Deep in one category | none |
| Remix, other Vinted-likes | Clothing resale | Vinted itself is already implemented |

Explicitly consider whether a **vertical** site beats a general one. The project's flipping thesis
(`MONETIZATION.md` §4.2) targets phones, laptops, tools and bikes. A site that only does cars
is useless for that; a site that only does electronics might be excellent.

### 2b. The scale test — do this before anything else

Establish, for each candidate: **how many active listings, and how many new per day.**

**Active listings** is usually cheap. Find a total-results count in the HTML, a count in a JSON
response, an `X-Total-Count`-style header, a sitemap index size, or derive it from pagination
depth (last page number × page size). `MONETIZATION.md` §2.3 did this for Bazos via
`x-total-count` on `api/v1/ads.php`.

**New-per-day is the hard one, and the Bazos method does not transfer.** ⚠️ That doc derives
`new/day ≥ active / 60` from the fact that **free Bazos ads auto-delete after 2 months**
(ToS §137). That arithmetic is a property of forced expiry, not a general technique. Aukro
auctions run for a fixed duration but relist; Sbazar's expiry rules are unknown; **Vinted items
never expire at all.** Applying `active / expiry_days` anywhere without a known forced-expiry
window produces a meaningless number that looks authoritative. Do not do it.

Use, in order of preference:

1. **Timestamp span of a newest-first page** — one request. Sort newest-first, take the page of
   *N* listings, read the timestamp of the newest and the oldest, and compute
   `new/day ≈ N / span_in_days`. This is the best single-request estimate available.
   ⚠️ **Filter out promoted/bumped listings first.** On Bazos, topped ads carry a `from` value
   equal to the request timestamp (`HIDDEN_API.md` §4.3), which would make the
   span look near-zero and the rate near-infinite. Assume every marketplace has this problem
   until you check.
2. **A known expiry window, if the ToS states one** — then `active / expiry_days` is legitimate,
   as it is for Bazos. Quote the clause.
3. **Two-sample id diff** — same query 24h apart, count ids in the second sample absent from the
   first. Only 2 requests and by far the most accurate. ⚠️ **But it needs 24h of wall-clock time,
   which a single research session does not have.** If you cannot span the gap, say so and use
   method 1; do not fake it by comparing two requests minutes apart.
4. **Nothing usable** — if timestamps are not exposed and no expiry is stated, record
   "new/day: not determinable within budget" and rank the candidate on active listings alone.
   That is an acceptable outcome; an invented rate is not.

Record the numbers for the categories this project actually cares about, not just the site
total. Bazos comparison points, live-measured 2026-07-29:

| Scope | Active listings |
|---|---|
| All of bazos.cz | 1,524,012 |
| notebook | 7,973 |
| iphone | 6,943 |
| naradi (tools) | 7,634 |

**A candidate one or two orders of magnitude below these in the target categories is not worth
building**, however elegant its API. Say so and move on. `MONETIZATION.md` §4.7 is the worked
example of killing an idea on measured volume — Bazos `Práce/Administrativa` turned out to have
70 total active listings, ~1.2/day, which ended that idea in one table.

---

## 2c. Track B — reference-price sources (a separate, smaller track)

The question this brief nominally asks is "which marketplace next". But §8's own weighting says a
source that closes the **realised-price gap** outranks a bigger one that just adds more asking
prices — and under that framing, two things that are not CZ marketplaces belong in scope:

| Source | Why | Prior work |
|---|---|---|
| **eBay completed/sold listings** | The canonical realised-price feed, and **official** — which converts §6a's legal problem into a signup form rather than a database-right argument | none |
| **Heureka / Zboží.cz** | New/retail price baseline — a *different* signal from both asking and realised prices | `BACKLOG_IDEAS.md` #4, explicitly **unresearched**: "no confirmed endpoint, no confirmed rate limits, nothing" |

**Keep Track B separate from Track A, and rank it separately.** These are not
`MarketplaceScraper` implementations: they never produce `Ad` rows, so §5's schema-fit checklist
does not apply to them at all — they would populate a new baseline/reference table. Scoring them
in one list against sites you would scrape for listings is apples-to-oranges and produces a
recommendation nobody can act on.

**Budget: ≤ 15 requests each, and only after Track A's Pass 1 is complete.** Use a cut-down file
(§1 verdict, §2 what data it exposes and how far back, §3 legal/ToS, §4 transport, plus the two
questions below). Skip §5 entirely; answer §6 only as "what would this unlock".

Two things to assess that are specific to this track:

1. ⚠️ **Verify eBay's completed-listings access actually still exists publicly.** It has been
   restricted in the past and may require an approved application, a partner tier, or may be gone
   from the public API entirely. **Do not assume it is available because it once was** — find the
   current endpoint, its access tier, and its terms, or record that you could not.
2. ⚠️ **The hard part is identification, not pricing.** `BACKLOG_IDEAS.md` #4 makes this point and
   it is the reason that idea has never moved: a free-text title like
   `"Macbook Pro 13 2020 i5 16GB"` has to resolve to a canonical product before any reference
   price means anything. **A price feed the project cannot join to is worth nothing.** So assess
   the *join*, not just the feed: does the source expose stable product ids, EANs/GTINs, or a
   search-by-free-text endpoint good enough to match on? If the answer is "you would need an LLM
   extraction step per ad", say so and cost it — that is a different project.

Also note the scope limit honestly: **eBay is not Czech.** Its realised prices transfer well for
globally fungible goods — phones, laptops, GPUs — and poorly for furniture, tools and bikes,
where local supply and collection distance dominate. Say which categories it would and would not
serve rather than treating it as a general baseline.

---

## 3. Phase 2 — the legal gate

Read [`MONETIZATION.md`](../../MONETIZATION.md) §6 in full before this phase. It is the
constraint that shapes everything, and the analysis there transfers directly.

For each surviving candidate, record **verbatim quotes**, not summaries:

### 3a. Terms of service
Look specifically for: an API-use clause (Bazos requires written consent), a prohibition on
unofficial apps displaying listings, and any anti-scraping/automation language. Quote the
original Czech.

### 3b. `robots.txt`
Fetch it and record it in full. Note which of the paths you'd actually need are disallowed.
Bazos's is instructive — it disallows exactly the search/filter endpoints the project depends
on, and explicitly blocks `trovitBot` and `pricebot`, i.e. aggregators.

### 3c. The distinction that decides viability
`MONETIZATION.md` §3 sorts every use by one line: **does the data stay with you, or go to a
third party?** Private deal-hunting is a different legal posture from anything public
(*Innoweb v Wegener*, C-202/12, on the sui generis database right). The current operating
posture is **private use**. Assess each candidate against that posture, and note separately if
a candidate would be *unusually* risky even privately.

### 3d. Special case — Facebook Marketplace
Do not spend meaningful time here without flagging it first. Meta's ToS, aggressive anti-bot,
and account-ban risk make it categorically different from the others. A short "assessed,
recommend against, here's why" file is the right output unless you find something surprising.

### 3e. GDPR surface
Note what personal data each marketplace exposes per listing (names, phone numbers, profile
links, precise location). More exposed PII is a *cost*, not a feature — see `MONETIZATION.md`
§6.5 and the retention rule in §6.1. A marketplace exposing full seller names and phone numbers
by default creates an Art 14 obligation the current Bazos setup partly dodges by only ever
seeing opaque ids.

---

## 4. Phase 3 — transport discovery

For each surviving candidate, answer: **what is the cheapest, most stable way to get structured
listing data?** Work down this list and stop when you find something solid.

### 4a. An official/public API
Check for developer docs, a partner programme, an affiliate feed. Seznam (Sbazar's owner) and
Aukro are both large enough that this is worth five minutes. An official API with terms you can
comply with beats everything else on this list — it converts the whole legal problem into a
signup form.

### 4b. Web-app internals — **start here**, it is the cheapest executable route

⚠️ **You have no browser Network panel.** An earlier draft of this brief called devtools "the
single highest-yield technique and usually your first move", which is useless advice to an agent.
The executable substitutes, in order — all of them plain `curl` + `grep`:

1. **Fetch the search-results HTML and grep it.** Look for `__NEXT_DATA__`
   (`<script id="__NEXT_DATA__" type="application/json">`), `<script type="application/ld+json">`
   (JSON-LD — often carries price, availability and seller in clean structured form, and is
   *intended* to be machine-read), and any inline `window.__` state blob.
2. **Fetch the JS bundles the HTML references and grep those.** Extract `<script src=...>` URLs,
   download them, and grep for `/api/`, `https://`, `graphql`, `v1/`, `v2/`. Minified bundles
   still contain endpoint path literals — this is the highest-yield step available to you and it
   substitutes directly for watching XHR in a Network panel.
3. **Next.js data routes** — if `__NEXT_DATA__` exists, try `/_next/data/<buildId>/<path>.json`;
   `buildId` is inside that blob.
4. **GraphQL** — try `POST /graphql` with a standard introspection query. It is often left
   enabled.
5. **Mobile web** (`m.` subdomain) — frequently a thinner, more parseable surface.
6. **`sitemap.xml` and any RSS/Atom feed** — both a discovery map and a cheap freshness signal.

If browser automation happens to be available in your environment, use it — but treat it as a
bonus, not the plan. Everything above works without it.

### 4c. A hidden/mobile JSON API — the Bazos playbook, and its real cost

This is how [`HIDDEN_API.md`](../bazos-api/HIDDEN_API.md)
came to exist: decompile the official Android app, grep for base URLs, endpoints, and the
`User-Agent` construction (see [`USER_AGENT.md`](../bazos-api/USER_AGENT.md)),
then probe live with `curl`.

⚠️ **Time-box this to a third of the site's Pass-2 budget, and abandon it if the APK does not
come down cleanly.** Three frictions, all verified in this environment on 2026-08-22:

- **`jadx` and `apktool` are not installed.** `unzip`, `strings` and `curl` are.
- **APK mirrors gate downloads behind browser flows.** APKMirror and APKPure generally will not
  serve a plain `curl`. If you cannot fetch an APK in two or three attempts, stop.
- **`bazos_app_decomplied/` is NOT a worked example you can read.** It exists on the original
  author's machine but is gitignored (`.gitignore:77`), so it is absent from any clone. Do not
  plan on studying it.

**Cheap fallback that usually works without a decompiler:** an APK is a zip.

```bash
unzip -o app.apk -d apk_extracted
strings apk_extracted/classes*.dex | grep -Eo 'https?://[a-zA-Z0-9./_-]+' | sort -u | head -50
strings apk_extracted/classes*.dex | grep -E '/api/|/v[0-9]+/' | sort -u | head -50
```

That recovers base URLs and endpoint path literals — usually enough to start probing — without
`jadx`. Full decompilation only earns its cost if you need to reconstruct request *signing* or a
non-obvious header scheme.

**If §4b already produced a working JSON endpoint, skip this section entirely.** The APK route is
the fallback for sites whose web app gives nothing up, not a rite of passage.

### 4d. Existing libraries
Check PyPI/GitHub for an existing client, as `vinted-scraper` was for Vinted. **If you find one,
you must run it** — install it in a throwaway venv and probe it live. Do not trust its README.
`VINTED_SCRAPER.md` §4.5–§4.6 exists entirely because a README was believed.

### 4e. HTML scraping as the fallback
Viable (it is what the production Bazos scraper still does), but note the maintenance cost: that
scraper depends on hardcoded CSS class names, and the P19 canary exists specifically because a
class rename would silently zero the deal flow.

### 4f. For whatever you find, characterise
- **Auth**: none / cookie bootstrap / token / account required. An account requirement is a
  major negative — it makes bans personal and ties activity to an identity.
- **Anti-bot**: Cloudflare, DataDome, PerimeterX, hCaptcha? (Vinted has Cloudflare + DataDome;
  the cookie bootstrap intermittently fails because of it.)
- **Rate limits**: what happens at 5 rapid requests? Record status codes. Do not push further.
- **Blocking shape**: what does a block look like — 403? 429? A challenge page? Bazos's is
  403-only and path-scoped, not domain-wide.
- **Pagination**: parameter, page size, and any server-enforced cap.
- **Ordering**: is newest-first available, and is it a parameter or the default? **This is
  load-bearing** — see §5b.
- **Payload size** per request, in KB. Latency and ban-risk math in
  [`PROXY_ROTATION.md`](../proxies/PROXY_ROTATION.md) §4–§5 is
  driven by this.

---

## 5. Phase 4 — fit against the current schema

**Read `bazos/models.py` before writing this section.** Do not work from this brief's summary of
it; the schema changed materially in the last week.

### 5a. What the schema now looks like

The relevant recent history, because it determines what "fit" means:

- **`Ad` / `AdDelivery` are split** (migrations `0026`–`0028`). `Ad` holds scraped *facts* and is
  globally unique on `(marketplace, external_id)`. `AdDelivery` holds per-`(ad, query)` pipeline
  state (`status`, `filter_reason`, `sent_at`, `send_attempts`). A new scraper yields plain `Ad`
  objects; `BazosQueryRunner` owns persistence and delivery creation.
- **`Ad.external_id` is now `BigIntegerField`**, widened for Vinted's ~9.7-billion ids.
- **`Ad.view_count` and `Ad.publish_date` are now nullable**, with help_text saying
  *"never synthesise a value here."* Respect that — see §5c.
- **`Query.extra_params`** (JSONField) carries marketplace-specific search params.

### 5b. The fit checklist

Answer each explicitly, with the marketplace's real field names:

1. **`external_id` — is the id an integer?** The column is `BigIntegerField` and there is a
   `UniqueConstraint(fields=("marketplace", "external_id"))`. **A marketplace using string,
   slug, or UUID ids does not fit today** and forces a schema decision. Say so loudly if you
   find one; it is the most likely hard blocker.
2. **Column widths.** `name` 120, `price_raw` 30, `location` 128, `short_description` 300,
   `publisher_name` 100, `url` 1024. Do the marketplace's real values fit? Postgres raises
   `DataError` on overflow — and **SQLite does not**, so the test suite will not catch it.
3. **Price shape.** `price_raw` is a string, and `parse_price` in `bazos/filters.py` does
   `re.sub(r"\D", "", ...)`. A decimal price string silently parses 10× too large. Does this
   marketplace have decimals, multiple currencies, price ranges, "make offer" placeholders,
   or auction bid-vs-buy-now (§5d)?
4. **Newest-first ordering.** `BazosQueryRunner.run_existing_query` walks results newest→oldest
   and **breaks on the first already-known non-topped ad**. If the marketplace cannot guarantee
   that ordering, the dedup walk is wrong. Vinted needed an explicit `order=newest_first`.
5. **A "topped"/promoted concept?** `Ad.topped` exists because promoted ads appear out of
   chronological order and must be skipped rather than breaking the walk.
6. **Publisher identity.** `EmailPublisher`/`PhonePublisher` are **Bazos-shaped**: opaque
   `bazos_id` integers, with `SellerAdCounts` walking the email↔phone graph transitively. A
   marketplace with real seller *accounts* (a stable user id, a shop page, ratings) does not fit
   this model — it is arguably a *better* model, but it needs new columns or a new table. Say
   which, and sketch it. Note Vinted hit exactly this and the decision was deferred.
7. **`publish_date` / `view_count` availability.** Null is fine and correct if absent.
8. **Detail-fetch cost.** Does the listing response carry the description, or does it need a
   second request per ad (`load_full_description`)? What is the failure mode when an item is
   sold/deleted between listing and detail? Vinted raises `RuntimeError` there, and uncaught it
   truncates a whole query's pass.
9. **Blacklist/blocking probe.** What should `check_blacklisted()` do? (Signature takes no
   arguments.)
10. **Filter-rule compatibility.** The shipped rules are in `bazos/filters.py`. Which apply?
    `publisher_blocklist` needs publisher FKs; keyword rules match on
    `f"{ad.name} {ad.short_description}"`, so an empty `short_description` weakens them.

### 5c. State required changes as a migration plan
If the marketplace needs schema changes, list them as concrete migration steps, and flag any
that are **additive vs. breaking** for the existing two marketplaces. Additive nullable columns
are cheap; anything that changes `external_id`'s type or the unique constraint is not.

---

## 6. Phase 5 — what NEW workflows does this marketplace unlock?

**This is the part most likely to produce something genuinely valuable, and the part a
1:1-with-Bazos mindset would miss.** The `MarketplaceScraper` protocol is a floor, not a ceiling
— a marketplace worth building may be worth building *because* it does something Bazos cannot.

### 6a. The big one — realised prices

`MONETIZATION.md` §7.2c calls this **"the single biggest gap"** in the whole project:

> You have asking prices, never realized prices. […] Every valuation or deal-scoring product
> needs to know what things actually *sold* for.

The current best available proxy is time-to-delisting plus last-seen price. **An auction site
publishes the actual closing price.** If Aukro (or any candidate) exposes completed-auction
results, that is a qualitatively different dataset from anything Bazos can produce, and it would
feed directly into:

- `PriceAnomalyRule` (`PROMPTS.md` P23), which currently has to baseline against asking prices
- the price-index / valuation ideas (`MONETIZATION.md` §4.1b, §4.6)
- calibrating any deal-scoring threshold at all (`BACKLOG_IDEAS.md` #9)

⚠️ **Do not write this section in isolation from §3 — for auction sites the prize and the legal
risk sit on the same asset.** A historical completed-results archive is a much clearer instance of
"a database in which the maker made a substantial investment" than a live listing feed is, so
extracting a substantial part of it is more exposed under the sui generis right
(`MONETIZATION.md` §6.4, *Innoweb v Wegener*), not less. It is also the asset an operator is most
likely to consider proprietary, since it is the part that cannot be re-derived from the live site.

So assess the two together and say so explicitly in the file: **realised prices are the highest
upside in this brief *and* the highest legal exposure.** Scoring a candidate on upside alone
would be the single easiest way to produce a recommendation that cannot actually be acted on.
Note that the current posture is private use (§3c), which is the most defensible footing this
would ever have — and that any future public use of such an archive is a different question with
a much worse answer.

**Investigate this specifically and in depth.** How far back does completed-auction history go?
Is it queryable by category? Is it behind auth? Even if the *live* listing scraper is
unremarkable, a historical realised-price feed could justify the marketplace on its own.

### 6b. Other capabilities worth checking

- **Seller reputation / ratings** — feeds the scam/dealer detection in
  `DISCOVERY_PIPELINE.md` §3.
- **Structured item attributes** (brand, model, condition, size) instead of free text — this
  largely solves the product-identification problem that `BACKLOG_IDEAS.md` #4 calls "the hard
  part", and could make external price cross-referencing viable.
- **Real timestamps at second resolution** — `BACKLOG_IDEAS.md` #6 (posting-time density) is
  blocked on exactly this.
- **Push/webhook/feed** for new listings — would make the whole polling-latency problem
  (`MONETIZATION.md` §7.1) disappear for that marketplace.
- **Watchlists / saved searches** exposed via API.
- **Delisting signal** — does the API distinguish "sold" from "withdrawn"? Bazos cannot; that
  distinction is worth a lot (`PROMPTS.md` P24).
- **Buyer-side data** — bid counts, watcher counts, view counts as demand signals.

For each capability found, say **what feature it would unlock and which existing doc it
connects to.** A capability with no consumer is a curiosity, not a reason to build.

---

## 7. Per-marketplace file template

⚠️ **§5a of this template is the single most important thing you produce.** It is what a
follow-up implementation spec consumes directly — `VINTED_SCRAPER.md` §4.4 is literally
titled "The field mapping — exact" — and it is precisely what went wrong last time, when a
mapping table was filled in from a library README instead of from a response. **Every cell in
that table must be a value you saw in a real response.** If you did not see it, write
"NOT OBSERVED", not a plausible guess.


```markdown
# <Marketplace> — feasibility assessment

> Status: assessed <date>. Verdict: VIABLE / DEFER / REJECT.
> All claims measured unless marked ⚠️ ASSUMED.

## 1. Verdict and why (3-5 sentences, lead with the conclusion)
   VIABLE = could be built and is worth building. DEFER = plausible, blocked on something named.
   REJECT = do not build, with the reason.
   ⚠️ **Do not write "BUILD" in a per-marketplace file.** Choosing which one to build is
   RECOMMENDATION.md's job, and several files marked BUILD would contradict it.
## 2. Scale — measured
   Active listings total + per target category; new/day and how derived.
## 3. Legal — ToS quotes, robots.txt, verdict against docs/MONETIZATION.md §3's posture
## 4. Transport — what you found, how, with the exact probe commands
   Auth, anti-bot, rate limits, blocking shape, pagination, ordering, payload size.
## 5. Schema fit
   ### 5a. Field mapping — MANDATORY, and every value must be one you actually saw
   | `Ad` column | Marketplace field | Measured example value | Notes |
   |---|---|---|---|
   | external_id | | | fits BigInteger? |
   | name | | | ≤120 chars? |
   | price_raw | | | decimals? currency? |
   | url | | | |
   | location | | | ≤128? |
   | short_description | | | present in listing, or detail-only? |
   | publish_date | | | null if absent — never synthesise |
   | view_count | | | null if absent |
   | topped | | | promoted/bumped equivalent? |
   | publisher_name | | | ≤100? |
   (one row per column; write "— absent" where the marketplace has no equivalent)
   ### 5b. The §5b checklist, answered
   ### 5c. Required migrations, additive vs breaking
## 6. New workflows unlocked — §6, with the doc each connects to
## 7. Effort estimate — S/M/L, and what the risky part is
## 8. Raw probe log — commands and trimmed responses, reproducible
## 9. Open questions / what you could not determine
```

---

## 8. Deliverable: the ranked recommendation

`RECOMMENDATION.md`. **Two ranked lists, not one** — Track A (marketplaces to
scrape) and Track B (reference-price sources, §2c). Name **one from Track A to build first** and
defend it. For Track B, either name one or say explicitly that it is premature — "not yet, and
here is the condition that would change that" is a legitimate and useful answer.

Rank on **value ÷ effort ÷ risk**. Weigh:

- Scale in the *target* categories, not overall
- Legal posture
- Transport stability (official API > hidden API > HTML)
- Schema fit (additive changes cheap; `external_id` type changes expensive)
- **New capability** — a marketplace that closes the realised-price gap outranks a bigger one
  that just adds more asking prices
- Concentration-risk value: `MONETIZATION.md` §7.4 notes the whole project rests on one
  marketplace, one ToS clause, and one sole trader who could end it in an afternoon

Include the cheap option honestly: **`bazos.sk` / `.at` / `.pl` are the same hidden API on a
different base URL** (`HIDDEN_API.md` §6 — "multi-country/multi-marketplace for
free", confirmed live on `.sk`). Near-zero engineering. But note it adds *little* diversification
— same operator, same ToS, same single point of failure — so it is cheap breadth, not a hedge.
Say which of those the project actually needs.

---

## 9. Anti-goals — do not do these

- **Do not write any implementation code.** No scrapers, no models, no migrations. If you find
  yourself designing a class, you have overshot — that is a follow-up spec, and this repo has a
  house style for those (see `VINTED_SCRAPER.md`).
- **Do not run a bulk crawl.** Characterise with a handful of requests.
- **Do not rotate IPs or evade blocks during research.** A block is a finding to record.
- **Do not create accounts, log in, or accept ToS on the user's behalf.** If a marketplace
  requires an account to see listings, record that as a finding and stop.
- **Do not harvest personal data.** You will see seller names and phone numbers; do not collect
  them into files. One redacted example is enough to characterise a field.
- **Do not assert anything you did not measure.** Mark it ⚠️ ASSUMED or leave it out.
- **Do not recommend building more than one.** The point is to pick the next one.

---

## 10. Required reading before you start

In this order:

1. [`CLAUDE.md`](../../../CLAUDE.md) — architecture, the pipeline, the "Adding a marketplace"
   coding pattern
2. `bazos/models.py` — the actual schema, especially `Ad`, `AdDelivery`, `Query`, the publisher
   models and `SellerAdCounts`
3. `bazos/scraping/marketplace.py` — the `MarketplaceScraper` protocol (four members)
4. [`MONETIZATION.md`](../../MONETIZATION.md) §3, §6, §7.1–§7.4 — the legal frame and what the
   project is actually for
5. [`HIDDEN_API.md`](../bazos-api/HIDDEN_API.md) — the
   methodology and quality bar to match
6. [`VINTED_SCRAPER.md`](../../archive/shipped/VINTED_SCRAPER.md) §2 and §4.5–§4.6 —
   the concrete traps a second marketplace actually hit, and what they cost
