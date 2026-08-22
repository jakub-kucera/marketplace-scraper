# Scale-method calibration against Bazos — measured 2026-08-22

> Why this file exists: RESEARCH_BRIEF §2b prescribes a new/day method but has never been run.
> Before applying it to unknown marketplaces it was validated against **Bazos**, the one
> marketplace whose true answer is already known. It needed three corrections. Every Pass 1
> number in this directory should be read with these in mind.

## 0. Vantage point

Egress: `185.242.6.116`, M247 Europe (AS9009), Prague CZ — a **datacenter** ASN behind the
user's VPN. `bazos.cz` serves it normally; see `BAZOS_SISTER_SITES_pass1.md` for domains that
do not. UA used throughout: the app UA from `bazos/scraping/bazos/user_agent.py`.

## 1. The baseline still reproduces — the market is stable

| Scope | 2026-07-29 (`MONETIZATION.md` §2.3) | **2026-08-22 (measured)** | Δ |
|---|---|---|---|
| `notebook` | 7,973 | **7,849** | −1.6% |
| `iphone` | 6,943 | **6,586** | −5.1% |
| `naradi` | 7,634 | **7,716** | +1.1% |

Three and a half weeks apart, all within ~5%. The `x-total-count` signal is stable and the
comparison baseline in the brief is safe to rank candidates against.

```bash
UA='bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0'
curl -s -D - -o /dev/null -A "$UA" \
  "https://www.bazos.cz/api/v1/ads.php?query=notebook&sort=date" | grep -i x-total-count
# -> x-total-count: 7849
```

## 2. Correction 1 — `topped` is the STRING `"true"`, not a boolean

The API returns `"topped": "true"` / `"topped": "false"` as **strings**. In Python,
`not ad["topped"]` is `False` for *both* values, because any non-empty string is truthy. A naive
filter therefore classifies **100% of ads as promoted** and the method silently reports "no
organic ads" on a page that is mostly organic.

This was hit live during calibration and produced a wrong intermediate conclusion before it was
caught. **Compare explicitly: `a.get("topped") == "false"`.**

Generalised for other marketplaces: **never trust a truthiness check on a JSON flag you have not
looked at.** Print the distinct raw values first.

## 3. Correction 2 — the method is impossible at default page size

RESEARCH_BRIEF §2b says to filter promoted listings out and measure the span of what remains. On
Bazos that is not merely a nuisance — at the **default page size it leaves nothing at all**:

| Request | Page size | Promoted | Organic |
|---|---|---|---|
| `query=notebook&sort=date` | 30 (default) | 30 | **0** |
| `query=notebook&sort=date&limit=210` | 210 (server cap) | 141 | 69 |
| `...&limit=210&offset=210` | 210 | 8 | 202 |
| `...&limit=210&offset=420` | 210 | 4 | 206 |

The promoted block runs ~141 deep on this query, consistent with the 132 measured for `iphone`
in `BAZOS_HIDDEN_API_RESEARCH.md` §4.3. A 30-item page never escapes it.

**Procedure for other marketplaces:** find the maximum page size first; if the promoted block is
deeper than one max-size page, page past it with an offset. **If neither is possible, method 1
is unavailable on that site** — record "not determinable within budget" rather than reporting a
number computed from a promoted-only page. §4.3 also documents a case where this is fatal
(`section=AU` was still 100% promoted after 3,150+ items).

## 4. Correction 3 — diurnal bias is real and ~2×

The same query measured over three consecutive windows on the same day:

| Window | Organic | Span | Implied rate |
|---|---|---|---|
| page 0 — freshest, ~13:15–16:45 Prague (afternoon peak) | 69 | 3.5 h | **474/day** |
| offset 210 — preceding ~20 h | 202 | 20.1 h | **241/day** |
| offset 420 — ~20 h before that | 206 | 22.5 h | **219/day** |

The freshest page overstates by **~2×** because it extrapolates the afternoon posting peak
across 24 h. This is the bias predicted by `BACKLOG_IDEAS.md` #6 (posting-time density), now
quantified.

**Rule:** prefer a window spanning **≥12 h**, always record the local sample time next to the
number, and present the result as an order of magnitude, not a measurement. Never compare two
candidates sampled at different times of day without saying so.

## 5. Cross-validation — the corrected method is sound

Corrected `notebook` rate ≈ **230/day** against 7,849 active listings implies
**≈34 days of inventory**. Bazos free ads expire at 60 days (ToS §137), and `MONETIZATION.md`
§2.3 notes that items selling early pull average life below the cap, citing public claims that
imply ~23 days. A measured 34 days sits between the two bounds and is consistent with both.

**Two independent signals agree, so the corrected method 1 is trustworthy.** Note this also
gives the project a per-category velocity figure it did not previously have: `notebook` turns
over roughly 230 new listings/day, i.e. about **10/hour**, which is the real ceiling on how much
deal flow any polling interval can capture.

## 6. Net effect on the brief

RESEARCH_BRIEF §2b method 1 should read: *max page size → verify you have escaped the promoted
block → filter promoted by explicit value comparison → require a ≥12 h span → report as
order-of-magnitude with the sample time.* As written it would have produced a number ~2× too
high on the freshest page, or a spurious "no organic ads" result, on the very first marketplace
it was applied to.
