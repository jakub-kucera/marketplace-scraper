---
title: Sbazar.cz — Pass 1 scale triage
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Sbazar.cz — Pass 1 scale triage

> Probed **2026-08-22, 14:47–14:59 UTC** (16:47–16:59 Prague). Requests used: **11** — 5 initial + a
> coordinator-authorised **+6 extension spent exclusively on `/static/sitemaps/`**.
> Egress: VPN datacenter IP **185.242.6.116, M247 Europe AS9009, Prague CZ**.
> All claims measured unless marked ⚠️ ASSUMED / EXTRAPOLATED or "NOT DETERMINED".

---

## 1. Headline: does it clear the scale bar?

**Yes — decisively, and in the one category the flipping thesis cares most about it is materially larger
than Bazos.** Sbazar carries **26,492** active tools listings (`22-stavebnictvi-naradi`) against Bazos's
7,716 — **3.4× bigger** — plus 4,384 notebooks (0.56× Bazos), 2,282 iPhones and 2,659 bikes/scooters. Every
target category is the **same order of magnitude** as Bazos; none is one or two orders below. Sbazar is not
killable on scale.

New-listing flow is real too: **~100/day notebooks, ~560/day tools, ~48/day iPhones, ~60/day bikes**,
derived from genuine per-listing `<lastmod>` timestamps in the public sitemaps.

**The open risk is access, not size.** The HTML listing surface returned a Seznam anti-bot challenge
(`bcr.iva.seznam.cz`) from this datacenter IP, and every number above therefore comes from the
`/static/sitemaps/` tree, which served cleanly. A Pass-2 build depends on either the sitemap route being
sufficient or the challenge not firing from a residential IP — **neither is yet established.**

---

## 2. Active listings — measured

**Method.** The robots-advertised sitemap index lists per-category files
`inzeraty_<catId>-<catSlug>_sitemap_<NNN>.xml.gz`. Each `<url>` entry is one live listing. I gunzipped and
counted `<url>` elements directly — these are **counts, not ceilings or extrapolations**, except where the
table says otherwise.

The **50,000-URL per-file cap is measured, not assumed**: `inzeraty_7-nahradni-dily-prislusenstvi_sitemap_001.xml.gz`
contains **exactly 50,000** entries, confirming Sbazar uses the standard sitemaps.org limit. Any category
fitting in one file is therefore counted exactly, with no truncation.

| Scope | Active listings | Bazos baseline | Ratio | How obtained |
|---|---|---|---|---|
| **`22-stavebnictvi-naradi`** (tools) | **26,492** | `naradi` 7,716 | **3.43× ⬆** | exact `<url>` count, 1 file |
| **`143-notebooky`** (notebooks) | **4,384** | `notebook` 7,849 | 0.56× | exact `<url>` count, 1 file |
| **`237-iphone`** (iPhone) | **2,282** | `iphone` 6,586 | 0.35× | exact `<url>` count, 1 file |
| `48-mobily-ostatni` (phones, other) | **1,801** | — | — | exact `<url>` count, 1 file |
| **iPhone + other phones combined** | **4,083** | `iphone` 6,586 | 0.62× | sum of the two above |
| **`437-kola-kolobezky`** (bikes/scooters) | **2,659** | — | — | exact `<url>` count, 1 file |
| `7-nahradni-dily-prislusenstvi` (spare parts) | **250,000 – 300,000** ⚠️ EXTRAPOLATED | — | — | file 001 counted at exactly 50,000; **6 files** ⇒ 5 full + 1 partial. Only file 001 was counted; the rest is `5 × 50,000 + partial`. |
| **Site-wide** | **≥ ~540,000** (hard floor); realistically **1–3M** ⚠️ EXTRAPOLATED | ~1.5M | — | floor = 6 multi-file categories at `(files−1)×50,000` = 500,000, plus the 37,618 counted in the five target categories. Upper figure extrapolates 404 single-file categories at the ~7,500 mean of my (target-biased) sample — **treat as an order-of-magnitude only.** |
| Distinct ad categories | **410** (in 420 sitemap files) | — | — | parsed from sitemap index |

**Caveats, stated plainly:**

- ⚠️ **These counts are "listings present in the public sitemap", which I ASSUME ≈ active listings.** I could
  not cross-check against an on-site total, because the search HTML is behind the anti-bot challenge. The
  residence-time consistency in §3 is indirect evidence the sitemap is a complete active snapshot, not a
  curated SEO subset — but it is evidence, not proof.
- **`48-mobily-ostatni` is a residual subcategory**, not the whole phone taxonomy. With `237-iphone` measured
  separately and `95-mobil-prislusenstvi` (accessories) not measured, Sbazar's true phone inventory is
  **higher than the 4,083 combined figure**. Phones are the category where Sbazar most clearly trails Bazos,
  but the gap is smaller than the raw `237-iphone` row suggests.
- Category-vs-keyword mismatch is now **largely resolved** for iPhone and notebooks, since Sbazar has
  dedicated categories that map cleanly onto the Bazos keyword searches. It remains a caveat for tools,
  where `22-stavebnictvi-naradi` ("construction & tools") is likely **broader** than the Bazos `naradi`
  keyword — so the 3.43× is probably an overstatement of like-for-like advantage. ⚠️ Not quantified.

---

## 3. New/day — method, numbers, confidence

**Solved.** Every `<url>` entry carries a `<lastmod>`, at **second resolution**:

```xml
<url><loc>https://www.sbazar.cz/inzerat/5096678-nabijecka-ibm-lenovo-02k6807</loc>
     <lastmod>2026-07-12T13:59:31Z</lastmod></url>
```

The `<urlset>` root carries `date="2026-08-22T03:05:02Z"` — the snapshot instant. All windows below end there.

| Category | Active | **new/day** (median of 14 full days) | mean | 24h window | 7d avg | distinct timestamps |
|---|---|---|---|---|---|---|
| `22-stavebnictvi-naradi` | 26,492 | **~559** | 529 | 624 | 627 | 91.9% |
| `143-notebooky` | 4,384 | **~100** | 117 | 103 | 145 | 91.4% |
| `437-kola-kolobezky` | 2,659 | **~60** | 63 | 93 | 72 | 99.1% |
| `237-iphone` | 2,282 | **~48** | 47 | 55 | 49 | 96.8% |
| `48-mobily-ostatni` | 1,801 | **~29** | 31 | 47 | 41 | 97.6% |

Bazos `notebook` measured today at ~230/day organic; **Sbazar notebooks run ~100/day, about 0.43× the flow** —
consistent with the 0.56× active-listing ratio.

**Why I trust these numbers:**

- **No bulk-bump contamination.** 91–99% of timestamps are distinct. A sitemap regenerated with a mass
  `lastmod` rewrite, or a promoted-listing bump of the kind that broke the Bazos method, would collapse that
  toward 0%. The coordinator's check passes: **no filtering was needed.**
- **Internal consistency across categories.** `active ÷ new-per-day` = implied mean listing lifetime:
  notebooks 43.8d, iPhone 47.5d, tools 47.4d, bikes 44.7d, other-phones 62.1d. **Four of five cluster at
  44–48 days.** Five independent categories agreeing this tightly is strong evidence both the counts and the
  rates are real, and that the sitemap is a complete snapshot rather than a filtered subset.
- **Diurnal bias handled — and it runs the opposite way to Bazos here.** The snapshot is taken at 03:05 UTC
  (05:05 Prague), so the freshest 12h window covers *overnight* and **understates** (notebooks: 62/day vs
  ~100 true). The Bazos calibration — freshest window overstates by ~2× — does not transfer, because there
  the window was daytime. Using the **median of 14 complete 24h days** sidesteps the issue entirely and
  satisfies the ≥12h span requirement by construction.

**The one caveat that matters:** ⚠️ **`<lastmod>` is last-modification, not creation.** These rates therefore
count "listings created **or edited or re-topped** per day" and are an **upper bound** on genuinely-new
listings. The 44–48 day residence consistency suggests edits are not dominant, but the split is
**NOT DETERMINED**. Report these as order-of-magnitude, which is all Pass 1 needs.

One anomaly, flagged rather than smoothed: `143-notebooky` shows **427 entries on 2026-08-17** against a
~100/day baseline, a 4× spike also visible (mildly) in tools. Cause unknown — plausibly a bulk re-index or a
promotion event. This is why the table leads with the **median**, not the mean or the 7-day average.

**Forced expiry: definitively ruled out.** Oldest `<lastmod>` values run 2025-06-23 to 2025-11-19 — i.e.
listings persist **9–14 months**. Bazos's `active / 60` arithmetic (which rests on ToS §137 auto-deletion)
**must not be transplanted to Sbazar**, and did not need to be: the timestamp method gave a direct answer.

---

## 4. Transport signals

### 4.1 The sitemap tree is a first-class ingest surface

`/static/sitemaps/` served **HTTP 200 on all 7 requests, with no SSO bounce and no anti-bot challenge** —
in contrast to every HTML listing attempt. 438 child sitemaps, regenerated daily at ~03:05 UTC. This alone
would support a working scraper: it yields listing URLs, integer ids and per-listing timestamps at ~4.4 KB
gzipped per 1,000 listings. What it does **not** carry is price, title beyond the URL slug, location or
seller — those still need a detail fetch, which is the surface that is challenged.

Beyond the 420 per-category ad sitemaps:

- `sitemap-phrases-1/2/3.xml.gz` — Sbazar publishes its own **search-phrase URL list**; a ready-made keyword map.
- `bazarky_sitemap_001/002.xml.gz` (user shops) and `firmy_sitemap_001.xml.gz` (companies) — implies
  **real seller accounts with stable page URLs**, which does *not* fit the Bazos-shaped
  `EmailPublisher`/`PhonePublisher` opaque-id-pair model (brief §5b.6). Flag for Pass 2.
- `kategorie_kraje` / `kategorie_okresy` / `kategorie_obce` — location taxonomy down to municipality.

### 4.2 Free schema-fit findings (87,618 URLs parsed offline)

| Check | Result |
|---|---|
| `external_id` integer? | **Yes.** `/inzerat/<id>-<slug>`; 87,618 ids parsed, all integer. min 129,862, max 233,325,018 (9 digits). Fits `BigIntegerField`, and even signed 32-bit. **No blocker.** |
| `url` ≤ 1024 chars? | **Yes.** Longest observed 91 chars. |
| `publish_date` available? | `<lastmod>` is available but is **modification**, not publication. Per `Ad.publish_date`'s "never synthesise a value here", it should **not** be mapped to `publish_date` without confirming semantics. |

### 4.3 Auth, anti-bot and blocking shape (from the initial 5 requests)

- **Seznam SSO autologin bounce, not an auth wall.** First hit on a content URL 302s to
  `https://login.seznam.cz/api/v1/autologin?service=sbazar&return_url=<url>%3Fnoredirect%3D1`, setting
  `last-redirect=1; Max-Age=900`. **No account is required** — see the judgement-call note in §5.2.
- **Anti-bot challenge.** With the bounce satisfied, the canonical URL 302s to
  `https://bcr.iva.seznam.cz/?cwtkn=<token>`, setting `cw_util` (30d) and `__cw_snc=1` (1h) on `.sbazar.cz`,
  and requesting client hints via `accept-ch: Sec-CH-UA-Model, Sec-CH-UA-Full-Version-List`. This is
  **Seznam's own in-house system**, not Cloudflare/DataDome/PerimeterX. The `cwtkn` is base64url of
  **XOR-0x0D-obfuscated JSON** (decoded offline, zero requests):
  ```json
  {"var":"cop","ts":1787410169.674,"rid":"61b430dd-4a33-4fe4-b86b-6d6c08ac1cb3",
   "url":"https://www.sbazar.cz/hledej/notebook/0-vsechny-kategorie/cela-cr/nejnovejsi","bh":"QIHrgv6vx_w"}
  ```
  `ts` decodes to `2026-08-22T14:49:29.674Z`, exactly the request's wall-clock time. Trivial obfuscation
  suggests a client-side-JS device check rather than anything cryptographic. **Not followed, not retried.**
- ⚠️ **Blocked from a datacenter IP; NOT proven to block a residential connection.** M247/AS9009 is a
  datacenter ASN. **Re-probing from residential egress is the single highest-value Pass-2 step.**
- **An `/api/` prefix exists** on `www.sbazar.cz` — `robots.txt` carries `Disallow: /api/` in 10 UA blocks
  (Googlebot and GoogleOther are the only whitelisted bots that do *not*). **No concrete endpoint was
  resolved and I did not guess one.**
- **`__NEXT_DATA__` / JSON-LD / `window.__` / "is it a JS app": NOT DETERMINED** — no HTML body was ever
  returned, so there was nothing to grep.

### 4.4 URL grammar (from `robots.txt` plus one live-confirmed shape)

`/hledej/<query>/<catId>-<catSlug>/<location>/<sort>`, e.g.
`/hledej/notebook/0-vsechny-kategorie/cela-cr/nejnovejsi`. Sorts: `nejnovejsi` (newest), `nejlevnejsi`,
`nejdrazsi`. Price filters `/cena-od-<X>-do-<Y>-kc`. Pagination is a trailing path digit. Detail pages
`/inzerat/<id>-<slug>` (confirmed live in 87,618 sitemap entries) and `/<category>/detail/<id>`.
Server is `envoy` throughout.

---

## 5. robots.txt and the legal posture

Fetched `https://www.sbazar.cz/robots.txt` → **HTTP 200, 20,013 bytes**, `last-modified: Mon, 17 Aug 2026 08:46:42 GMT`.

### 5.1 `/static/sitemaps/` **is** inside the blanket disallow — and that tension is a real Pass-2 input

The file opens with:

```
User-agent: *
Disallow: /
```

and ends, at line 849, with:

```
Sitemap: https://www.sbazar.cz/static/sitemaps/sitemap.xml.gz
```

**Recorded explicitly, as asked: there is no `Allow:` exception anywhere in the file for `/static/`,
`/static/sitemaps/`, or any sitemap path.** The complete set of `Allow:` lines in the entire file is
`/`, `/*?rozbalene=ano$`, `/0-vsechny-kategorie?rozbalene=ano$`, `/admin/novy-inzerat$`, `/nova-nabidka$`,
`/ulozena-hledani$`, `/ulozene-nabidky$` — and every one of those sits **inside a named-bot group**, not the
`*` group. So for any agent that is not one of the eleven whitelisted search-engine bots, **`/static/sitemaps/`
is disallowed along with everything else. My seven sitemap requests were made against a `Disallow: /` that
covers them.**

The tension is genuine and should not be papered over. Sbazar simultaneously:

- **denies all non-whitelisted agents everything** (`User-agent: * / Disallow: /`), and
- **globally advertises a machine-readable sitemap index.** Per the robots.txt specification the `Sitemap:`
  directive is **non-group-specific** — it is independent of any `User-agent` block and applies file-wide.
  Sitemaps exist for no purpose other than automated consumption.

Two readings are available, and I am not resolving them here: either the `*` block is aimed at *crawlers of
the listing surface* and the sitemap directive is a genuine global invitation, or the operator intends
whitelist-only access and the `Sitemap:` line is addressed solely to the eleven named bots. **The narrower
reading is the safer one to plan against.** Either way, Sbazar's posture is **categorically stricter than
Bazos's**, which is default-allow with specific paths disallowed. Under Sbazar's file a project scraper is
**default-denied site-wide**, and there is no path it could fetch that `robots.txt` affirmatively permits.

This does not by itself sink the candidate — the project's operating posture is **private use**
(`MONETIZATION.md` §3, §6.4), which is the most defensible footing available, and robots.txt is not itself
a contract. But it is a materially worse starting position than Bazos and belongs in the ranking.

### 5.2 ⚠️ Judgement call to flag: the `noredirect=1` / `last-redirect=1` step

**Recorded here explicitly for assessment rather than left implicit in the probe log.** On the SSO bounce I
sent `?noredirect=1` and then `Cookie: last-redirect=1` to suppress the redirect to `login.seznam.cz`. My
reasoning: both the parameter and the cookie are **the site's own mechanism**, minted by Sbazar's own 302 and
placed in its own `return_url` — this is the documented path back for a visitor with no Seznam session, not a
circumvention. No account was created, nothing was logged into, no ToS was accepted, and no IP was rotated.

**But it sits close to the brief's §9 "do not evade blocks" line, and a reader may reasonably score it
differently than I did.** The distinction I drew is between the *SSO bounce* (a session-detection
convenience, which I stepped past) and the *anti-bot challenge* at `bcr.iva.seznam.cz` (a deliberate access
control, which I did **not** follow, solve, or retry — I stopped and recorded it as a finding). If that
distinction is rejected, then requests 3 and 4 were out of policy and only requests 1, 2 and 5–11 should
count as clean. **None of the §2 or §3 numbers depend on requests 3 or 4** — every figure in this document
comes from `robots.txt` and the `/static/sitemaps/` tree — so rejecting that judgement call invalidates no
measurement here.

### 5.3 Other relevant Disallow lines, verbatim

```
# crawlbudget
Disallow: /*/cena-od-
Disallow: /*/cena-do-
Disallow: /*/nejnovejsi/
Disallow: /*/nejnovejsi$
Disallow: /*1$
...
Disallow: /*0$
# watchdogs
Disallow: /*watchdog_id=
Disallow: /*watchdog_hash=
Disallow: /*watchdog_timestamp=
Disallow: /inzerat/*/topovani
Disallow: /inzerat/*/topovano
Disallow: /*categoryId=
```

`Disallow: /*/nejnovejsi` — **the newest-first sort, exactly the ordering `QueryRunner.run_existing_query`
depends on, is disallowed** (in the Slurp/DuckDuckBot/Baiduspider/YandexBot/msnbot/Naverbot blocks; not in
Googlebot's or SeznamBot's). The same lesson as the Bazos robots.txt: the disallowed paths are precisely the
useful ones. `topovani`/`topovano` confirms a **"topping"/promotion feature exists**; `watchdog_*` confirms a
**saved-search feature** worth checking in Pass 2 as a push surface (brief §6b).

---

## 6. Raw probe log — 11 requests

`UA` = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36`.
Egress verified first: `curl -s https://api.ipify.org` → `185.242.6.116`.

| # | Target | Status | Bytes | Note |
|---|---|---|---|---|
| 1 | `/robots.txt` | **200** | 20,013 | `User-agent: * / Disallow: /` |
| 2 | `/hledej/notebook/0-vsechny-kategorie/cela-cr/nejnovejsi` | **302** | 0 | → `login.seznam.cz/api/v1/autologin` |
| 3 | same + `?noredirect=1` + cookie | **302** | 0 | → canonical, param stripped (see §5.2) |
| 4 | canonical + `last-redirect=1` | **302** | 0 | → **`bcr.iva.seznam.cz/?cwtkn=…`** anti-bot |
| 5 | `/static/sitemaps/sitemap.xml.gz` | **200** | 4,812 gz | 438 child sitemaps |
| 6 | `…/inzeraty_143-notebooky_sitemap_001.xml.gz` | **200** | 98,906 gz | **4,384** `<url>` |
| 7 | `…/inzeraty_48-mobily-ostatni_sitemap_001.xml.gz` | **200** | 40,538 gz | **1,801** `<url>` |
| 8 | `…/inzeraty_22-stavebnictvi-naradi_sitemap_001.xml.gz` | **200** | 658,847 gz | **26,492** `<url>` |
| 9 | `…/inzeraty_437-kola-kolobezky_sitemap_001.xml.gz` | **200** | 51,550 gz | **2,659** `<url>` |
| 10 | `…/inzeraty_237-iphone_sitemap_001.xml.gz` | **200** | 44,613 gz | **2,282** `<url>` |
| 11 | `…/inzeraty_7-nahradni-dily-prislusenstvi_sitemap_001.xml.gz` | **200** | 1,111,662 gz | **exactly 50,000** — confirms the per-file cap |

Requests 6–11 were issued ~2s apart. **No rate limiting, no 429, no challenge on any `/static/` path.**

Reproduce the counts:

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
for slug in 143-notebooky 48-mobily-ostatni 22-stavebnictvi-naradi 437-kola-kolobezky 237-iphone; do
  curl -sS -A "$UA" "https://www.sbazar.cz/static/sitemaps/inzeraty_${slug}_sitemap_001.xml.gz" \
  | gunzip -c | grep -o '<url>' | wc -l
done
```

Rate derivation (offline, on the saved XML): parse all `<lastmod>` values, bucket by UTC date, take the
**median of the 14 complete days** preceding the snapshot instant `2026-08-22T03:05:02Z`.

**No personal data was collected.** No listing detail page was ever fetched; no seller name, phone number or
profile was seen at any point. The sitemaps contain only URLs and timestamps.

---

## 7. What I could not determine

1. **Whether the anti-bot challenge fires from a residential IP.** The single most important open question —
   everything in §4.3 is measured from a datacenter ASN only.
2. **Whether the public sitemap equals the full active-listing set**, or is a filtered SEO subset. The 44–48
   day residence consistency is supporting evidence, not proof; an on-site total would settle it.
3. **The split between genuinely-new listings and edits/bumps inside the `<lastmod>` rate.** Rates are an
   upper bound on new-per-day.
4. **Whether `<lastmod>` can be mapped to `Ad.publish_date`** — semantics unconfirmed, and the column's
   help_text forbids synthesising.
5. **Any concrete endpoint under `/api/`.** Existence confirmed via `robots.txt`; shape not. Deliberately not guessed.
6. **Whether the site is Next.js / Nuxt / other**, and whether it ships `__NEXT_DATA__`, JSON-LD or an inline
   state blob — no HTML body was ever returned.
7. **Whether promoted/"topped" listings bump their timestamp** on the HTML surface. They evidently do **not**
   contaminate the sitemap (91–99% distinct timestamps), but the listing-page behaviour is unmeasured.
   Assume the Bazos hazard there until checked.
8. **Detail-page payload**: price, title, location, seller fields and their column widths — all
   **NOT OBSERVED**. §5a of the Pass-2 template cannot be filled from Pass 1 data.
9. **ToS text** — not fetched. §5.1's `Disallow: /` is suggestive but is not the ToS.
10. **Total phone inventory** — `95-mobil-prislusenstvi` and any other phone subcategories were not counted.
11. **Site-wide total** remains an extrapolation; only 6 of 410 categories were counted.

### Recommended Pass-2 opening sequence

1. **Re-attempt one search page from a residential IP.** Settles the single biggest unknown; nothing else
   should be planned until it is answered.
2. Fetch **one detail page** (`/inzerat/<id>-<slug>`) and fill the §5a field-mapping table from a real response.
3. `sitemap-phrases-*.xml.gz` — the site's own keyword map.
4. Read the ToS for API/automation clauses; quote verbatim.
5. Only then chase `/api/`.

**Bottom line for ranking:** Sbazar clears the scale bar on measured volume, is **3.4× Bazos in tools** and
comparable in notebooks and bikes, exposes **integer ids that fit the existing schema unchanged**, and
publishes **second-resolution timestamps** that make new-listing rates directly measurable. It carries two
real costs: a **stricter robots.txt posture** than Bazos (§5.1) and an **unresolved anti-bot challenge** on
the listing surface (§4.3).
