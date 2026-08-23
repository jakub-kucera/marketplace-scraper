---
title: Minor Czech classifieds — Pass 1 triage
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Minor Czech classifieds — Pass 1 triage

> Probed **2026-08-22, 16:48–16:58 CEST** (14:48–14:58 UTC).
> Egress: VPN datacenter IP — `185.242.6.116`, **M247 Europe SRL, AS9009, Prague CZ**
> (verified live: `curl -s https://ipinfo.io/json`). Anti-bot systems score datacenter ASNs
> harshly; every block recorded below is **⚠️ NOT proven to block a residential connection.**
>
> Pass 1 only: the §2b scale test plus an existence check. Hard cap **5 HTTP requests per site**.
> All User-Agents were a plain desktop Chrome string; **no IP rotation, no logins, no ToS
> acceptance, no evasion of any block, no paginated crawling.**
> Every number below comes from a request recorded in §"Raw probe log". Anything not measured is
> marked **NOT DETERMINED**.

## Comparison baseline (Bazos, measured live 2026-08-22)

| Bazos scope | Active listings |
|---|---|
| notebook | 7,849 |
| iphone | 6,586 |
| naradi | 7,716 |
| all of bazos.cz | ~1,500,000 |

---

## Summary table

| Site | Alive? | notebook | phones / iphone | nářadí (tools) | kolo (bikes) | Site total | Worst-case gap vs Bazos | Verdict | Requests used |
|---|---|---|---|---|---|---|---|---|---|
| **Mimibazar.cz** | Yes, 200 | **30** | **26** | **27** | NOT DETERMINED | NOT DETERMINED | **250–290× below** | **REJECT** | 5 / 5 |
| **Hyperinzerce.cz** | Yes, 200 | **168** | **126** | **530** | NOT DETERMINED | **52,206** | **15–52× below** | **REJECT** | 5 / 5 |
| **Annonce.cz** | Yes, 200 | **21–40** | **61–80** | **61–80** | NOT DETERMINED | NOT DETERMINED | **80–370× below** | **REJECT** | 5 / 5 |
| **Avizo.cz** | Alive but **blocked** (403, Cloudflare managed challenge) | blocked | blocked | blocked | blocked | blocked | not measurable | **REJECT** | 2 / 5 |

**All four fail the scale bar.** None is a Pass 2 candidate. Hyperinzerce is the least-bad of the
four and the only one where a target category (nářadí, 530) is within a single order of magnitude
of Bazos; it is still 15× below on its own best category and 29× below site-wide.

**Zero of the four exposes a JSON API surface.** Grepping every saved response body for
`__NEXT_DATA__`, `ld+json`, `window.__`, `/api/`, and `graphql` produced no listing-data endpoint on
any site (§"Free recon"). All three reachable sites are classic server-rendered HTML, so all three
would be §4e HTML scrapers with the full hardcoded-CSS-class maintenance cost — the most expensive
transport for the least data.

---

## Mimibazar.cz

**What it is.** Alive and healthy: `https://www.mimibazar.cz/` returns HTTP 200, Apache + PHP
(`PHPSESSID` cookie), operated by **CZECH NEWS CENTER a.s.** (the footer and the `www.cncenter.cz`
legal links confirm it — this is a publisher-owned property, not an independent bazaar). Its own
tagline is *"Místo, kde si maminky pomáhají"* ("a place where mums help each other"), and the site
navigation is dominated by blogs, recipes, discussion forums and family photos alongside the
classifieds. Ad search is a single GET endpoint, `nove_fotografie.php?hltext=<query>`, discovered
free from the search form in the saved homepage. Results are paginated 24/page via `&strana=N`,
with an exact total rendered as `(1–24 z N)` and a `data-pg-total` attribute — a genuinely cheap and
exact count, which is the one nice thing about this site.

**Measured scale.** The target categories are not thin here, they are essentially absent:
**notebook = 30**, **iphone = 26**, **nářadí = 27** active listings. Against Bazos's 7,849 / 6,586 /
7,716 that is a gap of **250–290×**, or two and a half orders of magnitude. Per-listing timestamps
are exposed at **minute resolution** ("22. 8. 2026, 16:50"), so a span estimate is available: the 24
notebook results span 4 Aug → 21 Aug (17 days) ⇒ **≤ 1.4 new/day**; iphone spans 9 Jul → 21 Aug
⇒ **≤ 0.55/day** (≤ 1.4/day if the single 9 Jul outlier is dropped); nářadí spans 2 Aug → 22 Aug
⇒ **≤ 1.2 new/day**. These are stated as upper bounds deliberately — see the next paragraph.
**Site-wide total: NOT DETERMINED.** The unfiltered feed reports `(1–24 z 230)` across 10 pages,
but that 230 is not a site total and I could not establish what window it covers.

**Verdict: REJECT.** The measured category counts confirm the children's/handmade skew outright —
this is a mums' marketplace where the whole electronics-and-tools surface is under 100 listings and
roughly 3 new items per day across all three target categories combined. The pipeline's polling
interval (15–45 min) would out-run the entire site's deal flow. One methodological finding worth
carrying forward: **Mimibazar has exactly the bumped-timestamp pathology the calibration warned
about, and worse than Bazos does.** The unfiltered `nove_fotografie.php` feed returned 24 listings
timestamped 16:50–16:54 — a **4-minute span ending at my request time**. Computed naively that is
8,640 new/day; it is in fact a *bump* rate, produced by the site's `aktualizace.php` refresh feature
which resets a listing's displayed time to now. Because the same ordering applies to filtered
searches, the per-category spans above are last-bump spans, so true posting rates are **lower** than
the numbers quoted, never higher. Anyone re-running this must filter bumps before computing a span.

---

## Hyperinzerce.cz

**What it is.** Alive: `https://www.hyperinzerce.cz/` 301s to `https://hyperinzerce.cz/` and returns
HTTP 200. Operated by **Inzeris s.r.o.** (footer, "© 2021"), running **ASP.NET Core on Azure App
Service** (`.AspNetCore.Antiforgery` cookie, `ARRAffinity`, `x-ms-routing-name`). It is a real
general-classifieds site with 15 top-level rubrics including a dedicated **Stroje a nářadí**
(machines and tools) and **PC a elektro**, plus per-category subdomains
(`autobazar.`, `detsky-bazar.`, `erotika.`). Search is a clean GET: `/inzeraty/Index?query=<q>`,
20 results/page via `&page=N`, with an exact total rendered as *"Nalezeno celkem N inzerátů"*. It
also exposes a `SortBy` parameter (options include *Nejnovější*) and an ad-age filter
`CreationPeriod` with `Max24Hours`/`Max48Hours`/`Max1Week`/… values — which would have been an ideal
one-request new/day measurement, except see below.

**Measured scale.** **notebook = 168** (9 pages), **iphone = 126**, **nářadí = 530** (27 pages),
and — the most useful number recovered from any of these four sites — a **site-wide total of
52,206 active listings**, cross-checked against a maximum pagination depth of 2,611 pages ×
20/page = 52,220. Against Bazos that is **47× below on notebook, 52× below on iphone, 15× below on
nářadí, and 29× below site-wide**. **New/day: not determinable within budget.** The search-results
HTML carries **no per-listing timestamp at all** (the only two dates on the notebook results page
were inside ad body text), so §2b method 1 is unavailable; and the `CreationPeriod` filter is
bound to a `POST /inzeraty/SearchPopup` form — passing it on the GET `Index` route was **silently
ignored**, which I verified rather than assumed: the response echoed back
`name="CreationPeriod" value=""` and returned the unfiltered total. That failed probe is what
produced the 52,206 site total, so it was not wasted, but the new/day figure is genuinely unknown.

**Verdict: REJECT.** This is the strongest of the four and it still is not close. Its best target
category is 15× below Bazos and its whole site is 29× below; adding it would grow the project's
notebook deal flow by roughly 2%, its iphone flow by roughly 2%, and its tools flow by roughly 7%,
in exchange for a fresh HTML scraper with the §4e maintenance liability and a P19-style canary of
its own. There is no compensating capability: no JSON API, no realised prices, no structured item
attributes, no per-listing timestamps (which would actively *hurt* — `Ad.publish_date` would have to
be null, and `BACKLOG_IDEAS.md` #6 posting-time density gets nothing). One genuine positive worth
recording in case it is ever revisited: the exact-total-in-HTML plus `SortBy=Nejnovější` plus
`CreationPeriod` combination makes this the easiest of the four to *characterise* cheaply, and the
`CreationPeriod=Max24Hours` filter would give a direct site-wide new/day in one POST if anyone
wanted to close that gap. It does not change the verdict.

---

## Annonce.cz

**What it is.** Alive: `https://www.annonce.cz/` returns HTTP 200, Java backend (`JSESSIONID`)
behind Cloudflare — and notably **Cloudflare served it without a challenge from the same datacenter
IP that Avizo blocked**, so the two Cloudflare configurations are materially different. Trading
since 1997 per the footer. It has the deepest and most granular taxonomy of the four, with flat
category URLs (`/notebooky.html`, `/mobilni-telefony.html`,
`/stroje-motory-pristroje-naradi.html`, `/jizdni-kola.html`) and manufacturer facets carrying
inline counts. Listings expose an integer `articleId` (e.g. `88114039`), a clean detail URL
(`/inzerat/<slug>-<id>-<code>.html`), a day-resolution `ad-date`, price, location and a long
description **inline in the results page** — structurally the best schema fit of the four, for
whatever that is worth given the volumes.

**Measured scale.** The headline search number is a trap and is worth recording as a caution:
`?q=notebook` returns *"nalezeno **1568** inzerátů"*, which looks respectable until the same line
breaks it down by category — **Práce (1544)**, Počítače (19), Reality (2), Hudba (1), Zdarma (1),
Mobily (1). 98% of that count is **job adverts that mention a laptop as an employee perk**. The real
numbers come from the category pages: **/notebooky.html = 21–40 active** (exactly 2 pages of 20;
manufacturer facets sum to 18 branded; the free-text Počítače figure of 19 corroborates),
**/mobilni-telefony.html = 61–80** (4 pages; manufacturer facets sum to 63),
**/stroje-motory-pristroje-naradi.html = 61–80** (4 pages). No page displays an exact total, and
deriving one precisely would need a paginated crawl, which is out of scope. Against Bazos that is
**~200–370× below on notebooks and ~80–130× below on phones and tools.** New/day, from date spans on
newest-first category pages: notebooky = 20 items over 16 Jun → 21 Aug (66 days) ⇒ **≈ 0.30/day**;
mobilní telefony = 20 items over 7 Aug → 22 Aug (15 days) ⇒ **≈ 1.3/day**. For nářadí the span is
unusable and I am not quoting a rate: the page opens with a **4-listing promoted block dated 18 Aug
pinned above 16 organic listings dated 21 Aug** — the topped-ad pattern, caught exactly where the
calibration said to look for it.

**Verdict: REJECT.** Roughly two listings a day across all target categories combined. The
`Práce (1544)` finding is the useful transferable lesson rather than the site: a site-wide free-text
result count on a general-classifieds site is not a category count, and taking that 1,568 at face
value would have promoted Annonce into Pass 2 on a number that was 98% noise. Two capabilities are
worth one line each in case Annonce ever comes up again: it has a native saved-search /
email-alert feature (*"hlídací pes"*), and it exposes integer article ids that would drop straight
into `Ad.external_id`'s `BigIntegerField` without the string/slug/UUID problem flagged in §5b. Both
are irrelevant at 0.3 notebooks per day.

---

## Avizo.cz

**What it is.** The domain resolves and is served, but `https://www.avizo.cz/` returned
**HTTP 403 with a Cloudflare managed challenge** — `cf-mitigated: challenge`,
`server: cloudflare`, `<title>Just a moment...</title>`, and a `_cf_chl_opt` blob with
`cType: 'managed'`. This is an interstitial, not a dead site: something is running behind it. Per
the ground rules I recorded the block and did not attempt to solve, bypass, or rotate around it.
**⚠️ This is a block from a datacenter ASN (M247 / AS9009) and is NOT proven to block a residential
connection** — Cloudflare's managed challenge is heavily ASN-weighted and a domestic Czech IP may
well pass it. That caveat is real, but it does not change the recommendation.

**Measured scale.** **NOT DETERMINED — nothing.** No listing count, no category count, no new/day,
no total. Every listing surface sits behind the challenge. I spent one further request on
`/robots.txt`, which returned **HTTP 200** — a useful structural finding in itself, since it shows
the challenge is **content-scoped rather than domain-wide**: static files pass, HTML pages do not.
That file is also the reason I stopped there rather than continuing to the `sitemap.xml` it
advertises. Its first stanza reads:

```
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Amazonbot
User-agent: Bytespider
User-agent: Baiduspider
User-agent: Baiduspider-render
User-agent: YandexBot
Disallow: /
```

followed by a `User-Agent: *` stanza that disallows, among ~55 other query-parameter patterns,
`/*search`, `*?hledej`, `*?cena`, `*?stari`, `*?typinz`, `*?znacka`, `*?model`, `/*?page`,
`/uzivatel/` and `*/*-kraj/`.

**Verdict: REJECT, on two independent grounds.** First, the operator has explicitly disallowed
**ClaudeBot** from the entire site alongside every other AI crawler, and separately disallows for
*all* agents precisely the search, filter, price, age and pagination parameters a scraper for this
project would have to use — the same shape as the Bazos `robots.txt` noted in §3b, but broader.
Second, it is behind an active Cloudflare managed challenge that this project has no sanctioned way
past (§9: *do not rotate IPs or evade blocks*). Both hold before the scale question is even reached,
and since scale was never measurable there is no upside on the other side of the ledger to weigh
them against. This one is closed unless someone re-probes from a residential IP **and** the
`robots.txt` posture changes; the former alone would not be enough.

---

## Free recon (zero extra requests)

Every response body was saved and grepped for the §4b markers. Counts are occurrences in the
homepage plus all saved search/category pages for that site.

| Marker | Mimibazar | Hyperinzerce | Annonce | Avizo |
|---|---|---|---|---|
| `__NEXT_DATA__` | 0 | 0 | 0 | n/a (challenge page only) |
| `ld+json` | 0 | 0 | 0 | n/a |
| `window.__` | 11 — **all ad-tech**: `window.__cncPageDefinition` (×8), `window.__cncAdsLogger` (×3). No listing data. | 0 | 0 | n/a |
| `/api/` | 0 | 0 | 0 | n/a |
| `graphql` | 0 | 0 | 0 | n/a |

A cross-site grep for any quoted path containing `api`, `json` or `ajax`
(`grep -ho -E '"/[a-zA-Z0-9._/-]*(api|json|ajax)[a-zA-Z0-9._/-]*"' *.html`) returned **zero matches
across all 16 saved HTML bodies.**

**Conclusion: none of the three reachable sites has a discoverable JSON transport.** All are
server-rendered HTML (PHP/Apache, ASP.NET Core, and Java respectively), so all three would be §4e
HTML scrapers. The one AJAX-ish affordance seen anywhere was a
`js-more-ads` / `next-queue-page` link on Annonce and a `data-ajax-action` on a newsletter form —
neither is a listing-data endpoint. Note this Pass-1 recon looked only at HTML bodies; **no JS
bundles were fetched** (§4b step 2), which is where endpoint literals would most likely hide. That
step was not worth a request against sites that fail on scale.

---

## Raw probe log

Constant for every request below:

```
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
```

Requests were spaced ~2s. Cookie jars (`-c` / `-b`) were used per site after the first request so
that session cookies set by the homepage were honoured. No other headers were set.

### Environment
```
$ curl -s --max-time 20 https://ipinfo.io/json
{"ip":"185.242.6.116","city":"Prague","region":"Prague","country":"CZ",
 "loc":"50.0880,14.4208","org":"AS9009 M247 Europe SRL","postal":"110 00",
 "timezone":"Europe/Prague"}
$ date            → Sat Aug 22 16:48:19 CEST 2026
```

### Existence checks (request 1 of 5, all four sites)
```
$ curl -s -L --max-time 25 -A "$UA" -D <site>.home.hdr -o <site>.home.html \
       -w 'http_code=%{http_code} url_eff=%{url_effective} size=%{size_download}\n' <url>

https://www.mimibazar.cz/     → http_code=200  size=276792  server: Apache; set-cookie: PHPSESSID
                                 <title>Mimibazar – Místo, kde si maminky pomáhají</title>
https://www.hyperinzerce.cz/  → 301 → https://hyperinzerce.cz/  http_code=200  size=36011
                                 ASP.NET Core / Azure (.AspNetCore.Antiforgery, ARRAffinity, x-ms-routing-name)
                                 <title>Inzerce zdarma, bazar, inzeráty, prodám a koupím - Hyperinzerce.cz</title>
https://www.annonce.cz/       → http_code=200  size=56878   server: cloudflare (NO challenge); JSESSIONID
                                 <title>Annonce.cz – inzerce zdarma, bazar, inzeráty</title>
https://www.avizo.cz/         → http_code=403  size=5595
                                 cf-mitigated: challenge | server: cloudflare | cf-ray: a2f2adfbdd3f0b9f-FRA
                                 <title>Just a moment...</title>  _cf_chl_opt = { cType: 'managed', cZone: 'www.avizo.cz' }
                                 BLOCKED — recorded and stopped, no bypass attempted.
```

### Mimibazar.cz — requests 2–5 of 5
Search endpoint `nove_fotografie.php?hltext=` was recovered free from the saved homepage
(`<form method="get" action="https://www.mimibazar.cz/nove_fotografie.php" class="searchbox">`,
`data-field="hltext"`), costing no request.
```
2) $ curl -s -L -A "$UA" -c mimibazar.jar 'https://www.mimibazar.cz/nove_fotografie.php?hltext=notebook'
   → 200, 588938 B.  Total in HTML: "(1–24 z 30)"   data-pg-total="2"
   → 24 timestamps, strictly descending:
     21.8. 9:53 · 19.8. 17:19 · 17.8. 14:49 · … · 4.8. 12:40 · 4.8. 12:07
     span 4 Aug → 21 Aug = 17 d ⇒ ≤1.4/day

3) $ curl -s -L -A "$UA" -b mimibazar.jar 'https://www.mimibazar.cz/nove_fotografie.php?hltext=iphone'
   → 200, 587778 B.  "(1–24 z 26)"   data-pg-total="2"
   → span 9 Jul → 21 Aug (44 d) ⇒ ≤0.55/day; ≤1.4/day excluding the lone 9 Jul outlier

4) $ curl -s -L -A "$UA" -b mimibazar.jar 'https://www.mimibazar.cz/nove_fotografie.php'   # unfiltered
   → 200, 599694 B.  "(1–24 z 230)"  data-pg-total="10"
   → ALL 24 timestamps within a 4-MINUTE window ending at request time:
     16:54 ×3, 16:53 ×3, 16:52 ×7, 16:51 ×4, 16:50 ×7   (wall clock at fetch: 16:54–16:55 CEST)
   → BUMP ARTIFACT, not a posting rate. Naive span math gives 24/4min = 8,640/day. Discarded.
     Site total NOT DETERMINED — 230 is the size of this bump-ordered window, not an active count.

5) $ curl -s -L -A "$UA" -b mimibazar.jar -G --data-urlencode 'hltext=nářadí' \
        'https://www.mimibazar.cz/nove_fotografie.php'
   → 200, 592161 B.  "(1–24 z 27)"   data-pg-total="2"
   → span 2 Aug → 22 Aug = 20 d ⇒ ≤1.2/day
```

### Hyperinzerce.cz — requests 2–5 of 5
Search endpoint `/inzeraty/Index?query=` recovered free from the saved homepage
(`<form method="get" class="js-search-form" action="/inzeraty/Index">`, input `name="query"`).
```
2) $ curl -s -L -A "$UA" -c hyperinzerce.jar 'https://hyperinzerce.cz/inzeraty/Index?query=notebook'
   → 200, 140185 B.  "Nalezeno celkem 168 inzerátů"   pagination → page=9 (9 × 20 = 180 ✓)
   → NO per-listing timestamps anywhere in the results HTML.

3) $ curl -s -L -A "$UA" -b hyperinzerce.jar 'https://hyperinzerce.cz/inzeraty/Index?query=iphone'
   → 200, 131709 B.  "Nalezeno celkem 126 inzerátů"

4) $ curl -s -L -A "$UA" -b hyperinzerce.jar -G --data-urlencode 'query=nářadí' \
        'https://hyperinzerce.cz/inzeraty/Index'
   → 200, 133798 B.  "Nalezeno celkem 530 inzerátů"   pagination → page=27 (27 × 20 = 540 ✓)
   → query echoed back correctly as name="Query" value="n&#xE1;&#x159;ad&#xED;" (encoding verified)

5) $ curl -s -L -A "$UA" -b hyperinzerce.jar \
        'https://hyperinzerce.cz/inzeraty/Index?query=&CreationPeriod=Max24Hours'
   → 200, 136044 B.  "Nalezeno celkem 52206 inzerátů"   max page=2611 (2611 × 20 = 52,220 ✓)
   → INTENDED as a 24h new-listing count; the filter was SILENTLY IGNORED on the GET route.
     Verified, not assumed: response echoes name="CreationPeriod" value="" (empty).
     CreationPeriod is bound to POST /inzeraty/SearchPopup only.
   → Therefore this figure is the SITE-WIDE ACTIVE TOTAL = 52,206, and new/day is NOT DETERMINED.
   → CreationPeriod option values observed in the filter markup:
     "" | Max24Hours | Max48Hours | Max1Week | Max2Weeks | Max1Month | Max2Months
```

### Annonce.cz — requests 2–5 of 5
Category URLs recovered free from the saved homepage.
```
2) $ curl -s -L -A "$UA" -c annonce.jar 'https://www.annonce.cz/vsechny-inzeraty$18-filter.html?q=notebook'
   → 200, 96503 B.
   → "Na dotaz: „notebook" nalezeno 1568 inzerátů v následujících kategoriích:
      Práce (1544)  Počítače (19)  Reality (2)  Hudba (1)  Zdarma (1)  Mobily (1)"
   → 98% job ads. Headline count unusable as a category count.

3) $ curl -s -L -A "$UA" -b annonce.jar 'https://www.annonce.cz/notebooky.html'
   → 200, 93281 B.  20 items on page 1; pagination widget: "1 2 další" ⇒ 2 pages ⇒ 21–40 active
   → manufacturer facets: Dell (2) Fujitsu Siemens (1) HP (6) Lenovo (2) Samsung (7) = 18 branded
   → ad-date, strictly descending: 21.8 21.8 21.8 20.8 19.8 18.8 5.8 29.7 29.7 26.7 26.7 22.7
     21.7 20.7 17.7 15.7 13.7 8.7 19.6 16.6  → 20 items / 66 d ≈ 0.30/day
   → item shape: <input name="articleId" value="88114039">  (INTEGER id)
     <a href="/inzerat/usb-c-gigabit-lan-s-65w-88114039-wc64tx.html">  <div class="ad-date">21. 8. 2026</div>

4) $ curl -s -L -A "$UA" -b annonce.jar 'https://www.annonce.cz/mobilni-telefony.html'
   → 200, 94416 B.  20 items; pagination "1 2 3 4 další" ⇒ ~4 pages ⇒ 61–80 active
   → manufacturer facets sum to 63
   → ad-date descending 22.8 → 7.8 (15 d) ⇒ ≈1.3/day

5) $ curl -s -L -A "$UA" -b annonce.jar 'https://www.annonce.cz/stroje-motory-pristroje-naradi.html'
   → 200, 88408 B.  20 items; pagination "1 2 3 4 další" ⇒ ~4 pages ⇒ 61–80 active
   → ad-date NOT monotonic: 18.8 ×4, then 21.8 ×16
     ⇒ a 4-listing PROMOTED/TOP block pinned above the organic listings (each item carries
       <a class="ico-top" href="/napoveda/topovani.html?webId=...">)
     ⇒ span unusable; no new/day quoted for this category.
```

### Avizo.cz — request 2 of 5 (stopped early)
```
2) $ curl -s -A "$UA" -D avizo.robots.hdr -o avizo.robots.txt 'https://www.avizo.cz/robots.txt'
   → http_code=200, 1427 B  — static files pass the challenge; HTML does not.
   Full contents (first stanza + selected Disallow lines from the "*" stanza):
     Sitemap: https://www.avizo.cz/sitemap.xml
     User-agent: GPTBot / ClaudeBot / Google-Extended / Amazonbot / Bytespider /
                 Baiduspider / Baiduspider-render / YandexBot
     Disallow: /
     User-Agent: *
     Disallow: /*search    Disallow: *?hledej    Disallow: *?cena     Disallow: *?stari
     Disallow: /*?page     Disallow: *?typinz    Disallow: *?znacka   Disallow: *?model
     Disallow: /uzivatel/  Disallow: */*-kraj/   Disallow: */ceska-republika/
     (~55 Disallow lines in total, overwhelmingly search/filter query parameters)
   STOPPED HERE. The advertised sitemap.xml was deliberately NOT fetched: robots.txt disallows
   ClaudeBot from "/" entirely, so continuing would have meant crawling against an explicit
   operator instruction. 3 of 5 requests left unspent.
```

---

## What I could not determine

**Kolo (bikes) was not measured on any site.** It is the fourth target category and it fell off the
budget on all three reachable sites — 5 requests bought an existence check plus three of the four
categories. On the evidence this does not change any verdict (Mimibazar would plausibly score
*best* here, since children's bikes are on-thesis for that audience, and its ceiling is a few dozen
listings), but it is an unmeasured gap and is not being presented as anything else. Annonce has a
ready `/jizdni-kola.html` category page and Hyperinzerce a ready `?query=kolo`; each is one request
if anyone wants to close it.

**Site-wide active totals for Mimibazar and Annonce.** Neither renders one. Mimibazar's unfiltered
feed shows `(1–24 z 230)`, but that is a bump-ordered window of unknown span — **explicitly not a
site total**, and I could not establish what defines it without further requests. Annonce shows no
total on category pages at all; its pagination widget appears to show the true last page for
shallow categories (`1 2 další` on notebooky) but I could not confirm it does not window on deeper
ones, so the 4-page categories are reported as ranges (61–80) rather than exact figures. Deriving
either precisely would require paginated crawling, which §9 forbids.

**New/day for Hyperinzerce.** No per-listing timestamps in the results HTML and the
`CreationPeriod` filter is POST-only (verified — the GET echoed an empty value). §2b method 1 is
unavailable, method 2 needs a ToS expiry clause I did not fetch, method 3 needs 24h of wall clock.
A single `POST /inzeraty/SearchPopup` with `CreationPeriod=Max24Hours` would answer it directly.

**Everything about Avizo.** Alive but fully unmeasured: no counts, no timestamps, no transport, no
schema observations. The 403 is from a datacenter ASN and is **⚠️ NOT proven** to apply to a
residential connection — but the ClaudeBot `Disallow: /` in robots.txt is IP-independent and is the
binding constraint regardless.

**No JS bundles were fetched on any site** (§4b step 2), and no ToS pages were read. Both are
Pass 2 work and neither was worth a request against candidates that fail on scale. The
"no JSON transport" finding above is therefore scoped to HTML bodies only, and is stated that way.

**Anti-bot / rate-limit behaviour was not characterised** beyond what the probes incidentally
showed. 5 spaced requests per site produced no 429 and no degradation on Mimibazar, Hyperinzerce or
Annonce; that is far too small a sample to call a rate limit, and deliberately so — §9 forbids
pushing further.
