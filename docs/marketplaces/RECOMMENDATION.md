---
title: Which marketplace to build next — ranked recommendation
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Which marketplace to build next — ranked recommendation

> Completed 2026-08-22. Two ranked lists per RESEARCH_BRIEF §8: **Track A** (marketplaces to
> scrape) and **Track B** (reference-price sources). All claims measured unless marked ⚠️ ASSUMED.
>
> **Build next: Sbazar.cz.** Then run three cheap probes that decide whether Aukro is the one
> after it. Reasoning in §3 — including why this does *not* follow the brief's own headline
> weighting, and why I think the brief's weighting is wrong on the measured evidence.

---

## 1. Track A — marketplaces

| # | Candidate | Verdict | Target-category scale | New capability | Cost to build | Legal posture |
|---|---|---|---|---|---|---|
| **1** | **Sbazar.cz** | **VIABLE** | tools **26,738 (3.4× Bazos)**, notebooks 4,401 | **None** | **Lowest — zero migrations** | **Worst of the three** |
| **2** | **Aukro.cz** | **VIABLE** | 145k–162k (broad cats) | **⭐ Realised prices** | Medium + breaking prerequisite | **Best of the three** |
| **3** | bazos.sk/.at/.pl | VIABLE | `.sk` notebook **7,225 (0.92× .cz)** | None | Near-zero | Same as Bazos |
| — | Hyperinzerce, Annonce, Mimibazar, Avizo | REJECT | 15–370× below | — | — | — |
| — | TipCars, Sauto, Sreality, Bezrealitky, Remix | REJECT | Wrong categories | — | — | — |
| — | Facebook Marketplace | REJECT | Not measured | — | — | Prohibitive |

## 2. Track B — reference-price sources

| # | Source | Verdict | Why |
|---|---|---|---|
| 1 | **Heureka / Zboží.cz** | **DEFER** | Works for **current-model** goods — **tools best-served** (Makita DHP484 → 4 canonical products, 2,920–5,391 Kč across 44 shops). Useless for discontinued electronics. **Blocked on our side, not theirs.** |
| 2 | eBay sold listings | **DEFER (effectively unavailable)** | `findCompletedItems` decommissioned 2025-02-05. Marketplace Insights is Limited Release, "not open to new users". **There is no signup form.** |

**Track B is premature — and here is the condition that changes that**, as §8 permits:

> **Track B unblocks the moment `Ad` gains structured brand/model fields.** Today `Ad` has only
> free text (`name` 120, `short_description` 300) — there is nothing to join *from*. Both sources
> fail on the same near side. **Do not start Track B until an extraction step exists.**

⚠️ **Both Track B assessments inverted a brief assumption.** §2c says a reference-price baseline
"transfers well for phones, laptops, GPUs — and poorly for furniture, tools and bikes." Measured,
that is **backwards**: the discriminator is *product lifecycle*, not category. Tools stay in
production for years and match richly; laptops churn annually and fall out of the new-goods
catalogue. `Macbook Pro 13 2020` returned exactly one "match" — **a phone case at 999 Kč**. This
matters because tools are the biggest opportunity in Track A.

---

## 3. Build Sbazar first — the argument, including against myself

### 3.1 The case for Sbazar

- **Biggest measured gain in the category that matters most.** `stavebnictvi-naradi` holds
  **26,738** active listings — **3.4× Bazos's `naradi` (7,716)**, the largest single-category
  uplift found anywhere in this study, in a core flipping category.
- **Genuinely near-zero engineering, and this is measured not estimated.** `id` is an integer
  (range 6,962,902–233,341,956) fitting `BigIntegerField` unchanged. **Zero migrations** beyond a
  `Marketplace` choice and a registry entry.
- **The cleanest transport found.** `GET /api/v1/items/search` and `/api/v1/items/{id}` —
  unauthenticated, no token, no cookie, `limit=1000` served whole (1.3 MB in 1.37 s), and
  **newest-first by default**, so §5b.4's dedup-ordering requirement is satisfied for free.
- **No price trap.** `price` is a plain integer in whole CZK (1,100 rows: zero floats). It is
  neither Aukro's `861.0`→`8610` nor Zboží's hundredths.
- **`topped` is a real boolean**, so the Bazos bumped-timestamp trap
  (`pass1/METHOD_CALIBRATION.md` §2–§4) does not apply.

### 3.2 The case against — stated plainly, because it is real

- **It adds no new capability.** No realised prices, no seller ratings, no structured attributes,
  no view count — all measured absent. Sbazar is *more asking prices*, which is exactly what
  RESEARCH_BRIEF §8 says should rank **below** a capability play.
- **It has the worst legal posture of the three.** `robots.txt` is `User-agent: * / Disallow: /`
  with per-crawler allowlists, it separately carries `Disallow: /api/` — covering the very
  endpoint this design rests on — and it disallows `/*/nejnovejsi` (newest-first), the ordering
  the pipeline needs. There is also a `cmp.seznam.cz` consent wall on HTML documents (the API
  layer bypasses it, which is a *technical* observation, not a permission).
- **The ToS have never been read.** Neither pass fetched them. This is the single largest
  unquantified risk on the recommended build.

### 3.3 Why Sbazar anyway — where I part company with the brief

§8 says a candidate closing the realised-price gap outranks a bigger one adding asking prices.
Applied naively that selects Aukro. **The measurements say that weighting assumes something not
yet true: that Aukro's capability is real *in the categories this project cares about*.** Three
findings put that in doubt, all measured today:

1. **The realised-price corpus is sparse.** Across 9 sampled ended items, **1** carried bids
   (~11%). Roughly 9 detail fetches per realised price.
2. **Buy-now listings are a blind spot.** They return `price: null` and `biddersCount: null`, with
   **no observed field distinguishing sold from expired.** So the capability is *auction-only*.
3. **Aukro is a collectibles marketplace with a general-goods wing** — `antikvariat`,
   `numismatika`, `filatelie`, `faleristika`. Phones/laptops/tools skew to buy-now far more than
   postcards do, so ⚠️ **the capability is plausibly weakest exactly where the flipping thesis
   needs it** — untested, and the most important open question in this study.

Add the engineering asymmetry: Aukro needs **P22 (`price_raw` → integer + `price_type`) as a hard
prerequisite** — a breaking refactor touching Bazos and Vinted — because its float silently
corrupts prices by 10×. And its Cloudflare blocks by ASN, so it **may be incompatible with the
production Tor stack entirely.**

**So: Sbazar is cheap, immediate, reversible, and doubles deal flow in the best category. Aukro is
a bigger prize resting on three unverified premises and a breaking refactor.** Build the certain
thing; spend five requests establishing whether the bigger prize is real.

⚠️ **The honest counter-argument, which you should weigh yourself:** if the project's goal is the
*data asset* rather than deal flow (`MONETIZATION.md` §7.3's compounding-archive thesis), then
Aukro's realised prices are the only thing in this entire study that compounds, Sbazar is merely
more of what you already have, and **every day Aukro is not being archived is data destroyed
permanently.** That argument is strong, and it would flip the recommendation. It hinges on
whether §3.4's probes come back positive.

### 3.4 ✅ The three probes were RUN (2026-08-22) — here is what they returned

All three are answered. **The recommendation is unchanged, but the reasoning shifted: two probes
came back *better* than expected and one came back worse.**

| Probe | Result |
|---|---|
| **1. Aukro through Tor?** | ❌ **No — `403 cf-mitigated: challenge` on 3/3.** Sbazar returned `200` on 3/3 through the same circuit. **Now a hard infrastructure dependency** (`AUKRO.md` §4.1.1). |
| **2. Do buy-now items expose sold-ness?** | ⚠️ **Probably yes — `quantity == 0` marks sold, 21/21 consistent.** Confirmed on `BIDDING`; no sold `BUYNOW` observed yet, so not settled. |
| **3. Realised-price density in target categories?** | ✅ **Yes.** Second sold item found was `Počítače a hry`, 7 bidders, **3,126 CZK**. Target + adjacent categories ≈ **30%** of ended inventory. Sell-through ≈ **9.5%** over 21 samples. |

**What this changes:**

- **Aukro's capability is more real than §3.3 assumed.** Two of the three doubts there —
  "buy-now is a blind spot" and "the capability may be weakest where the thesis needs it" — are
  substantially answered in Aukro's favour. `quantity` is a general stock field, and computers
  genuinely carry realised prices.
- **But Aukro now has a prerequisite it did not have before.** It cannot run on the Tor stack at
  all. Building it requires either a residential rotating proxy
  (`../proxies/PROXY_ROTATION_RESEARCH.md`, which already prices this) or direct host egress as
  Vinted uses. **That is an infrastructure decision, not a scraper task.**
- **Sbazar is unaffected and cleared its own pre-flight** — `200` on 3/3 through Tor, so it needs
  no carve-out. Build it exactly as spec'd.

**Net: build Sbazar now; Aukro is a stronger candidate than before but has grown a second
prerequisite (proxy) on top of the first (P22).** Both are worth doing — neither is a scraper.

### 3.4-orig The three probes that decide Aukro — ~5 requests total

Do these **before** committing to Aukro, and ideally while Sbazar is being built:

1. **Does Aukro work through Tor?** The production stack is `IP_CHANGER_TYPE=TOR`; Aukro blocks by
   ASN and Tor exits are datacenter-reputation. **This can invalidate the whole build.**
   ```bash
   docker compose up -d tor_proxy
   curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:9050 \
     -H 'X-Accept-Subbrand: BAZAAR' \
     'https://aukro.cz/backend-web/api/offers/7130732448/offerDetail?pageType=DETAIL&requestedFor=DETAIL'
   ```
2. **Do buy-now items expose sold-ness anywhere?** Fetch 2–3 ended `BUYNOW` items and diff their
   payloads against an ended `BIDDING` one. If not, realised prices are auction-only — halving the
   capability's value.
3. **What is realised-price density in `pocitace-a-hry` / `dum-a-zahrada`?** Sample ~10 ended items
   *in the target categories*, not random ids. If sell-through there is near zero, the capability
   does not serve the flipping thesis and Aukro drops to a data-archive play only.

### 3.5 On bazos.sk / .at / .pl — the cheap breadth option

**Now confirmed working from residential**: `bazos.sk` returns `x-total-count: 7225` for
`notebook` — **0.92× bazos.cz**, i.e. a near-doubling of Bazos-shaped inventory for essentially
zero engineering (`BazosApiScraper` + base URL + currency).

**But take the brief's own warning seriously, and one thing it did not know:** all three refused a
datacenter VPN IP that `.cz` *accepted at the same moment*, with the IP named in the response body.
So the sister domains run a **stricter blocklist than `.cz`** — same operator, same ToS, same
control plane, and now demonstrably a *more* fragile access path. **This is cheap breadth, not a
hedge**, and against `MONETIZATION.md` §7.4's concentration risk it does nothing: one sole trader
can still end all four in an afternoon.

**Take it if you want volume this week; do not count it as diversification.**

---

## 4. Sequencing

0. ✅ **Tor pre-flight — done.** Sbazar `200` ×3, Aukro `403` ×3. Sbazar needs no carve-out.
1. **Read Sbazar's ToS.** One request. The largest unquantified risk on the recommended build.
2. **Build `SbazarScraper`** against `/api/v1/items/search`. Two gotchas, both measured:
   `short_description` is detail-only **and overflows the 300-char column (679 observed)**;
   and "price by agreement" is `price: 0` + `price_by_agreement: true`, where **`price == 0` does
   not imply by-agreement** (15/1000 disagree — genuine giveaways). Branch on the boolean, never
   on the integer, or `PriceRangeRule` silently rejects every negotiable ad.
3. **Run §3.4's three Aukro probes in parallel.** ~5 requests, and they decide the next build.
4. **Then P22** (`price_raw` → integer + `price_type`) — required for Aukro, independently useful,
   and the thing `PROMPTS.md` P23 is actually blocked on.
5. **Only then reconsider Track B**, which needs structured brand/model on `Ad` (§2).

## 5. What this study could not determine

- **No ToS were read for any candidate.** robots.txt only. The largest gap across the whole study.
- ~~Aukro through Tor~~ — **answered: blocked** (§3.4). Replaced by a live question: **residential
  proxy or direct host egress?** That is now Aukro's gating decision.
- ~~Aukro's realised-price density in target categories~~ — **answered: ~9.5% overall, target
  categories ≈30% of ended inventory, confirmed realised price in `Počítače a hry`** (§3.4).
- **Whether `quantity == 0` marks a sold BUY-NOW** as it does a sold auction. One sold buy-now item
  settles it, and it decides whether realised prices are auction-only or Aukro-wide.
- **Whether `price` on an ended Aukro auction is always the winning bid** vs a reserve-not-met
  last bid. **One example.** Do not generalise.
- **Aukro's newest-first sort parameter name** — known to exist, name unresolved; blocks both a
  valid new/day figure and correct dedup ordering.
- **Heureka's own price shape** — Cloudflare-challenged from datacenter; not retried residential.
- **eBay's current licence terms verbatim** — its docs 403'd every first-hand request, so those
  claims are search-index retrievals, **not safe to paste into a spec**.

## 6. Methodology corrections this study produced

Recorded because they change how the next assessment should be run, and two of them corrected
conclusions already written down here:

1. **`METHOD_CALIBRATION.md`** — the brief's §2b new/day method failed twice on Bazos before
   working: `topped` is the **string** `"true"` (a truthiness check marks 100% of ads promoted),
   the method is **impossible at default page size** (0 organic ads in 30), and **diurnal bias is
   ~2×** (474/day from a 3.5 h window vs 241 and 219 from ~20 h windows).
2. **Sitemap `<lastmod>` overstated new/day by ~4×** on Sbazar (tools ~139/day actual, not ~559)
   because it conflates edits with creations. Active counts were unaffected (within 1%).
3. **A vendored third-party API description is not evidence about the live service.** Pass 1
   concluded Aukro had no realised prices, reasoning from an Allegro WSDL on GitHub. Two of its
   three inferences were measured false. The brief's §4d rule ("if you find a library, you must
   run it") generalises to API specs.
4. **A site's own headline count can be a trap.** Annonce reported "1568 inzerátů" for `notebook`;
   the category breakdown showed **1,544 were job ads** mentioning a laptop as a perk. Real count
   ~21–40. Always check the breakdown before believing a total.
5. **"Datacenter IP" explains Czech marketplace blocks but is not universal.** Aukro, Sbazar and
   `bazos.sk` all cleared instantly from residential; **eBay blocked the same residential line just
   as hard.** A residential IP is not a master key.
