---
title: Aukro.cz — Pass 1 scale triage
status: reference
updated: 2026-09-18
verified: 2026-08-22
---

# Aukro.cz — Pass 1 scale triage

> Probed **2026-08-22, 16:48–16:57 CEST (14:48–14:57 UTC)**.
> **Requests used: 4 of the 7 allowed** (5 base + 2 realised-price extras). I stopped at 4 because
> every one returned an identical Cloudflare challenge; a 5th would have added no information.
> Egress: VPN datacenter IP **185.242.6.116, M247 Europe SRL (AS9009), Prague CZ** — verified live
> via `ipinfo.io`. One of the four (r3) went out over Anthropic's `WebFetch` egress instead, i.e. a
> **different network path** — noted inline because it makes the block-shape finding stronger.
> All claims measured unless marked ⚠️ ASSUMED or **[third-party, not measured]**.
>
> **⚠️ Overturned on the facts - read [`AUKRO.md`](../AUKRO.md) before this file.** Everything
> here was reasoned from zero retrieved bytes plus a vendored Allegro WSDL. Re-probed the same day
> from a residential Czech IP, the site served normally, and two of the three inferences below
> were measured **false**: ended auctions *do* expose a public realised price (`biddersCount > 0`
> plus `price.amount`, readable ≥2.75 years back), and both listing and detail carry
> `startingTime`. What survives is the block shape - a domain-wide Cloudflare challenge from a
> datacenter ASN, `robots.txt` included - and the methodology lesson this file paid for: a
> third-party API description is not evidence about the live service.

---

## 1. Headline

**Scale: NOT DETERMINED — I could not retrieve a single byte of content from aukro.cz.** All four
probes, across three different hostnames (`www.aukro.cz`, `api.aukro.cz`, `doc.aukro.cz`) and two
different egress networks, returned **HTTP 403 with `cf-mitigated: challenge`** — a Cloudflare
*managed* bot challenge. Unlike Bazos (whose block is 403-only and **path-scoped**, per this repo's
memory note), Aukro's challenge is **domain-wide and hits `robots.txt` itself**.

**Realised prices: the answer appears to be NO, and this is the finding that matters.** Three
independent lines of evidence converge on "Aukro does not publish a public, login-free, queryable
archive of completed auctions with final prices": (a) the dedicated public archive service
`archiv.aukro.cz` was shut down in 2018 and **its DNS record no longer resolves — measured**;
(b) in the Aukro WebAPI WSDL, *every* method that returns sold/won items is `doGetMy*`, i.e.
scoped to the authenticated caller's own account — there is no search-by-category over finished
items; (c) all consumer-facing completed-transaction views are inside "Moje Aukro" (login).
**Caveat I could not close:** whether an *individual* ended auction's permalink still renders its
final price publicly. That is the one remaining door, and the Cloudflare block prevented me from
testing it. See §4 and §9.

**Pass-1 disposition: do not promote to Pass 2 on current evidence** — the headline capability
that would have justified Aukro looks absent, and the transport is hostile from any datacenter IP.

---

## 2. Active listings — measured

| Scope | Active listings | Source |
|---|---|---|
| All of aukro.cz | **NOT DETERMINED** | all probes 403 |
| notebook / laptop | **NOT DETERMINED** | all probes 403 |
| iphone / mobilní telefony | **NOT DETERMINED** | all probes 403 |
| nářadí (tools) | **NOT DETERMINED** | all probes 403 |
| kolo (bikes) | **NOT DETERMINED** | all probes 403 |

**Zero category counts were measured.** I will not estimate them.

For context only — **[third-party, not measured; vendor marketing figures surfaced via web search,
never verified against the site]**: Aukro is described as carrying *"on average up to 2 million
active listings"*, *"more than 30,000 sold items daily"*, ~6 M transactions/year, ~12 M visits/month.
If the 2 M figure were true it would put Aukro **at or above** the measured Bazos total (~1.5 M).
**Treat this as an unverified hypothesis, not a comparison point.** It is exactly the kind of
recalled/PR number this brief forbids relying on, and it is recorded here only so a Pass 2 knows
the claim exists and needs checking.

Comparison baseline (measured on Bazos today, from the task): notebook 7,849 / iphone 6,586 /
naradi 7,716 / all ~1.5 M.

### The count *would* be cheap if reachable
`doGetItemsListResponse` in the WebAPI WSDL (§5) carries **`itemsCount` (xsd:int)** and
**`itemsFeaturedCount` (xsd:int)** — a total-results count *and* a separate promoted count, in the
search response. So the scale test is a one-request job against a reachable transport. The blocker
is access, not instrumentation.

---

## 3. New/day — method, number, confidence

**NOT DETERMINABLE WITHIN BUDGET.** No listing page was retrieved, so no timestamp span exists to
compute from. §2b method 1 needs a page of listings; method 3 needs 24h of wall clock. Neither was
available.

Two structural findings from the WSDL that a Pass 2 must plan around:

1. **The search-result item carries `endingTime` (xsd:dateTime), not a start/publish time.**
   `ItemsListType` fields are `itemId, itemTitle, leftCount, bidsCount, biddersCount, quantityType,
   endingTime, timeToEnd, categoryId, conditionInfo, promotionInfo, additionalInfo, sellerInfo,
   priceInfo, photosInfo, parametersInfo, advertInfo`. **There is no `startingTime` / `createdAt`
   in the search projection.** So the §2b "timestamp span of a newest-first page" method does not
   transfer directly — you would be measuring when auctions *end*, which is a function of seller-chosen
   durations, not of arrival rate. ⚠️ ASSUMED that no equivalent start field is exposed elsewhere;
   `doShowItemInfoExt` (item detail) was not inspected in this pass.
2. **The promoted-listing trap has a clean escape here**, unlike Bazos. `promotionInfo` is a
   per-item field and `itemsFeaturedCount` is a separate response counter, so promoted items are
   *labelled* rather than silently bumped into the ordering. ⚠️ ASSUMED this maps to the bumped-timestamp
   behaviour; unverified against a live response.

**Auction-specific caveat the task flagged, restated as an open problem:** an auction site's "new/day"
must separate genuinely new auctions from **relists**. The WSDL exposes `doSellSomeAgain` /
`doSellSomeAgainInShop` — relisting is a first-class operation, so relists are certainly a material
fraction of apparent new listings. Nothing in `ItemsListType` distinguishes a relist from an original.
**I could not determine the relist share, and any new/day figure for Aukro that ignores it would be
wrong in an unknown direction.**

---

## 4. ⭐ Completed-auction / realised prices — what is publicly available, measured

**Verdict: no public, login-free, category-queryable realised-price archive found. Confidence:
moderate-to-high on the negative, but note that one specific sub-case is untested.**

### 4.1 The dedicated public archive is gone — partly MEASURED

`archiv.aukro.cz` was a public archive of completed offers. It was **discontinued on 2018-06-29**
*[third-party: Aukro's own newsroom post "Ukončení služby archiv.aukro.cz", surfaced via search;
I did not fetch the post itself — it lives on `novinky.aukro.cz`, an aukro.cz host, and would have
cost budget for a 403]*. Aukro stated the old system was outdated and unstable and that a replacement
was planned.

**MEASURED corroboration:** the hostname no longer exists in DNS.

```
$ dig +short archiv.aukro.cz A     -> (empty)
$ dig +short archive.aukro.cz A    -> (empty)
```

This is meaningful because I **verified there is no DNS wildcard** on the zone — two control names
returned empty while `www`, `api`, `cdn`, `backend`, `doc` all returned records. So an empty result
is a real absence, not a resolver artifact. The dedicated archive host is genuinely retired, and
**no replacement archive hostname exists** under the names I tested.

### 4.2 The official WebAPI exposes realised prices ONLY for your own account — MEASURED (from the WSDL)

I obtained the **Aukro WebAPI WSDL** from a community PHP client
(`github.com/PavelJurasek/AukroApi`, file `wsdl/AukroWebAPIService.xml`, 226,120 bytes) — a
third-party host, so **zero aukro.cz requests**. 129 operations. The full list is in §8.

Every operation that returns **sold / won / finished** items is account-scoped:

| Operation | Scope |
|---|---|
| `doGetMySoldItems` | caller's own sold items |
| `doGetMyWonItems` | caller's own won items |
| `doGetMyNotSoldItems` | caller's own unsold items |
| `doGetMyNotWonItems` | caller's own lost bids |
| `doGetMyBidItems` | caller's own bids |

**There is no operation that searches finished items by category, keyword, or seller.** The
retrieval operations that *do* take a search (`doGetItemsList`, `doGetItemsInfo`,
`doShowItemInfoExt`, `doGetCatsData`) are the live-listing surface. `doFinishItem` / `doFinishItems`
are **write actions** (end your own auction early), not retrieval — easy to misread from the name.

Authentication is mandatory for the `doGetMy*` family: the API has `doLogin`, `doLoginEnc`,
`doLoginWithAccessToken` and threads a session handle through calls. **Per the hard rules I did not
log in, register, or create an account.** The realised-price data therefore sits behind auth, which
is where this line of enquiry stops.

⚠️ **Important provenance caveat, stated plainly:** this WSDL's endpoint is
`location="https://webapi.allegro.pl/service.php"` — it is the **Allegro (Poland) WSDL vendored into
a Czech client library**, reflecting the legacy Allegro-derived WebAPI that Aukro shared. It is
strong evidence about the *shape* of that API family and Aukro published the same `webapi` doc tree
(`doc.aukro.cz/webapi/docs/`), but **it is not proof of what `api.aukro.cz` serves today.** Aukro was
rebuilt after 2016 and `api.aukro.cz` is very likely a modern REST API whose surface I could not
inspect (403). Do not carry these method names into an implementation spec without re-verifying.

### 4.3 Consumer-facing completed views are behind login — [third-party, not measured]

Aukro's own help/affiliate content describes offer data being available in **Moje Aukro for 90 days**,
after which offers move to an archive showing *"pouze základní informace o nabídce"* (only basic
offer information), with detail requiring a contact form. "Moje nákupy" / "Můj prodej" (with a
"Prodáno od–do" date filter) are likewise account sections. **All of this is inside a logged-in
account and describes only the user's own transactions.**

One search-engine summary paraphrased a *"Vyhledat v ukončených aukcích"* ("search in completed
auctions") feature. **I could not corroborate this from any primary source and it did not appear in
the WSDL.** I am recording it as an unverified lead, not a finding — it may be a paraphrase of the
account-scoped history, or of a different site entirely.

### 4.4 How far back does history go?

**NOT DETERMINED.** The only retention figure found is the 90-day Moje Aukro window
*[third-party]*, which is account-scoped, not a public archive depth.

### 4.5 Queryable by category/search term?

**No, on current evidence.** No finished-item search operation exists in the WSDL, and the
category-search operations cover live listings. Reachability per-item is the untested case below.

### 4.6 The one door I could not open — state this as open, not closed

Individual ended-auction **permalinks** may still render publicly with their final price. Aukro item
URLs follow `https://aukro.cz/<slug>-<numeric-id>` — real examples appear in search-engine indexes
(e.g. `aukro.cz/ukoncena-rada-aukci-7000404274`, `aukro.cz/archiv-6949271586`), and the ~10-digit
ids are consistent with the WSDL's `itemId xsd:long`. **If ended items stay public at their
permalink, a realised-price dataset could be assembled per-item** — but that would be a
crawl-every-item pattern, not a query, and it is precisely the "extract a substantial part of a
database" shape that RESEARCH_BRIEF §6a warns carries the *highest* legal exposure under the sui
generis right. **I did not test this** — it needs one successful request, which the Cloudflare
challenge denied. This is the single highest-value follow-up and it is cheap: one item fetch from a
residential IP.

### 4.7 Behind auth or paywall?

Realised prices via the official API: **behind auth** (session login required). Public archive:
**retired**. No paywall observed — but I saw no pricing page either, so "no paywall" is not measured.

---

## 5. Transport signals spotted for free

**From the saved response bodies: nothing — and that is itself the finding.** All three saved bodies
are Cloudflare interstitials. Grepped every body for the §4b signal set:

| Signal | r1 robots.txt | r2 api root | r4 search |
|---|---|---|---|
| `__NEXT_DATA__` | 0 | 0 | 0 |
| `application/ld+json` | 0 | 0 | 0 |
| `window.__` | 0 | 0 | 0 |
| `graphql` | 0 | 0 | 0 |
| `/api/` `/v1/` `/v2/` | 0 | 0 | 0 |
| `buildId` | 0 | 0 | 0 |

The **only** absolute URL present in any of the three bodies is `https://challenges.cloudflare.com`.
No origin JS bundle URL was exposed, so the §4b step-2 "download the bundles and grep for endpoint
literals" technique has **no entry point** from a blocked IP — the challenge page references no
first-party scripts.

**Signals obtained from free, non-aukro sources instead:**

- **Hosts that really exist** (no wildcard; controls empty): `www`, `api`, `cdn`, `backend`, `doc`.
  `api.aukro.cz` and `backend.aukro.cz` are deliberately configured records — the obvious Pass 2
  targets. `docs`, `archiv`, `archive` do **not** exist.
- **Whole zone is on Cloudflare**: `NS = paul.ns.cloudflare.com / kay.ns.cloudflare.com`; A records
  are Cloudflare anycast (`104.26.2.125`, `104.26.3.125`, `172.67.69.168`). There is **no origin IP
  to reach around the edge**, and finding one is out of scope anyway.
- **An official API programme exists** — `api.aukro.cz` is titled "Aukro API Documentation" and
  `doc.aukro.cz/webapi/docs/documentation.html` hosts WebAPI method docs *[third-party search
  results; both hosts 403'd on direct fetch]*. Per brief §4a an official API "converts the whole
  legal problem into a signup form", so this is the correct Pass 2 entry point — **not** HTML scraping.
- **Integration ecosystem exists** (`conviu.cz`, PowerHub, BizBox advertise Aukro integrations),
  implying a supported partner/seller API with real onboarding.

**Schema-fit previews visible for free** (from the WSDL; all ⚠️ provenance-caveated per §4.2):
`itemId xsd:long` fits `BigIntegerField`; `promotionInfo` is a plausible `topped` analogue;
`parametersInfo` gives **structured attributes** (brand/model/condition), which speaks directly to
`BACKLOG_IDEAS.md` #4's product-identification problem; `bidsCount` / `biddersCount` are demand
signals Bazos cannot produce; `priceInfo` is an **array** of prices (bid vs buy-now), which is a
real hazard for the single `price_raw` string column and `parse_price`'s `re.sub(r"\D","",...)`.

---

## 6. robots.txt — relevant Disallow lines verbatim

**NOT DETERMINED — could not retrieve.** `https://www.aukro.cz/robots.txt` returned **HTTP 403** with
a Cloudflare managed challenge (probe r1, §8). Aukro challenges even its own robots.txt to
non-browser clients from this IP.

I attempted to recover an archived copy from the Wayback Machine (a **third-party** host, costing
zero aukro requests). A snapshot exists — `20260203021405` (2026-02-03) — but every retrieval
attempt returned **HTTP 429 Too Many Requests** from `web.archive.org` (7+ attempts with backoff up
to 45 s), and `WebFetch` reports it cannot fetch `web.archive.org` at all. **So the robots.txt
contents, including whether any archive/completed-auction path is disallowed, are unknown.**

Recovering it is a Pass 2 item and costs one request from an unblocked connection.

---

## 7. Anti-bot observed

**Cloudflare managed challenge, domain-wide. This is the dominant fact about Aukro as a target.**

Measured response headers, consistent across all probes:

```
HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2ad7c0fd7d39a-FRA      (r1)
cf-ray: a2f2b0b35df5c614-FRA      (r2)
cf-ray: a2f2b47aca188e2c-FRA      (r4)
server-timing: chlray;desc="..."
content-type: text/html; charset=UTF-8
```

Body is the `<title>Just a moment...</title>` interstitial with
`window._cf_chl_opt = { ... cType: 'managed', cvId: '3', cZone: 'www.aukro.cz' ... }`.
`cType: 'managed'` = Cloudflare **Managed Challenge**, which requires JS execution and a
cookie round-trip. A plain HTTP client cannot pass it, by design.

Additional fingerprinting surface, measured on the challenge response:

```
accept-ch:   Sec-CH-UA-Bitness, Sec-CH-UA-Arch, Sec-CH-UA-Full-Version, Sec-CH-UA-Mobile,
             Sec-CH-UA-Model, Sec-CH-UA-Platform-Version, Sec-CH-UA-Full-Version-List,
             Sec-CH-UA-Platform, Sec-CH-UA, UA-Bitness, UA-Arch, UA-Full-Version, UA-Mobile,
             UA-Model, UA-Platform-Version, UA-Platform, UA
critical-ch: (same list)
```

Aukro/Cloudflare is demanding the **full Client Hints set** — high-entropy device fingerprinting on
top of the JS challenge.

**Blocking shape — the direct Bazos contrast:**

| | Bazos | Aukro |
|---|---|---|
| Status | 403 only | 403 only |
| Scope | **path-scoped**, not domain-wide | **domain-wide**, incl. `/robots.txt` |
| Mechanism | plain block | Cloudflare Managed Challenge (JS + cookie) |
| Hosts affected | — | `www.aukro.cz`, `api.aukro.cz`, `doc.aukro.cz` |
| 429 observed | none | none |

**Required framing, per the task's environment note:** this was measured from a **datacenter ASN**
(M247 / AS9009), which Cloudflare scores far more harshly than residential space.
⚠️ **This is NOT proven to block a residential connection.** Aukro's pages are clearly indexed by
search engines, so the site is not challenging everything unconditionally — the challenge is
reputation- and fingerprint-driven. Re-testing from a residential IP is the necessary next step
before drawing any conclusion about scrapability.

I did **not** attempt to solve the challenge, spoof a search-engine crawler UA, rotate IPs, or
otherwise evade — per the hard rules, the block is recorded as a finding.

---

## 8. Raw probe log

**4 requests to aukro.cz.** Spaced ~2 s apart minimum. Every body saved to
`<scratchpad>/aukro/`.

### Free reconnaissance first (0 aukro.cz requests)

```
$ curl -s https://ipinfo.io/json
{"ip":"185.242.6.116","city":"Prague","region":"Prague","country":"CZ",
 "loc":"50.0880,14.4208","org":"AS9009 M247 Europe SRL","postal":"110 00",
 "timezone":"Europe/Prague"}
$ date -u '+UTC %Y-%m-%dT%H:%M:%SZ'   ->  UTC 2026-08-22T14:48:04Z
```

```
$ for h in www api api2 mobile m gateway graphql static cdn images sitemap admin be \
           backend service services public-api openapi developers dev partner doc docs \
           archiv archive; do dig +short $h.aukro.cz A; done
www      -> 104.26.3.125 172.67.69.168 104.26.2.125
api      -> 172.67.69.168 104.26.2.125 104.26.3.125
cdn      -> 172.67.69.168 104.26.2.125 104.26.3.125
backend  -> 104.26.3.125 104.26.2.125 172.67.69.168
doc      -> 104.26.2.125 172.67.69.168 104.26.3.125
(all others, including archiv / archive / docs -> empty)

$ dig +short zzqx-nonexistent-test123.aukro.cz A   -> (empty)   # wildcard control
$ dig +short another-bogus-xyz.aukro.cz A          -> (empty)   # wildcard control
$ dig +short aukro.cz NS -> paul.ns.cloudflare.com. kay.ns.cloudflare.com.
```
Conclusion: no wildcard ⇒ empty result = real absence ⇒ `archiv.aukro.cz` is genuinely retired.

Subdomain enumeration via crt.sh and AlienVault OTX both **failed** (crt.sh returned
`502 Bad Gateway`; OTX returned 0 records), so the host list above is from targeted guesses only
and is **not exhaustive**.

```
$ curl -s https://api.github.com/repos/PavelJurasek/AukroApi/git/trees/master?recursive=1
  -> ... wsdl/AukroWebAPIService.xml
$ curl -s -o aukro_wsdl.xml \
   https://raw.githubusercontent.com/PavelJurasek/AukroApi/master/wsdl/AukroWebAPIService.xml
$ wc -c aukro_wsdl.xml   -> 226120
$ grep -oE 'location="[^"]*"' aukro_wsdl.xml | sort -u
   location="https://webapi.allegro.pl/service.php"
```

129 operations (`grep -oE '<operation name="[^"]*"' | sort -u`), abbreviated — sold/won/finished
family shown in full, rest truncated:

```
doGetMySoldItems  doGetMyWonItems  doGetMyNotSoldItems  doGetMyNotWonItems  doGetMyBidItems
doFinishItem  doFinishItems  doSellSomeAgain  doSellSomeAgainInShop  doGetArchiveRefundsList
doGetItemsList  doGetItemsInfo  doShowItemInfoExt  doGetCatsData  doGetCatsDataCount
doLogin  doLoginEnc  doLoginWithAccessToken  doGetSiteJournal  doGetSiteJournalDeals
doBidItem  doGetBidItem2  doShowUser  doGetFeedback  doMyFeedback2 ... (129 total)
```

```
$ python3 -> xsd:element name="doGetItemsListResponse"
   itemsCount            xsd:int
   itemsFeaturedCount    xsd:int
   itemsList             tns:ArrayOfItemslisttype
   categoriesList        tns:CategoriesListType
   filtersList           tns:ArrayOfFilterslisttype
   filtersRejected       tns:ArrayOfString

$ python3 -> xsd:complexType name="ItemsListType"
   itemId xsd:long | itemTitle xsd:string | leftCount xsd:int | bidsCount xsd:int
   biddersCount xsd:int | quantityType xsd:string | endingTime xsd:dateTime
   timeToEnd xsd:string | categoryId xsd:int | conditionInfo xsd:string
   promotionInfo xsd:int | additionalInfo xsd:int | sellerInfo tns:UserInfoType
   priceInfo tns:ArrayOfPriceinfotype | photosInfo tns:ArrayOfPhotoinfotype
   parametersInfo tns:ArrayOfParameterinfotype | advertInfo tns:AdvertInfoType
```

### Request 1/4 — `www.aukro.cz/robots.txt` → **403**

```
$ curl -s -D r1_headers.txt -o r1_robots.txt \
  -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36' \
  'https://www.aukro.cz/robots.txt'

HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2ad7c0fd7d39a-FRA
content-length: 5689
content-type: text/html; charset=UTF-8

<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>...
window._cf_chl_opt = { cRay:'a2f2ad7c0fd7d39a', cType:'managed', cvId:'3', cZone:'www.aukro.cz' }
```

### Request 2/4 — `api.aukro.cz/` → **403**

```
$ sleep 2 && curl -s -D r2_headers.txt -o r2_api_root.html \
  -A 'Mozilla/5.0 ... Chrome/127.0.0.0 Safari/537.36' \
  -H 'Accept: text/html,application/xhtml+xml,...' -H 'Accept-Language: cs-CZ,cs;q=0.9,en;q=0.8' \
  'https://api.aukro.cz/'

HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2b0b35df5c614-FRA
content-length: 5702
-> identical "Just a moment..." managed-challenge interstitial
```

### Request 3/4 — `doc.aukro.cz/webapi/docs/documentation.html` → **403**

Issued via `WebFetch`, i.e. over **Anthropic's egress, not the VPN**. Still blocked — so the
challenge is not specific to the M247 range, though both are datacenter networks.

```
WebFetch https://doc.aukro.cz/webapi/docs/documentation.html
-> "The server returned HTTP 403 Forbidden."
```

### Request 4/4 — search page, full browser header set → **403**

The decisive test: a real content page (not `robots.txt`, not an API root) with a complete
Chrome header set including Sec-Fetch-* and Client Hints.

```
$ sleep 2 && curl -s -D r4_headers.txt -o r4_search.html --compressed \
  -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36' \
  -H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8' \
  -H 'Accept-Language: cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7' \
  -H 'sec-ch-ua: "Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"' \
  -H 'sec-ch-ua-mobile: ?0' -H 'sec-ch-ua-platform: "macOS"' \
  -H 'Sec-Fetch-Dest: document' -H 'Sec-Fetch-Mode: navigate' \
  -H 'Sec-Fetch-Site: none' -H 'Sec-Fetch-User: ?1' \
  -H 'Upgrade-Insecure-Requests: 1' \
  'https://aukro.cz/vyhledavani?text=notebook'

HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2b47aca188e2c-FRA
$ grep -c 'Just a moment' r4_search.html   -> 1
```

⚠️ **`/vyhledavani?text=notebook` is a GUESSED path and is NOT verified to exist.** Cloudflare
challenges at the edge *before* origin routing, so this 403 says nothing about whether that route is
real. The correct search URL/params for Aukro remain **NOT DETERMINED**.

### Transport-signal grep over all saved bodies

```
$ for f in r1_robots.txt r2_api_root.html r4_search.html; do
    grep -c -e __NEXT_DATA__ -e 'application/ld+json' -e 'window\.__' -e graphql -e '/api/' "$f"
  done
-> 0 for every pattern in every file
$ grep -ohE 'https?://[a-zA-Z0-9./_-]+' r*.html r1_robots.txt | sort -u
   https://challenges.cloudflare.com
```

### Wayback Machine attempts (0 aukro.cz requests) — all failed

```
$ curl -s 'https://archive.org/wayback/available?url=aukro.cz%2Frobots.txt'
   -> 20260203021405  http://web.archive.org/web/20260203021405/https://aukro.cz/robots.txt
$ curl -s 'https://web.archive.org/web/20260203021405id_/https://aukro.cz/robots.txt'
   -> <title>429 Too Many Requests</title>      (7+ attempts, backoff to 45s, always 429)
WebFetch https://web.archive.org/...
   -> "Claude Code is unable to fetch from web.archive.org"
```

---

## 9. What I could not determine

1. **Every listing count** — site total and all four target categories. No content retrieved.
2. **New/day**, and the new-vs-relist split that an auction site specifically requires.
3. **`robots.txt` contents** — blocked live; archived copy blocked by archive.org 429. So whether
   completed-auction/archive paths are disallowed is **unknown**, and §6 of this file is empty for
   that reason rather than because the file is permissive.
4. **⭐ Whether an individual ended auction's permalink publicly shows its final price.** This is the
   single unresolved question that could still change Aukro's verdict, and it costs exactly one
   request from a residential IP. Everything else in §4 points to "no public realised-price archive",
   but this specific case is untested and I will not guess it.
5. **What `api.aukro.cz` actually serves today** — whether it is a modern REST API, its auth model,
   whether it has a free/public tier, and whether any endpoint exposes finished items. The WSDL in
   §4.2 is the *legacy Allegro-derived* API and must not be treated as current.
6. **Whether a residential IP passes the Cloudflare challenge.** All findings here are from
   datacenter ASNs (two different ones). This is the prerequisite for any further Aukro work.
7. **The real search URL/params, pagination, page-size cap, and ordering options.**
8. **Any ToS quotes** — not attempted this pass (Pass 2 scope), and unreachable anyway.
9. **Whether the WSDL's `doGetSiteJournalDeals` ("deals" change feed) is seller-scoped or broader.**
   In the Allegro lineage this was licence-gated; if it were ever broader it would be a realised-
   transaction feed. Not investigated — flagging it as the one WSDL lead that could contradict §4.2.

### Budget note

I used **4 of 7** permitted requests. I deliberately did not spend the remaining 3: after four
identical `cf-mitigated: challenge` 403s across three hostnames and two egress networks, further
requests from this IP would have produced more of the same while adding nothing. The unspent budget
is better applied from a residential connection against item 4 above.
