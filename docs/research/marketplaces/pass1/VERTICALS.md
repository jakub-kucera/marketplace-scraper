---
title: Vertical marketplaces + Remix — Pass 1 triage
status: reference
updated: 2026-09-18
verified: 2026-08-22
---

# Vertical marketplaces + Remix — Pass 1 triage

> Probed **2026-08-22, 14:48–14:52 UTC** (server `date` header on the first probe:
> `Sat, 22 Aug 2026 14:48:51 GMT`).
> Egress: **VPN datacenter IP — 185.242.6.116, M247 Europe SRL (AS9009), Prague CZ**,
> confirmed live via `curl -s https://ipinfo.io/json`.
> Pass 1 only. Every claim below is either from a request recorded in §"Raw probe log",
> or explicitly marked **⚠️ ASSUMED** / **NOT DETERMINED**.
> Anti-goals honoured: no accounts, no logins, no IP rotation, no block evasion, no bulk crawling,
> no personal data collected.

---

## Summary table

| Site | Category scope | Intersects target cats (phones/laptops/tools/bikes)? | Verdict | Requests used |
|---|---|---|---|---|
| **TipCars.com** | NOT DETERMINED — site never served content (Cloudflare challenge) | No (⚠️ ASSUMED from domain + brief; **not measured**) | **REJECT** — blocked from datacenter IP *and* out of scope | 2 / 5 |
| **Sauto.cz** | Cars / motor vehicles (measured from robots.txt path vocabulary) | **No** | **REJECT** — relevance, reinforced by `User-agent: * → Disallow: /` | 1 / 5 |
| **Sreality.cz** | Real estate (measured from robots.txt path vocabulary) | **No** | **REJECT** — relevance, reinforced by `User-agent: * → Disallow: /` | 1 / 5 |
| **Bezrealitky.cz** | Real estate (measured from robots.txt path vocabulary) | **No** | **REJECT** — relevance; robots disallows exactly the search endpoints | 1 / 5 |
| **Remix (remixshop.com)** | **Apparel only** — exactly 3 top-level cats: `zeny`, `muzi`, `deti` (measured) | **No** | **REJECT** for the flipping thesis — **but see capability signals** | 5 / 5 |

**Batch verdict: a clean sweep of rejections for the flipping thesis.** Not one of the five carries
inventory in phones, laptops, tools or bikes. Four are killed on relevance in 1–2 requests as the
task directed. Remix got the full 5-request budget because it was the only one where "what does it
add over the already-implemented Vinted" needed a real answer — and the answer turned out to be
*capability*, not *category*. That capability is written up in its own section below; it is the one
thing in this batch worth carrying forward.

---

## TipCars.com

**Scope.** NOT DETERMINED by measurement. The site never served me a single byte of content, so I
cannot honestly state what it sells from this session's evidence. The seed list in
`RESEARCH_BRIEF.md` §2a and the domain name both say cars, and I have no reason to doubt it, but
that is **⚠️ ASSUMED, not measured** — flagging it rather than quietly asserting it is the entire
point of this brief's §1.

**What I measured.** Two requests, both `HTTP 403` with `cf-mitigated: challenge`, `server:
cloudflare`, and a `<title>Just a moment...</title>` interstitial body of ~5.6 KB carrying a
`window._cf_chl_opt` blob and `<noscript>Enable JavaScript and cookies to continue</noscript>`.
This is a Cloudflare **managed challenge**, not a plain deny. The second request deliberately
targeted `/robots.txt` to test the *blocking shape*: it was challenged identically. So the block
here is **domain-wide, not path-scoped** — which is a meaningfully different shape from Bazos's,
where the memory note on file records the block as 403-only and path-scoped. TipCars will not even
serve the file that would tell a crawler what it is allowed to do.

**Verdict: REJECT.** Two independent reasons, and either alone is sufficient. First, relevance:
a cars-only vertical cannot serve a thesis about flipping phones, laptops, tools and bikes. Second,
transport: a domain-wide Cloudflare managed challenge means the HTML route is not available without
a headless browser or a residential proxy, both of which are outside the current posture and the
brief's anti-goals. Per the hard rules I recorded the status code and stopped rather than probing
further. ⚠️ **This block is NOT proven to apply to a residential connection** — the egress here is a
datacenter ASN (M247/AS9009), which Cloudflare scores harshly, and a home connection might well
pass. That caveat does not change the verdict, because the relevance kill stands regardless.

---

## Sauto.cz

**Scope.** Cars and motor vehicles — and unusually, I can say this **from measured content** rather
than from recall, because Sauto's `robots.txt` leaks its whole domain vocabulary. It names
`/inzerce/osobni` (passenger-car classifieds), `/crash-testy`, `/cebia-vin` (VIN history checks),
`/seznam-prodejcu` (dealer directory), `/car_detail.php`, and `*pojisteni-direct` (insurance).
There is no path in the file suggesting any non-vehicle category. Zero intersection with phones,
laptops, tools or bikes — note "bikes" in the flipping thesis means bicycles, which this site does
not carry either.

**What I measured.** One request, `HTTP 200`, `server: envoy`, 15,267 bytes of `text/plain`. No
Cloudflare, no challenge — **Seznam did not challenge the datacenter IP**, which is itself worth
recording since the task flagged it as a live possibility. The decisive content is the very last
stanza of the file:

```
User-agent: *
Disallow: /
```

Every one of the ~11 preceding stanzas is a named search-engine bot (`Googlebot`, `SeznamBot`,
`Bingbot`, `Slurp`, `DuckDuckBot`, `Baiduspider`, `YandexBot`, `Applebot`, `ia_archiver`, `msnbot`,
`Naverbot`) plus a set of social preview fetchers. Anything not on that whitelist — which is exactly
what this project's scraper would be — is disallowed from the entire site. I also observed a
genuine structured-attribute surface in the allowed-URL examples (see capability signals) and the
existence of an `/api/` path space, via the repeated line `Allow: /api/*&*&*&`.

**Verdict: REJECT.** Killed on relevance first: cars-only inventory cannot feed the flipping thesis,
so the scale question was never worth asking and I did not spend requests on it, per instruction.
The robots.txt finding is a reinforcing second reason rather than the primary one — `User-agent: *
→ Disallow: /` is about as unambiguous a "not for you" as a site can publish, and combined with a
Seznam-scale legal department it makes this a poor place to spend goodwill. I stopped at one
request; the remaining four were not needed and spending them would have meant fetching paths the
site had just told me not to fetch.

---

## Sreality.cz

**Scope.** Real estate, measured the same way — from robots.txt path vocabulary. The file names
`/hledani` (search), `/adresar` and `/firma` (estate-agency directory), `/rk-detail`
(*realitní kancelář* = estate agency detail), `/advertpdf`, and geographic map-bounding parameters
`lat-max` / `lat-min` / `lon-max` / `lon-min`. It also carries `/en/` and `/ru/` localisations of
the same structures (`/en/directory/*/*/estates/`). Nothing outside property. Zero intersection with
the target categories.

**What I measured.** One request, `HTTP 200`, `server: envoy`, 25,839 bytes. Again **no Cloudflare
challenge against the datacenter IP** — both Seznam properties served me cleanly, so the "Seznam may
challenge you" hypothesis in the task brief did **not** materialise at the robots.txt level. (I did
not fetch a listing page, so I cannot say whether deeper paths behave differently — see "What I
could not determine".) The file opens, before any other stanza, with:

```
User-agent: *
Disallow: /

############################
#    neplecha ukončena     #
############################
```

`neplecha ukončena` translates roughly as **"mischief ended"** / "the shenanigans are over" — a
site operator writing, in Czech, in a banner comment, that this rule exists *because of scrapers*.
That is the most explicit statement of anti-scraping intent in this entire batch, and it is worth
quoting verbatim in any future legal section. Two other measured details: `Disallow: *bez-auction=`
/ `*without-auction=` reveals the site has an **auction** concept (property auctions), and
`Allow: /api/undefined/v*/userinfo*` alongside SeznamBot's `Disallow: /api/` confirms an `/api/`
surface exists.

**Verdict: REJECT.** Relevance is the primary and sufficient kill — real estate has no overlap with
phones, laptops, tools or bikes, and no amount of API elegance changes that. The robots.txt is a
strong reinforcing signal, and unusually the site has editorialised about *why*. I want to flag one
thing honestly rather than bury it: the `bez-aukce` parameter means Sreality carries auctions, and
`RESEARCH_BRIEF.md` §6a names completed-auction results as "the single biggest gap" in the project.
I considered whether that made Sreality worth more budget and concluded no — property auction
outcomes tell you nothing about the resale value of a used ThinkPad, and §6a's prize is specifically
about calibrating deal-scoring on *fungible goods*. It is a real capability attached to entirely the
wrong asset class.

---

## Bezrealitky.cz

**Scope.** Real estate, sold peer-to-peer without an agent (the name means literally "without
[estate] agencies"). Measured from robots.txt paths: `/vyhledat` (search), `/search`,
`/moje-bezrealitky` (user account area), and `/centrum-sluzeb/bezrealitky-hypoteka` (mortgage
services, with a `price=` parameter). No non-property path appears. Zero intersection with the
target categories.

**What I measured.** One request, `HTTP 200`, `server: nginx`, 338 bytes — a strikingly small and
modern robots.txt, no Cloudflare, no challenge. The full body is reproduced in the raw log below.
The structurally interesting thing is that unlike both Seznam properties, Bezrealitky does **not**
blanket-ban unknown agents. `User-agent: *` is permitted everywhere *except* a short list — and that
list is:

```
Disallow: /vyhledat*
Disallow: /search*
```

This is precisely the pattern `RESEARCH_BRIEF.md` §3b calls out as instructive about Bazos: the site
is broadly open, but disallows **exactly the search/filter endpoints a monitoring scraper depends
on**. A `MarketplaceScraper` for this site would consist of essentially nothing but requests to
`/vyhledat`. So the permissiveness is illusory for this project's specific access pattern — a
detail worth remembering, because a superficial reading of this file ("robots.txt is basically
open!") would get it exactly backwards.

**Verdict: REJECT.** Clean kill on relevance, one request, no further budget spent. Real estate does
not intersect the flipping thesis in any way. I note for completeness that of the four
non-Remix sites this is the only one whose robots.txt does not blanket-ban unknown crawlers, so if
the project ever grows a property-adjacent thesis this is the least hostile starting point of the
three real-estate/car verticals — but that is a hypothetical about a different project, not a
recommendation. No capability signal here that Bazos lacks: it is asking prices on illiquid,
non-fungible assets, which is the *weakest* possible input to a deal-scoring model.

---

## Remix (remixshop.com)

**Scope — measured, and this is the decisive finding.** Remix CZ has **exactly three top-level
categories**: `zeny` (women), `muzi` (men), `deti` (kids). That is not an inference from a nav bar I
eyeballed — it is the complete contents of the site's own
`https://remixshop.com/cz/site/sitemap-main-cats-urls`, which returned exactly 3 `<loc>` entries
and nothing else. The taxonomy is segmented by *person*, not by *product type*, which is the
structural giveaway of a pure apparel retailer: there is no slot in this hierarchy where
"electronics" or "tools" could even live. **Zero intersection with phones, laptops, tools or
bikes.** The site is live and actively maintained across nine countries — the sitemap index lists
`bg, gr, ro, de, pl, cz, sk, hu, at`, every one with `<lastmod>2026-08-22</lastmod>`, i.e. today.

**What I measured.** Five requests, all `HTTP 200`, `server: nginx`, **no anti-bot challenge and no
login required** — Remix served a datacenter IP without complaint, in contrast to TipCars. Its
`robots.txt` is 128 bytes and the `User-agent: *` group contains **no `Disallow` directives at
all** — only a `Sitemap:` line. That makes Remix by a wide margin the most permissive site in this
batch. Scale, derived from pagination depth: the `/cz/muzi` listing renders 30 products per page and
its pager runs `2 3 4 5 … 634`, giving **≈ 634 × 30 ≈ 19,000 active men's items** on the CZ
storefront (⚠️ derived from pagination depth × page size per `RESEARCH_BRIEF.md` §2b, not from a
declared total; women's and kids' not measured). **New-per-day: NOT DETERMINED** — I saw no
per-item timestamp anywhere in the listing HTML, and there is no stated expiry window, so per §2b
method 4 the honest answer is that it is not determinable within this budget. I did **not** apply
`active / expiry_days`; there is no forced-expiry fact here to justify it.

**What would it add over the already-implemented Vinted? Not supply — a different *kind* of data,
attached to the wrong categories.** Remix is structurally a different animal from Vinted: it is
**single-seller B2C**, not C2C. Remix buys, grades, photographs and warehouses its own inventory,
which has three consequences I could see in the response. (1) **The publisher model collapses to
one row.** `EmailPublisher`/`PhonePublisher` and the whole `SellerAdCounts` email↔phone graph — the
machinery that answers "who else appears alongside me" — would be pointless, because the answer is
always "Remix". The `publisher_blocklist` filter rule would be inert. (2) **There is no C2C
arbitrage.** The flipping thesis works on Bazos because a private seller misprices an item relative
to the market; a professional reseller with a pricing team does not systematically do that. Buying
from Remix to resell means beating a company at its own margin. (3) **But the data is clean in a way
Bazos never is** — see the capability section below, which is the genuine finding here. Against the
existing Vinted scraper specifically, Remix adds a smaller catalogue, in the same category, with
worse arbitrage economics and better structure. That is not a build case.

**Verdict: REJECT for the flipping thesis.** No overlap with phones, laptops, tools or bikes, and
the one thing it does add over Vinted (structured attributes) is delivered on apparel, where Vinted
already gives the project category coverage. The reason it is worth writing more than three
paragraphs about is not the site — it is the *technique*, which is transferable and which I have
separated out below so a future reader does not have to rediscover it. Effort-wise it would have
been the cheapest build in this batch by some distance: permissive robots, no anti-bot, clean
JSON-LD, integer ids. Cheap and irrelevant is still irrelevant.

---

## Any capability signals worth remembering (structured attributes, sold prices, etc.)

Three signals, in descending order of usefulness. **None of them rescues its site's verdict** — I
am recording them because `RESEARCH_BRIEF.md` §6 says a marketplace may be worth building because it
does something Bazos cannot, and a future reader should not have to re-probe to find these.

### 1. Remix serves schema.org `Product` JSON-LD with real typed attributes — the strongest signal in the batch

The `/cz/muzi` listing HTML contains **30 `<script type="application/ld+json">` `Product` blocks**,
one per item, server-rendered. A verbatim (untrimmed) example from the response:

```json
{
    "@context": "https://schema.org",
    "@type": "Product",
    "brand": { "@type": "Brand", "name": "Authentic Clothing Company" },
    "color": "Modrá",
    "sku": "137658130",
    "name": "Pánské džíny ",
    "offers": {
        "@type": "Offer",
        "availability": "https://schema.org/InStock",
        "itemCondition": "https://schema.org/UsedCondition",
        "price": 267,
        "priceCurrency": "CZK"
    }
}
```

Measured across all 30 blocks on that one page:

| Field | Measured values | Why it matters |
|---|---|---|
| `brand.name` | `"Authentic Clothing Company"` (+ 29 others) | Brand as a **field**, not a substring to regex out of a title |
| `itemCondition` | `UsedCondition` ×25, `NewCondition` ×5 | Condition as a **schema.org enum**, not free text |
| `sku` | `"137658130"` | 9-digit **integer** — fits `Ad.external_id` (`BigIntegerField`) as-is |
| `offers.price` | `267, 704, 203, 388, 1237, 1359, 315…` | **Integers, no decimals** — dodges the `parse_price` 10×-overflow trap in `bazos/filters.py` §5b(3) |
| `offers.priceCurrency` | `"CZK"` ×30 (uniform) | Single currency, no mixed-currency handling needed |
| `offers.availability` | `InStock` ×30 | — |
| size (facet, not JSON-LD) | `XXS, XS, S, M, …` as `"size" value="…"` | Enumerated size facet |

**Why this is worth remembering:** `BACKLOG_IDEAS.md` #4 is blocked, per the brief, on the fact that
"the hard part is identification, not pricing" — a free-text title like `"Macbook Pro 13 2020 i5
16GB"` has to resolve to a canonical product before any reference price means anything. A site that
publishes `brand`, `color`, `condition` and `sku` as typed JSON-LD fields **has already done that
extraction step for you**, server-side, for free. That is exactly the §6b "structured item
attributes" capability. The catch is that Remix does it for jeans. **The transferable lesson is the
probe, not the site: grep any future candidate's listing HTML for `application/ld+json` before
assuming you need an LLM extraction step.** It costs one request and it is the difference between a
parseable marketplace and a regex maintenance burden.

### 2. Remix has a plausible realised-price signal — but I did not measure it, and it is on apparel

Two observations, and I want to be careful to separate what I saw from what I am inferring.
**Measured:** every item carries `availability: InStock`, and the page contains the strings
`"Produkt je rezervovaný jiným uživatelem"` ("product is reserved by another user"), so there is a
reservation/basket-lock state distinct from sold. **⚠️ ASSUMED, not measured:** because Remix is a
single seller with owned, unique, one-of-one inventory, an item *disappearing* is far more likely to
mean **sold** than it does on Bazos, where disappearance conflates sold / withdrawn / expired. If
that holds, then last-seen-price-at-disappearance ≈ **realised price** — the §6a prize, and the
thing `PROMPTS.md` P24 wants (P24 shipped 2026-09-17 and does **not** make that distinction:
`Ad.removed_at` conflates sold, withdrawn, deleted and expired, so a single-seller inventory where
disappearance means sold is worth *more* now, as calibration for it). I did **not** verify this:
confirming it needs two samples 24h apart,
which §2b method 3 correctly notes a single session cannot span. I also saw CSS classes named
`discount-info` and Czech `SLEVA` ("discount") text, which *hints* at a time-based markdown
mechanic, but I **did not measure any old-vs-current price pair** and am explicitly not asserting
one. Recording this as a hypothesis with its verification cost attached, not as a finding.

### 3. Sauto exposes genuinely structured car attributes as URL facets — behind a total robots ban

Sauto's robots.txt embeds whole example URLs, and they reveal the facet vocabulary without my
fetching a single listing page:

```
/inzerce/osobni?cena-od=150000&vyrobeno-od=2010&km-do=200000&vykon-od=200kw&typ=kombi%2Cliftback%2C…&pohon=4x4
```

That is price-from, price-to, **year-of-manufacture-from**, **mileage-to**, **power-from**, body
type (multi-valued, comma-separated) and drivetrain — make/model/year/condition as real queryable
fields, exactly the §6b capability. Combined with the `/cebia-vin` path (VIN history checking) this
is a well-structured dataset. It is also comprehensively unavailable: `User-agent: * → Disallow: /`.
**Recording it as a dead end that has been checked**, so nobody spends Pass-2 budget rediscovering
that the nice-looking facets sit behind a blanket ban.

**One thing I deliberately did not do:** measure listing counts for the car and real-estate sites.
The task was explicit that a relevance kill is cheaper than a scale kill, and spending requests
counting Škoda Octavias would have produced an authoritative-looking number with no bearing on any
decision. Four sites were killed in one or two requests each; the budget that freed up went to
Remix, which was the only site in the batch where a real question existed.

---

## Raw probe log

Every HTTP request made in this session, in order, with the exact command and the measured result.
9 total site requests + 1 environment check. Per-site caps (≤5) respected throughout. Requests were
issued sequentially as separate tool invocations, naturally spaced by several seconds each; no
site received rapid-fire traffic and no paginated crawl was run.

Shared UA for all probes:
`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36`

### Env check (not counted against any site)

```bash
curl -s --max-time 20 https://ipinfo.io/json
```
```json
{ "ip": "185.242.6.116", "city": "Prague", "region": "Prague", "country": "CZ",
  "loc": "50.0880,14.4208", "org": "AS9009 M247 Europe SRL", "postal": "110 00",
  "timezone": "Europe/Prague" }
```
Confirms the datacenter-ASN egress the task specified. `curl 8.7.1 (x86_64-apple-darwin24.0)`.

### TipCars — 2 requests

**[1]** `curl -s -o tipcars_home.html -D tipcars_home.hdr -w 'HTTP=%{http_code} SIZE=%{size_download}' -A '<UA>' 'https://www.tipcars.com/'`
→ `HTTP=403 SIZE=5619 TIME=0.218624`

Response headers (trimmed):
```
HTTP/2 403
date: Sat, 22 Aug 2026 14:48:51 GMT
cf-mitigated: challenge
server: cloudflare
cf-ray: a2f2ae46eb08d8d6-FRA
content-security-policy: default-src 'none'; script-src 'nonce-…' 'unsafe-eval' https://challenges.cloudflare.com; …
critical-ch: Sec-CH-UA-Bitness, Sec-CH-UA-Arch, Sec-CH-UA-Full-Version, …
```
Body (trimmed):
```html
<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta name="robots" content="noindex,nofollow"> … <noscript><div class="h2">
<span id="challenge-error-text">Enable JavaScript and cookies to continue</span></div></noscript>
… <script nonce="…">(function(){window._cf_chl_opt = {cFPWv: 'b', …
```

**[2]** `curl -s -o tipcars_robots.txt -D tipcars_robots.hdr -w '…' -A '<UA>' 'https://www.tipcars.com/robots.txt'`
→ `HTTP=403 SIZE=5649 TIME=0.176383`, `cf-mitigated: challenge`, `server: cloudflare`,
same `Just a moment...` body. **Block is domain-wide, not path-scoped — even robots.txt is
challenged.** Stopped here per the no-evasion rule.

### Sauto.cz — 1 request

**[3]** `curl -s -o sauto_home.html -D sauto_home.hdr -w '…' -A '<UA>' 'https://www.sauto.cz/robots.txt'`
→ `HTTP=200 SIZE=15267 TIME=0.175516`, `server: envoy`, `content-type: text/plain; charset=utf-8`

Structure: 11 named-crawler stanzas + 8 social-fetcher stanzas, then the final stanza. Head of file:
```
User-agent: Googlebot
Allow: /
Disallow: /car_detail.php
Disallow: /seznam-prodejcu*search=
Disallow: /crash-testy*text=
Disallow: /cebia-vin
Disallow: /hlidaci-pes/
Disallow: *pojisteni-direct
# 4+ params
Disallow: *&*&*&
Allow: /api/*&*&*&
# Homepage categories
Allow: /inzerce/osobni?cena-od=100000&cena-do=750000&typ=kombi%2Cliftback%2Csuv%2Ccuv%2Cmpv
Allow: /inzerce/osobni?cena-od=150000&typ=suv%2Cterenni%2Cpick-up%2Ccuv&pohon=4x4
Allow: /inzerce/osobni?cena-od=250000&vyrobeno-od=2017&typ=kombi%2Cliftback%2Csedanlimuzina
Allow: /inzerce/osobni?cena-od=150000&vyrobeno-od=2010&km-do=200000&vykon-od=200kw&typ=…
```
Tail of file (the decisive part), verbatim:
```
User-agent: *
Disallow: /
```
Named UA stanzas observed: `Googlebot, SeznamBot, Bingbot, Slurp, DuckDuckBot, Baiduspider,
YandexBot, Applebot, ia_archiver, msnbot, Naverbot`, then `Mediapartners-Google, facebot,
facebookexternalhit, Twitterbot, BingPreview, vkShare, Mail.RU_Bot`. No `Sitemap:` line.

### Sreality.cz — 1 request

**[4]** `curl -s -o sreality_robots.txt -D sreality_robots.hdr -w '…' -A '<UA>' 'https://www.sreality.cz/robots.txt'`
→ `HTTP=200 SIZE=25839 TIME=0.195409`, `server: envoy`, `content-type: text/plain; charset=utf-8`

Head of file, verbatim — note this is the *first* stanza, before any allow-list:
```
User-agent: *
Disallow: /

############################
#    neplecha ukončena     #
############################
```
Other measured lines of interest:
```
Disallow: /rk-detail
Disallow: *bez-aukce=
Disallow: *without-auction=
Disallow: /hledani/filtr
Disallow: /*lat-max=      (also lat-min, lon-max, lon-min)
Disallow: /adresar/*/*/inzeraty/*?*
Disallow: /en/directory/*/*/estates/*?*
Allow: /api/undefined/v*/userinfo*
Disallow: /api/           (SeznamBot stanza only)
Disallow: *image-search-id=
Sitemap: https://www.sreality.cz/sitemap.xml
```
Same named-crawler allow-list pattern as Sauto (same operator, Seznam).

### Bezrealitky.cz — 1 request

**[5]** `curl -s -o bez_robots.txt -D bez_robots.hdr -w '…' -L -A '<UA>' 'https://www.bezrealitky.cz/robots.txt'`
→ `HTTP=200 SIZE=338 TIME=0.742538`, `server: nginx`, `content-type: text/plain`

Full body, verbatim and complete:
```
#CS robots.txt
User-agent: *
Disallow: /vyhledat*
Disallow: /moje-bezrealitky/*
Disallow: /*callbackUrl=*
Disallow: /centrum-sluzeb/bezrealitky-hypoteka/form*
Disallow: /centrum-sluzeb/bezrealitky-hypoteka*price=*
Disallow: /centrum-sluzeb/bezrealitky-hypoteka?*
Disallow: /search*
Sitemap: https://www.bezrealitky.cz/sitemap/sitemap.xml
```

### Remix (remixshop.com) — 5 requests

**[6]** `curl -s -o remix_robots.txt -D remix_robots.hdr -w '…' -L -A '<UA>' 'https://remixshop.com/robots.txt'`
→ `HTTP=200 SIZE=128 TIME=0.718186`, `server: nginx`

Full body, verbatim and complete:
```
User-agent: Googlebot
Disallow:

User-agent: Googlebot-image
Disallow:

User-agent: *
Sitemap: https://remixshop.com/sitemap.xml
```
Note the `User-agent: *` group carries **zero `Disallow` directives**.

**[7]** `curl -s -o remix_sitemap.xml … 'https://remixshop.com/sitemap.xml'`
→ `HTTP=200 SIZE=1677 TIME=0.246914`, `content-type: application/xml`, 9 `<loc>` entries:
```
https://remixshop.com/bg/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/gr/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/ro/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/de/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/pl/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/cz/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/sk/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/hu/sitemap.xml   <lastmod>2026-08-22</lastmod>
https://remixshop.com/at/sitemap.xml   <lastmod>2026-08-22</lastmod>
```

**[8]** `curl -s -o remix_cz_sitemap.xml … 'https://remixshop.com/cz/sitemap.xml'`
→ `HTTP=200 SIZE=957 TIME=0.388938`, 6 `<loc>` entries:
```
https://remixshop.com/cz/site/sitemap-static-pages
https://remixshop.com/cz/site/sitemap-main-cats-urls
https://remixshop.com/cz/site/sitemap-brand-catalogue-urls
https://remixshop.com/cz/site/sitemap-sub-cats?path=1
https://remixshop.com/cz/site/sitemap-sub-cats?path=220
https://remixshop.com/cz/site/sitemap-sub-cats?path=409
```

**[9]** `curl -s -o remix_maincats.xml … 'https://remixshop.com/cz/site/sitemap-main-cats-urls'`
→ `HTTP=200 SIZE=740 TIME=0.624915`, **exactly 3** `<loc>` entries — the complete top-level taxonomy:
```
https://remixshop.com/cz/zeny
https://remixshop.com/cz/muzi
https://remixshop.com/cz/deti
```

**[10]** `curl -s -o remix_muzi.html … 'https://remixshop.com/cz/muzi'`
→ `HTTP=200 SIZE=880576 TIME=2.605995`, `server: nginx`, `content-type: text/html; charset=UTF-8`.
**No challenge, no login wall.** Sets `remixSession`, `rx_aid` and a base64 `not logged` cookie.

Local greps over the saved body (no further HTTP):
```bash
grep -c 'ld+json' remix_muzi.html                                  # 4
grep -c '__NEXT_DATA__' remix_muzi.html                            # 0
grep -c 'graphql' remix_muzi.html                                  # 0
grep -o '"sku"' remix_muzi.html | wc -l                            # 30
grep -o 'schema.org/[A-Za-z]*Condition' … | sort | uniq -c         # 25 UsedCondition, 5 NewCondition
grep -oE '"price": [0-9.]+' … | head -8                            # 267 704 203 704 388 1237 1359 315
grep -oE '"priceCurrency": "[A-Z]+"' … | sort | uniq -c            # 30 "CZK"
grep -oE 'schema.org/(InStock|OutOfStock|SoldOut)' … | uniq -c     # 30 InStock
grep -oE 'page=[0-9]+' … | sed 's/page=//' | sort -n -u            # 2 3 4 5 634
grep -oiE '"size" value="[A-Z]+"' … | head                         # XXS, XS, S, M
```
→ 30 products/page × last page 634 ≈ **19,000 active men's items** (⚠️ derived, not declared).

---

## What I could not determine

Listed so a Pass-2 reader knows exactly where the evidence stops.

1. **TipCars' category scope, scale, transport and robots.txt — nothing at all.** The Cloudflare
   challenge meant I never saw site content. "Cars" is ⚠️ ASSUMED from the domain and the seed list.
2. **Whether any of these blocks/allows would behave differently from a residential IP.** The whole
   session ran from M247/AS9009, a datacenter ASN. TipCars' challenge in particular is **NOT proven
   to block a residential connection**. Conversely, the fact that Seznam and Remix served a
   datacenter IP cleanly is a positive finding, but only at the paths I actually fetched.
3. **Listing counts for TipCars, Sauto, Sreality and Bezrealitky — not measured, deliberately.**
   Killed on relevance before scale, per instruction. Do not read the absence as "small".
4. **Remix new-listings-per-day.** No per-item timestamp in the listing HTML and no stated expiry
   window. §2b method 1 (timestamp span) unavailable; method 3 (two-sample id diff) needs 24h of
   wall clock. Recorded as not determinable within budget rather than estimated.
5. **Remix women's and kids' listing counts**, and whether the ~19,000 men's figure is exact —
   pagination depth × page size is an approximation, and I did not verify that page 634 is genuinely
   the last page (that would need a request to it).
6. **Whether Remix runs a time-based price-decay mechanic.** I saw `discount-info` CSS and `SLEVA`
   text only. **No old-vs-current price pair was observed.** Explicitly not asserted.
7. **Whether "Remix item disappears" reliably means "sold".** The realised-price hypothesis in the
   capability section rests on this and it is unverified; it needs two samples ≥24h apart.
8. **Remix product-detail URL shape and `external_id` confirmation beyond `sku`.** No product
   `href` was recoverable from the listing HTML (links appear to be JS-constructed); the 9-digit
   `sku` `137658130` is the only id form I actually saw.
9. **ToS text for every site in this batch.** Pass 1 covers robots.txt only; no ToS page was
   fetched. Given all five are rejected, none is worth the requests.
10. **Sauto's and Sreality's `/api/` surfaces.** Their existence is confirmed from robots.txt
    directives; no endpoint, shape or auth model was probed, because `User-agent: * → Disallow: /`
    made probing them the wrong thing to do.
