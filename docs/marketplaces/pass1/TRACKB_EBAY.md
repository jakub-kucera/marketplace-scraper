---
title: eBay sold/completed listings — Track B assessment
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# eBay sold/completed listings — Track B assessment

> Assessed **2026-08-22**. Requests used **15/15** (budget exhausted — see §8 and §9).
> Verdict: **DEFER** — and read §1 before treating that as "come back later".
>
> Written against `RESEARCH_BRIEF.md` §2c (Track B), §6a (realised prices), §9 (anti-goals).
> Per §9: **no eBay account was created, no developer app registered, no ToS accepted, no login.**
>
> **Vantage point (first-hand measured):** egress `194.212.162.35`,
> `194-212-162-35.customers.tmcz.cz`, **AS13036 T-Mobile Czech Republic**, Velký Luh CZ — a
> *residential* ISP, deliberately different from the M247 datacenter IP that blocked three Track A
> candidates (`RANKING.md` §3). **The residential vantage point did not help.** See §8 probe 2.

---

## 0. Evidence classes used in this file — read this first

This assessment did **not** achieve the evidence standard of `BAZOS_HIDDEN_API_RESEARCH.md`, and
saying so up front is more useful than dressing it up. `developer.ebay.com` returned **HTTP 403
domain-wide, including `/robots.txt`**, to every first-hand request from this machine. Three
distinct claim classes appear below and each is tagged inline:

| Tag | Meaning | Trust |
|---|---|---|
| **[M]** | **Measured first-hand.** A `curl` I ran, with the command in §8. | Full |
| **[X]** | **Search-index retrieval.** Text attributed to a named official `developer.ebay.com` doc URL, obtained through the search channel because the page itself would not serve me. I never rendered the page. | Medium — see caveat |
| **[V]** | **Third-party / vendor source.** | Low — see caveat |

⚠️ **The [X] caveat is real and you must carry it forward.** These strings are attributed to
official eBay doc URLs but I did not fetch those URLs. A search summariser can paraphrase, compress
or merge sources. **Do not paste any [X] string into an implementation spec as a verbatim quote.**
This is exactly the `STAGE8_VINTED_DESIGN.md` failure mode the brief opens by warning about —
except this time the gap is labelled rather than hidden.

⚠️ **The [V] caveat is sharper than usual.** One recurring third-party source in the search results
was `sold-comps.com`, a **commercial vendor selling an eBay-sold-data product**. It has a direct
financial interest in asserting that eBay's official channel is closed. Its claims are recorded
below only where an independent [X] source agrees; nothing rests on it alone.

**Mitigating factor.** The central finding (§2) was returned by **two independently-worded searches
run at different times**, is attributed to two *different* official doc pages, and is internally
consistent with a separately-attested public event (the Finding API decommissioning). That is not
first-hand measurement, but it is not a single unsupported snippet either.

---

## 1. Verdict — can a non-partner get sold prices today?

**No. Not through any official eBay API.** [X]

The chain is short and each link is independently attested:

1. **The historic public route is gone.** `findCompletedItems` (Finding API) — the endpoint every
   "eBay sold prices" tutorial written before 2021 uses — was **deprecated 2020-10** and the
   Finding API was **decommissioned 2025-02-05**. [X][V] The brief's §2c caveat ("it has been
   restricted before and may require an approved application… **do not assume it is available
   because it once was**") was correct, and this is the specific thing it was warning about.
2. **The open-tier replacement does not carry the data.** The **Browse API** returns *active*
   listings only; sold/completed data is explicitly described as restricted and reachable only
   through a restricted API. [X]
3. **The one official sold-data surface is invitation-gated.** The **Marketplace Insights API**
   (`buy/marketplace-insights`, `item_sales/search`) is the single official source of eBay sold
   history. It is a **Limited Release** API, and eBay's own documentation states it is
   **"restricted and not open to new users at this time."** [X]

So the brief's framing — that eBay "converts §6a's legal problem into a signup form" — **does not
hold.** There is no signup form. There is an invitation, a business-case review, and a signed
contract, for an API whose docs say it is not taking new users at all (§2).

**Why DEFER rather than REJECT.** The `RANKING.md` §2 precedent applies: Aukro was DEFERred rather
than REJECTed because zero bytes were retrieved from a blocked vantage point, and
*"not determinable"* is not the same statement as *"does not exist"*. The same discipline binds
here — I could not render a single official eBay page (§8). REJECT is a verdict that should rest on
first-hand evidence, and mine does not.

**But do not read DEFER as encouragement.** Unlike Aukro, the blocker here is not the vantage
point — it is a **documented programme gate that the 403 does not conceal and that this project
cannot influence from its side**. Two independent conditions would both have to change:

- **Condition A (eBay-side, outside your control):** eBay reopens Marketplace Insights to new
  applicants, *and* grants a hobby deal-hunting tool a Limited Release contract. A private
  arbitrage tool is close to the weakest possible business case for an access tier whose stated
  purpose is "developers/applications that provide the most value to eBay". [X]
- **Condition B (your side, and it is a different project):** the join in §4 gets solved.

**Even granting both, eBay would serve at most half the target categories** (§5) — and *not* the
one Track A measured as the single biggest opportunity.

**Recommended action: none. Do not spend further budget here.** If the realised-price gap
(`MONETIZATION.md` §7.2c) is the goal, the cheap in-house proxy already documented — *time-to-
delisting + last-seen price* via the bulk `ad_id[]=` refresh and the HTTP 410 signal
(`BAZOS_HIDDEN_API_RESEARCH.md`) — remains the best available route, is legally on the project's
existing footing, needs no third party's permission, and is already scoped in that same §7.2c.

---

## 2. Which API surface, which access tier — with doc URLs

⚠️ **Every row is [X].** The URLs are the official pages the strings are attributed to; all of them
403'd when I tried to fetch them myself (§8).

| Surface | Sold prices? | Access tier | Doc URL |
|---|---|---|---|
| **Marketplace Insights API** (`item_sales/search`) | **Yes — the only official source** | **Limited Release. "restricted and not open to new users at this time."** | `https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html` · `.../resources/item_sales/methods/search` |
| **Browse API** (`item_summary/search`) | **No — active listings only** | Open / keyset on signup ⚠️ ASSUMED tier name | `https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search` |
| **Finding API** (`findCompletedItems`) | Formerly yes | **Decommissioned 2025-02-05** (deprecated 2020-10) | `https://developer.ebay.com/develop/get-started/api-deprecation-status` |
| **Feed API** (`getItemFeed`) | NOT DETERMINED | NOT DETERMINED — appeared in results, never examined | `https://developer.ebay.com/api-docs/buy/feed/resources/item/methods/getItemFeed` |
| **Catalog API** (`product_summary/search`) | No (catalog, not transactions) | NOT DETERMINED | `https://developer.ebay.com/api-docs/commerce/catalog/resources/product_summary/methods/search` |

### 2.1 What "Limited Release" means, in eBay's own framing

[X] — attributed to `https://developer.ebay.com/api-docs/static/versioning.html` and
`.../gs_understand-the-ebay-apis.html`:

> Limited Release APIs are restricted to developers/applications that provide the most value to
> eBay, eBay buyers and sellers, and the eBay developer community, with access contingent upon
> **invitation from eBay and/or a rigorous business case review and signed contracts.**

And the access process [X], attributed to
`https://developer.ebay.com/api-docs/static/gs_use-the-application-growth.html`:

> …you must request an **application growth check** if you want to use restricted APIs in
> Production. […] file a support ticket via your developer account with your use case and the APIs
> you would like to use, […] and **you will be asked to present the end-to-end flow of your
> application in Sandbox.**

Three things follow, and they are the crux of Q1:

- **This is not "keyset on signup".** It is not even "apply and wait". It is *invitation and/or
  business-case review and signed contracts*, gated behind a support ticket, a stated user base,
  and a **live Sandbox demo of a working end-to-end application**.
- **It is circular for this project.** You must demonstrate a working application in Sandbox to be
  granted the API the application needs. You would build the whole integration on speculation.
- **"Not open to new users at this time" supersedes all of it.** Even a perfect business case has
  no queue to join, per the doc's own words. [X]

⚠️ **NOT DETERMINED:** whether Sandbox exposes Marketplace Insights with synthetic sold data,
which would at least allow schema discovery without an access grant. Worth exactly one probe if
this is ever revisited — but note that reaching Sandbox at all requires a developer account, which
§9 forbids and which I did not create.

---

## 3. Geographic scope and history depth

| Question | Answer | Class |
|---|---|---|
| How far back does sold history go? | **90 days** ("returning the last 90 days") | [X][V] — corroborated across two sources |
| Queryable by free-text keyword? | Yes — a `q` parameter exists | [X] |
| ⚠️ `q` length limit | **Search strings over 100 characters in `q` are automatically truncated** | [X] |
| Queryable by category? | ⚠️ ASSUMED yes — the Buy-API family shares `category_ids`; **not verified for this API** | ⚠️ |
| Date filter | A `lastSoldDate` filter is referenced | [X] |
| **Which marketplaces (EBAY_DE / EBAY_GB / EU)?** | **NOT DETERMINED** | — |

### 3.1 The marketplace-coverage question is unresolved and it matters

The authoritative page is **`https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html`**
("Buy API Support by Marketplace"). I tried to fetch it directly and got a **403** (§8, probe 4);
a targeted search against it returned the URL but no usable content.

**Do not fill this gap from memory.** Buy-API marketplace support is per-API and has changed
repeatedly, and Marketplace Insights being a Limited Release API makes a narrower footprint than
Browse's entirely plausible. If eBay's sold data were **EBAY_US-only**, its value to a Czech-facing
project drops sharply — Czech resale prices track **eBay.de** and local EU supply far more closely
than they track US completed sales, before you even reach currency, VAT, import duty and shipping.

**This single unknown is load-bearing for any future revisit.** ⚠️ **ASSUMED, and flagged as the
thing to check first:** even in the best case, eBay.de realised prices are a *European retail-ish
reference*, not a Czech one — see §5.

### 3.2 90 days is a real limitation for this project's actual thesis

`MONETIZATION.md` §7.3 argues the compounding asset is a **24-month** price and velocity history.
A 90-day rolling window is a *spot* reference, not an archive — you would have to poll and
accumulate it yourself to build history, which multiplies both the call volume and the §6 retention
exposure. The API does not hand you a back-catalogue; it hands you a trailing quarter.

---

## 4. ⭐ The join problem — and where it actually lives

**The join is the harder of the two questions, and the decisive finding is that the blocker is not
on eBay's side.** [M]

### 4.1 eBay's half — probably fine, but unverified

[X] eBay maintains real product identifiers: **ePID** (eBay catalog product id, returned as
`productSummaries.epid` by the Catalog API), plus **GTIN / EAN / UPC / MPN**, which appear across
`slr:Product` (Inventory API) and `ProductListingDetailsType` (Trading API).

⚠️ **NOT DETERMINED — and this is a genuine gap:** whether the Marketplace Insights response type
(`sal:ItemSales` / `ItemSale`) carries `epid` / `gtin` / `mpn` **on a sold item**. I attempted the
type-definition page and could not retrieve it. **Do not assume the sold-item payload mirrors the
Browse item payload** — that is precisely the "asserted a field mapping from a README" error the
brief opens by naming. It is plausible [⚠️ ASSUMED] but unmeasured.

⚠️ Also unmeasured: **what fraction of relevant sold listings actually carries a structured id.**
Used consumer-electronics listings on eBay are largely seller-authored free text; catalog matching
is strong for new/boxed goods and weak for exactly the used, damaged, incomplete items this project
hunts. No number is offered because none was measured.

### 4.2 This project's half — the actual blocker, and it is measured

`bazos/models.py`, `Ad` — every identity-bearing field, read directly:

```
name              = CharField(max_length=120)      # free text
short_description = CharField(max_length=300)      # free text
full_description  = TextField(null=True)           # free text
external_id       = BigIntegerField()              # marketplace-local, meaningless off-site
```

**There is no brand field, no model field, no EAN/GTIN field, no condition field, no structured
attribute of any kind.** [M] The unique constraint is `(marketplace, external_id)` — an identifier
scoped to the *source marketplace*, which by construction cannot join to anything external.

**So the join does not fail on eBay. It fails on Bazos.** Even a perfect eBay feed emitting a clean
ePID on every sold row would have nothing to join *to*. `BACKLOG_IDEAS.md` #4's sentence — *"the
hard part is identification, not pricing"* — is exactly right, and this assessment's only real
contribution to it is confirming which side the hard part sits on. That is also why the gap is
**independent of the access question**: solving Condition A in §1 would leave this untouched.

### 4.3 Is the join solvable without per-ad LLM extraction?

**Partially, for a narrow slice — and `BACKLOG_IDEAS.md` #4 already reached this conclusion
without eBay.** The routes, cheapest first:

| Route | Works for | Fails on | Cost |
|---|---|---|---|
| **Pass the raw title as `q`** | almost nothing | Czech noise tokens (`prodám`, `zánovní`, `TOP stav`, `levně`, `spěchá`) are query poison against a German/US corpus; the 100-char `q` truncation [X] bites a 120-char `name` | ~zero |
| **Regex/keyword extraction per category** | Apple hardware, GPUs — standardised model strings | brittle, hand-maintained per product line; near-useless for tools/bikes/furniture | days per category |
| **LLM extraction per ad** | general | real per-ad cost, new external dependency | see below |

**The honest answer the brief asked for: yes, the general case needs an LLM extraction step per
ad, and that is a separate project.** Naming it plainly:

- **It is a new pipeline stage, not a filter rule.** `LLM_AD_REVIEW_DESIGN.md` §2 and
  `MONETIZATION.md` §4.7 independently reached this conclusion, and the concrete reason is
  recorded: `FILTER_BATCH_SIZE = 50`, so an in-rule LLM call would hold `select_for_update` locks
  across **50 serial round-trips**. [M, from `bazos/const.py:46`]
- **Cost, anchored to this repo's own 2026-07-30 spike rather than to recalled pricing:** that
  spike found a free tier on the order of **~1,500 requests/day** can carry a *filtered* candidate
  stream but **not an unfiltered broad-category one** — cheap rules must run first, LLM sees
  survivors only. (`LLM_AD_REVIEW_DESIGN.md` §2f.) That figure is a **judging** workload;
  extraction is a comparable per-ad shape. ⚠️ **No per-token cost is asserted here** — the repo's
  own doc calls the cost/rate-limit spike unfinished, and inventing a figure would breach §9.
- **It is not a small addition.** It needs new `Ad` columns (extracted brand/model/attributes), a
  new pipeline stage with its own status, an extraction-failure path, a cost cap, and a
  match-confidence threshold — before the first eBay call is made.

**And note the sequencing this produces.** If you build LLM extraction, you unlock
`PriceAnomalyRule` (P23) against *your own* accumulated Bazos history — which needs no external
permission, no partner tier, and no 90-day window. **The extraction step is worth more without
eBay than eBay is worth without the extraction step.** That asymmetry is the single most useful
thing in this file.

---

## 5. Category fit — and why this misses Track A's biggest finding

`RESEARCH_BRIEF.md` §2c requires this to be stated plainly rather than treating eBay as a general
baseline. Applying it to `MONETIZATION.md` §4.2's four target categories:

| Category | Does eBay's realised price transfer to a Czech listing? | Why |
|---|---|---|
| **Phones** | **Yes** | Globally fungible, model-identifiable, shipped internationally. Best case for this whole idea. |
| **Laptops** | **Yes** | Same — though CZ/SK keyboard layout is a real local premium eBay.de prices will not show. |
| **GPUs** (§2c names these explicitly) | **Yes** | The most globally-arbitraged category there is. |
| **Tools** | **No** | Heavy, low value-density, collection-distance dominated. A German sold price for a used angle grinder says nothing about its Czech clearing price. |
| **Bikes** | **No** | Shipping cost approaches item value; frame size, local demand and collection radius dominate. |
| Furniture | **No** | §2c's own example. |

**The decisive line.** Track A measured **Sbazar's tools category at 26,492 active listings —
3.4× Bazos, the single biggest opportunity in the entire study** (`RANKING.md` §1). **eBay serves
that category worst of all.** So even in the best case where §1's Conditions A and B are both
somehow met, eBay would be a reference price for the two categories the project already understands
best, and silent on the one where the newly-measured volume actually is.

⚠️ **ASSUMED** (reasoned, not measured): the phones/laptops transfer is itself *degraded* by
CZ-vs-DE price-level differences, VAT treatment, and shipping. eBay.de realised prices would be an
**upper-bound reference**, not a comparable — usable for spotting gross anomalies (a 40% outlier),
not for the margin arithmetic `BACKLOG_IDEAS.md` #10 wants.

---

## 6. Legal — the terms are the gate, not the database right

The brief's framing is right and worth stating precisely: **for an official API the sui generis
database right (`MONETIZATION.md` §6.4, *Innoweb v Wegener*) is not the operative constraint — the
licence agreement is.** You are not extracting from a database against the maker's will; you are a
licensee, and the licence says what you may keep.

⚠️ **Everything in this section is [X] and NONE of it is a verified verbatim quote.** I did not
fetch the API License Agreement. The relevant documents, for a future first-hand read:

- `https://developers.ebay.com/join/api-license-agreement`
- `https://developer.ebay.com/cms/files/api_license_2018-10-26.pdf` (dated 2018 — **stale**; the
  agreement was reportedly updated **June 2025** [V], so the PDF must not be relied on)

Attributed provisions [X], recorded as leads to verify, **not as findings**:

1. **A 30-day destruction obligation.** On termination, when eBay Data is no longer required, on
   eBay's written request, or when retention exceeds industry best practice, eBay Data must be
   removed and destroyed **within 30 days**, with media sanitised and written certification on
   request.
2. **A storage restriction.** You may not "sell, rent, trade, distribute, lease, copy, **store** or
   modify eBay Content" other than for purposes the agreement allows.
3. **Caching is nonetheless encouraged** for call efficiency, per
   `https://developer.ebay.com/api-docs/static/gs_follow-best-practices.html`.
4. **An AI-training restriction was reportedly added in 2025** [V — trade press,
   `ecommercebytes.com`, **unverified**].

**If (1) and (2) are anywhere near accurate, they are close to fatal for the actual use case** — and
notice the shape of the problem. `MONETIZATION.md` §7.3's whole thesis is that **the accumulated
archive is the only compounding asset**. A termination-triggered 30-day destruction clause means an
eBay-derived price history is an asset **eBay can require you to delete**, at which point every
model calibrated on it loses its baseline. That is a categorically worse footing than Bazos data,
where the project's exposure is a ToS argument it has already reasoned through and where nobody
holds a contractual delete switch.

**Interaction with §3c's private-use posture.** Private use is the most defensible footing for the
*scraping* question — but a licence agreement **binds regardless of whether the data ever leaves
your machine.** Private use does not soften clause (2). This is one of the few places in the whole
study where "official API" is a *worse* legal posture than scraping, not a better one, and the
brief's §2c premise ("converts the legal problem into a signup form") should be corrected on this
point.

⚠️ `robots.txt` **could not be assessed** — `https://developer.ebay.com/robots.txt` itself returned
403 [M]. Same shape as Aukro (`RANKING.md` §2): a site that blocks the file describing how it wants
to be crawled. Note this is the *developer portal's* robots.txt, not `www.ebay.com`'s, which was
not probed.

---

## 7. What it unlocks, and which docs it connects to

Recorded so the value is visible even though it is not reachable — and so a future revisit does not
have to re-derive it.

| If it worked, it would feed | Doc | Reality check |
|---|---|---|
| `PriceAnomalyRule` — a **realised**-price baseline instead of an asking-price one | `PROMPTS.md` **P23** | P23 already has a workable baseline (own accumulated Bazos history) and is blocked on **P22** (`price_raw` → int), not on eBay. **eBay is not on P23's critical path.** |
| Closing the realised-price gap | `MONETIZATION.md` **§7.2c** | §7.2c already names its own answer: time-to-delisting + last-seen price via bulk `ad_id[]=` + HTTP 410. **Cheaper, in-house, no permission needed.** |
| Calibrating any deal-scoring threshold | `BACKLOG_IDEAS.md` **#9** (`AdOutcome`) | #9 is "the cheapest idea in this document" and needs **your own labelled outcomes**, not eBay's. eBay cannot tell you what *you* should have paid. |
| Reference-price cross-referencing | `BACKLOG_IDEAS.md` **#4** | eBay is a *better* source than #4's Heureka guess (realised, not retail) — but hits the identical identification blocker (§4), which is the reason #4 never moved. |

**The pattern across all four rows is the finding.** Every consumer that eBay would serve either
(a) already has a cheaper in-house answer, or (b) is blocked on something eBay does not fix.
Per the brief's own standard — *"a capability with no consumer is a curiosity, not a reason to
build"* — **eBay has no consumer that is actually waiting on it.**

**Where it would rank on Track B.** Against `BACKLOG_IDEAS.md` #4's Heureka/Zboží.cz candidate:
eBay is the better *signal* (realised beats retail) but the worse *access story* (invitation-gated
vs. merely unresearched), and it is **not Czech**, which Heureka is. Neither is ready. The honest
Track B recommendation is the one `RESEARCH_BRIEF.md` §8 explicitly permits: **"not yet, and here
is the condition that would change that"** — the condition being §4.3's extraction stage, which
should be evaluated on its *internal* merits (P23) first.

---

## 8. Raw probe log

15/15 requests. Reproducible. All timestamps 2026-08-22, egress AS13036 (T-Mobile CZ, residential).

**#1 — egress identification** [M]
```bash
curl -s https://ipinfo.io/json
# -> {"ip":"194.212.162.35","hostname":"194-212-162-35.customers.tmcz.cz",
#     "city":"Velký Luh","country":"CZ","org":"AS13036 T-Mobile Czech Republic a.s.",
#     "timezone":"Europe/Prague"}
```

**#2 — Marketplace Insights overview, plain curl → 403** [M]
```bash
curl -s -D - -o body.html -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/126.0 Safari/537.36' \
  'https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html'
# -> HTTP/2 403
#    server: AkamaiGHost
#    content-length: 1831
#    set-cookie: bm_s=...; bm_so=...   (Akamai Bot Manager)
```
Body is an eBay-branded error page, **not** a challenge page — no captcha, no JS challenge, nothing
to solve:
```html
<title>Error Page | eBay</title> <meta name="robots" content="noindex,nofollow">
SORRY / Something went wrong on our end
<p class="reference-id">0.add72c17.1787411315.55de66b</p>
```
⚠️ Worth noting for anyone re-probing: **the page claims a server-side error, not a block.** The
`AkamaiGHost` server header, the `bm_s`/`bm_so` Bot Manager cookies and the 403 status make it a
bot-management denial. Taking the page's own wording at face value would produce a wrong finding.

**#3, #5, #7 — WebFetch (different fetcher, different egress) → timeout ×3** [M]
```
WebFetch https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html   -> timeout 60s
WebFetch https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html   -> timeout 60s
WebFetch https://developer.ebay.com/api-docs/static/gs_use-the-application-growth.html -> timeout 60s
```
Three of three, two distinct paths. A second, independent network path also fails to render the
docs — so this is **not** an artefact of my curl TLS fingerprint alone.

**#4 — same URL, full browser header set + cookie jar (carrying the Akamai cookies from #2) → still 403** [M]
```bash
curl -s -D - -o body2.html --compressed -b cookies.txt -c cookies.txt \
  -H 'User-Agent: Mozilla/5.0 ... Chrome/126.0.0.0 Safari/537.36' \
  -H 'Accept: text/html,application/xhtml+xml,...' -H 'Accept-Language: en-US,en;q=0.9' \
  -H 'sec-ch-ua: "Chromium";v="126", "Not:A-Brand";v="24"' -H 'sec-ch-ua-platform: "macOS"' \
  -H 'Sec-Fetch-Dest: document' -H 'Sec-Fetch-Mode: navigate' -H 'Sec-Fetch-Site: none' \
  'https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html'
# -> HTTP/2 403, server: AkamaiGHost, 1831 bytes (byte-identical to #2)
```
Realistic headers + a valid Bot Manager cookie change nothing. Per §9, **no further evasion was
attempted.**

**#8–#11 — is the block path-scoped or domain-wide?** [M]
```bash
for u in "https://developer.ebay.com/robots.txt" \
         "https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html"; do
  curl -s -o body.tmp -w 'status=%{http_code} bytes=%{size_download}\n' --compressed -A "$UA" "$u"
done
# -> https://developer.ebay.com/robots.txt                          status=403 bytes=1831
# -> .../buy/static/ref-marketplace-supported.html                  status=403 bytes=1832
```
**Domain-wide, `robots.txt` included.** This is the Aukro shape (`RANKING.md` §2), *not* the Bazos
shape (403 but path-scoped, `MEMORY.md`). **The residential CZ IP did not change the outcome** —
which is a genuinely useful negative result for the rest of the study: `RANKING.md` §3 hypothesised
that the datacenter ASN was the single cause of Track A's blocks. For eBay's developer portal, a
clean residential Czech ISP is blocked just as hard.

**#6, #12, #13, #14, #15 — search channel** [X]
```
#6  WebSearch (site:developer.ebay.com) "Marketplace Insights API limited release access restricted item_sales/search 2026"
#12 WebSearch (site:developer.ebay.com) "Marketplace Insights item_sales search supported marketplaces EBAY_DE EBAY_GB last 90 days lastSoldDate"
#13 WebSearch  "eBay Finding API findCompletedItems decommissioned ... Browse API does not return sold items epid gtin"
#14 WebSearch (site:developer.ebay.com) "Marketplace Insights ItemSale response fields epid gtin mpn lastSoldPrice lastSoldDate ..."
#15 WebSearch  "eBay API License Agreement storing eBay data retention caching prices ..."
```
Yield: §2 (access tier), §3 (90 days, `q` truncation), §4.1 (identifiers), §6 (licence leads).
**#12 and #14 both failed to return the two facts most wanted** — Marketplace Insights' supported
marketplace list, and the `sal:ItemSales` field list. Both are §9 gaps.

**Not probed, deliberately:** `www.ebay.com` and `www.ebay.de` HTML sold-listings pages
(`&LH_Sold=1`). Scraping eBay's consumer web UI is a different legal posture from the official API
this assessment was scoped to, is a well-known anti-bot target, and §2c framed this candidate as
*"official — which converts the legal problem into a signup form"*. Falling back to scraping would
discard the only property that put eBay on the list. **Recording it as out of scope rather than
silently substituting it.**

---

## 9. What I could not determine

Ranked by how much each would change the answer.

1. **Which marketplaces Marketplace Insights covers — EBAY_US only, or EBAY_DE/EBAY_GB too.**
   *The most important gap.* US-only would make it near-useless for a Czech-facing project even if
   access were granted. Authority: `.../buy/static/ref-marketplace-supported.html` — 403'd (§8 #10).
2. **Whether the sold-item payload (`sal:ItemSales`) carries `epid` / `gtin` / `mpn`.** Decides
   whether eBay's half of the join is clean. Attempted via #14, not retrieved. **Do not assume it
   mirrors the Browse item shape.**
3. **The API License Agreement, first-hand and current.** §6's clauses are the difference between
   "constrained" and "unusable", and my only sources are a search summary plus a **2018** PDF
   against a reportedly **June-2025** revision.
4. **Whether "not open to new users" is permanent or a pause.** No date, no queue, no
   reopening signal was found — and the phrase "at this time" is doing unexamined work.
5. **Whether Sandbox exposes Marketplace Insights with synthetic data.** Would allow schema
   discovery without production access — but requires a developer account, which §9 forbids and
   which I did not create.
6. **Rate limits and payload size.** Never reached; meaningless without access.
7. **What fraction of used-electronics sold listings carry a structured identifier.** Unmeasurable
   without access. §4.1 gives no number rather than a plausible one.
8. **Whether a residential IP in another country reaches the docs.** The block is confirmed for
   AS13036 (CZ). Not tested elsewhere; per §9, no rotation was attempted.

**Budget note per `RESEARCH_BRIEF.md` §1:** stopped at exactly 15/15 requests. Gaps 1–3 are the
ones that would most improve this file, and all three are single-fetch questions against known
URLs — **they are blocked on the 403, not on budget.** A vantage point that can render
`developer.ebay.com` would close all three in three requests. That, and not more searching, is the
next action if this is ever revisited.
