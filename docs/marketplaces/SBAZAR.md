---
title: Sbazar.cz — feasibility assessment
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Sbazar.cz — feasibility assessment

> **Verdict: VIABLE** — assessed 2026-08-22.
> All claims measured unless marked ⚠️ ASSUMED.
> Egress: residential Czech ISP, `194.212.162.35`, **T-Mobile CZ, AS13036** (verified via
> `ip-api.com`). Pass 1 ran from an M247 datacenter VPN and could not retrieve a single content
> byte; §4.1 explains what actually changed and what did not.
> Requests used: **28 of 30** (full log in §8).

## 1. Verdict and why

**Sbazar exposes an unauthenticated, first-party JSON API at `https://www.sbazar.cz/api/v1/` that
is not behind the consent wall, returns clean typed fields, and answers every schema question the
brief asks.** `GET /api/v1/items/search?category_id=143&limit=1000` returns 1,000 listings with
integer ids, **integer** prices, second-resolution `create_date` *and* `edit_date`, a real boolean
`topped`, and structured locality — 1.3 MB, 1.37 s, no auth, no token, no cookie bootstrap.
Schema fit is unusually good: `external_id` is an integer, every string fits the existing column
widths with large margins, and `parse_price` is **not** broken (see §5b.3 — Sbazar is neither
Aukro's float trap nor Zboží's hundredths trap). The two real costs are a **blanket
`Disallow: /` robots.txt** (Pass 1 §5.1, categorically stricter than Bazos) and a **materially
larger GDPR surface** — the detail endpoint returns the seller's **real full name** (§3.3), which
Bazos never exposes.

**Why VIABLE and not something stronger:** picking the one to build is `RECOMMENDATION.md`'s job.
On its own merits Sbazar is buildable today with **zero migrations** (§5c) and is 3.4× Bazos in
tools, the flipping thesis's best category.

### 1.1 What this reverses from Pass 1

| Pass 1 claim | Measured now |
|---|---|
| "`__NEXT_DATA__` / JSON-LD / is-it-a-JS-app: NOT DETERMINED — no HTML body was ever returned" | Still **not determined from HTML** — the consent wall fires from residential too (§4.1). **Made irrelevant**: the JSON API is a better surface than any HTML blob would have been. |
| "An `/api/` prefix exists … **No concrete endpoint was resolved and I did not guess one.**" | **Resolved.** `/api/v1/items/search` and `/api/v1/items/<id>`, both 200, both unauthenticated. |
| "`<lastmod>` is last-modification, not creation … rates are an **upper bound**" | **Confirmed and quantified.** The API separates `create_date` from `edit_date`. Tools: 455 bumps/day vs **~139 genuinely-new/day** (§2.1). The sitemap rate overstated by ~4×. |
| "Whether the public sitemap equals the full active-listing set" — open | **Effectively settled.** API `pagination.total` vs Pass 1 sitemap counts: notebooks 4,401 vs 4,384 (+0.4%), tools 26,738 vs 26,492 (+0.9%). The sitemap is a complete active snapshot. |
| "`publish_date` should **not** be mapped without confirming semantics" | **Confirmed safe.** `create_date` is a genuine creation timestamp, distinct from `edit_date`. Maps to `Ad.publish_date` with no synthesis. |
| "Assume the Bazos topped-bumps-the-timestamp hazard until checked" | **Checked. Sbazar is clean** — `topped` is a real JSON boolean and topped ads are *labelled*, not silently bumped (§5b.5). |

## 2. Scale — measured

Pass 1 numbers, **already measured from `/static/sitemaps/` and carried over unchanged** (see
`pass1/SBAZAR_pass1.md` §2–§3) — not re-measured here:

| Scope | Active (Pass 1, sitemap) | Bazos comparator | Ratio |
|---|---|---|---|
| `22-stavebnictvi-naradi` (tools) | **26,492** | naradi 7,716 | **3.43× ⬆** |
| `143-notebooky` | 4,384 | notebook 7,849 | 0.56× |
| `237-iphone` | 2,282 | iphone 6,586 | 0.35× |
| `48-mobily-ostatni` | 1,801 | — | — |
| `437-kola-kolobezky` (bikes) | 2,659 | — | — |
| new/day (sitemap `<lastmod>`, 14-day median) | tools ~559, notebooks ~100, bikes ~60, iPhone ~48 | | |

**New this pass — an independent cross-check of those counts**, from `pagination.total` on the API:

| Category | API `pagination.total` | Pass 1 sitemap `<url>` count | Δ |
|---|---|---|---|
| `category_id=143` (notebooks) | **4,401** | 4,384 | **+0.4%** |
| `category_id=22` (tools) | **26,738** | 26,492 | **+0.9%** |

Two independently-derived counts agreeing inside 1% **retires Pass 1 open question #2**: the
public sitemap is a complete active-listing snapshot, not a curated SEO subset.

### 2.1 New/day, corrected — the sitemap rate was ~4× too high

The API separates creation from modification, so §2b method 1 can be run properly for the first
time. On `category_id=22&limit=1000`, dropping the 334 promoted rows leaves 666 organic rows
strictly ordered newest-first by `sorting_date`:

| Measure | Tools (`cat 22`, n=666 organic, span **35.1 h**) | Notebooks (`cat 143`, n=66 organic, span 28.5 h) |
|---|---|---|
| Bump rate (all `sorting_date` events) | 455/day | 56/day |
| **Rows whose `create_date` also falls in the window** | **204 → ~139 genuinely-new/day** | 39 → ~33/day |
| Pass 1 sitemap `<lastmod>` rate | ~559/day | ~100/day |

**So roughly 30% of `<lastmod>` events are genuinely new listings; the rest are edits and
re-topping.** Both windows exceed the ≥12 h that `METHOD_CALIBRATION.md` §4 requires, so the
diurnal correction is satisfied by construction. ⚠️ The notebooks figure rests on only 66 organic
rows and should be read as order-of-magnitude.

⚠️ **These are still not like-for-like with the Bazos keyword baselines** — `22-stavebnictvi-naradi`
("construction & tools") is broader than the Bazos `naradi` keyword, so the 3.43× overstates the
real advantage by an unquantified amount. Pass 1 flagged this and it is not resolved.

**Forced expiry — corrected from Pass 1.** Pass 1 ruled expiry out because sitemap `<lastmod>`
values ran 9–14 months back. The API shows there **is** an expiry window: every item carries
`valid_to`, measured at exactly **`edit_date` + 60 days** on both samples
(`edit_date 2026-08-22T17:20:23` → `valid_to 2026-10-21T17:20:23`;
`edit_date 2026-07-12T15:59:31` → `valid_to 2026-09-10T15:59:31`). It is a **rolling** window that
any edit or bump renews, which is why item `5096678` has been alive since **2017-06-10**. So
`active / expiry_days` is still **not** a valid method here — but `valid_to` is a directly readable
per-item deadline, which is strictly better than the inference Bazos requires.

## 3. Legal

### 3.1 robots.txt — carried over from Pass 1, not re-fetched

`pass1/SBAZAR_pass1.md` §5.1 fetched it in full (HTTP 200, 20,013 bytes). The operative fact is
unchanged and is the worst legal input in this file:

```
User-agent: *
Disallow: /
```

with the complete set of `Allow:` lines in the file (`/`, `/*?rozbalene=ano$`,
`/0-vsechny-kategorie?rozbalene=ano$`, `/admin/novy-inzerat$`, `/nova-nabidka$`,
`/ulozena-hledani$`, `/ulozene-nabidky$`) **all sitting inside named-bot groups**, never the `*`
group. Sbazar is **default-deny site-wide** for anything that is not one of eleven whitelisted
search-engine crawlers. That is categorically stricter than Bazos, which is default-allow with
specific paths disallowed.

Three lines matter for this pass specifically:

```
Disallow: /api/
Disallow: /*/nejnovejsi/
Disallow: /inzerat/*/topovani
Disallow: /inzerat/*/topovano
Disallow: /*watchdog_id=
```

**`Disallow: /api/` covers the exact endpoint this assessment is built on** (it appears in 10 UA
blocks; Googlebot and GoogleOther are the only whitelisted bots *not* carrying it). This is not a
technicality to wave past: the transport recommendation in §4 and the robots directive point in
opposite directions, and the reader should weigh that consciously. The user has stated this is
personal, non-commercial, research-only use and directed that robots.txt not be treated as a
blocker for the research itself — so the probes were made — but **the same directive would apply
to a production scraper, and it does not go away.**

### 3.2 ToS — NOT FETCHED, budget-limited

⚠️ **NOT OBSERVED.** Pass 1 did not fetch the ToS and neither did this pass; the 25 requests went
to transport and schema, which is where the decision-relevant unknowns were. **No verbatim ToS
quote exists for Sbazar anywhere in this repo.** Specifically unanswered: whether Seznam's terms
carry an API-use clause (Bazos requires written consent), a prohibition on unofficial apps
displaying listings, or explicit anti-automation language. This is a ~2-request follow-up and it
should be done before any build decision — see §9.

### 3.3 GDPR surface (§3e) — **materially worse than Bazos, and this is the main hidden cost**

`MONETIZATION.md` §6.5 treats exposed PII as a cost. Bazos only ever shows the project opaque
integer ids, which is how the current setup partly dodges an Art 14 obligation. **Sbazar does
not.** Measured on the detail endpoint, one redacted example per field:

| Field | Where | Redacted example | PII? |
|---|---|---|---|
| `result.user.user_service.shop_name` | detail only | `M••••• K•••••` | ⚠️ **Real full name, first + last.** Present and populated on a private individual's listing. |
| `result.user.portrait_url` | detail only | `https://i.im.cz/ac/oneL2100Bw9…` | ⚠️ **Profile photograph URL.** |
| `result.user.user_service.shop_url` | listing **and** detail | `M•••••K••••` (name-derived, redacted) *or* `9736e8ea981704565f56cb2023b8eb4f` | ⚠️ Mixed — sometimes a 32-hex opaque hash, sometimes a **human-chosen handle derived from the real name**. |
| `result.user.id` | listing and detail | `326577859` | Opaque integer — Bazos-equivalent, benign. |
| `result.user.unique_url` | detail only | `9736e8ea981704565f56cb2023b8eb4f` | Opaque 32-hex. |
| `result.user.ubox_created_date` | detail only | `2026-08-22` | Account-creation date. |
| `locality.municipality` / `district` / `region` | listing and detail | `Červený Kostelec` / `Náchod` / `Královéhradecký kraj` | Municipality-level, comparable to Bazos. |
| `locality.street`, `housenumber`, `streetnumber`, `address`, `zip` | listing and detail | all `''` in 1,100 sampled listings; `zip` populated in 24/100 | ⚠️ **The schema carries street-level address fields.** Empty throughout this sample, but the capability exists and a seller could populate it. |
| phone number | — | **not returned.** `phone_obfuscated: true`, `dont_show_phone: false` | ✅ Good news: the phone is flagged but **not present in the payload**. |

**Consequences for the project, stated plainly:**

1. **A `publisher_name` populated from `shop_name` stores real people's names in Postgres.** That
   is a different retention posture from anything the Bazos pipeline does today, and
   `MONETIZATION.md` §6.1's retention rule would need to be applied deliberately rather than
   inherited. The mitigation is cheap and should be the default: **populate `publisher_name` from
   `shop_url`, not `shop_name`, and never call the detail endpoint's user block into storage.**
2. Conversely, **no phone number is exposed**, which is better than the leaked-FB-dataset join
   path (`PhonePublisher.fb_user`) that exists on the Bazos side.
3. Because listing-level data carries only `user.id` + `shop_url`, **a listing-only scraper has a
   PII surface roughly equal to Bazos's.** The exposure is entirely in the optional detail fetch.

### 3.4 Posture against MONETIZATION.md §3

The current operating posture is **private use** — data stays with the operator, nothing is
republished (`MONETIZATION.md` §3, §6.4, *Innoweb v Wegener* C-202/12). Sbazar under that posture
is **workable but the weakest-footed candidate in this study on the legal axis**: a blanket
`Disallow: /` that explicitly names `/api/`, no ToS review yet, and real seller names in the
payload. None of those is fatal to private use; all three would become serious the moment
anything is published or shared. ⚠️ **Any public-facing use of Sbazar data is a materially worse
proposition than the equivalent for Bazos**, and should be treated as a separate decision.

## 4. Transport

### 4.1 The consent wall — the vantage point was NOT the whole story

Pass 1 attributed the `bcr.iva.seznam.cz` interception to the M247 datacenter ASN and called a
residential re-probe "the single highest-value Pass-2 step". **That re-probe was run, and the
interception still fires.** It is not IP reputation:

```
# r01, residential T-Mobile CZ, no cookies
curl -sS -A "$UA" -D - -o /dev/null https://www.sbazar.cz/143-notebooky
#  -> HTTP/2 302   location: https://login.seznam.cz/api/v1/autologin?service=sbazar&return_url=…
#     set-cookie: last-redirect=1; Max-Age=900

# r02, same URL with -L and a cookie jar: 9 redirects, terminating at
#  -> 200  https://cmp.seznam.cz/nastaveni-souhlasu?service=bcr
#          &return_url=…%2F143-notebooky%3Fcwreturn%3D1
#          &reason=missing&service_id=sbazar&cwvariant=cop
```

The decisive parameters are **`reason=missing`** and **`cwvariant=cop`**. This is Seznam's
**consent-management gate ("consent or pay")**, not a bot challenge — it fires because the
consent cookie is absent, and it fires identically from a residential Czech ISP. Adding a full
browser header set (`sec-ch-ua`, `sec-ch-ua-platform`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`)
changed nothing (r03 → same 302).

⚠️ **Discrepancy recorded honestly:** the coordinator reports `GET /143-notebooky` returning
**200 with ~1.0 MB of HTML** from the same residential egress. I could not reproduce that in three
attempts with three different header/cookie configurations. The most likely explanation is a
consent cookie already present in their client. **I did not accept the consent dialog** — doing so
is accepting terms on the user's behalf, which RESEARCH_BRIEF §9 forbids — so per the standing
instruction I recorded the wall and pivoted to a different surface.

**That pivot is the finding.** The wall is applied at the **HTML document layer only**.

### 4.2 ⭐ The API — unauthenticated, ungated, first-party

The discriminating probe was two requests to a path that cannot usefully redirect to a consent page:

```bash
curl -sS -H 'Accept: application/json' https://www.sbazar.cz/api/
#  -> HTTP/2 404  application/json  186 B
#     {"description":"The requested URL was not found on the server. …","status_code":404,…}
```

**A JSON 404, not a 302.** So `/api/` is served by a real API application that the consent
redirect does not touch. Endpoint *paths* were then recovered at zero request cost from public
third-party source (`gh search code 'sbazar.cz/api/v1'` — five independent repos), and
**every one was then verified live**, per brief §4d's "never trust an unrun source" rule:

| Endpoint | Verified | Notes |
|---|---|---|
| `GET /api/v1/items/search` | ✅ 200 | The listing surface. Params below. |
| `GET /api/v1/items/<id>` | ✅ 200 | Detail. **No trailing slash** — `/api/v1/items/<id>/` returns 404 (r09 vs r10). |
| `GET /api/v1/items/search?user_id=<id>` | ⚠️ NOT OBSERVED | Literal found in public source; probe was lost to a shell error and not re-run. |
| `GET /api/v1/users/public?shop_url=<s>` | ⚠️ NOT OBSERVED | Same. |

Characterisation (brief §4f):

| Property | Measured |
|---|---|
| **Auth** | **None.** No account, no token, no cookie bootstrap, no `Referer` requirement. Requests sent with a plain browser UA and `Accept: application/json` only. |
| **Anti-bot** | **None on `/api/`.** The `bcr.iva.seznam.cz` / `cmp.seznam.cz` consent gate applies to HTML document routes; 13 consecutive API requests were never challenged. Server is `envoy`; responses carry `x-request-id`, `x-correlation-id`, `x-trace-id`, `x-envoy-upstream-service-time`. |
| **Rate limits** | **None observed** across 13 API requests at ~2 s spacing. ⚠️ No burst test was run — budget went elsewhere. **NOT DETERMINED.** |
| **Blocking shape** | Not observed for the API. For HTML it is a **302 redirect chain to a consent page**, never a 403 or 429. Distinct from Bazos's path-scoped 403. |
| **Pagination** | `?limit=N&offset=M`. Response echoes `{"pagination":{"limit":1000,"offset":0,"total":26738}}`. |
| **Page-size cap** | **`limit=1000` served 1,000 results.** No server-side clamp observed at that value — vastly above the Bazos API's 210 cap. Public third-party code uses `limit=999`. ⚠️ The true ceiling above 1000 was not probed. |
| **Ordering** | **Newest-first is the DEFAULT**, no parameter needed. Verified: among 666 non-promoted rows, `sorting_date` is monotonically non-increasing with **zero violations**. An unknown `sort=zzz` is **silently ignored** (r08 byte-identical to r06), so there is no server-side validation to enumerate valid sorts from. |
| **Payload size** | listing ~**1.28 KB/item** (100 items → 128,023 B; 1,000 items → 1,312,486 B, 1.37 s). Detail **4,106 B** for a 7-image listing. |
| **Filter params** | `category_id`, `phrase`, `price_from`, `price_to`, `user_id`, `limit`, `offset` (all from verified third-party literals; `category_id`/`limit`/`offset` verified live here). |
| **Category ids** | Identical to the sitemap slugs — `143-notebooky` ⇒ `category_id=143`, `22-stavebnictvi-naradi` ⇒ `category_id=22`. The Pass 1 sitemap index is therefore a **ready-made category-id map for all 410 categories, already downloaded**. |

**On `__NEXT_DATA__` / `ng-state` / JSON-LD (brief §4b, and the Aukro hint):** the coordinator
reports the category HTML has **no `__NEXT_DATA__`, no `ng-state`, no `__NUXT__`**, a single
`application/ld+json` that is only a `WebPage` breadcrumb, and a `window.__merkur__` marker
(Merkur = Seznam's SSR framework). **I did not verify this myself — I never obtained an HTML
body.** It is moot: an SSR state blob would at best re-serve what `/api/v1/items/search` already
returns directly, in a form that breaks whenever the frontend re-renders. **No JS bundle was
fetched and no APK was needed.**

## 5. Schema fit

Read against `bazos/models.py` as it stands today (`Ad`/`AdDelivery` split, `external_id` a
`BigIntegerField`, `view_count`/`publish_date` nullable), not against the brief's summary.

### 5a. Field mapping — every value below was seen in a real response

Sources: **L** = `GET /api/v1/items/search?category_id=22&limit=1000` and `…category_id=143&limit=100`
(1,100 listing rows). **D** = `GET /api/v1/items/233341956` (+ two more detail probes).

| `Ad` column | Sbazar field | Measured example value | Notes |
|---|---|---|---|
| `external_id` | **L/D** `id` | `233341956` | ✅ **Integer.** 1,100 sampled ids all `int`, range **6,962,902 – 233,341,956** (9 digits). Pass 1 parsed 87,618 sitemap ids to the same conclusion. Fits `BigIntegerField` with ~10 orders of headroom; would even fit signed int32. **No blocker.** |
| `marketplace` | — | `"sbazar"` | New `Marketplace` choice; not a Sbazar field. |
| `url` | **L/D** `seo_name`, composed | `https://www.sbazar.cz/inzerat/227369692-zesilene-tenisove-pletivo-poplastovane-vyska-300cm` | ✅ Built as `https://www.sbazar.cz/inzerat/{seo_name}`. **Max 90 chars** over 1,100 rows vs a 1024 column. `seo_name` alone maxes at 60 and always begins with the id. |
| `name` | **L/D** `name` | `Acer Nitro V 15 (i5 13. gen / 16GB RAM / RTX 2050)` (50 chars) | ✅ **Max 50 chars across 1,100 rows; zero over 90.** Sbazar appears to hard-cap titles at 50. Never empty (0/1,100). Column is 120 — huge margin. |
| `price_raw` | **L/D** `price` (**int**) + `price_by_agreement` (**bool**) | `11990` / `0` + `true` | ⚠️ **Requires composition — see §5b.3.** `price` is a plain **integer in whole CZK**. Max seen `1000000` ⇒ 7 digits; rendered `"1 000 000 Kč"` = 12 chars vs a 30-char column. ✅ Fits. |
| `location` | **L/D** `locality.municipality`, `.district`, `.region` | `Červený Kostelec, Náchod, Královéhradecký kraj` | ✅ **Max 64 chars** composed all three ways, vs a 128 column. ⚠️ `municipality` is **empty in 58/1,100** (exactly the rows with `locality.entity_type == "district"`); `district` and `region` are **never** empty. Compose with a filter, not a bare f-string. |
| `short_description` | **D only** `description` | `Nabízím k prodeji herní notebook Acer Nitro V 15 ve stavu nového kusu…` | ⚠️ **Detail-only — absent from every one of the 1,100 listing rows** (key not present at all). ⚠️ **Overflows the 300-char column**: measured lengths **679 / 241 / 0**. Must be truncated. ⚠️ Can be the **empty string** (1 of 3 detail probes) — see §5b.10. |
| `full_description` | **D** `description` | same | Full text, untruncated. |
| `publish_date` | **D/L** `create_date` | `2026-08-22T17:16:53` | ✅ **A genuine creation timestamp at second resolution**, distinct from `edit_date`. Safe to map — no synthesis. Retires Pass 1 open question #4. Naive local time (no `Z`, no offset) — ⚠️ timezone **NOT OBSERVED**, presumably Europe/Prague. |
| `view_count` | **— absent** | **NOT OBSERVED** | No `view_count`, `views` or `visits` key in any listing row (1,100) or any of 3 detail responses. Store `NULL`, as with Vinted. |
| `topped` | **L/D** `topped` (**bool**) | `true` / `false` | ✅ **A real JSON boolean**, not Bazos's `"true"` string. `METHOD_CALIBRATION.md` §2's truthiness trap does **not** apply. Also present on detail. |
| `publisher_name` | **L/D** `user.user_service.shop_url` | `M•••••K••••` (redacted) / `9736e8ea981704565f56cb2023b8eb4f` | ✅ Max 32 chars vs a 100 column; **never empty (0/1,100)**. ⚠️ **Use `shop_url`, not `shop_name`** — `shop_name` is the seller's real full name (§3.3). |
| `email_publisher` | **— absent** | — | No email id of any kind. Store `NULL`. |
| `phone_publisher` | **— absent** | `phone_obfuscated: true`, `dont_show_phone: false` | Phone is **flagged but not returned**. Store `NULL`. See §5b.6. |

**Sbazar fields with no `Ad` column** (all measured; the interesting ones are worked up in §6):

`edit_date`, `sorting_date`, `valid_to`, `status`, `deactivation_reason`, `price_original`,
`is_reserved`, `is_orderable`, `buyer_protection`, `source` (`web_source` 1,075 / `import_source`
25), `user.id`, `user.verification` (`verified` / `unverified`), `user.unique_url`,
`user.ubox_created_date`, `category.{id,name,seo_name}`, `locality.*` (20 sub-fields incl. ids),
`images[]`, `videos`, `approval_admin`, `custom_id`, `old_id`, `mirroring_id`,
`is_advert_mirroring`, `premise` (business seller — `null` in all 1,100), `other_localities_count`
(>1 in 36/1,100), `latest_order_data`, `recommendation_data`.
⚠️ `images_total_count` is **0 in all 1,100 rows even when `images` is non-empty** — a dead field, do not use it.

### 5b. The §5b checklist, answered

**1. `external_id` — is the id an integer?** ✅ **Yes, unambiguously.** `id` is a JSON integer in
all 1,100 listing rows and all 3 detail rows; range 6,962,902 – 233,341,956. **This is the most
likely hard blocker in the brief and Sbazar clears it with no schema change at all.**

**2. Column widths.** ✅ **Every column fits, most with large margins.** Measured maxima over
1,100 real listings, against the live column widths:

| Column | Limit | Measured max | Over-limit rows | Verdict |
|---|---|---|---|---|
| `name` | 120 | **50** | 0/1,100 | ✅ huge margin |
| `price_raw` | 30 | **12** (`"1 000 000 Kč"`) | 0/1,100 | ✅ |
| `location` | 128 | **64** | 0/1,100 | ✅ |
| `url` | 1024 | **90** | 0/1,100 | ✅ |
| `publisher_name` | 100 | **32** | 0/1,100 | ✅ |
| `short_description` | 300 | **679** (n=3 detail probes) | **1/3** | ⚠️ **MUST truncate** |

`short_description` is the only overflow, and it is the one field that lives on the *detail*
endpoint where the sample is only 3. **Postgres raises `DataError` and SQLite silently accepts**,
so the test suite will not catch it — truncate at the scraper, as the Bazos scraper already does.

**3. Price shape — `parse_price` is SAFE, but `price_raw` composition is where the bug will be.**
This was the headline risk and the answer is good news, with one sharp edge.

- `price` is a **JSON integer in whole CZK**. Measured over 1,100 rows: `Counter({'int': 1000})`
  and `Counter({'int': 100})` — **zero floats, zero non-integral values**, min `0`, max `1000000`.
- **Sbazar is neither of the two known traps.** It is *not* Aukro's float (`861.0` →
  `re.sub(r"\D","",…)` → `8610`, 10× too large) and it is *not* Zboží's integer hundredths
  (`292000` = 2,920 Kč, 100× too large). A Sbazar `price` of `11990` is eleven thousand nine
  hundred ninety crowns, full stop.
- There is **no currency string, no decimal separator, no price range, no auction bid/buy-now
  split**, and no `"Dohodou"`/`"V textu"` free-text placeholder anywhere in the payload.
- ⚠️ **The placeholder is structural, and this is the trap.** "Price by agreement" is
  `price: 0` + `price_by_agreement: true`. If the scraper writes `price_raw = str(price)`, then
  `parse_price("0")` returns **`0`, not `None`** — and `PriceRangeRule` will **reject every
  by-agreement ad** on any query with `price_lower > 0`, silently. On Bazos the same ads reach
  `parse_price` as `"Dohodou"` → `None` → `PASS`. **The mapping must emit a non-numeric string
  (e.g. `"Dohodou"`) when `price_by_agreement` is true**, to reproduce the Bazos semantics.
- ⚠️ **And `price == 0` does NOT imply `price_by_agreement`.** Measured: 165 rows with `price == 0`
  but only 150 with `price_by_agreement == true` — **15/1,000 disagree**, all of them genuine
  giveaways (`Daruji za odvoz skolni lavice`, `Suť na zásyp zdarma`, `Kámen`). So branch on
  `price_by_agreement`, **never** on `price == 0`, or 15-in-1,000 free items get mislabelled as
  negotiable.

**4. Newest-first ordering.** ✅ **Yes, and it is the DEFAULT — no parameter required.** Verified
on the 1,000-row tools page: after dropping the 334 promoted rows, `sorting_date` across the
remaining **666 organic rows is monotonically non-increasing with zero violations**
(`all(sd[i] >= sd[i+1])` → `True`, violations list empty). The same held on the 100-row notebooks
page. So `BazosQueryRunner.run_existing_query`'s "walk newest→oldest, break on the first known
non-topped ad" is **correct as written**.
⚠️ Two caveats worth writing into any spec: the ordering key is **`sorting_date` (≈ `edit_date`),
not `create_date`** — `create_date` is *not* monotonic in the response (an item created 2017-05-30
appears mid-page after a bump). And an unknown `sort=` value is **silently ignored**, so there is
no way to assert the sort server-side; the walk must rely on the default.

**5. Topped/promoted — labelled, deterministic, and it does NOT bump the timestamp.** ✅ The
Bazos hazard is absent.
- `topped` is a **real JSON boolean**. Distinct raw values over 1,000 rows: `{'False': 666,
  'True': 334}`. `METHOD_CALIBRATION.md` §2's `"true"`-string truthiness bug cannot occur.
- Promoted rows are **injected at a fixed cadence of exactly every third slot** — indices
  `0, 3, 6, 9, …`, and the gap between consecutive topped indices is `3` in **333 of 333** cases.
  Unlike Bazos, where the promoted block ran ~141 deep and a 30-item page never escaped it, on
  Sbazar **any page size yields a 2/3 organic stream**. `METHOD_CALIBRATION.md` §3's
  "impossible at default page size" problem does not arise here.
- **Topping does not rewrite `create_date`.** The topped MacBook (`231936777`) reports
  `create_date 2026-07-02T13:13:05` against `sorting_date 2026-08-21T16:11:34` — seven weeks
  apart. Bazos's `from == request timestamp` behaviour has no analogue.

**6. Publisher identity — Sbazar has REAL seller accounts, and the Bazos model does not fit.**
This is the one genuine modelling mismatch.
- Every listing carries `user.id` (int, e.g. `326577859`; 404 distinct users across 1,000 tools
  rows) and `user.user_service.shop_url` (≤32 chars, never empty). Detail adds
  `user.unique_url` (32-hex), `user.verification` (**`verified` / `unverified` — measured both**),
  `user.ubox_created_date` (account age), and `portrait_url`.
- **There is no email id and no phone id.** `EmailPublisher`/`PhonePublisher` are Bazos-shaped
  opaque *pairs*, and `SellerAdCounts`'s whole reason for existing — walking the email↔phone graph
  because neither id alone is the seller — **is meaningless here**: `user.id` *is* the seller,
  stably, with one id per account. Sbazar's model is strictly better; it just is not this one.
- ⚠️ **`GET /api/v1/users/public?shop_url=<s>` carries NO reputation data.** Probed live
  (r19, 200, 478 B): the entire payload is `id`, `enabled`, `verification`, `unique_url`,
  `portrait_url`, `ubox_created_date`, `messenger_testing`, and a `user_service` block
  (`created_date`, `service_enabled`, `service_name`, `shop_description`, `shop_name`,
  `shop_url`). **No rating, no review count, no transaction count, no feedback score.** Anyone
  planning seller-reputation work on Sbazar should read that as a negative finding.
- **Sketch of what fits** (not an implementation — brief §9 forbids designing classes here):
  a `MarketplaceUser` table keyed `(marketplace, external_user_id)` with `handle`
  (← `shop_url`), `verified` (← `verification == "verified"`), `account_created`
  (← `ubox_created_date`), `blocked`; and a nullable `Ad.marketplace_user` FK. That is **purely
  additive** and would later suit Vinted, which hit exactly this wall and deferred.
  **Deliberately excluded: `shop_name`.** Storing it means storing real people's names (§3.3).

**7. `publish_date` / `view_count` availability.** `publish_date` ✅ **available and genuine** —
`create_date`, second resolution, distinct from `edit_date`, present on both listing and detail.
`view_count` ❌ **NOT OBSERVED anywhere** — store `NULL`, which the column already permits.

**8. Detail-fetch cost — one extra request per ad if you want a description at all.**
- ⚠️ **`description` is absent from the listing response entirely** — not empty, *absent*: the key
  does not appear in any of the 1,100 rows. So `short_description` is **detail-only**, and
  `load_full_description` is not optional enrichment on Sbazar, it is the only way to get the
  field the keyword filters read.
- Cost: listing ~**1.28 KB/item** vs detail **2.5–4.1 KB/item**, i.e. a full-description pass
  costs roughly **3× the bytes of the listing pass**, plus one round trip per ad. With a 1,000-item
  page size, a listing-only pass over a whole category is 1–2 requests.
- **Failure mode when an item disappears: HTTP 404 with a 49-byte body**
  `{"status_code":404,"status_message":"Not found"}` — measured on four ids. Clean, cheap,
  unambiguous. ⚠️ **It is byte-identical to a never-existed id**, so a 404 alone cannot tell
  "sold" from "typo". Note this is a *different* 404 from the generic 186-byte Flask body returned
  for an unrouted path — the two are distinguishable, which is useful for detecting an endpoint
  rename. Contrast Vinted, where the equivalent raises `RuntimeError` and uncaught truncates a
  whole query's pass; here it is an ordinary status code to swallow.

**9. Blacklist/blocking probe — `check_blacklisted()`.** The signature takes no arguments and
returns `bool`. The natural implementation is a single cheap `GET /api/v1/items/search?limit=1`
and a check that the response is HTTP 200 with `status_code == 200` and a `pagination` key.
⚠️ **No blocked state was ever observed on `/api/`** across 16 requests, so the *shape* of an
Sbazar API block is **NOT OBSERVED** — the probe above is written against a success signature
rather than a known failure signature, which is the safer way round. Note the HTML surface fails
by **302 to a consent page, never 403/429**, so a redirect-following client would see a 200 full
of HTML; the check must assert JSON, not just `resp.ok`.

**10. Filter-rule compatibility.**

| Rule | Works on Sbazar? |
|---|---|
| `price_range` | ✅ **Yes, and better than Bazos** — the price is already an integer, so `parse_price` round-trips exactly. ⚠️ Conditional on the §5b.3 `price_by_agreement` mapping; get that wrong and this rule silently rejects every negotiable ad. |
| `blocklist_keyword` | ⚠️ **Yes, but weakened without a detail fetch.** The haystack is `f"{ad.name} {ad.short_description}"`. With listing-only scraping `short_description` is empty, leaving a **50-char** title as the entire haystack. |
| `required_keyword` | ⚠️ Same, and **worse** — this rule *rejects* on absence, so a title-only haystack turns it into a title-match filter. Measured: one of three detail probes had `description == ""`, so even with the detail fetch the haystack is sometimes just the title. |
| `publisher_blocklist` | ❌ **No.** Needs `email_publisher` / `phone_publisher` FKs, and Sbazar exposes neither. Both would be `NULL`, so the rule returns `PASS` always — harmless but inert. Restoring the capability needs the §5b.6 `MarketplaceUser` sketch. |
| `price_drop` | ✅ **Yes.** Reads `PriceChange` rows the pipeline writes itself, so it is marketplace-agnostic; and because Sbazar prices are integers, `parse_price(old) `/`parse_price(new)` are exact. **Bonus:** Sbazar also ships `price_original` alongside `price`, so a drop is detectable on a *first* sighting, which `PriceChange` cannot do. ⚠️ `price_original == price` in all 3 detail probes — its semantics are **NOT OBSERVED**. |

### 5c. Required migrations — additive vs breaking

**Sbazar can be scraped today with ZERO migrations.** That is the headline: `external_id` already
fits, every string fits, `view_count`/`publish_date` are already nullable, and the publisher FKs
are already nullable.

| # | Change | Additive or breaking | Needed for |
|---|---|---|---|
| 1 | Add `SBAZAR = "sbazar", "Sbazar"` to the `Marketplace` `TextChoices` | **Additive.** `Marketplace` is a `TextChoices` on a `CharField(max_length=20)`; `"sbazar"` is 6 chars. Django emits an `AlterField` for the `choices` change on `Query.marketplace` and `Ad.marketplace`, which is a **no-op at the database level**. **No impact on Bazos or Vinted.** | Minimum viable |
| 2 | *(nothing else)* | — | Minimum viable |

Optional, all **additive and nullable**, none breaking for Bazos or Vinted:

| # | Change | Notes |
|---|---|---|
| 3 | `Ad.marketplace_user` → nullable FK to a new `MarketplaceUser` table keyed `(marketplace, external_user_id)` | Restores `publisher_blocklist` on Sbazar and gives Vinted the same thing. New table + one nullable FK = additive. **Do not add a `shop_name` column** (§3.3). |
| 4 | `Ad.expires_at` (nullable `DateTimeField`) ← `valid_to` | Sbazar-only today; Bazos could later derive it. Unlocks the §6 delisting work. |
| 5 | `Ad.item_status` (nullable `CharField`) ← `status` / `deactivation_reason` | Only worth adding once a non-`active` value has actually been observed — it has not (§9). |
| 6 | `Ad.is_reserved` (nullable `BooleanField`) ← `is_reserved` | Cheap. `false` in all 1,100 rows, so its live behaviour is unverified. |

**Explicitly NOT required, and this is what makes Sbazar cheap:** no change to `external_id`'s
type, no change to the `UniqueConstraint(fields=("marketplace","external_id"))`, no widening of
any `CharField`, and no change to `AdDelivery` or the status state machine. Compare Vinted, which
forced `external_id` to `BigIntegerField` and both nullable columns.

## 6. New workflows unlocked

Assessed against the brief's §6 checklist. **Two of the six are outright negatives, and saying so
is the point** — a capability with no consumer is a curiosity, and a capability that turns out not
to exist is worth more than a plausible guess that it does.

### 6a. Realised prices — ❌ **NO. Sbazar does not close the biggest gap.**

`MONETIZATION.md` §7.2c calls realised prices "the single biggest gap" in the project. **Sbazar
does not close it.** It is a fixed-price classifieds site, not an auction house: there is no bid,
no closing price, and no completed-listing archive. `status` was `active` on every item observed,
and a removed item returns a bare 404 (§5b.8) carrying no final price.

⚠️ **One unexplored lead, flagged rather than guessed.** The detail payload carries a transaction
layer that is inert in this sample:

```
result.is_orderable: false        (0/1,100 true)
result.buyer_protection: false    (0/1,100 true)
result.is_reserved: false         (0/1,100 true)
result.latest_order_data: null    (null in all 3 detail probes)
```

Sbazar evidently runs an **in-platform order/escrow flow**, and `latest_order_data` is where its
result would live. **Whether that field is ever publicly populated is NOT OBSERVED** — I never
found an orderable item within budget. If it *were* populated on completed orders, it would be a
genuine realised-price feed.

⚠️ **Read that against §3 before chasing it, exactly as the brief warns.** A historical
completed-order archive is a far clearer instance of "a database in which the maker made a
substantial investment" (*Innoweb v Wegener*, `MONETIZATION.md` §6.4) than a live listing feed is,
**and Sbazar already has the worst legal posture in this study** (blanket `Disallow: /` naming
`/api/`, no ToS review). **Highest upside and highest exposure sit on the same asset, and on
Sbazar the exposure side is worse than for any other candidate.** Under the current private-use
posture it is defensible; any public use of such an archive would not be.

### 6b. Delisting signal — ⚠️ **PARTIAL, but with a genuinely new trick**
> Connects to: **`PROMPTS.md` P24** (delisting / time-to-disappear), **`MONETIZATION.md` §7.2c**.

P24's Bazos mechanism is better on the raw signal: `ad-detail-2.php` returns
**HTTP 410 `{"status":"deleted"}`**, an explicit tombstone. **Sbazar returns a bare 404 that is
byte-identical to a never-existed id** (§5b.8), so on its face it is a downgrade.

**But Sbazar ships something Bazos has no analogue for: `valid_to`.** Every item declares its own
expiry, measured at exactly `edit_date + 60 days` on both samples. That converts an undifferentiated
disappearance into a **two-way classification P24 cannot make on Bazos**:

| Observation | Inference |
|---|---|
| Item 404s **well before** its `valid_to` | Removed deliberately — **sold or withdrawn** |
| Item 404s **at/after** its `valid_to` | Expired naturally — **no demand signal** |

Today Bazos's 60-day expiry has to be inferred from a ToS clause and applied uniformly; Sbazar
states it **per item**, and it is a *rolling* window that any edit renews, so the uniform
assumption would be wrong. This is the strongest single argument for optional migration #4
(`Ad.expires_at`) in §5c. ⚠️ The schema also carries `status` and `deactivation_reason`, which
would give the distinction *directly* — but **no non-`active` value was ever observed** and I
will not assume the endpoint serves one.

⚠️ **Cost caveat:** P24's Bazos design is cheap because `ads.php` takes up to **210 `ad_id[]=`
values in one request**. **Whether Sbazar's API accepts a batch of ids is NOT OBSERVED** — if it
does not, delisting detection costs one request per tracked ad and the economics are much worse.
This is a 1–2 request follow-up and it materially changes the effort estimate.

### 6c. Real second-resolution timestamps — ✅ **YES, and this unblocks a named backlog item**
> Connects to: **`BACKLOG_IDEAS.md` #6** (posting-time-of-day analysis → interval tuning),
> **`METHOD_CALIBRATION.md` §4**.

`create_date` is a genuine creation timestamp at second resolution, **separate from `edit_date`**,
and it survives topping (§5b.5). `BACKLOG_IDEAS.md` #6 is blocked on exactly this. Better still,
Sbazar gives it **retrospectively**: a single 1,000-item request returns ~35 hours of creation
timestamps for a whole category, so the posting-density curve can be measured *without* waiting
for the scraper to accumulate history. This pass already used it to correct Pass 1's new/day
figure by ~4× (§2.1).

### 6d. Seller reputation — ❌ **NO. Measured negative.**
> Would have connected to: `bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md` §3 (scam/dealer detection).

`GET /api/v1/users/public?shop_url=<s>` (r19, 200, 478 B) returns **no rating, no review count, no
transaction count, no feedback score** — the full field list is in §5b.6. Pass 1 saw
`bazarky_sitemap_*.xml.gz` / `firmy_sitemap_001.xml.gz` and inferred real seller shops, which is
correct, but **the shops carry no public reputation metric.**

Three weaker proxies *are* available and are worth having:

| Field | Measured | Use |
|---|---|---|
| `user.verification` | `verified` / `unverified` — **both values observed** | Cheapest trust signal on the site. |
| `user.ubox_created_date` | `2026-08-22` (account created the same day it listed) | **Account age.** A day-old account listing an underpriced flagship is the classic scam pattern. |
| `source` | `web_source` 1,075 / `import_source` **25** (2.3%) | ⚠️ **`import_source` marks feed-imported inventory, i.e. a dealer**, not a private seller. Bazos has no equivalent flag — dealer detection there needs the `SellerAdCounts` graph walk. This is a **free dealer label**. |

### 6e. Structured item attributes — ❌ **NO. Measured negative.**
> Would have connected to: `BACKLOG_IDEAS.md` #4 (external price cross-referencing).

There is **no attribute, parameter, spec or condition block** in either the listing or the detail
payload — the complete key list is in §5a and it contains nothing of the kind. Brand, model,
condition and capacity live only in the 50-char free-text `name` and the free-text `description`.
**So Sbazar does nothing to solve what `BACKLOG_IDEAS.md` #4 calls "the hard part" — identification.**
It is not worse than Bazos here; it is simply no better, and anyone hoping a second marketplace
would supply canonical product ids should stop hoping.

### 6f. Buyer-side demand signals — ❌ **NO.**
No `view_count`, no watcher count, no favourite count, no bid count anywhere in 1,100 listing rows
or 3 detail responses. **This is a regression against Bazos**, which does expose a view count
(hence `Ad.view_count` existing at all). Sbazar rows would store `NULL`.

### 6g. Push / saved-search feed — ⚠️ **NOT OBSERVED, but strongly indicated**
> Would connect to: `MONETIZATION.md` §7.1 (polling latency is the binding constraint).

Pass 1 found `Disallow: /*watchdog_id=`, `/*watchdog_hash=`, `/*watchdog_timestamp=` in
`robots.txt`, which confirms a **saved-search ("hlídací pes") feature exists**. **I did not probe
for an API surface for it**, and it would almost certainly require an account — which brief §9
forbids creating. Recorded as a lead, not a capability.

### 6h. Operational wins that are not "capabilities" but change the economics

- **`limit=1000` on a newest-first default.** One request returns 1,000 listings (1.3 MB, 1.37 s).
  The Bazos API caps at 210 and its promoted block runs ~141 deep, so escaping it needs an offset
  page (`METHOD_CALIBRATION.md` §3). On Sbazar **a single request covers an entire category's
  daily new-listing flow with ~7× headroom** (tools: ~139 new/day vs 666 organic rows per page).
  That is a direct answer to `MONETIZATION.md` §7.1: polling latency on Sbazar is bounded by
  politeness, not by pagination.
- **`price_original` alongside `price`** — a price cut is visible on **first sighting**, which
  `PriceChange` structurally cannot do (it needs two observations). ⚠️ Equal to `price` in all 3
  detail probes; semantics NOT OBSERVED.
- **A free category-id map.** `category_id` equals the numeric prefix of the sitemap slug
  (`143-notebooky` ⇒ 143, verified twice), so Pass 1's already-downloaded sitemap index supplies
  ids for all **410** categories at zero request cost. Contrast the Bazos `Section`/`Category`
  tables, which needed `create_sections` / `create_categories` management commands.

## 7. Effort estimate — **S/M**, and where the risk actually is

**S for the scraper, M for doing it properly.**

**Why S is defensible.** The `MarketplaceScraper` protocol has four members and Sbazar satisfies
all of them from two JSON endpoints with **zero migrations** beyond adding a `Marketplace` choice
(§5c). No HTML parsing, no CSS class names to rot (contrast §4e and the P19 canary), no cookie
bootstrap, no token, no auth, no IP rotation, no APK. `run_query` is one `GET` with
`category_id`/`phrase`/`price_from`/`price_to`; ordering is correct by default; `topped` is a real
boolean; `check_blacklisted` is a one-line probe. Realistically a day's work plus tests.

**What is actually risky, in descending order:**

1. ⚠️ **The `price_by_agreement` mapping (§5b.3).** The single highest-probability bug in the whole
   build, and it **fails silently**: map it wrong and `PriceRangeRule` rejects every negotiable ad
   on any query with a price floor, with no error and no log line. It is one branch of code and it
   needs a dedicated test. Note it is *not* the trap the brief warned about — no float, no
   hundredths — which makes it easier to walk past.
2. ⚠️ **Legal, not technical.** `Disallow: /api/` covers the endpoint the entire design rests on,
   and **the ToS has never been read** (§3.2). This is the largest unquantified risk in the file
   and it is cheap to reduce.
3. ⚠️ **PII discipline (§3.3).** `shop_name` is a real full name and it sits one field away from
   the obvious `publisher_name` mapping. Getting this wrong is a data-protection problem, not a
   bug, and it is a *one-line* difference.
4. ⚠️ **Undocumented API stability.** `/api/v1/` is a first-party internal API with **no published
   contract and no versioning guarantee beyond the `v1` in the path**. It is far more stable than
   HTML scraping, but Seznam owes no notice before changing it. `check_blacklisted` distinguishing
   the 186-byte routing 404 from the 49-byte item 404 (§5b.8) gives a cheap rename canary.
5. ⚠️ **Rate limits are unmeasured.** 16 API requests at ~2 s spacing drew no throttling; **no
   burst test was run**. Do not size a production poller on this.
6. **`short_description` truncation** — measured at 679 chars against a 300-char column. Postgres
   `DataError`, and SQLite will not catch it in tests.
7. **Detail-fetch cost** — the keyword filters need `description`, which is detail-only, so a
   filtering deployment is one extra request per new ad (~139/day for tools).

**What is NOT risky and is worth stating**: `external_id` fits, every string column fits with
margin, ordering is correct by default, the promoted-ad trap is absent, and no existing
marketplace is touched by any required change.

## 8. Raw probe log

**28 HTTP round trips to `*.sbazar.cz` / `*.seznam.cz`** (of a 30 budget), spaced ~2 s apart.
Plus 2 non-target requests to `api.ipify.org` / `ip-api.com` to verify egress, and several
`gh search code` / `WebSearch` calls that touch no Sbazar host.

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
# egress verified first (not counted against the Sbazar budget)
curl -s https://api.ipify.org                 # -> 194.212.162.35
curl -s 'http://ip-api.com/json/?fields=query,as,isp,country'
#   -> {"country":"Czechia","isp":"T-Mobile Czech Republic a.s.","as":"AS13036 …"}
```

| # | Request | Status | Bytes | Finding |
|---|---|---|---|---|
| 1 | `GET /143-notebooky` (no cookies) | **302** | 0 | → `login.seznam.cz/api/v1/autologin`; sets `last-redirect=1` |
| 2–11 | same, `-L` with cookie jar (**9 redirects**) | **200** | 21,123 | terminates at `cmp.seznam.cz/nastaveni-souhlasu?…&reason=missing&cwvariant=cop`. **Consent wall, not IP reputation.** Sets `cw_util`, `__cw_snc` |
| 12 | `GET /143-notebooky` + full client hints (`sec-ch-ua*`, `Sec-Fetch-*`) | **302** | 0 | → same CMP URL. Browser headers change nothing |
| 13 | `GET /api/` | **404** | 186 | ⭐ **`application/json`, not a 302 — `/api/` is NOT behind the consent wall** |
| 14 | `GET /api/v1/items/?limit=1` | **404** | 186 | generic routing 404 |
| 15 | `GET /api/v1/items/search?category_id=143&limit=2` | **200** | 2,731 | ⭐ **The endpoint.** `pagination.total = 4401` |
| 16 | `…?category_id=143&limit=100` | **200** | 128,023 | 1.28 KB/item; ordering + topped analysis |
| 17 | `…?category_id=143&limit=2&sort=zzz` | **200** | 2,760 | **unknown `sort` silently ignored** (body ≡ #15) |
| 18 | `GET /api/v1/items/233341956/` (trailing slash) | **404** | 186 | trailing slash breaks routing |
| 19 | `GET /api/v1/items/233341956` | **200** | 4,106 | ⭐ **Detail.** `description`, `status`, `valid_to`, `price_original`, seller block |
| 20 | `GET /api/v1/items/5096678` | **200** | 2,570 | `create_date 2017-06-10`, `edit_date 2026-07-12`, still `active` — expiry is a **rolling** window |
| 21 | `GET /api/v1/items/999999999` | **404** | **49** | `{"status_code":404,"status_message":"Not found"}` — distinct from the 186 B routing 404 |
| 22–24 | `GET /api/v1/items/{231936778,232000000,220000000}` | **404** | 49 | ⚠️ **Dead end — ids are sparse.** Do not repeat |
| 25 | `…?category_id=22&limit=1000` | **200** | **1,312,486** | ⭐ `limit=1000` served in full, 1.37 s. `total = 26738`. All width/price/ordering stats |
| 26 | `GET /api/v1/items/233341140` | **200** | 2,464 | `price=0` + `price_by_agreement=true`; **`description` is `""`** |
| 27 | `GET /api/v1/items/231936777` | **200** | 3,049 | `topped=true` with `create_date` 7 weeks before `sorting_date` — **topping does not bump creation** |
| 28 | `GET /api/v1/users/public?shop_url=<redacted>` | **200** | **478** | ⭐ **Negative finding: no rating/review/transaction data** |

Reproduce the core numbers (2 requests):

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
# scale + ordering + price shape + column widths, all from one response
curl -sS -A "$UA" -H 'Accept: application/json' --compressed \
  'https://www.sbazar.cz/api/v1/items/search?category_id=22&limit=1000' > tools.json
python3 - <<'PY'
import json, collections
rs = json.load(open("tools.json"))["results"]
print("total:", json.load(open("tools.json"))["pagination"])
print("topped raw values:", collections.Counter(repr(r["topped"]) for r in rs))
org = [r for r in rs if not r["topped"]]
sd  = [r["sorting_date"] for r in org]
print("organic newest-first:", all(sd[i] >= sd[i+1] for i in range(len(sd)-1)))
print("price types:", collections.Counter(type(r["price"]).__name__ for r in rs))
print("name max:", max(len(r["name"]) for r in rs))
print("price==0 xor by_agreement:", sum((r["price"]==0) != bool(r["price_by_agreement"]) for r in rs))
PY
# detail: description / status / valid_to
curl -sS -A "$UA" -H 'Accept: application/json' https://www.sbazar.cz/api/v1/items/233341956
```

**Endpoint paths were recovered at zero request cost** and then verified live:

```bash
gh search code 'sbazar.cz/api/v1' --limit 30
#  -> 5 independent repos, converging on:
#     https://www.sbazar.cz/api/v1/items/search?price_from=&price_to=&category_id=&phrase=&limit=&offset=
#     https://www.sbazar.cz/api/v1/items/search?user_id=<id>
#     https://www.sbazar.cz/api/v1/users/public?shop_url=<slug>
```

**PII handling.** No account was created, nothing was logged into, no consent dialog was accepted,
and no IP was rotated. One seller's public shop page was fetched to characterise the user
endpoint; the real name it returned is **redacted everywhere in this file** (§3.3) and no personal
data was written to disk in this repository. Item titles quoted here are public listing text.

## 8.5 Tor compatibility — measured 2026-08-22 ✅

Closes the gap §9 flagged. The production stack runs `IP_CHANGER_TYPE=TOR`, so the scraper's
requests egress through Tor, whereas every other measurement in this document was taken over a
direct residential connection.

```bash
docker compose up -d tor_proxy
curl -s --socks5-hostname 127.0.0.1:9050 https://icanhazip.com     # -> 192.42.116.110 (Tor exit)
curl -s                                   https://icanhazip.com     # -> 88.146.116.43  (direct)

curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:9050 \
  -H 'Accept: application/json' \
  'https://www.sbazar.cz/api/v1/items/search?category_id=143&limit=3'
```

| Attempt | Status | Time |
|---|---|---|
| 1 | **200** | 0.47 s |
| 2 | **200** | 0.34 s |
| 3 | **200** | 0.43 s |

**Sbazar's API serves Tor exit nodes normally.** No 403, no challenge, no rate limiting across
3 requests. `SbazarScraper` can use the shared Tor-proxied session with no carve-out — unlike
`VintedScraper`, and unlike Aukro, which was `403 cf-mitigated: challenge` on 3/3 through the same
circuit (`AUKRO.md` §4.1).

⚠️ Still not measured: sustained volume through Tor, and whether a *specific* exit node could be
blocked where this one was not. Three requests through one circuit is a green light, not a
guarantee.

## 9. Open questions / what I could not determine

**Ranked by how much they would change a build decision.**

1. ⚠️ **The ToS has never been read — by Pass 1 or by this pass.** §3.2. No verbatim quote of
   Seznam's terms exists anywhere in this repo: no idea whether there is an API-use clause, an
   unofficial-app prohibition, or explicit anti-automation language. **Combined with
   `Disallow: /api/`, this is the largest unquantified risk in the file, and it is ~2 requests to
   reduce.** Do this before any build decision.
2. ⚠️ **Rate limits and the shape of an API block.** 16 API requests at ~2 s drew nothing. **No
   burst test was run**, so both the throttle threshold and the block shape (403? 429? challenge?)
   are **NOT OBSERVED**. `check_blacklisted()` (§5b.9) is consequently written against a success
   signature rather than a known failure signature.
   **Update, 2026-08-22 (Stage 9 §1.5 pre-flight, through this project's Tor proxy):** 5 requests
   to `GET /api/v1/items/search?category_id=143&limit=3` via `socks5h://127.0.0.1:9050`
   (`dperson/torproxy`, one circuit, ~1 s spacing) all returned **`200`** with well-formed JSON
   (`pagination`/`results` present, real listing data). This is a **single Tor circuit, 5 requests**
   — it rules out an outright Tor IP-range block but is not the burst/sustained-load test this
   item still asks for, and exit-node rotation was not exercised. `SbazarScraper` therefore ships
   using the shared Tor-proxied session (no Vinted-style opt-out); see
   `docs/refactor/STAGE10_SBAZAR_SPEC.md` §1.5 for the probe and §3.2 for the escape hatch that
   would apply if a future, larger probe finds otherwise.
3. ⚠️ **Whether the API accepts a batch of ids in one request.** Bazos takes 210 `ad_id[]=` values,
   which is the whole reason P24's delisting design is affordable. **NOT OBSERVED for Sbazar.** If
   it does not, delisting detection is one request per tracked ad — a different project. 1–2
   requests to settle.
4. ⚠️ **Whether `status` ever returns a non-`active` value, and whether `deactivation_reason` is
   ever populated.** Both fields exist; `status` was `active` and `deactivation_reason` `null` in
   all 3 detail probes, and delisted items appear to just 404. This decides whether the
   sold-vs-withdrawn distinction is *direct* or only *inferable* from `valid_to` (§6b).
5. ⚠️ **Whether `latest_order_data` is ever publicly populated.** The one lead to a realised-price
   feed on Sbazar (§6a). `null` in every probe; I never found an `is_orderable` item.
   **Read §6a's legal warning before spending requests here.**
6. ⚠️ **`price_original` semantics.** Equal to `price` in all 3 probes. Is it a pre-discount price,
   a shop RRP, or a copy? Unknown.
7. ⚠️ **The timezone of `create_date` / `edit_date` / `valid_to`.** All are naive ISO-8601 with no
   `Z` and no offset. Presumed Europe/Prague, **not verified.** An hour's error in
   `Ad.publish_date` would quietly corrupt `BACKLOG_IDEAS.md` #6's posting-density work.
8. ⚠️ **The true `limit` ceiling.** `limit=1000` was served in full; **above that is unprobed.**
9. ⚠️ **The HTML surface remains unread by me.** The consent wall fired on all 3 attempts from
   residential, and I did not accept the consent dialog (brief §9). The coordinator reports a
   200 with ~1.0 MB HTML, `window.__merkur__`, and only a `WebPage` `ld+json` — **recorded on
   their authority, not verified here.** Moot for the build, since the JSON API is strictly better.
10. ⚠️ **`items/search?user_id=<id>`** — literal found in public source, never probed. Would give a
    seller's true live ad count, which is what `SellerAdCounts`'s docstring says the DB-local
    counts are a poor substitute for.
11. ⚠️ **The saved-search / watchdog API** (§6g). Almost certainly account-gated; not pursued.
12. ⚠️ **Notebook new/day (~33/day) rests on only 66 organic rows.** Order-of-magnitude only. The
    tools figure (~139/day, 666 rows, 35.1 h) is solid.
13. **Category breadth is still not like-for-like with the Bazos keyword baselines** (§2). Pass 1
    flagged it; still unquantified.
