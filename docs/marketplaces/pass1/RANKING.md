# Pass 1 ranking — written before any Pass 2 work began

> RESEARCH_BRIEF §1 requires the ranking be committed *before* Pass 2, so the cut is made on
> measured scale rather than on whichever site was most interesting to poke at. This file is that
> commitment. Date 2026-08-22. Egress throughout: VPN datacenter IP 185.242.6.116 (M247, AS9009,
> Prague CZ).

## The ranking

| # | Candidate | Verdict | Target-category scale | Decided by |
|---|---|---|---|---|
| **1** | **Sbazar.cz** | **PROMOTE to Pass 2** | tools **26,492 (3.4× Bazos)**, notebooks 4,384, phones 4,083, bikes 2,659 | Measured, clears the bar |
| **2** | **Aukro.cz** | **DEFER — undetermined, not rejected** | NOT DETERMINED (zero bytes retrieved) | Blocked domain-wide; capability looks absent |
| **3** | bazos.sk / .at / .pl | DEFER | NOT DETERMINED (403) | Blocked; needs a residential re-probe |
| — | Hyperinzerce.cz | REJECT | tools 530, notebooks 168 (15–52× below) | Measured |
| — | Annonce.cz | REJECT | notebooks 21–40 (80–370× below) | Measured |
| — | Mimibazar.cz | REJECT | notebooks 30 (250–290× below) | Measured |
| — | Avizo.cz | REJECT | Blocked + robots names `ClaudeBot` | Measured |
| — | TipCars | REJECT | Cars; domain-wide Cloudflare challenge | Relevance + transport |
| — | Sauto.cz | REJECT | Cars | Relevance |
| — | Sreality.cz | REJECT | Real estate | Relevance |
| — | Bezrealitky.cz | REJECT | Real estate | Relevance |
| — | Remix | REJECT | Apparel only (3 top categories: `zeny`/`muzi`/`deti`) | Relevance |
| — | Facebook Marketplace | REJECT | Not measured, deliberately | Legal gate (§3d) |

**Only ONE candidate is promoted to a full Pass 2 workup, not three.** The brief allows three. Two
of the three plausible slots are occupied by candidates that are *blocked from this vantage point*
rather than small, and spending Pass-2 budget re-confirming a 403 from the same IP would produce
nothing. See "the egress problem" below.

## 1. Sbazar.cz — the one to work up

Measured via `/static/sitemaps/`, which served cleanly with no challenge (7 requests, no 429s):

| Category | Active | vs Bazos |
|---|---|---|
| `22-stavebnictvi-naradi` (tools) | **26,492** | **3.43× bigger** |
| `143-notebooky` | 4,384 | 0.56× |
| `237-iphone` + `48-mobily-ostatni` | 2,282 + 1,801 = 4,083 | 0.62× |
| `437-kola-kolobezky` (bikes) | 2,659 | — |
| Site-wide floor | ~540,000 | ~0.35× |

New/day from `<lastmod>`, 14-day median: tools ~559, notebooks ~100, bikes ~60, iPhone ~48.

> ⚠️ **Superseded 2026-08-22 by Pass 2.** The API exposes a real `create_date` distinct from
> `edit_date`, and comparing them shows `<lastmod>` conflates edits with creations: the true
> new/day for tools is **~139, not ~559 — the sitemap figure was ~4× too high.** The Pass 1
> caveat ("`<lastmod>` is modification, not creation, so these are an upper bound") was correct
> and the size of the error is now measured. Active-listing counts were *not* affected —
> `pagination.total` cross-checks them to within 1%. See `../SBAZAR.md` §2.

**Two independent validations make these trustworthy:**
- `active ÷ new-per-day` implies listing lifetimes of **43.8 / 47.5 / 47.4 / 44.7 days** across four
  categories measured separately. That tight clustering is strong evidence the sitemap is a
  complete active snapshot, not a curated SEO subset.
- 91–99% of `<lastmod>` values are distinct, so there is no bulk-bump contamination of the kind
  that wrecked the naive Mimibazar and Bazos readings (`METHOD_CALIBRATION.md` §2–§4).

**Schema fit already looks cheap** (measured, not assumed): `external_id` is an integer, max
233,325,018 across 87,618 parsed — fits `BigIntegerField` with no migration. URLs max 91 chars
against a 1024 column.

**Standing caveats, both material:**
- `<lastmod>` is *modification*, not creation, so the rates are an upper bound on genuinely-new
  listings.
- **The listing surface has never been successfully fetched.** Every content request was
  intercepted by Seznam's anti-bot (`bcr.iva.seznam.cz`). All scale numbers come from sitemaps.
  Nothing is yet known first-hand about field names, prices, or descriptions.
- `robots.txt` is `User-agent: * / Disallow: /` with per-crawler allowlists, and `/static/` has no
  `Allow:` exception — so the sitemap requests were made against a rule that covers them. It also
  disallows `/*/nejnovejsi` (newest-first) for named crawlers, i.e. exactly the ordering §5b.4
  calls load-bearing. This is a real Pass-2 legal question, not a technicality.

## 2. Aukro.cz — the hypothesis the brief was built around, and it did not survive

RESEARCH_BRIEF §6a treats completed-auction realised prices as the highest-value prize in the
study. **On current evidence that prize appears not to exist publicly**, from three independent
lines:

1. **`archiv.aukro.cz`, the dedicated public completed-auction archive, is gone.** Verified at DNS
   level and independently re-verified: it returns no record, while `www`/`api` resolve to
   Cloudflare — and a deliberate nonsense control name also returns nothing, proving there is no
   wildcard masking the result. Reported shutdown 2018-06-29 (third-party, ⚠️ unverified).
2. **The WebAPI exposes realised prices only for your own account.** Of 129 operations, every
   sold/finished retrieval is `doGetMy*` (`doGetMySoldItems`, `doGetMyWonItems`, …). There is **no
   search-finished-items-by-category or by-keyword operation at all.** All require a login, which
   §9 forbids. ⚠️ **Provenance caveat, important:** that WSDL's endpoint is `webapi.allegro.pl` —
   the legacy Allegro-shared API vendored into a Czech client. **It is not proof of what
   `api.aukro.cz` serves today** and its method names must not be carried into a spec unverified.
3. Consumer "Moje Aukro" completed views are account-scoped, 90-day window.

**Transport is hostile.** Four probes, all `403` + `cf-mitigated: challenge` + `cType: 'managed'`,
across `www`/`api`/`doc`, from **two different egress networks**. Independently re-verified today:
`/` and `/robots.txt` both 403. Note the contrast with Bazos, whose block is 403-only and
path-scoped — **Aukro's is domain-wide and challenges `robots.txt` itself**, so even the legal
gate cannot be evaluated. §4b's "grep the JS bundles" technique has no entry point, because the
only URL in any response body is `challenges.cloudflare.com`.

**Why DEFER and not REJECT — the distinction matters.** We retrieved **zero bytes** of Aukro. The
honest statement is *"not determinable from a blocked vantage point"*, not *"Aukro has no realised
prices."* Two specific things could still overturn this, both cheap:
- Whether an **individual ended-auction permalink** (`aukro.cz/<slug>-<numeric-id>`) still renders
  its final price publicly. If it does, realised prices are assemblable — though only by crawling
  every item, which is precisely the highest-legal-exposure shape §6a warns about.
- What `api.aukro.cz` actually serves today, as opposed to the legacy Allegro WSDL.

Two facts recovered for free that would matter *if* it is ever unblocked: `doGetItemsListResponse`
carries `itemsCount`/`itemsFeaturedCount`, so the scale test is one cheap request; and promoted
items are **labelled** rather than silently bumped, avoiding the Bazos trap. But `ItemsListType`
has `endingTime` and **no start/publish timestamp**, so §2b's timestamp-span method does not
transfer, and `doSellSomeAgain` confirms relisting is first-class — new-vs-relist would be a real
unsolved problem.

## 3. The egress problem — the single biggest constraint on this study

Three of the four most interesting candidates are blocked, and **all of it traces to one cause**:

| Candidate | Result from datacenter IP |
|---|---|
| Aukro | 403 domain-wide, incl. `robots.txt`, on two networks |
| Sbazar listing pages | Intercepted by `bcr.iva.seznam.cz` anti-bot |
| bazos.sk/.at/.pl | 403, IP named in body; `.cz` fine from same IP |
| Avizo | Cloudflare challenge |
| TipCars | Cloudflare challenge, domain-wide |

**None of these is proven to block a residential connection.** Per §9, no IP rotation was
attempted to find out. The egress is a commercial VPN range (M247, AS9009) that anti-bot vendors
score harshly by default, and the Bazos result proves the vantage point is the variable: `.cz`
serves it happily while its own sister domains refuse it.

> ⚠️ **Corrected 2026-08-22, after the residential re-probe.** The prediction below was right for
> every Track A candidate — Aukro, Sbazar's listing surface and `bazos.sk` all cleared instantly
> from a residential IP (see `../AUKRO.md` §4.1). But it does **not** generalise: Track B's eBay
> probe was blocked *just as hard* from the same residential T-Mobile CZ line — Akamai 403,
> domain-wide including `/robots.txt`, byte-identical with browser headers. So "datacenter ASN" is
> the right explanation for the Czech marketplaces here, **not a universal one**. Some operators
> block by other signals entirely, and a residential IP is not a master key.

**The highest-value next action in this entire study is not another probe — it is re-running a
handful of the existing probes from a residential connection.** Roughly five requests would settle
Aukro's realised-price question, Sbazar's listing surface, and the bazos.sk claim simultaneously.
Until then, Pass 2 depth on anything but Sbazar's sitemaps is not achievable.
