---
title: Bazos API Cutover and Cadence
status: active
updated: 2026-09-18
verified: 2026-09-18
---

# Bazos API Cutover and Cadence

**The executable form of [`PROMPTS.md`](PROMPTS.md) P21a Parts 1 and 4a.** That prompt says what
to do in nine numbered steps; this says what is actually true when you start, which is different
from what the prompt assumed, and it names three ways the cutover degrades filtering **silently**
if you do it as written.

Read `HIDDEN_API.md` §4–§5 and
`PROXY_ROTATION.md` §4–§5 first for the payload shapes
and the volume model. This doc does not restate them; it corrects one of them and builds on both.

---

## 1. Measured baseline — and a correction to the volume model

Measured against the production DB on the Pi, **2026-08-30 → 2026-09-06** (7 days), and
**re-measured over 2026-09-11 → 2026-09-18** to check it had not drifted. It had not, except in
one respect worth naming:

| Measure | 2026-09-06 | 2026-09-18 |
|---|---|---|
| Query-run attempts | 5,293 | 6,462 |
| Failed | 2,637 — **49.8 %** | 3,498 — **54.1 %** |
| …of which `MarketplaceBlockedError` | **2,635** (the other two: one `SSLError`, one `RuntimeError`) | **3,427** (plus 67 `RuntimeError`, 2 `ReadTimeout`, 1 `SSLError`, 1 `AttributeError`) |
| Distinct blocked exit IPs | 503 | 537 |
| Enabled queries | 13 (12 during the sample window) | 14 |
| Median duration of a successful query | 19.8 s | 6.1 s |
| **Median cycle per query** | **42.2 min** (mean 45.2, p90 71.8) | **42.7 min** (mean 46.3, p90 74.0) |

Two consequences, both load-bearing for this work:

**The transport's dominant failure mode is still the only one that matters, but it is no longer
the *only* one.** 3,427 of 3,498 failures are Bazos 403-ing the exit IP - 98.0 %, against 99.9 %
in the first window. The ~48 % coin flip that
`PROXY_ROTATION.md` inferred from two spot probes is
confirmed and has if anything worsened: **54.1 % over 6,462 attempts and 537 distinct exits**.
The new 2 % tail is **not** a Bazos transport fact and joining `bazos_queryrun` to
`bazos_query.marketplace` says so outright: all 67 `RuntimeError` rows are Vinted's withdrawn
`/api/v2/catalog/items` endpoint (last seen 2026-09-16, the day `v1.2.0` replaced that scraper),
the two `ReadTimeout`/`SSLError` rows are Sbazar and Vinted, and the single `AttributeError`
(`'NoneType' object has no attribute 'text'`, 2026-09-17) is the blocked-detail-fetch defect
fixed in `a877177`. Bazos itself contributed **one** non-block failure in seven days.
⚠️ **Do not quote "exactly one failure mode" without re-running the breakdown grouped by
marketplace** - unqualified, it reads as a claim about the fleet.

**The median successful-query duration fell 19.8 s → 6.1 s while the cycle did not move.** That
is consistent with the two things that landed in between - the mobile-UA fix and the per-query
failure alerting - trimming wasted work inside a query without touching the number of 403'd
attempts a pass has to walk through. It is the block rate, not per-query parse cost, that sets
pass duration, which is exactly §1.1's point.

**`PROXY_ROTATION.md` §5's cadence model omits pass duration, and every latency number
downstream inherits the error.** It computes `passes/day = 1200 / interval_minutes`, treating the
sleep interval as the cycle. The real cycle is `sleep + pass duration`. Measured cycle is 42 min
against a ~30 min average sleep, so **a pass costs ~12 minutes of wall clock**, roughly half of
it spent on attempts that 403. This is the most durable number in this section: two independent
7-day windows twelve days apart give 42.2 and 42.7 min.

So the honest current figure is a **~21 min median detection latency, not ~15**, and at p90 an ad
sits ~36 min before discovery.

### 1.1 What this work can and cannot buy

`P21a`'s "~5 min median" assumes pass duration is zero. It is not, and this work does **not**
reduce the block rate (49.8 % then, 54.1 % now) — that is P21b's job, and it is the term that
dominates pass duration.

| | Sleep | Pass | Cycle | Median latency |
|---|---|---|---|---|
| Today (HTML, 15–45 min) | ~30 min | ~12 min | **42 min** | **~21 min** |
| After this work (API, ~10 min) | ~10 min | shorter, but block-bound | **~13–15 min** | **~7 min** |
| After P21b as well | ~10 min | ~halved again | ~11–12 min | ~5–6 min |

A genuine 3×. Just not by the arithmetic in the prompt — **do not promise 5 minutes from this
work alone**, and re-measure with §8.1 rather than asserting the improvement.

---

## 2. The three silent-degradation traps

The cutover is not "switch `Query.marketplace` to `bazos_api`". The API's **thin** listing
payload (`ads.php`, §5.1) carries strictly less than the HTML listing page, and three filter
rules read fields it omits. Every one degrades to *permissive*, which is indistinguishable from
"not configured" — nothing errors, nothing logs, the query just quietly notifies more.

Production evidence, **re-measured 2026-09-18**: all 425 existing `bazos_api` ads (was 273) vs
27,568 `bazos` ads (was 19,904). Every proportion below is unchanged - the gaps are structural,
not a sampling artifact of the small early corpus:

| Field | `bazos` missing | `bazos_api` missing | What breaks |
|---|---|---|---|
| `short_description` | 0 / 27,568 | **425 / 425** | `blocklist_keyword`, `required_keyword` — their haystack is `f"{ad.name} {ad.short_description}"` (`filters.py:138,155`), so both degrade to **name-only matching** |
| `location` postcode | 0 / 27,568 | **425 / 425** | `location_distance` — it parses the PSČ out of `Ad.location`; the API sends `locality` (`"Praha 10"`) with no code, so the rule PASSes everything |
| `publisher_name`, publisher FKs | 0 / 27,568 | **425 / 425** | `publisher_blocklist` can never fire; `Ad.message` renders `"Seller: unknown"`; `SellerAdCounts` is meaningless |
| `view_count`, `publish_date` | 0 | 0 | — fine, the API sends both |

**None of these is a bug in `BazosApiScraper`.** They are all the same fact: `ads.php` is a thin
payload and `ad-detail-2.php` is the rich one (§5.1 vs §5.2). The prompt's Part 4a says "confirm
parity" without saying parity *of what*; §7 below makes that testable.

---

## 3. Part 1 — tunable page size

`_fetch_page` (`bazos/scraping/bazos/bazos_api_scraper.py:166-167`) hardcodes `limit=API_PAGE_SIZE`
(210). Measured wire sizes (`PROXY_ROTATION.md` §4):

```
HTML search.php (20 ads)   11.2 KB   1.20 s     ← today, ~3 per query per pass
API ads.php limit=210      15.0 KB   0.85 s     ← what the cutover would send today
API ads.php limit=10        1.1 KB   0.78 s     ← what a steady-state pass needs
```

210 is right for a **backfill** — it is the server's hard cap, and one request gets a new query's
whole first page-set. It is wrong for a **routine pass**, which fetches 210 listings to discover
the 0–3 new ones at the top.

**Changes:**

1. Add `STEADY_STATE_PAGE_SIZE: Final[int] = 10` to `bazos/const.py`, next to `API_PAGE_SIZE`,
   with a comment naming the measurement above.
2. Give `_fetch_page` a `limit: int = API_PAGE_SIZE` parameter and use it in `page_params`.
3. `run_query` passes `STEADY_STATE_PAGE_SIZE` on the dedup walk and `API_PAGE_SIZE` from
   `run_new_query`'s backfill path. The distinction already exists in `QueryRunner`
   (`run_new_query` vs `run_existing_query`); thread it, do not infer it inside the scraper.
4. Leave any bulk `ad_id[]=` path at 210 — that form has no pagination cost to save.

**Trap:** `dedup_break_streak` is 1 for Bazos, so a pass stops at the first known non-topped ad.
With `limit=10` that is still comfortable, but topped ads are pinned to the front under
`sort=date` (§4.3) — if a query's category carries more than ~8 topped ads, a 10-item page could
be all topped and the walk would page again anyway. Check the topped count on the canary query
before assuming 10 is enough; raise to 20 if so. This is cheap to get wrong and cheap to fix.

---

## 4. Part 1b — close the three gaps before cutting over

Do these in the same change as Part 1. Each is a decision, not a mechanical fix.

### 4.1 `short_description` — the one that matters most

The API listing has no description text at all, so there is nothing to copy. Two honest options:

- **(a) Widen the filter haystack.** Change `blocklist_keyword`/`required_keyword` in
  `bazos/filters.py` to match `f"{ad.name} {ad.short_description} {ad.full_description or ''}"`.
  Then the rules work on the API path **for queries with `load_full_description=True`**, and are
  name-only otherwise. This is a behaviour change for existing HTML queries too — a blocklist
  phrase appearing only in a long description now rejects where it previously did not. That is
  arguably a fix, but it is a change; it needs its own test and its own line in `SHIPPED.md`.
- **(b) Only cut over queries whose filtering does not depend on description text.** Cheapest,
  and it keeps the blast radius at zero. Query 11 (`hole OR hul`) and the section-scoped queries
  with empty `filter_required` are candidates; query 15
  (`macbook m3 OR macbook m4 OR macbook m5`) is not.

**Recommendation: (b) for the cutover, (a) as a separate follow-up.** Bundling a filter-semantics
change into a transport migration is how you lose the ability to attribute a regression to
either.

### 4.2 The postcode

`zip_code` is detail-only. Options, cheapest first:

- **(a) Geocode the locality string.** `zip.php` resolves names, not just codes — verified live,
  `query=Praha` returns coordinates. `bazos/geo.py::ensure_postal_code` currently takes a code;
  it would need a sibling that takes a locality. Accuracy is city-centre-level, which for a
  10 km radius is already inside the noise of the post-office coordinates
  (see the `PostalCode` docstring). **Cheapest and probably sufficient.**
- **(b) Take it from the detail call** when `load_full_description=True` — free where the call
  already happens, useless where it does not.
- **(c) Keep distance-filtered queries on HTML.** Zero work, and correct, but it means the
  cutover is permanently partial.

**Recommendation: (a)**, with (c) as the fallback if locality strings turn out to resolve poorly.
Whichever you pick, the acceptance test in §7 must fail if a cut-over query's ads produce no
resolvable location.

### 4.3 Publishers

`email_id`/`phone_id` are detail-only, exactly like the postcode. `publisher_blocklist` is a
per-query opt-in that no production query currently relies on, and `Ad.message` already degrades
honestly to `"Seller: unknown"` (`models.py:623`) rather than claiming a false zero.

**Recommendation: accept the loss for now, and record it.** Fixing it means a detail call per ad,
which is P13's territory (filter-before-detail-fetch) and is the one thing
`PROXY_ROTATION.md` §5.1 names as the real ban vector.
Do not enable `load_full_description` on cut-over queries just to recover seller identity.

---

## 5. Part 4a — the cutover

1. **Pick a canary.** Query 12 is already `bazos_api` and has been running — use it as the
   reference, not the canary. The canary should be a query whose filtering survives §4.1's
   option (b): no `filter_required`, no `filter_blocklist`, no distance filter.
2. **Run the parity check** — `python manage.py compare_bazos_scrapers --query-id <id>` — and
   apply §7's criteria. This is read-only and never writes `Ad` rows.
3. **Cut the canary over**, deploy, and let it run for **at least 24 h** at the *current*
   interval. Do not change cadence and transport in the same step; if something regresses you
   need to know which one did it.
4. **Compare against the HTML baseline** with §8.1's query: new-ad rate per pass, and the block
   rate on that query specifically.
5. **Migrate the rest**, in batches, respecting §4.1's exclusion list.
6. **Only then** lower `INTERVAL_LOWER`/`INTERVAL_UPPER` to ~600 s. These are already env-driven
   (`scraper/settings.py:263-264`), so this is a `.env` edit and a
   `docker compose up -d marketplace_scraper` — no deploy.
7. **Watch for a few days**: the P19 zero-results canary, the block rate, and §8.1's cycle
   measurement. `PROXY_ROTATION.md` §5's table says request volume should land near today's;
   verify that rather than assuming it.

---

## 6. What must NOT change

- **Do not reintroduce a pre-flight blacklist probe.** See CLAUDE.md's "Blacklist / IP guards"
  note — the query attempt is the probe, and the old one was actively misleading under
  `IsolateDestAddr`.
- **Do not enable `load_full_description` broadly to recover the missing fields.** §5.1 of
  `PROXY_ROTATION.md` is explicit that detail-endpoint
  volume, not query count, is what re-creates the ban. That is P13's problem to solve first.
- **Do not lower the interval below ~10 min in this work.** Below that, request volume exceeds
  today's and the "free" argument stops holding. That is P21b.

---

## 7. Parity acceptance criteria

"Confirm parity" is untestable as written. Use these, on the canary query, over the same listing
window:

| Criterion | Threshold |
|---|---|
| Ads discovered by both scrapers | **≥ 95 %** overlap on `external_id` |
| `price` / `price_type` agreement on the overlap | **100 %** — any disagreement is a parser bug, not a payload difference |
| `name` agreement | 100 % after whitespace normalisation |
| `view_count`, `publish_date` present | 100 % — the API sends both; a gap means a parse bug |
| `short_description` present | **expected 0 %** — record it, do not treat it as failure |
| Location resolvable to a `PostalCode` | **≥ 95 %**, once §4.2 is implemented. **This is the gate**: if it fails, the distance filter is dead on this query |
| Publisher FKs present | **expected 0 %** — accepted per §4.3 |

The three "expected 0 %" rows are why this table exists: without it, a reviewer sees empty
columns and either panics or shrugs. Say in advance which gaps are the design.

---

## 8. Verifying it worked

### 8.1 The measurement

Re-run the query that produced §1's baseline, after the cadence change has been live ≥ 48 h:

```sql
WITH g AS (
  SELECT query_id, run_start,
         run_start - lag(run_start) OVER (PARTITION BY query_id ORDER BY run_start) AS gap
  FROM bazos_queryrun
  WHERE success AND run_start > now() - interval '2 days'
)
SELECT round(extract(epoch from percentile_cont(0.5) WITHIN GROUP (ORDER BY gap))/60,1) AS median_cycle_min,
       round(extract(epoch from percentile_cont(0.9) WITHIN GROUP (ORDER BY gap))/60,1) AS p90_min
FROM g WHERE gap IS NOT NULL AND gap < interval '4 hours';
```

**Success is the median cycle falling from 42 min to ~13–15 min** (§1.1). If it lands materially
above that, pass duration is dominating and the answer is P21b, not a shorter sleep.

### 8.2 The guardrail

Block rate must not rise. Same window:

```sql
SELECT count(*) FILTER (WHERE NOT success)::float / count(*) AS block_rate
FROM bazos_queryrun WHERE run_start > now() - interval '2 days';
```

Baseline is 0.498 (2026-09-06) or 0.541 (2026-09-18) - use the more recent, and re-run it
immediately before the change rather than trusting either; it moved 4.3 pp in twelve days with
no cadence change at all, so a stale baseline will read a normal drift as a regression.
A material rise means the cadence outran what one Tor circuit pool tolerates —
back the interval off before doing anything else.

---

## 9. Rollback

Every step is independently reversible, which is the point of the ordering in §5:

- **Cadence** — revert `INTERVAL_*` in `.env`, restart `marketplace_scraper`. No deploy.
- **A cut-over query** — set `Query.marketplace` back to `bazos`. Existing `Ad` rows keep
  `marketplace='bazos_api'` and are not rewritten; that is correct, they record how they were
  found. Note this leaves the query's dedup state split across two `marketplace` values, so the
  first HTML pass after reverting re-discovers ads it already has under the other key. They are
  distinct `Ad` rows by `(marketplace, external_id)`, so this produces **duplicate
  notifications**, not errors. Revert during a quiet period, or accept one noisy pass.
- **Part 1** — pure code, revert the commit.

---

## 10. Tests

- `_fetch_page` sends the limit it is given; `run_new_query` sends 210 and the dedup walk sends
  the steady-state value (assert on the request params, not on a live call).
- A cut-over query's ads resolve to a `PostalCode` (§4.2), using a recorded `zip.php` response.
- The existing e2e cassettes still pass unchanged — Part 1 must not alter the HTML path.
- Parity: extend `compare_bazos_scrapers` to emit §7's table, so the acceptance criteria are
  produced by the tool rather than assembled by hand.

---

## 11. Out of scope

- **The 49.8 % block rate** — P21b. This work is deliberately transport-neutral.
- **`ExitNodes {cz},{sk},{de}`** — the free Tor stopgap in
  `PROXY_ROTATION.md` §6 Option D. Worth trying, costs
  nothing, unrelated to this.
- **P13 (filter-before-detail-fetch)**, **P16 (thumbnails)**, **P25 (publisher name from the
  detail payload)** — all become cheaper after this lands; none is a prerequisite.
- **Interval below 10 min**, image downloads, and the broad scrape-all model.
