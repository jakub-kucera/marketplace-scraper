---
title: Bazos User-Agents — the app's, and the trap on the HTML path
status: shipped
updated: 2026-09-18
verified: 2026-09-18
shipped_in: bazos/scraping/bazos/user_agent.py
---

# Bazos User-Agents — the app's, and the trap on the HTML path

**§1–§8 are the API path**: how the official Android app builds the `User-Agent` it sends to
`api/v1/`, and how `bazos/scraping/bazos/user_agent.py` reproduces it. **§9 is the HTML path** —
a different pool, a different problem, and the one that has actually cost production passes.
Read it before touching `ip_changer/tor.py`'s import-time filtering.

How the official Android app (`cz.ackee.bazos`) builds the `User-Agent` header it
sends to the hidden `api/v1/` endpoints, and how to reproduce it faithfully.

> Reverse-engineered from the decompiled app **v2.19.1** (versionCode 4630) in
> `bazos_app_decomplied/`. Reference implementation:
> **`bazos/scraping/bazos/user_agent.py`**.

---

## 1. Key insight

The app does **not** ship a hard-coded UA string. It **constructs one at runtime**
from app metadata + the device's `android.os.Build` fields, appends OkHttp's own UA,
then normalises the whole thing (strip accents → lowercase → strip accents → trim).

So "behaving like the app" means **reproducing the construction**, not copying a
literal — the device-specific parts (`Build.MODEL`, Android version) differ per
install, and the fixed parts must match the exact APK you're mimicking.

---

## 2. Construction pipeline

### Step 1 — base string
`i4(yk.a, zk.b)` constructor, `com/google/android/gms/internal/measurement/i4.java:264`:

```java
String.format(Locale.US,
    "%s/%s (%s; build:%d; Android %s; Model:%s)",
    appLabel,                 // ApplicationInfo label → "Bazoš" (cs) / "Bazos"
    versionName,              // "2.19.1"
    packageName,              // "cz.ackee.bazos"
    versionCode,              // 4630
    Build.VERSION.RELEASE,    // OS version, e.g. "13"  ← device-specific
    Build.MODEL)              // e.g. "Pixel 7"          ← device-specific
```

### Step 2 — append OkHttp's default UA
The UA interceptor is registered as a **network** interceptor — it's added to the
`OkHttpClient.Builder`'s *second* interceptor list (`zn/g0.java:91`, which is
`networkInterceptors`). Network interceptors run **after** OkHttp's internal
`BridgeInterceptor`, which has already set `User-Agent: okhttp/4.11.0`. The app reads
that and appends it with a leading space
(`OkHttpClientFactory.createNormalizedUserAgent`):

```
<base> okhttp/4.11.0
```

(OkHttp version `4.11.0` is the one bundled in this APK.)

### Step 3 — normalise
`createNormalizedUserAgent` + the transformer `j()` (`l0/r.java:225`), in order:

1. NFD-normalise, strip combining diacritical marks (`Bazoš` → `Bazos`),
2. `toLowerCase()`,
3. NFD-normalise + strip diacritics again,
4. `trim()`.

Net effect: the final UA is **lowercase ASCII**.

---

## 3. Final result

```
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0
```

(That exact string is the one the §7 live probes in
[`HIDDEN_API.md`](HIDDEN_API.md) used. Note `default_user_agent()` does **not** emit it -
`DEVICE_PROFILES[0]` is Pixel 7 on Android **14**, the first line below; re-ran
2026-09-18.)

More examples (varying only the device, verified via `python bazos/scraping/bazos/user_agent.py`):

```
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 14; model:pixel 7) okhttp/4.11.0
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:sm-g991b) okhttp/4.11.0
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:sm-a528b) okhttp/4.11.0
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:2201117ty) okhttp/4.11.0
bazos/2.19.1 (cz.ackee.bazos; build:4630; android 14; model:pixel 6a) okhttp/4.11.0
```

That distinctive lowercase shape — `build:` / `android ` / `model:` tokens plus the
trailing `okhttp/…` — **is** the fingerprint. A generic browser UA, a title-cased
string, or a missing `okhttp/` suffix would all stand out from real app traffic.

### Fixed vs. device-specific

| Component | Value | Varies? |
|-----------|-------|---------|
| app label | `bazos` (post-normalisation) | no |
| versionName | `2.19.1` | per app release |
| packageName | `cz.ackee.bazos` | no |
| versionCode | `4630` | per app release |
| **Android release** | e.g. `13`, `14` | **yes — per device** |
| **Build.MODEL** | e.g. `pixel 7`, `sm-g991b` | **yes — per device** |
| okhttp version | `4.11.0` | per app release (bundled lib) |

---

## 4. Reproduction — `bazos/scraping/bazos/user_agent.py`

The module mirrors the pipeline exactly:

- `APP_LABEL / APP_PACKAGE / APP_VERSION_NAME / APP_VERSION_CODE / OKHTTP_VERSION`
  — pinned constants (documented with where to re-read them on an APK bump).
- `DeviceProfile(model, android_release)` + a `DEVICE_PROFILES` list of 5 real,
  common devices. Any single one is a legitimate, indistinguishable fingerprint.
- `_normalize()` — the double diacritic-strip + lowercase + trim.
- `build_user_agent(profile)` — returns the exact string for that device.
- `default_user_agent()` — the first profile, for a stable single-identity scraper.

```python
from bazos.scraping.bazos.user_agent import build_user_agent, DEVICE_PROFILES, default_user_agent

ua = default_user_agent()
# or rotate: build_user_agent(random.choice(DEVICE_PROFILES))
```

---

## 5. Co-travelling headers (full request fidelity)

The UA alone isn't the whole fingerprint. When the scraper eventually sends requests,
match the app's header envelope (`OkHttpClientFactory.addCommonNetworkInterceptor`):

| Header | App behaviour | Recommendation |
|--------|---------------|----------------|
| `User-Agent` | constructed as above | use the module |
| `Accept-Encoding` | **removed** (forces identity encoding) | `requests` sends `gzip, deflate` by default and decompresses transparently — functionally fine; pop it only if matching the app byte-for-byte |
| `Date` | `SimpleDateFormat(...).format(new Date(currentTimeMillis()/1000))` | **buggy** — the `/1000` formats seconds-as-millis, so the app emits a date near **Jan 1970**. Almost certainly ignored server-side; prefer to omit rather than replicate the bug |
| `token` | added **only if** a login token exists | omit — not needed for public reads |
| `X-DeviceId` | added **only if** a device GUID exists (from `api/v1/guid.php`) | omit for the MVP → no cross-IP identifier to correlate |

---

## 6. Rotation strategy

A real device has a **stable** `(User-Agent, X-DeviceId)` pair; Bazos's traffic is
many such devices across many IPs. Two coherent options:

- **Stable single identity (simplest / MVP default):** `default_user_agent()`, and
  send **no** `X-DeviceId`. There's no identifier tying requests across Tor exit IPs
  together — the safest default until a live probe confirms what the API requires.
- **Per-identity rotation (best blend):** on each Tor identity change, pick a fresh
  `DeviceProfile` (and, if you ever send it, fetch a new GUID). Each exit IP then
  looks like a distinct fresh install rather than one device teleporting across the
  network. Bind this to the existing `IPChanger` rotation hook so UA + GUID + IP
  always change as a unit — a device must not change model while keeping the same id.

---

## 7. Maintenance

The pinned constants track a specific APK. If Bazos ships a new app version, an
outdated UA could (in theory) be soft-blocked or simply look stale. On an APK bump,
re-read and update from the new decompiled app:

| Constant | Source |
|----------|--------|
| `APP_VERSION_NAME` / `APP_VERSION_CODE` | `AndroidManifest.xml` (`versionName` / `versionCode`) |
| `APP_LABEL` | `res/values*/strings.xml` → `app_name` |
| `OKHTTP_VERSION` | bundled okhttp default-UA string (`okhttp/x.y.z`) |
| device profiles | any current real `Build.MODEL` + `Build.VERSION.RELEASE` pairs |

---

## 8. Confidence

The construction, interceptor ordering, and the appended `okhttp/4.11.0` are read
directly from the bytecode and are reliable.

**The open question here is answered - updated 2026-09-18.** This section used to say the
server's acceptance of this UA was unverified and wanted one probe. There have since been
two kinds of evidence, and the second is the stronger one:

- **Direct probes, 2026-07-19** - search, detail, taxonomy, geocoding, suggestions and
  ratings all returned `200` with *only* this UA and no other headers
  ([`HIDDEN_API.md`](HIDDEN_API.md) §7).
- **Sustained production traffic through Tor** - `BazosApiScraper` sends
  `default_user_agent()` on every request, and query 12 has run on it since 2026-08-08:
  **219 successful query-runs in the 7 days to 2026-09-18**, 425 ads collected. A UA-level
  gate could not produce that.

So there is no TLS/HTTP2 fingerprint gate *that this UA fails* - a stricter claim would need
an A/B against a deliberately mismatched client, which nobody has run. The failures this
transport does see are IP blocks: a `403` whose body names the offending egress in as many
words (`... permission to access this server. IP: x.x.x.x`, parsed by
`MarketplaceBlockedError.from_response`). **Bazos attributes the refusal to the IP, not to
the client string** - do not reach for the UA when diagnosing a 403.

What stays genuinely unverified is §7's *maintenance* risk: whether an outdated
`APP_VERSION_NAME`/`build:` pair is soft-treated differently. The pinned APK is v2.19.1 and
nothing has re-checked whether that is still current.

---

## 9. The HTML path — Bazos serves a different DOM to mobile User-Agents

> **Not about §1–§8's app UA.** `BazosScraper` fetches ordinary web pages, not `api/v1/`, and
> draws its agent from `requests_random_user_agent`'s pool — which patches
> `requests.utils.default_user_agent` to pick a fresh one **per call**. That pool ships phone
> and tablet agents.

Measured live 2026-09-17 on one query's own listing URL, same Tor circuit, seconds apart:

| User-Agent | rows parsed | rows missing `inzeratycena` |
|---|---|---|
| desktop Chrome | 20 | **0** |
| iPhone Safari | 20 | **20** |
| Android Chrome | 20 | **20** |

The mobile markup is a **different template, not a degraded one**: it carries price and
locality inline inside `div.popis` and has no `inzeratycena` / `inzeratylok` / `inzeratyview` /
`inzeratyakce` at all.

### 9.1 Why that costs a whole pass, not one ad

`_parse_product` is written against the desktop template, so it raises `AttributeError` on the
**first** row. Three properties compound:

- It fires **while the generator is being iterated** — `run_query` does
  `list(get_page_products(...))` — so it lands **outside** `_tolerating_one_bad_ad`, whose
  guard wraps the loop *body*. The per-ad tolerance does not apply.
- It is not a `MarketplaceBlockedError`, so `_run_query_with_rotation` does not retry it. One
  draw of a mobile agent writes the query off for the pass.
- It is **invisible in the aggregate**. The zero-rows canary counts rows *parsed*, and a query
  that raised parsed none — it stops contributing to the numerator while the healthy queries
  keep the totals looking normal. Same blind spot that let every Vinted query 404 for eight
  days; `QUERY_FAILURE_ALERT_THRESHOLD` is what now covers it.

**2 of 62 agents in the pool were mobile — about 3% of sessions.** Frequent enough to lose
passes steadily, rare enough to read as ordinary Bazos flakiness. (Re-counted against the
installed `requests_random_user_agent` on 2026-09-18: still 62 agents, still 2 mobile. The
pool ships with the library and `poetry.lock` pins it at 2023.10.25, so the ratio does not
drift on its own - but a dependency bump can move it, which is why
`drop_mobile_user_agents()` filters by marker rather than by a hardcoded list.)

### 9.2 The fix, and the fix that would be wrong

`ip_changer/tor.py::drop_mobile_user_agents()` strips them at import, matching
`MOBILE_UA_MARKERS = ("Mobile", "Android", "iPhone", "iPad", "Windows Phone")`. Two details are
load-bearing: it mutates the pool **in place** (`pool[:] = desktop`), because the library's
patch closes over that list object by name in its own module; and it **refuses to empty the
pool**, because `random.choice([])` raises inside the patched `default_user_agent` and would
break 100% of requests instead of 3%.

⚠️ **Do not "fix" this by teaching `_parse_product` the mobile layout.** The mobile template
has no `inzeratyakce`, and that block is the only source of `publisher_email` /
`publisher_phone` on the HTML path. A parser that handled both would stop raising and start
**silently dropping seller identity** on ~3% of ads — which feeds `SellerAdCounts`,
`PublisherBlocklistRule`, and every seller-keyed lookup in §6.4 of `HIDDEN_API.md`. A loud
failure on 3% of passes beats quiet corruption of 3% of rows.

### 9.3 What this implies for §6's rotation strategy

§6 recommends rotating a `DeviceProfile` per Tor identity so each exit looks like a distinct
fresh install. That reasoning holds **for the API path only**. On the HTML path the constraint
runs the other way — the parser pins us to one device class, so agent variety there is bounded
by what the DOM allows rather than by what looks most natural. Any future per-identity rotation
on the HTML path must draw from the desktop subset.
