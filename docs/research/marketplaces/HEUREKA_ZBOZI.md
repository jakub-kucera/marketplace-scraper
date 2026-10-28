---
title: Heureka.cz / Zboží.cz — Track B assessment
status: reference
updated: 2026-09-18
verified: 2026-08-22
---

# Heureka.cz / Zboží.cz — Track B assessment

> Assessed 2026-08-22. Requests used **15/15**. Verdict: **REJECT**.
>
> Closes the gap named in [`BACKLOG_IDEAS.md`](../../backlog/BACKLOG_IDEAS.md) #4:
> *"no research has been done for Heureka or any price-comparison source — no confirmed endpoint,
> no confirmed rate limits, nothing."* There is now an endpoint, a measured rate-limit shape, and a
> measured answer on the join.
>
> All claims below are live-measured unless marked **⚠️ ASSUMED**. Egress throughout: VPN
> datacenter IP `185.242.6.116` (M247, AS9009, Prague CZ) — the same vantage point as
> [`RANKING.md`](pass1/RANKING.md). Per RESEARCH_BRIEF §9: **no account was created, nothing was
> registered for, no ToS was accepted, and no block was evaded.**
>
> **⚠️ Superseded in part - read [`ZBOZI_API.md`](ZBOZI_API.md) (2026-09-16) before acting on
> anything below.** A re-probe from a third vantage point found a JSON surface this file never
> located and measured three of its headline claims false: the join step is **not** the
> robots-disallowed one (`/suggestV2?phrase=` → `/api/v3/product/<slug>/`, both allowed for
> `User-agent: *`), `productNo` **does** carry a manufacturer part number (§4a grepped for
> `mpn`/`partNumber` and missed it on spelling), and a discontinued MacBook Pro 13 **is** in the
> catalogue - unreachable from typeahead, which is a different defect from absent. It also found a
> `medianPrice` and ~24 months of price history, and the capability shipped as `refprice/` on
> 2026-09-16. **What still stands here:** no official third-party read API, no EAN/GTIN, the
> dangerous-not-empty failure on discontinued goods, and **Heureka.cz itself Cloudflare-blocked**,
> re-confirmed 2026-09-16 from a third egress.

---

## 1. Verdict (lead with it)

**REJECT.** Not "blocked on transport" — the transport is the easy part. Zboží.cz hands over a
clean, unauthenticated JSON surface with canonical integer product ids and a cross-merchant price
range, and it did not rate-limit or challenge a single one of our requests. The idea dies two
levels above that, on three measured findings:

1. **There is no official read API on either site, at any price.** Every "API" Heureka publishes is
   merchant-side — you push your catalogue *to* them, or you implement endpoints *they* call. The
   affiliate programme's "interface" turns out to be HTML ad widgets, and it gates on registration
   plus per-website approval. (§2)
2. **Neither site exposes EAN/GTIN.** Zero occurrences of `ean`, `gtin`, `isbn`, `mpn` or
   `partNumber` anywhere in a full Zboží product payload. Heureka's own feed spec makes EAN
   **mandatory only for books, films, music and comics** and tells every other merchant not to
   bother sending it. The premise that "Heureka's whole model is matching feeds to canonical
   products, so it may be unusually good at identity" is **false as an external interface** — the
   matching is real, but it is name-based, internal, takes ~4 working days, and is never exposed. (§4)
3. **The catalogue only covers what is currently sold new — which is the complement of what this
   project scrapes.** `"Macbook Pro 13 2020 i5 16GB"`, the exact example from BACKLOG_IDEAS #4,
   returned **3 results, zero canonical products**. Re-querying with a *clean* canonical name,
   `"Apple MacBook Pro 13 2020"`, returned 292 results and **one** product — a phone case. A used-
   goods baseline that has no entry for used goods is worth nothing. (§4, §6)

Finding 3 is the one that makes this REJECT rather than DEFER, and it is the one measured on the
narrowest base — see §11 for the single probe that would overturn it.

---

## 2. Official API / feed — what exists, what it requires

**Nothing readable by a third party exists.** Heureka publishes four interfaces; all four are for
merchants or publishers, none returns product prices to a caller.

| Surface | Direction | What it requires | Measured |
|---|---|---|---|
| **Heureka XML feed** (`sluzby.heureka.cz/napoveda/xml-feed/`) | **You → Heureka.** You publish a catalogue file; Heureka ingests it. | Being an e-shop | R6, HTTP 200 |
| **Heureka Marketplace API** (`sluzby.heureka.cz/napoveda/marketplace-api/`) | **Heureka → you.** *You* host the endpoints. | Registered e-shop enrolled in Marketplace | R5, HTTP 200 |
| **Ověřeno zákazníky API** (`api.heureka.[TLD]/shop-certification/v2/`) | You → Heureka, order data for review solicitation | Shop API key | Not probed — docs only |
| **Heureka Affiliate** (`affiliate.heureka.cz`) | Rendered ad widgets | Registration + **per-site approval** + bank details | R7, HTTP 200 (PDF) |

**The Marketplace API is the decisive one, and it is the exact inverse of what was hoped for.** Its
own documentation gives the base URL as the *merchant's* domain:

> `https://www.example.com/api/:verze_api:/:oblast:/:akce:/`
>
> — *"API na straně obchodu slouží k získávání aktuálních informací o nabízených produktech […]
> Jsou stejně důležité a je nutné mít implementované obě dvě části."*

That is Heureka calling `GET https://your-shop.cz/api/1/products/availability` to ask *you* about
*your* stock. Its methods are `GET products/availability`, `POST order/send`, `PUT order/cancel`,
`POST order/invoice` — order-fulfilment plumbing. The page renders a logged-in shop-admin chrome
("Administrace e-shopu", "Přidat obchod", "Odhlásit se"), and testing requires
*"Po přihlášení do správy e-shopu"*.

**This is the decisive finding the brief asked for: yes, the official route requires being a
registered e-shop merchant.** Not a developer key, not a rate-limited free tier — a business
relationship in which you sell goods through Heureka.

**The affiliate programme is not a data feed.** Its published "POPIS ROZHRANÍ" (interface
description, 4pp) enumerates what a partner can actually embed, and every item is a rendered banner:
*Graf ceny produktu* (a price-history chart), *Textový odkaz*, *Vyhledávací pole*, *Produkt*,
*Výběr produktů* (up to 20 rotating), *Kategorie*, *Slevy*. Delivery is two HTML snippets — a
"Hlavní kód" placed once per page and a "Kód umístění" per unit. There is no queryable endpoint and
no structured payload; you get pixels and a click-tracking redirect. Access requires an account,
and separately:

> *"Všechny webové stránky, kde chcete mít reklamní prvky affiliate programu Heureka.cz, musí být
> uvedeny v administraci a být schváleny."*

Per RESEARCH_BRIEF §9 this is where the assessment stops: **registration and per-site approval are
required, so no account was created.** Recorded as a finding, not pursued.

**Zboží.cz is worse, and closed a door recently.** Seznam's own engineering blog announced in
November 2025 that **the Zboží API is being retired**, folded into the Sklik API ("Fénix"), with
existing Zboží API keys ceasing to be valid. Sklik is the *advertising* API — advertiser-side, keyed
to an ad account. There is no consumer/product read API on the Seznam side either. ⚠️ **ASSUMED** —
this comes from a search result, not from a request we made; the retirement date and current status
were not verified against a Seznam endpoint.

---

## 3. Transport if scraping — what you found, with probe commands

### 3a. Heureka.cz — Cloudflare managed challenge, everything except robots.txt

Content pages are **not retrievable from this vantage point**. Both a canonical product page and the
sitemap index returned an identical Cloudflare interstitial:

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
curl -s -A "$UA" -H 'Accept-Language: cs,en;q=0.8' --compressed -D - -o body.html \
  "https://mobilni-telefony.heureka.cz/apple-iphone-13-pro-1tb/"
```
```
HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2cab3eed9dd73-PRG
critical-ch: Sec-CH-UA-Bitness, Sec-CH-UA-Arch, Sec-CH-UA-Full-Version, ...
```

Body: `<title>Checking security</title>`, a `cdn-cgi/challenge-platform` script, an "Enable
JavaScript" notice. **Zero** occurrences of `ld+json`, `__NEXT_DATA__`, or `window.__` — the §4b
grep playbook has nothing to grep. `www.heureka.cz/sitemaps/sitemap_index.xml` returned byte-for-
byte the same challenge.

**Blocking shape:** HTTP **403** with a `cf-mitigated: challenge` header and a JS interstitial —
materially different from Bazos, whose block is a bare path-scoped 403 with no challenge platform
(live-verified separately: 403-only, path-scoped, not domain-wide, no 429 observed).
It also differs from Sbazar's, which is Seznam's in-house `bcr.iva.seznam.cz`
([`SBAZAR.md`](pass1/SBAZAR.md)). Three marketplaces, three different anti-bot vendors.

Scope: **not domain-wide.** `www.heureka.cz/robots.txt` (200), `sluzby.heureka.cz` (200), and
`affiliate.heureka.cz` (200) all served cleanly. The challenge sits on the consumer product/search
properties (`www` content paths and the `<category>.heureka.cz` subdomains) — i.e. precisely the
surface a price scraper needs.

⚠️ **This is blocked from a datacenter IP; it is NOT proven to block a residential connection.** The
`critical-ch` header requests a full client-hints set, which is consistent with a browser-fingerprint
challenge rather than a pure IP reputation block, but we did not test a residential path and did not
attempt to solve or bypass the challenge.

### 3b. Zboží.cz — Next.js, wide open, three usable layers

The contrast is stark. A canonical product page served fully:

```bash
curl -s -A "$UA" -H 'Accept-Language: cs,en;q=0.8' --compressed \
  "https://www.zbozi.cz/vyrobek/apple-iphone-13/?varianta=128-gb-cerny&noredirect=1"
# HTTP/2 200 | 105,362 B gzip / 454,559 B raw | 1.31 s | server: envoy
```

Note the `noredirect=1`. A bare `/vyrobek/apple-iphone-13/` returns **302** to
`https://login.seznam.cz/api/v1/autologin?service=zbozi&return_url=…%3Fnoredirect%3D1`. That is
Seznam's SSO probe, not a login wall — the redirect target Seznam itself constructs already carries
`noredirect=1`, and following the chain lands back on the page. **No account, no cookie, no
authentication of any kind is required.**

Three layers found in that body, in increasing order of usefulness:

**1. JSON-LD `AggregateOffer`** — present, valid, and intended to be machine-read:
```json
{"@context":"https://schema.org","@type":"Product","name":"Apple iPhone 13",
 "brand":{"@type":"Brand","name":"Apple"},
 "category":"Telefony, navigace/Mobilní telefony",
 "offers":[{"@type":"AggregateOffer","lowPrice":10581,"highPrice":12743,
            "priceCurrency":"CZK","offerCount":3}, …]}
```
No `gtin13`, no `sku`, no `mpn`, no `productID`.

**2. `__NEXT_DATA__`** — 272 KB of JSON, far richer than the JSON-LD (see §5).
`buildId = qKaIrxCbar6XQmnqpuYPF`.

**3. The Next.js data route** — the buildId unlocks a pure-JSON transport at
`/_next/data/<buildId>/<page>.json`, which is the cheapest surface on the site:

```bash
curl -s -A "$UA" --compressed \
  "https://www.zbozi.cz/_next/data/qKaIrxCbar6XQmnqpuYPF/hledej.json?q=Apple%20iPhone%2013%20128GB"
# HTTP/2 200 | 184,428 B | 1.37 s | content-type: application/json
```

**Characterisation:**

| Property | Measured |
|---|---|
| Auth | **None.** Anonymous, no cookie bootstrap, no token |
| Anti-bot | **None observed.** No Cloudflare, no DataDome, no `bcr.iva.seznam.cz` |
| Blocking shape | Not observed — no block occurred |
| Rate limits | None hit; see §8 |
| Ordering / pagination | `paging.pages[]`, `resultsPerPage = 48`; relevance-ordered (not a listings feed) |
| Payload | Product HTML 105 KB gzip / 455 KB raw; search JSON 18 KB (0 products) to 374 KB (48 products) |
| Stability risk | `buildId` is a deploy artifact — it **will** rotate on every Zboží release, silently 404-ing the data route. Scrape it from the page each pass, never hardcode |

**No JS bundles were grepped and no `/api/` path was recovered** — the product HTML contains zero
`/api/` literals, and the budget was spent on the join instead. See §11.

---

## 4. ⭐ The join — EAN/GTIN, product ids, free-text search, and the honest cost

This is the section that decides the verdict, and the answer is **no** on three of four sub-questions.

### 4a. EAN / GTIN — absent on both sites

Exhaustive substring scan of the full 272 KB Zboží product payload:

```bash
python3 -c "
import re; raw=open('zbozi_next.json').read()
for t in ['ean','gtin','isbn','sku','mpn','partNumber','barcode']:
    print(t, sorted(set(re.findall(r'\"[^\"]{0,25}'+t+r'[^\"]{0,25}\"', raw, re.I)))[:8])"
```
```
ean          ['"boolean"', '"return Boolean(window.login)"']    <- false positives
gtin         []
isbn         []
sku          ['"ctecka-otisku-prstu"', '"senzor-sily-stisku"']  <- Czech words
mpn          []
partNumber   []
barcode      []
```

**Zero.** Not in `__NEXT_DATA__`, not in the JSON-LD `Product`, not on any of the 3 merchant offers.

Heureka's side is answered by its own feed spec, which is the authoritative statement of what
Heureka asks merchants for and therefore what it could possibly hold:

> **EAN** — *"EAN kód je povinnou položkou pro kategorie Knihy, Učebnice, Mapy a průvodci, Filmy,
> Hudba a Komiksy. Pokud tedy prodáváte jiné zboží, pak EAN není povinný a není tedy třeba ho
> zasílat."*

EAN is mandatory for **books, textbooks, maps, films, music and comics** — and Heureka explicitly
tells merchants of everything else *not to send it*. Phones, laptops, tools and bikes are all in the
"don't bother" set. Even if the Heureka block were lifted, there is no reason to expect a populated
GTIN on the categories this project cares about.

### 4b. How Heureka actually does identity — and why it is not available to you

Heureka's matching is real and good, and its own docs describe the mechanism:

> *"Při změně URL adres vašich produktů, názvů produktů či kategorií v XML se na Heurece **odpárují
> všechny produkty** a poté se znovu čeká na jejich **spárování, které může trvat cca 4 pracovní
> dny**."*

> **ITEM_ID** — *"Musí zůstat unikátní navždy […] **Tag se dosud pro párování položek nevyužívá.**"*

> **PRODUCTNAME** — *"Maximální délka textu v tomto tagu je omezena na 200 znaků […] název nesmí být
> obecný. Pokud tedy uvedete do názvu produktu **výrobce, řadu a produktové číslo**, měl by být
> produkt v pořádku zařazen."*

Three consequences, and each one cuts against the idea:

- Pairing keys on **PRODUCTNAME + URL**, not on any identifier. The merchant's own stable id is
  explicitly *not* used for matching.
- It is **asynchronous and slow** — ~4 working days, re-triggered by a name change. This is a
  batch back-office process, not a lookup service.
- It works because merchant catalogue names are **disciplined**: manufacturer + product line +
  product number, ≤200 chars, no gifts or accessories in the name. A Bazos title is the exact
  opposite of a well-formed feed name. Heureka's competence at this problem is competence on
  *clean* input, and it is **never exposed as an interface** in any case.

### 4c. Free-text search — the measured contrast, and the robots problem

Both queries hit the same endpoint, minutes apart, from the same IP.

**Query A — the messy title, verbatim from BACKLOG_IDEAS #4:** `"Macbook Pro 13 2020 i5 16GB"`

```
totalResults = 3
firstCategory = {"id": 111, "name": "Notebooky"}      <- category inferred correctly
productsResults.products = []                          <- ZERO canonical products
results.results = 3 x  type: "offer"
```
| type | name | price | shopCount |
|---|---|---|---|
| `offer` | `Apple MacBook Pro 13'' 2020 / i5 / 16GB / 512GB SSD / Stříbrná - Stav B` | 9,990 Kč | 1 |
| `offer` | `Apple MacBook Pro 13'' 2020 / i5 / 16GB / 512GB SSD / Vesmírně Šedá - Stav B` | 9,490 Kč | 1 |
| `offer` | `Apple 13 MacBook Air M1 2020 Retina 8jádro 256/16Gb` | 14,980 Kč | 1 |

Three problems in three rows: nothing resolved to a canonical product; the top two hits are
**"Stav B"** — refurbished grade B, i.e. a *used* price, not the new-retail baseline the whole idea
is premised on; and the third hit is a **MacBook Air M1**, a different machine.

**Query B — a clean canonical name:** `"Apple iPhone 13 128GB"`

```
totalResults = 48
firstCategory = {"id": 81, "name": "Mobilní telefony"}
results.results = 48 x  type: "product"                <- ALL canonical
```
| type | id | name | minPrice | maxPrice | shopCount | url |
|---|---|---|---|---|---|---|
| `product` | 6712570 | Apple iPhone 13 | 749000 | 1095000 | 3 | `/vyrobek/apple-iphone-13/?varianta=128-gb-modry` |
| `product` | 6712505 | Apple iPhone 13 Pro | 849000 | 1290000 | 5 | `/vyrobek/apple-iphone-13-pro/?varianta=128-gb-modry` |
| `product` | 6712599 | Apple iPhone 13 mini | 649000 | 975000 | 6 | `/vyrobek/apple-iphone-13-mini/?varianta=128-gb-bily` |

Integer ids, a real relative URL, and a cross-merchant range on every row. **The response type flips
from `offer` to `product` and the price-range fields appear.** That flip is the join, and it is a
single boolean you can test on: `results.results[i].type == "product"`.

**Query C — the disambiguation.** Query A failing could mean *messy title* or *product absent from
the catalogue*. Those imply completely different remedies, so it was worth a request to separate
them. Clean canonical name for the **same old product**: `"Apple MacBook Pro 13 2020"`

```
totalResults = 292
types: Counter({'offer': 47, 'product': 1})
```
The single `product` is **`Epico Shell Cover 2018/2020 13"`** — a laptop case, 999 Kč. The 47 offers
are overwhelmingly accessories: screen films (270–294 Kč), a replacement battery (743 Kč), sleeves,
tempered glass.

**So the cause is not title messiness. Zboží.cz has no canonical product entry for a 2020 MacBook Pro
at all.** Its canonical catalogue tracks what merchants currently sell *new*; a five-year-old laptop
has aged out and left behind only accessories and one-off refurb listings.

**And there is a live trap in that result.** A naive "cheapest match wins" join over Query C computes
a baseline of **~270 Kč for a MacBook Pro** — from a screen protector. Every used MacBook on Bazos
would score as a catastrophic overprice. Any implementation would need an accessory filter that the
data gives you no clean signal for (`categoryId` is `111 Notebooky` on the *query*, but the offers
themselves carry mixed categories).

**The robots.txt problem — and it lands exactly on the join step.** Zboží's `User-agent: *` block
disallows search comprehensively:
```
Disallow: /hledani/
Disallow: /hledej/
Disallow: /hledani/*
Disallow: /hledej/*
Disallow: /*?q=
```
`Disallow: /*?q=` is a path-and-query pattern that matches **any** URL containing `?q=` — including
`/_next/data/<buildId>/hledej.json?q=…`. The `Allow: /api/` and `Allow: /api/*?*&*&*` rules do not
rescue it, because the data route is under `/_next/`, not `/api/`. **The Next data route we used for
the search probes is robots-disallowed**, and this is disclosed rather than glossed: R10–R15 hit a
`Disallow`d pattern. Meanwhile `/vyrobek/<slug>/?varianta=…` **is** explicitly `Allow`ed.

The shape of that is unusually precise and it is the crux:

> **Zboží.cz permits fetching a product page you already have the URL for, and forbids the free-text
> search that is the only way to find that URL from a scruffy classified title.** The join step is
> exactly the step robots.txt forbids.

### 4d. The honest cost — "you would need an LLM extraction step per ad"

Yes, and per the brief it is named as a separate project rather than hidden. Costing the *extraction*
half honestly:

- Input per ad: system prompt + `Ad.name` (≤120 chars) + `Ad.short_description` (≤300 chars)
  ≈ **500 input tokens**; structured JSON out (`{brand, line, model, variant, capacity, year}`)
  ≈ **60 output tokens**.
- At **Claude Haiku 4.5** ($1 / $5 per MTok): `500e-6 × 1 + 60e-6 × 5` = **$0.0008 per ad**.
- Volume from [`RANKING.md`](pass1/RANKING.md)'s measured Sbazar `<lastmod>` rates — tools 559/day,
  notebooks 100, bikes 60, iPhone 48 = **767 ads/day** → **$0.61/day ≈ $18/month**, before Bazos.
- At **Claude Opus 5** ($5 / $25): **$0.004 per ad** → ~$92/month on the same volume. Prompt caching
  on the frozen system prompt cuts the input side substantially at either tier.
- The project already researched a **free-tier** option that would carry this
  ([`LLM_AD_REVIEW.md`](../../proposals/LLM_AD_REVIEW.md), 2026-07-30: ~1,500 req/day,
  and the EEA carve-out means free-tier prompts are not used for training) — so the *marginal money
  cost could be zero*, provided cheap rules run first.

**But the money was never the objection, and costing it is not the answer.** The measured findings
say a perfect extractor does not fix this:

- A perfect `{Apple, MacBook Pro, 13", 2020, i5, 16GB}` extraction still has **nothing to look up** —
  Query C proves the canonical entry does not exist (§4c).
- The lookup it would feed is **robots-disallowed** (§4c).
- There is no EAN to key on, so the lookup is *still* fuzzy name-matching at the far end (§4a) — the
  LLM step converts one fuzzy-matching problem into a slightly-less-fuzzy-matching problem, it does
  not eliminate it.

So the honest framing is stronger than "this is a different project": **the LLM extraction project is
a prerequisite that would not be sufficient even if completed.** That is a materially different
answer from "expensive but doable", and it should not be softened into one.

---

## 5. Price shape — single price or cross-merchant range?

**Cross-merchant range, and it is genuinely the more useful signal — where it exists.** Measured on
`/vyrobek/apple-iphone-13/?varianta=128-gb-cerny`:

| Field (`props.pageProps.data`) | Value | Meaning |
|---|---|---|
| `id` | `6712502` | canonical product id (integer) |
| `minPrice` / `maxPrice` | `1058100` / `1274300` | **integer hundredths of CZK** → 10,581 / 12,743 Kč |
| `offers.shopCount` | `3` | distinct merchants |
| `variants[]` | 18 entries | each with own `id`, `minPrice`, `maxPrice`, `offerCount`, `url` |
| `offers.items[]` | 3 entries | `price`, `availability`, `shop{id,name,ratings}`, `minPriceDelivery` |
| `brand` | `{"name":"Apple","id":"17819163333647859135"}` | brand id is a **string** (u64-ish) |
| `category` | `{"id":81,"path":"telefony-navigace/mobilni-telefony"}` | |

**The ×100 trap, measured:** `offers.items[0].price = 1058100` while the very same offer's
`clickLogData.WAData.price = 10581`. Two different scales in one object. `parse_price` in
`bazos/filters.py` does `re.sub(r"\D", "", …)`, so an unconverted value would land in the DB
**100× too large**. (Track B never produces `Ad` rows so §5's schema checklist doesn't apply — but a
baseline table would hit the identical bug.) The JSON-LD reports whole CZK (`lowPrice: 10581`), so
the two layers disagree on units; prefer JSON-LD if only the range is needed.

### 5a. The range is thin and demonstrably mis-paired

Three measured defects that would poison a naive baseline:

**Mis-pairing.** On the **128 GB černý** variant page, the cheapest of three offers is:

| shop | price | offer name |
|---|---|---|
| Elektroshock.cz | 10,581 Kč | `Apple iPhone 13 **mini** 128GB Barva: Černá` |
| Smartphoner.cz | 10,950 Kč | `Apple iPhone 13 128GB, midnight` |
| Allegro.cz | 12,743 Kč | `Smartphone Apple iPhone 13 4 GB / 128 GB 5G černý` |

An **iPhone 13 mini** offer is paired onto the **iPhone 13** product, and because it is the cheapest
it *sets* `minPrice` — and therefore the JSON-LD `lowPrice: 10581` too. Heureka-style name-based
pairing produces this class of error, and it lands on the exact field a deal-scorer would key on.

**Thin offer counts.** Across 18 variants, `offerCount` ranges 1–6. Six of eighteen have exactly one
merchant, where "range" degenerates to a point estimate.

**Incoherent across variants.** Same model, same generation:

| variant | minPrice | maxPrice | offers |
|---|---|---|---|
| 128 GB červený | 6,499 | 10,950 | 3 |
| **512 GB černý** | **9,490** | 9,490 | 1 |
| **128 GB černý** | **10,581** | 12,743 | 3 |

The 512 GB is **cheaper than the 128 GB**, and identical-spec colour variants differ by **63%**
(6,499 vs 10,581). These are thin-sample and mis-pairing artefacts, not real market structure. A
baseline built on this needs cross-variant reconciliation before it means anything.

---

## 6. Category fit — which of phones/laptops/tools/bikes this actually serves

The mechanism is the one measured in §4c: **the canonical catalogue holds products currently sold
new.** Everything below follows from that.

| Target category | Serves it? | Basis |
|---|---|---|
| **Phones** | **Partly — the only real yes.** | Measured: iPhone 13 has a canonical product, 18 variants, min/max, `shopCount`. But it is a 2021 model with 1–6 offers/variant and a mis-paired cheapest offer (§5a). A 2018 phone would likely look like the MacBook. ⚠️ ASSUMED |
| **Laptops** | **Measured NO for aged stock.** | `"Apple MacBook Pro 13 2020"` → 292 results, 1 product, and that product is a *phone case*. Current-model laptops would presumably resolve — not measured. |
| **Tools** | **⚠️ ASSUMED no — and this is the worst case.** Not measured. | Two independent reasons. (a) By the §4c mechanism, a used 2015 Makita has no current-new entry. (b) A new-price baseline is close to meaningless for hand tools, where condition, completeness (case? battery? charger?) and wear dominate value far more than model identity. |
| **Bikes** | **⚠️ ASSUMED no.** Not measured. | Second-hand bikes are largely non-canonical — frame size, year, component swaps, and condition dominate. There is often no "the same product, new" to compare against. |

**This is the part that should decide it, and it points the wrong way.** Track A's Pass 1 measured
Sbazar's **tools** category as the single biggest opportunity in the whole brief — 26,492 active,
**3.4× Bazos**, ~559 new/day ([`RANKING.md`](pass1/RANKING.md)). Tools is precisely the category a
new-price baseline serves *worst*: used-condition-dominated, non-canonical, and (⚠️ ASSUMED) absent
from the catalogue by the same mechanism that removed the MacBook.

The categories a Heureka/Zboží baseline would genuinely serve — **current-generation phones and
current-model laptops** — are the two smallest of the four on Sbazar (phones 4,083 active / ~48 per
day; notebooks 4,384 / ~100 per day), and they are also the categories where an *internal* rolling
price median is easiest to build, because volume is adequate and titles are relatively canonical.
That internal baseline is already designed
(`DISCOVERY_PIPELINE.md` §2 Stage 2),
needs no external dependency, no LLM step, no robots-disallowed request, and answers a *closely
related* question. **It should be built first regardless of what happens to this idea**, and if it
works the marginal value of the external baseline shrinks further.

**Say it plainly: this serves one and a half of the project's four target categories, and not the
big one.**

---

## 7. Legal — ToS, robots.txt verbatim on the paths you'd need

**Neither site's ToS was fetched — budget exhausted. NOT DETERMINED.** (§11.) What follows is
robots.txt, verbatim, on the paths that matter.

### 7a. heureka.cz/robots.txt — `User-agent: *` block, complete

```
# Webmasters contact: seo@heureka.cz
User-agent: *
Disallow: /ocm/sdk.js*
Disallow: /direct/mapa/*
Disallow: /direct/ajax/*
Disallow: /direct/bannery/*
Disallow: /direct/js/*
Disallow: /exit/*
Disallow: *exit-click-web*
Disallow: /unsecured-data-feeds/
Disallow: /unsecured-data-feeds/*.xml$
Disallow: /srovnani-produktu/
#SearchRelated
Disallow: *?searchedQuery=*
Disallow: *;q:*
#Bugs
Disallow: */config/slots-definitions$
Disallow: */slots-definitions$
Disallow: */config/utils$
Disallow: */utils$
Disallow: */config/config$
Disallow: */config/*
Disallow: */config$
# Filters
Disallow: /f:*:*,*
Disallow: /f:*;l:*
Disallow: /f:l:*;*
Disallow: /f:*;*;*;*
# Rating
Disallow: /f:r:*
Disallow: /f:*r:*
Allow: /f:r:1/$
Disallow: /?p=f:r:*
Disallow: /?p=f:*r:*
Allow: /?p=f:r:1$
# Ordering
Disallow: /?o=*
Disallow: /*?o=*
Disallow: /*?*&o=*
# HP
Disallow: /hp-landing-page
Allow: /direct/i/*
```

Sitemap: `https://www.heureka.cz/sitemaps/sitemap_index.xml`.

**Read against the paths a baseline would need:**
- **Product pages** (`https://<category>.heureka.cz/<slug>/`) — **not disallowed for `*`.**
- **Text search** — `/hledat/?h[fraze]=` and `/?h…` are disallowed **only for `Bingbot` and
  `Yandex`**, which have their own longer blocks; they are *not* in the `*` block. But
  `Disallow: *;q:*` blocks within-category text search (Heureka's `;q:` filter syntax), and
  `Disallow: *?searchedQuery=*` blocks another search form.
- **`Disallow: /srovnani-produktu/`** — "product comparison". Blocked for everyone.
- **No `ClaudeBot` / `GPTBot` / `CCBot` entry.** Named full-blocks: `Baiduspider`,
  `AhrefsSiteAudit`, `SemrushBot`, `SentiBot`, `grapeshot`, `BLEXBot`, `YaK`, `SEOkicks`,
  `Screaming Frog SEO Spider`, `DotBot`, `MixnodeCache`, `Barkrowler`, `Seekport Crawler`, `ltx71`,
  `Statusoid`, `Testomatobot`, `coccocbot`, `Exabot`, `proximic`, `ScooperBot`, `serpstatbot`.
  `Yandex` gets `Crawl-delay: 20`, `AhrefsBot` 30, `MJ12Bot` 60.
- Note what is **absent**: unlike Bazos, Heureka does **not** name `pricebot` or `trovitBot`. It is
  itself an aggregator.

Worth stating: **robots.txt is close to moot for Heureka.** Cloudflare denies the pages regardless
(§3a), so the permissive product-page rule buys nothing from this vantage point.

### 7b. zbozi.cz/robots.txt — `User-agent: *` block, the load-bearing lines

```
User-agent: *
## Disallow clicks to shops
Disallow: /action/
Disallow: /mobileCheck
Disallow: /clickthru
## Disallow result pages - search results
Disallow: /hledani/
Disallow: /hledej/
Disallow: /stats
## multichoice in left menu
Disallow: /*,
...
Disallow: /*origQuery=
## Disallow pages with 2 and more parameters - seznambot
Disallow: /*?*&*&*
## kvuli pravidlu Disallow: /*?*&*&*&*
Allow: /api/*?*&*&*
Allow: /api/
Disallow: /nabidka/
Disallow: /opes/clickthru
...
# Disallow all searchScreen
Disallow: /hledani/*
Disallow: /hledej/*
Disallow: /*?q=
Disallow: /hledani/?q=
Disallow: /hledej/?q=
...
Disallow: /vyrobek/*?*=*
Allow: /vyrobek/*?varianta=*
```
Sitemap: `https://zbozi.cz/sitemap/index.xml`. Other agents blocked entirely: `Rogerbot`, `Exabot`,
`MJ12bot`, `DotBot`, `Gigabot`, `BLEXBot`, `SemrushBot`, `SEOkicks`, `grapeshot`, `dwarf`,
`PiplBot`, `SentiBot`, `DataForSeoBot`, `GoogleOther`. No `ClaudeBot`/`GPTBot` entry.

**Read against the paths a baseline would need:**

| Path | Verdict | Rule |
|---|---|---|
| `/vyrobek/<slug>/` (no params) | **Allowed** | no matching Disallow |
| `/vyrobek/<slug>/?varianta=…` | **Allowed** | `Allow: /vyrobek/*?varianta=*` (21 ch) beats `Disallow: /vyrobek/*?*=*` (14 ch) on longest-match |
| `/vyrobek/<slug>/?noredirect=1` | **Disallowed** | matches `/vyrobek/*?*=*`; no Allow applies |
| `/hledej/?q=…` | **Disallowed** ×3 | `/hledej/`, `/hledej/*`, `/hledej/?q=` |
| `/_next/data/<buildId>/hledej.json?q=…` | **Disallowed** | `Disallow: /*?q=` matches any URL containing `?q=`. `Allow: /api/…` does not apply — this is under `/_next/` |
| `/nabidka/<offerId>/` (offer detail) | **Disallowed** | `Disallow: /nabidka/` |

**`Allow: /api/` is Zboží explicitly permitting an `/api/` surface** — a genuine lead that we ran out
of budget to chase (§11). The product page HTML contains zero `/api/` literals; recovering the paths
would require grepping the JS bundles.

### 7c. Verdict against MONETIZATION.md §3's posture

The current posture is **private use** — data stays with the operator, nothing is republished
(`MONETIZATION.md` §3, and *Innoweb v Wegener* C-202/12 on the sui generis
right). Two things distinguish this from the Bazos situation:

- **Volume is inherently low.** A baseline lookup is per-*product*, not per-listing, and results
  cache for days or weeks. This is nothing like extracting a substantial part of a database. Under a
  private-use posture the sui generis exposure is the lowest of anything in this brief.
- **But the compliance problem is qualitatively different, and it is not about volume.** The only
  path from a Bazos title to a Zboží product id runs through a **robots-disallowed** endpoint. The
  Bazos situation is "robots disallows the search endpoints the project depends on" — already
  documented and already accepted under private use. Here it is narrower and more awkward: the site
  has drawn its line **precisely around the capability the idea needs**, while explicitly permitting
  everything either side of it. Choosing to cross that specific line is a different decision from
  the one already taken on Bazos, and it should be made deliberately rather than inherited.
- **GDPR surface: effectively nil, and this is a genuine point in its favour.** Merchant offers
  expose shop names (`Elektroshock.cz`), numeric shop ids and aggregate ratings — companies, not
  natural persons. No seller names, no phone numbers, no addresses. Compared to the Art. 14 exposure
  the Bazos scraper partly dodges by only ever seeing opaque ids
  (`MONETIZATION.md` §6.5), a price-comparison source is close to a
  best case. **This is the one dimension on which Track B beats every Track A candidate** — it just
  isn't enough to carry the rest.

---

## 8. Rate limits / blocking shape observed

**Heureka:** 6 requests total. `robots.txt` 200; `sluzby.heureka.cz` ×2 200; `affiliate.heureka.cz`
200; product page **403 `cf-mitigated: challenge`**; sitemap index **403 `cf-mitigated: challenge`**.
The two 403s were the 3rd and 4th requests — **the challenge is immediate, not a
volume response.** No 429 at any point. Never escalated beyond the interstitial (we did not retry).

**Zboží:** 9 requests, **zero blocks, zero challenges, zero 429s**. The only non-200 was a 302 to
Seznam's `autologin`, which is SSO probing rather than a block. Notably **`bcr.iva.seznam.cz` — the
in-house anti-bot that intercepted every Sbazar content request today
([`SBAZAR.md`](pass1/SBAZAR.md)) — never appeared**, despite the same operator, the same
egress IP, and the same session. Same company, same day, same IP, opposite outcome: Sbazar's listing
surface is defended and Zboží's product surface is not.

Rapid burst, no delay between requests, same URL:
```bash
for i in 1 2 3; do curl -s -A "$UA" --compressed -o /dev/null \
  -w "  burst#$i  HTTP %{http_code}  %{size_download}B  %{time_total}s\n" \
  "https://www.zbozi.cz/_next/data/qKaIrxCbar6XQmnqpuYPF/hledej.json?q=Apple%20iPhone%2013%20128GB"; done
```
```
  burst#1  HTTP 200  187058B  0.614477s
  burst#2  HTTP 200  186991B  0.660192s
  burst#3  HTTP 200  187089B  0.630007s
```
Response sizes vary by ~100 B between identical requests (ad/tracking tokens), confirming these are
freshly rendered, not a cached edge response. Latency flat at ~0.6 s.

**Conclusion: at 6 requests to the same Zboží endpoint (3 spaced + 3 rapid) there is no rate limiting,
no throttling and no challenge.** Per the brief this was not pushed further. ⚠️ Six requests is
*characterisation, not a limit* — it establishes that a low-volume baseline lookup is unlikely to
trip anything, and says nothing about sustained volume.

---

## 9. Zboží.cz — materially different, or strictly worse?

**Materially different, and on transport it is dramatically better — it is the only reason this
assessment has any measured data at all.**

| | Heureka.cz | Zboží.cz |
|---|---|---|
| Content pages from datacenter IP | **403 Cloudflare challenge** | **200, clean** |
| Structured data recovered | **none** (challenge page) | JSON-LD `AggregateOffer` + 272 KB `__NEXT_DATA__` + `/_next/data/` JSON route |
| Canonical product id | not observable | **integer** (`6712502`) |
| Cross-merchant min/max/count | not observable | **yes**, product- and variant-level |
| EAN / GTIN | **not held** for non-media categories (per feed spec) | **absent** (measured) |
| Free-text search | not reachable | works — but **robots-disallowed** |
| Auth | n/a | **none** |
| Rate limiting observed | n/a | **none at 6 requests** |
| Official third-party read API | **no** | **no** — and the merchant Zboží API is being retired into Sklik ⚠️ ASSUMED |
| Seller PII | n/a | **none** — merchants are companies |

Where Heureka is better, on paper: it is the larger and more authoritative Czech comparison engine,
its `robots.txt` does *not* disallow product pages for `*`, and its editorial product catalogue is
generally considered deeper. None of that is measurable from here, and the second point is moot
while Cloudflare denies the pages.

**But the two share the finding that kills the idea.** Zboží's catalogue has the same
currently-sold-new scope, and it has *no* EAN at all where Heureka at least holds EAN for media
categories. Better transport on a source with the same missing join key and the same coverage gap
does not change the verdict — it just means we could *measure* the verdict instead of guessing at it.
**Zboží is the better site and the same answer.**

---

## 10. Raw probe log

15 requests, all from `185.242.6.116`, 2026-08-22 ~15:05–15:20 UTC. `$UA` throughout:
`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36`

| # | Request | Status | Bytes | Time | Note |
|---|---|---|---|---|---|
| R1 | `GET https://www.heureka.cz/robots.txt` | 200 | 3,822 | 0.63 s | 186 lines |
| R2 | `GET https://www.zbozi.cz/robots.txt` | 200 | 11,992 | 0.18 s | 444 lines |
| R3 | `GET https://mobilni-telefony.heureka.cz/apple-iphone-13-pro-1tb/` | **403** | 15,573 | 0.19 s | `cf-mitigated: challenge` |
| R4 | `GET https://www.heureka.cz/sitemaps/sitemap_index.xml` | **403** | 15,498 | 0.15 s | same challenge |
| R5 | `GET https://sluzby.heureka.cz/napoveda/marketplace-api/` | 200 | 85,189 | 0.35 s | merchant API docs |
| R6 | `GET https://sluzby.heureka.cz/napoveda/xml-feed/` | 200 | 84,100 | 0.47 s | feed spec, EAN rule |
| R7 | `GET https://affiliate.heureka.cz/Files/Heureka_affiliate_navod_pbl.pdf?ver=2` | 200 | 215,676 | — | `application/pdf`, 4 pp |
| R8 | `GET https://www.zbozi.cz/vyrobek/apple-iphone-13/` | **302** | 0 | 0.17 s | → `login.seznam.cz/api/v1/autologin?service=zbozi&return_url=…%3Fnoredirect%3D1` |
| R9 | `GET https://www.zbozi.cz/vyrobek/apple-iphone-13/?varianta=128-gb-cerny&noredirect=1` | 200 | 105,362 gz / 454,559 raw | 1.31 s | JSON-LD + `__NEXT_DATA__` |
| R10 | `GET /_next/data/qKaIrxCbar6XQmnqpuYPF/hledej.json?q=Macbook%20Pro%2013%202020%20i5%2016GB` | 200 | 17,860 | 0.31 s | **0 products, 3 offers** ⚠️ robots-disallowed |
| R11 | `GET /_next/data/…/hledej.json?q=Apple%20iPhone%2013%20128GB` | 200 | 184,428 | 1.37 s | **48 products** ⚠️ robots-disallowed |
| R12 | `GET /_next/data/…/hledej.json?q=Apple%20MacBook%20Pro%2013%202020` | 200 | 374,447 | 0.91 s | **1 product (a case)**, 47 offers ⚠️ robots-disallowed |
| R13 | burst 1/3, same URL as R11 | 200 | 187,058 | 0.61 s | ⚠️ robots-disallowed |
| R14 | burst 2/3 | 200 | 186,991 | 0.66 s | ⚠️ robots-disallowed |
| R15 | burst 3/3 | 200 | 187,089 | 0.63 s | ⚠️ robots-disallowed |

Not counted against the 15 (not requests to heureka.cz / zbozi.cz): one `api.ipify.org` egress check,
and four search-engine queries used only to locate candidate URLs and orient on the existence of an
official API. Every factual claim above is sourced from R1–R15; search results are used only where
explicitly marked ⚠️ ASSUMED.

**Reproducing the two decisive probes:**
```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'

# buildId rotates every Zbozi deploy — re-scrape it, never hardcode:
BUILD=$(curl -s -A "$UA" --compressed \
  "https://www.zbozi.cz/vyrobek/apple-iphone-13/?varianta=128-gb-cerny&noredirect=1" \
  | grep -o '"buildId":"[^"]*"' | cut -d'"' -f4)

# The join test. type=="product" -> joined; type=="offer" -> not joined.
curl -s -A "$UA" --compressed \
  "https://www.zbozi.cz/_next/data/$BUILD/hledej.json?q=Macbook%20Pro%2013%202020%20i5%2016GB" \
  | python3 -c "import json,sys,collections
d=json.load(sys.stdin)['pageProps']['data']
print('totalResults', d['totalResults'])
print(collections.Counter(x['type'] for x in d['results']['results']))"
```

---

## 11. What I could not determine

Ordered by how much it would change the verdict.

1. **Whether the coverage gap generalises — the single most important gap.** The claim "the canonical
   catalogue holds only currently-sold-new products" is measured on **one product** (a 2020 MacBook
   Pro, via two queries, R10 and R12). It is the finding that turns DEFER into REJECT and it has the
   thinnest base of anything here.
   **The falsifying test, ~6 requests:** query Zboží for three used-goods archetypes at known age —
   e.g. `Makita DHP484` (a current-production drill, should resolve), `Bosch GSB 18-2-LI` (a
   discontinued 2015-era drill, should not), and `Apple iPhone 11 64GB` (a 2019 phone, the
   interesting middle case) — and count `type=="product"` in each response. If discontinued-but-
   recent items *do* retain canonical entries, the verdict should be revisited as DEFER for
   electronics. **Do this before acting on the REJECT.**
2. **Whether Heureka blocks a residential IP.** Everything about Heureka's transport is unknown
   because of a Cloudflare challenge served to a datacenter ASN. The `critical-ch` client-hints
   header suggests a browser-fingerprint check rather than pure IP reputation, so a residential
   connection may well be served — **but this is not proven either way**, and no bypass was
   attempted. This is the same egress problem that left Aukro and the Bazos sister-sites undetermined
   in [`RANKING.md`](pass1/RANKING.md); one residential re-probe session would resolve all four at once.
3. **What `Allow: /api/` on zbozi.cz actually permits.** Zboží's robots.txt explicitly allows an
   `/api/` surface (twice), which is a strong hint that a supported JSON API exists — and it would
   sit *outside* the `Disallow: /*?q=` search ban that is the idea's main compliance problem. The
   product HTML contains **zero** `/api/` literals; recovering the paths needs a JS-bundle grep
   (RESEARCH_BRIEF §4b step 2) across the ~30 `/_next/static/chunks/*.js` files. **Not attempted —
   budget.** This is the highest-value remaining transport question and could partly reopen §7c.
4. **Terms of Service for both sites. Not fetched at all.** §7 is robots.txt only. Heureka's terms
   live under `heureka.group/cs/podminky-pouzivani/`; Zboží's under Seznam's general terms. An
   API-use or anti-automation clause on either would matter independently of robots.txt, and
   RESEARCH_BRIEF §3a asks for verbatim Czech quotes that this file does not have.
5. **Whether Zboží's canonical product ids are stable over time.** `id: 6712502` looks like a durable
   catalogue key, but nothing was measured across time. If ids churn on re-pairing (Heureka's docs
   say a name change *unpairs* everything), a cached baseline table would silently rot.
6. **Heureka's price shape.** Whether Heureka exposes min/max/merchant-count like Zboží is
   **NOT DETERMINED** — the pages never rendered. Its `/srovnani-produktu/` path name implies a
   comparison surface, and it is robots-disallowed for `*` regardless.
7. **Rate limits under sustained load.** Six requests establishes only that a low-volume lookup is
   safe. Nothing about hundreds/day was tested, per the brief's instruction not to push.
8. **The `bcr.iva.seznam.cz` asymmetry.** Zboží and Sbazar share an operator and Sbazar's content
   surface was defended today while Zboží's was not. Whether that is per-property policy, per-path,
   or luck was not investigated — it bears on how durable Zboží's open transport is.

---

# ⚠️ CORRECTION — falsifying test run 2026-08-22, from a residential IP

> This section was added by the lead after running the ~6-request falsifying test that §11 of this
> document correctly asked for. **It overturns the category conclusion above.** The verdict on
> Heureka's *official route* and on the *discontinued-goods* gap stands; the claim that the
> catalogue "almost certainly" does not serve tools does not.

## What was tested

Zboží.cz search, via `__NEXT_DATA__` on `https://www.zbozi.cz/hledani/?q=…`
(`props.pageProps.data.productsResults.products`). Three queries, residential T-Mobile CZ IP:

| Query | Canonical products | Top match |
|---|---|---|
| `Makita DHP484` (current-model tool) | **4** | `Makita DHP484Z Li-ion 18 V`, id `5325309` |
| `Bosch GSB 18-2-LI` (current-model tool) | **30** | `BOSCH Professional GSB 185-Li` |
| `Macbook Pro 13 2020` (discontinued laptop) | **1** | `Epico Shell Cover 2018/2020 13"` — **a case** |

## What this changes

**The discriminator is product lifecycle, not category.** The original analysis inferred from one
discontinued MacBook that the catalogue is thin outside current phones — and generalised that to
tools. The measurement says otherwise: tools match *better* than laptops, because tool models stay
in production for years while laptop and phone models churn annually and drop out of the
new-goods catalogue.

**This matters more than a normal correction, because it inverts RESEARCH_BRIEF §2c's own
assumption.** The brief states a reference-price baseline "transfers well for globally fungible
goods — phones, laptops, GPUs — and poorly for furniture, tools and bikes." For a *new-price*
baseline the opposite is true, and it matters because **tools are the single biggest measured
opportunity in Track A** (Sbazar `stavebnictvi-naradi`, 26,492 active, 3.43× Bazos).

## The payload is genuinely rich for tools

Measured fields on `Makita DHP484Z` (id `5325309`):

| Field | Value | Use |
|---|---|---|
| `minPrice` / `maxPrice` | `292000` / `539100` | **hundredths** → 2,920–5,391 CZK. ⚠️ Divide by 100 — this is a second, different price-scaling trap from Aukro's float |
| `shopCount` | `44` | Cross-merchant breadth — the §2c "price range" question, answered |
| `brandName` | `Makita` | **Structured brand**, not free text (`BACKLOG_IDEAS.md` #4) |
| `parameters` | `['Ruční', 'Typ pohonu akumulátorový', '2000 ot/min.', …]` | Structured attributes |
| `rating` / `ratingCount` | `100` / `16` | Quality signal |
| `priceBeforeDrop` / `…Date` | `500000` / `1787316730` | A price-history reference point |
| `availability` | `in_stock` | Still-sold check |
| `id` | `5325309` | Stable integer product id |

## What still stands from the original assessment

- **No official third-party route.** All Heureka APIs are merchant-side. Unchanged.
- **No EAN/GTIN exposed.** Unchanged — the join is name-based.
- **Discontinued goods are a real gap, and the failure is dangerous rather than empty.**
  `Macbook Pro 13 2020` did not return "no results" — it returned *a phone case*. A naive top-1
  match would baseline a laptop at 999 Kč. Any consumer must validate the match, not trust rank 1.
- **⚠️ Near-miss matching is a real error mode, newly measured.** `Bosch GSB 18-2-LI` returned
  `GSB 185-Li` — a *different model* — as its top hit. So even in the well-covered tool case,
  fuzzy name matching returns confident wrong answers. The join needs a validation step
  (brand + model-token agreement at minimum), not just a search call.
- **Zboží's robots.txt allows the product page but disallows `/*?q=` free-text search**, so the
  join step remains the disallowed step. Unchanged, and the probes above hit that pattern.

## Revised verdict

**DEFER, not REJECT** — and specifically: *viable as a new-price baseline for current-model goods,
with tools the best-served category; useless for discontinued electronics; blocked on a join
validation step that does not exist yet.* Its value is still gated on the same prerequisite as
everything else in Track B: `Ad` has no brand/model field to join *from*
(`EBAY.md` §4). Fix that first and this becomes cheap; leave it and this stays unusable.

> **Update 2026-09-18 - the gate turned out to be the validator, not the schema.** The "join
> validation step that does not exist yet" was built: `refprice/resolution/validate.py` gates every
> candidate on brand, model-code (prefix-tolerant, so `DHP484` matches `DHP484Z`), bundle words,
> contrast tokens and `shopCount >= 2`, resolving from the ad's free-text title with **no**
> brand/model column on `Ad`. Shipped 2026-09-16; ⚠️ 0 `RefProduct` and 0 `RefProductLink` rows in
> production on 2026-09-18, so it is built and not yet exercised.
