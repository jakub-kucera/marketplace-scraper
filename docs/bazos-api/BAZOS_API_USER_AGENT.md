# Bazos Mobile App — User-Agent Behaviour

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
directly from the bytecode and are reliable. What remains **unverified without a live
capture**: that the server actually accepts this UA and doesn't additionally gate on a
TLS/HTTP2 fingerprint. One probe (through the project's Tor proxy) would confirm it.
</content>
