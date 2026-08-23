---
title: Proxy / IP-Rotation Research — Replacing Tor for Bazos Requests
status: reference
updated: 2026-07-26
verified: 2026-07-26
---

# Proxy / IP-Rotation Research — Replacing Tor for Bazos Requests

> **Question:** the current Tor-based `IPChanger` throws errors, and a previously
> used long-lived single VPN (Surfshark) got the IP banned by Bazos. What are the
> alternatives — including reasonably-priced paid ones — and what request volume do
> they need to sustain, especially if we want to **run queries more often**?
>
> **Provenance of claims:** the architecture/volume sections are read directly from the
> code (`bazos/scraping/*`, `ip_changer/*`, `bazos/const.py`, `scraper/settings.py`)
> as of 2026-07-26. The byte-size / latency numbers in §4 are **live-measured** with
> `experiments/bench_proxy.py` against `bazos.cz` on 2026-07-26 — see §9 for the tool.
> Provider pricing in §6 is from public 2026 pricing pages (sources in §11) and drifts;
> re-check before buying. The one thing **not** yet measured is sustained block-rate
> through a real candidate proxy — that requires running the tool's `--repeat` probe
> through each provider's trial (§9).

---

## 1. TL;DR

- The two failures have **different root causes**. Tor fails on **IP reputation** —
  its exit-node list is public and blocklisted by anti-bot vendors, so Bazos 403s
  most exits regardless of our request rate. Surfshark failed on **request rate on a
  single identity** — one static IP + many requests = a rate-ban. The fix for both is
  a **pool of many clean IPs that rotate**, ideally **Czech/EU residential**.
- **Bandwidth is not the constraint and should not drive the decision.** Live
  measurement shows a Bazos HTML search page is **~11 KB on the wire** (gzipped), and
  an API listing dedup-probe is **~1.1 KB**. Even at a **2-minute cadence** across ~12
  queries, the API path is **~0.24 GB/month** (§5). At any realistic residential price
  that is a rounding error / the plan minimum.
- Because bytes are free, **choose the proxy on quality** — pool size, residential
  trust, CZ geo — not on `$/GB`. That points at **rotating residential proxies**,
  whose huge pool drives the only metric that actually governs bans —
  **requests per IP per day** — to effectively zero at any cadence (§7).
- **To run more often affordably:** (a) migrate production queries to the API scraper
  (`BazosApiScraper`) with a small `limit` for the steady-state dedup probe; (b)
  collapse the current **double** blacklist check to one probe per pass; (c) keep
  ad-detail calls event-driven off the free listing-level `price`/`views` signals —
  detail volume, not query count, is the thing that re-creates the Surfshark ban (§5).
- **Two heavier scenarios were modelled with real measurements (§5.2–5.3):** (A) the
  broad category "scrape-all" pipeline stays **cheap on bytes** but raises the
  **request count** — which only *reinforces* needing a big residential pool. (B)
  **downloading every image** is the one case where bandwidth explodes: a car ad has
  **20 images at ~270 KB ≈ 5.3 MB/ad**, so pulling images for even 500 ads/day is
  **~77 GB/month**. The answer is **split transport**: bulk images (high-bytes,
  low-ban-risk static assets) go through a **cheap datacenter unlimited-bandwidth**
  plan; the API/listing/detail traffic stays on **rotating residential**.
- **Recommended path:** start on **Webshare** (free tier + cheap plans; lets you test
  datacenter *and* residential under one account). Try datacenter first (~$3/mo); if
  bans reappear, switch to **rotating residential, CZ-geo** (~$3–6/mo at our volume).
  If image-download becomes a workload, add a **second datacenter pool just for images**.
  Everything drops behind a new `IP_CHANGER_TYPE=HTTP_PROXY` so nothing changes until
  it's set in `.env` (§8).

---

## 2. Why the two previous approaches failed

| Approach | Pool size | Failure mode | Root cause |
|---|---|---|---|
| **Tor** (`TorIPChanger`) | ~thousands of exit nodes, but a **public, finite, blocklisted** set | 403s, slow circuits, `NEWNYM` churn | **IP reputation** — every anti-bot vendor ships the Tor exit list. Rotating faster doesn't help; the whole set is flagged. |
| **Surfshark** (single long-lived VPN IP) | **1** | IP banned after sustained volume | **Request rate on one identity** — a single IP doing many requests/hour looks nothing like a human. |

The gap between "one flagged pool" and "one clean-but-single IP" is exactly what a
**rotating pool of clean IPs** fills: many identities (so per-IP rate stays low) that
aren't pre-flagged (so they aren't 403'd on arrival).

---

## 3. Current architecture (what the code does today)

**IP layer** (`ip_changer/`): `IPChanger` ABC holds a `requests.Session`; concrete
`TorIPChanger` routes it through `socks5h://TOR_PROXY_IP:9050` and renews identity via
the Tor control port (`Signal.NEWNYM`). `DummyIPChanger` is a no-op for dev. Selected
in `BazosRunner.__init__` by `settings.IP_CHANGER_TYPE` (`TOR` / `DUMMY`).

**Request pattern per query, steady state (no new ads)** — tracing
`BazosRunner.run()` → `BazosQueryRunner` → `BazosScraper.run_query()`:

| # | Request | Target | Purpose |
|---|---|---|---|
| 1 | `ip_changer.check_bazos_blacklisted(query.url)` | Bazos | runner-level guard |
| 2 | `ip_changer.check_ip_local()` → `icanhazip.com` | not Bazos | local-IP guard |
| 3 | `scraper.check_blacklisted(query.url)` | Bazos | scraper-level guard — **redundant with #1** |
| 4 | first listing page (20 ads) | Bazos | dedup breaks on first already-known non-TOP ad |

So **≈3 Bazos requests per query per pass**, and **two of the three are duplicate
blacklist checks**. New ads add +1 listing page per 20 new ads, and +1 detail request
per new ad **only** when the `Query.load_full_description` flag is set (default off).

**Existing-query dedup** relies on Bazos returning newest-first and stops on the first
non-TOP ad already in the DB — so in the common "nothing new" case only the **first
page** is fetched.

---

## 4. Live-measured request sizes (2026-07-26)

Measured with `bench_proxy.py` against `bazos.cz`, direct connection. The sandbox
happened to egress from an **Italian** IP and **every request returned HTTP 200** —
useful evidence that Bazos does **not** hard geo-block non-CZ IPs at low volume (it
says nothing about sustained-volume behaviour; see §9).

| Request shape | Wire (billed, gzip) | Decoded | Latency | Per-ad (wire) |
|---|---|---|---|---|
| HTML `search.php` (20 ads) | **11.2 KB** | 47.5 KB | 1.20 s | 572 B |
| API `ads.php` `limit=10` | **1.1 KB** | 4.4 KB | 0.78 s | 115 B |
| API `ads.php` `limit=210` | **15.0 KB** | 92.6 KB | 0.85 s | 73 B |
| API `ad-detail-2.php` | **1.5 KB** | 3.3 KB | 0.04 s | — |

Key correction to earlier estimates: a search page was assumed to be ~60 KB; it is
**~11 KB gzipped on the wire**. Bandwidth is ~5× cheaper than first guessed. The API
listing carries `price_formatted` **and** `views` per ad, so those change-signals are
available **without** any detail request.

---

## 5. Volume model — what "run more often" costs

**Passes/day** (from `scraper/settings.py`: `INTERVAL_LOWER=900s`, `INTERVAL_UPPER=2700s`
= 15–45 min, avg 30 min; `NightMultiplier` doubles the interval 22:00–06:00 Prague):

```
passes/day = 1200 / interval_minutes      # = 16h day + 8h night@×2 interval
           = 40  at the current 30-min average
```

**Monthly bandwidth** = `passes/day × N_queries × requests_per_query × bytes × 30`.
With **N = 12** queries (current is ~6 broad; planning 10–15, mix of narrow and
"all of cars"-broad), using the §4 wire sizes:

| Cadence | Passes/day | HTML today (3 req/q × 11.2 KB) | **API trimmed (1 req/q × 1.1 KB)** |
|---|---|---|---|
| 30 min (now) | 40 | 472 MB/mo | **16 MB/mo** |
| 15 min | 80 | 943 MB/mo | **31 MB/mo** |
| 5 min | 240 | 2.8 GB/mo | **94 MB/mo** |
| 2 min | 600 | 6.9 GB/mo | **236 MB/mo** |

**Takeaways:**

- Even the **unoptimised HTML** path at a 5-minute cadence is only **2.8 GB/mo**
  (~$8 at $3/GB residential). Bandwidth is never the blocker.
- The **API + trimmed-guards** path is **~30× leaner** — a 2-minute cadence is
  ~0.24 GB/mo, i.e. you sit on the provider's plan minimum no matter how often you run.
- The value of the API migration here is **request efficiency and headroom**, not
  money: 1 tiny request/query instead of 3 page-loads keeps the *request count* — the
  ban-relevant number — low as cadence rises.

### 5.1 The detail endpoint is the one thing that can blow up

`ad-detail-2.php` cost scales with **(#ads pulled) × (passes/day)** — **not** query
count. This is the exact multiplier that killed Surfshark. Measured detail = 1.5 KB.

| Tracked ads | Cadence | Detail req/day | Bandwidth/mo | Req/IP/day on a 100-IP pool |
|---|---|---|---|---|
| 50 | 30 min | 2,000 | 87 MB | 20 |
| 50 | 5 min | 12,000 | 524 MB | 120 |
| 300 | 30 min | 12,000 | 524 MB | 120 |
| 300 | 5 min | **72,000** | 3.1 GB | **720** |

The 3.1 GB bandwidth is fine; the **72,000 requests/day** is the ban vector. On a
rotating residential pool of thousands→millions of IPs that spreads to **<1 req/IP/day**
(invisible); on a 100-IP datacenter pool it's **720 req/IP/day** on already-suspicious
IPs (risky). **Mitigation:** keep detail calls event-driven — watch the free listing
`price_formatted`/`views` and only hit detail when a signal changed or on first
discovery, rather than re-scanning every pass.

### 5.2 Scenario A — the broad "scrape-all" approach

Instead of ~12 narrow keyword `Query` rows fetching only their first page, the
category-scoped discovery pipeline (`bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md`)
sweeps whole categories — "everything under Auto" rather than "iPhone 13 Pro". Live
scale, measured 2026-07-26: the `auto` category alone has **49,372 active listings**
(vs 6,867 for `iphone`).

How this changes volume, term by term:

- **Listing requests** grow with **category count**, not ad count. Steady-state each
  category still resolves in ~1 request/pass (dedup breaks at the first known non-TOP
  id; a category-scoped topped run is bounded to ~1-2 pages per the discovery doc §1).
  A measured `limit=210` page is **~19.5 KB**. 50 categories × 240 passes/day (5-min)
  × 19.5 KB ≈ **7 GB/mo** — still cheap; the point is the **request count** (~12k/day)
  rises, which only a large pool absorbs safely (§7).
- **Detail requests** are bounded by **new ads posted/day in scope × filter-pass rate**
  — *independent of cadence* (you fetch detail once per newly-discovered ad, not every
  pass). A busy scope (say ~3,000 new/day, 30% pass filter) ≈ 900 detail/day × 1.9 KB ≈
  **~1.7 MB/day**. Bytes are trivial; the ~900 requests/day are fine on residential.
- **Seller/reviewer enrichment** (`ratings.php`, seller-inventory pulls via
  `email_id=`/`phone_id=`) adds a few requests per *flagged* seller — small bytes,
  modest request count.

**Verdict:** broad scrape-all is **cheap on bandwidth** (single-digit GB/mo even wide)
but pushes the **request count** up across the board. That *reinforces* the residential
recommendation — a bigger pool is exactly what keeps per-IP rate invisible as request
count climbs (§7). It does **not** change the transport choice; it strengthens it.

### 5.3 Scenario B — download every image of an ad

This is the one scenario where **bandwidth becomes the dominant cost by 2-3 orders of
magnitude.** Measured 2026-07-26 on a real car ad:

| Item | Measured | Notes |
|---|---|---|
| Images per car ad (`images[]`) | **20** | detail-only field; thin listing has none |
| Full-size image | **~269 KB** | `/img/{n}/{id}.jpg` |
| `image_thumbnail` | **~283 KB** | ⚠️ *not* small — ≈ full size; see caveat |
| **Full gallery per ad** | **~5.3 MB** | 20 × 269 KB |

Extrapolated (scales with **ads-with-images-pulled × imgs/ad**, *independent of cadence*):

| Ads/day pulled | Full gallery/mo | On residential @ $3/GB |
|---|---|---|
| 500 | **~77 GB** | ~$231/mo |
| 2,000 | **~308 GB** | ~$924/mo |

Compared to the entire API discovery path at **<0.3 GB/mo**, images are **100–1000×**
everything else. Downloading them over rotating residential is financially absurd.

**Consequences for the proposal:**

1. **Split transport by workload** — the key architectural point. Image bulk-download
   is **high-bytes, low-ban-sensitivity** (static assets under `bazos.cz/img/`, not the
   anti-bot-gated API). Route it through a **cheap datacenter plan with unlimited /
   large bandwidth** (e.g. Webshare datacenter ~$2.99/mo). Keep the **low-bytes,
   high-ban-sensitivity** API/listing/detail traffic on **rotating residential**. Two
   pools, matched to each workload's actual constraint.
2. **Never download images blanket.** Per discovery doc §3.3, image-hash duplicate
   detection is "the one real per-check cost" — reserve downloads for candidates that
   already passed the cheap text/price/locality pre-filter, and store a perceptual
   hash (pHash/dHash), not the image bytes.
3. **Thumbnail mitigation needs verifying.** The measured `image_thumbnail` came back
   **~as large as the full image** (~283 KB), so "download small thumbnails to save
   bandwidth" does **not** hold for Bazos's `1m` size code as-is. Check whether a
   smaller size-code variant exists (the URL path encodes a size segment) before
   assuming any thumbnail saving — the benchmark can measure it once found.

---

## 6. Provider options & 2026 pricing

Pricing is from public 2026 pages (§11) and moves — verify before buying. CZ
geo-targeting on residential providers is a username flag (e.g. `user-country-cz`).

### Option A — Rotating residential (recommended)

Many real Czech residential IPs, rotated per request. Solves reputation **and**
per-IP-rate at once. Billed per-GB → cheap at our volume.

| Provider | Price | Notes |
|---|---|---|
| **Webshare** | rotating residential ~**$2.99/GB** (50% promo → ~$1.40 first GB); **static residential $0.50/IP/mo**; 10 free IPs | cleanest dev UX; one account tests datacenter + residential. Good default. |
| **IPRoyal** | from ~**$1.75/GB** at volume; **PAYG credits never expire** | best for bursty use — buy 2 GB, it lasts months. CZ geo. |
| **DataImpulse** | ~**$1/GB** PAYG, no monthly minimum | cheapest credible per-GB; smaller pool. |
| **Decodo** (ex-Smartproxy) | ~**$3.5–4/GB** at small volume | bigger pool / higher success rate; pricier. |

### Option B — Rotating datacenter (cheapest, more fragile)

- **Webshare**: 100 shared datacenter proxies for **$2.99/mo**, often unlimited bandwidth.
- **Proxy-Cheap**: ~**$0.20–1.18/IP**; has a CZ location page.
- **Oxylabs**: Czech IPs from **$2.75/IP**.

You round-robin a list of IPs yourself. Much cheaper/faster, but datacenter IPs are
easier for Bazos to detect and mass-ban later, and a small pool caps safe request rate
(§5.1). Reasonable to **try first** precisely because it's near-free — if Bazos
tolerates it, done; if bans creep back, move to Option A.

### Option C — Static residential / ISP (the "do Surfshark right" version)

Webshare static residential at **$0.50/IP/mo**: buy ~10 Czech ISP IPs and round-robin.
Literally "many Surfshark IPs instead of one" — residential trust + spread load. Cheap
and stable, but a small fixed pool means keep per-IP rate modest.

### Option D — Keep Tor, but pin exit nodes (free stopgap)

`torrc`: `ExitNodes {cz},{sk},{de}` + `StrictNodes 1`, raise `CircuitBuildTimeout`.
Fewer, more-local exits → fewer 403s. Still drawing from a publicly-blocklisted set, so
diminishing returns — fine as a fallback tier, not a primary.

### Option E — Managed scraping API (least effort, most $)

Zyte / ScraperAPI / Bright Data Web Unlocker handle proxies + retries + anti-bot behind
one endpoint (~$0.50–2 per 1k requests). Overkill for Bazos, which isn't heavily
protected — listed for completeness.

---

## 7. The metric that actually governs bans

Surfshark died from **requests/hour on one IP**, not from GB. The governing number is:

```
requests per IP per day  =  total requests/day  ÷  pool size
```

| Approach | Pool size | At 14k req/day (5-min HTML) | Verdict |
|---|---|---|---|
| Single VPN (Surfshark) | 1 | 14,000 / IP | banned — what happened |
| Datacenter pool (Webshare 100) | ~100 | ~140 / IP, on pre-flagged IPs | risky at high frequency |
| **Rotating residential** | thousands–millions | **<1 / IP effectively** | frequency becomes irrelevant |

This is why, **if the goal is to run more often, rotating residential is the enabler,
not merely the cleanest option** — datacenter can't safely absorb high request rates;
residential's pool size makes cadence a non-issue.

---

## 8. Integration sketch

Everything routes through the existing `IPChanger.session`, so a provider swap is small.
A rotating endpoint hands a fresh IP **per request**, so `renew_ip` becomes a no-op —
the provider rotates for us.

```python
# ip_changer/http_proxy.py
class HttpProxyIPChanger(IPChanger):
    """Rotating provider endpoint — a fresh IP per request, no NEWNYM needed."""
    def renew_session(self):
        self.session = requests.Session()
        self.session.proxies = {
            "http":  settings.PROXY_URL,   # e.g. http://user-country-cz:pass@p.webshare.io:80
            "https": settings.PROXY_URL,
        }

    def renew_ip(self):
        pass  # rotation is per-request at the provider

    def renew_ip_and_check_new(self) -> str:
        self.renew_session()            # new session → new upstream IP on next request
        return self.get_current_ip()
```

Wire-up:

1. Add an `HTTP_PROXY` branch in `BazosRunner.__init__` alongside `DUMMY`/`TOR`
   (gate on `IP_CHANGER_TYPE`), and `PROXY_URL` in settings/`.env`. Nothing changes
   until it's set.
2. **Collapse the double blacklist check** (§3, requests #1 and #3) to a single probe
   **per pass** rather than per query — ~3 req/query → ~1.
3. **Tunable `limit` on the API dedup probe** — `BazosApiScraper` currently hardcodes
   `limit=210`; a steady-state dedup check only needs the newest handful, so `limit≈10`
   makes the dominant request ~1.1 KB (§4). Keep 210 for backfill / deep paging only.
4. For a **sticky-IP** variant (Option C — hold one IP across a query's pages), rotate
   by changing a session token in the proxy username (`user-session-<id>`) inside
   `renew_ip` instead.
5. **Split transport for images (Scenario B).** If image bulk-download lands, give the
   image fetcher its **own** `requests.Session` pointed at a cheap datacenter
   unlimited-bandwidth pool (`settings.IMAGE_PROXY_URL`), separate from the residential
   session used for API/listing/detail. Don't route 77+ GB/mo of static images through
   the per-GB residential pool. This is a second, independent `Session`, not a new
   `IPChanger` mode.

The `check_bazos_blacklisted` / `check_ip_local` guards and per-page sleeps otherwise
stay as-is — this only swaps the transport.

---

## 9. The benchmark tool — `experiments/bench_proxy.py`

Standalone (no Django/DB) script at the **repo root**. Measures real on-the-wire byte
sizes, latency, and HTTP status for the three request shapes **plus the image gallery
(full-size + `image_thumbnail`)**, extrapolates monthly bandwidth for all scenarios
(including images/day and the split-transport point), and doubles as a **block-rate
probe** via `--repeat`. All numbers in §4–5 are its output.

```bash
# your current Tor setup — expect some 403/429 in the status distribution
python experiments/bench_proxy.py --proxy socks5h://127.0.0.1:9050 --repeat 30 --query auto

# a provider free trial (Webshare / IPRoyal), CZ-geo endpoint
python experiments/bench_proxy.py --proxy http://USER-country-cz:PASS@HOST:PORT --repeat 30 --query auto

# your real query count, broad term
python experiments/bench_proxy.py --queries 15 --query auto
```

`--repeat N` reports the **status distribution + success %** — the apples-to-apples
"does this proxy actually get through" comparison that the single-sample run in §4
can't give. `--query auto` exercises the broad cars case (compare `total=` across
terms). "wire" = compressed bytes as billed by a proxy; add ~5–10% for request/header
overhead. (Throwaway tooling — safe to delete once a provider is chosen.)

---

## 10. Recommendation & open questions

**Recommended path:**

1. **Benchmark first.** Run `bench_proxy.py --repeat` through (a) current Tor, (b) a
   Webshare datacenter trial, (c) a Webshare/IPRoyal residential-CZ trial. Compare
   success %. This is the only missing data point.
2. **Start on Webshare** — free tier + cheap plans, one account covers datacenter and
   residential. Try **datacenter** first (~$3/mo); if success % is high and stays high,
   stop there.
3. If bans reappear, switch to **rotating residential, CZ-geo** (~$3–6/mo at our
   volume). Pool size makes cadence irrelevant.
4. In parallel, land the three efficiency changes (§8.2–8.4) so higher cadence doesn't
   inflate the request count.
5. Keep **detail-endpoint** usage event-driven (§5.1) — this is the real scaling risk.
6. **If/when broad scrape-all (§5.2) lands:** no transport change needed — it only
   raises request count, which residential absorbs. Just size the pool for it.
7. **If/when image-download (§5.3) lands:** stand up a **second, datacenter
   unlimited-bandwidth** pool for images only (`IMAGE_PROXY_URL`, §8.5); never put
   image bytes on the residential meter; download images only for pre-filtered
   candidates and store pHash, not bytes.

**Open questions:**

- Sustained block-rate per provider (needs the `--repeat` probe — not yet run).
- Does Bazos rate-limit the **API** differently from HTML? (`check_blacklisted` treats
  403 **and** 429 as blocked on the API path but only 403 on HTML.)
- Does CZ-geo materially beat generic-EU residential on success %? (measurable with the
  same tool via different `-country-` flags).
- **Is there a genuinely small image size-code?** The measured `image_thumbnail` (`1m`
  code) was ~283 KB — *not* a saving. Find and benchmark a smaller variant before
  assuming any thumbnail-based bandwidth reduction (§5.3).
- Do **image requests** through a datacenter pool draw blocks at bulk volume, or are
  static assets under `/img/` genuinely un-gated? (measurable with `--repeat` on an
  image URL).

**Related docs:** the API-migration case (`bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`),
interval tuning (`refactor/BACKLOG_IDEAS.md`).

---

## 11. Sources

- [Webshare pricing 2026](https://www.toptierproxy.com/blog/webshare-pricing-2026/)
- [Best cheap rotating proxies 2026 (DataImpulse)](https://dataimpulse.com/blog/best-cheap-rotating-proxies/)
- [Residential proxy $/GB comparison 2026](https://dataimpulse.com/blog/residential-proxy-pricing-comparison/)
- [Proxy-Cheap — Czech Republic proxies](https://www.proxy-cheap.com/locations/europe/czech-republic)
- [Oxylabs — Czech Republic proxies](https://oxylabs.io/location-proxy/czech-republic)
