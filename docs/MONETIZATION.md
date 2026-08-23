# Monetization Options — Analysis & Plan

> **Question:** how can this repository be turned into money? Options across selling
> scraped data, buying/reselling on the back of it, subscription products, and anything
> else. Plus: does it already exist, what are the financials, what are the legal issues.
>
> **Status of claims:** repo/data facts are read from the code and
> `data_export_23_3_2024/` on 2026-07-29. Bazos scale numbers are **live-measured**
> today via `api/v1/ads.php` `x-total-count`. Bazos ToS and `robots.txt` are quoted
> verbatim from the live site. Competitor and pricing figures are from public 2026
> sources (§9) and drift. Legal analysis is **research, not legal advice** — the
> GDPR/database-right questions in §6 are worth one paid hour with a Czech IT lawyer
> before anything public ships.

---

## 1. TL;DR

- **The valuable asset is not the data — it's the capability and the archive.** The
  scraper itself is ~2 weeks of work for a competent competitor (five Bazos scrapers
  already exist on Apify, §4.1). What can't be bought or copied is (a) a multi-year
  price/velocity archive of a market that **deletes itself every 2 months**, and (b)
  your demonstrated reverse-engineering ability. Neither is monetized today.
- **The archive still doesn't exist, but the schema no longer blocks it** *(updated
  2026-08-23)*. Of the three data-model defects in §7.2, **two are fixed**: price is a real
  integer with a `price_type` enum, and the `Ad`/`AdDelivery` split means one row per
  real-world ad rather than one per query. The archive is also **backed up** now. What remains
  is (c), the one that was always the biggest — **you have asking prices, never realised
  prices** — plus the fact that accumulation itself hasn't started: the corpus is still the
  16,987 ads of Jun 2023 – Mar 2024. If you want the data option ever, **start accumulating
  now**; it is the only item here that gets strictly more expensive to delay.
- **The flipping option still doesn't work at the current cadence.** A 15–45 min interval
  means a **~15 minute median detection latency**, while competing services poll every 60
  seconds and good deals are gone in minutes. §4.2's economics only exist after this is fixed.
  The free half of the fix (removing the redundant blacklist probes) landed 2026-08-23, but
  **the interval is unchanged and the API cutover hasn't happened**, so none of the latency win
  has been realised. ~1–2 days of already-designed work gets to ~5 min; ~$3–6/mo gets below
  that. **Still the highest-return change in the repository (§7.1).**
- **Ranked by risk-adjusted Y1 return per hour invested:** (1) contract/consulting off
  the back of this portfolio, (2) flipping for your own account, (3) an Apify actor as
  near-free pocket change, (4) a narrow B2B subscription **only with Bazos's written
  consent**, (5) selling datasets — don't, (6) selling contact/lead data — never.
- **Two hard legal walls shape everything.** Bazos's ToS requires **written consent for
  API use** and declares unofficial listing-display apps a breach (§6.3); and
  *Innoweb v Wegener* (CJEU C-202/12) held that a dedicated meta-search engine over a
  car-classifieds database infringes the **sui generis database right** (§6.4). Those
  two together mean: **anything that shows Bazos listings to a third party is legally
  exposed; anything that keeps the data inside your own head/hands is not.** That single
  distinction sorts the whole option list.
- **One thing must be deleted before any commercialization**, and arguably today: the
  `facebook/` app's leaked-dataset importer (§6.1). It is currently empty in every DB
  checked, but the code path exists and is wired into `PhonePublisher.fb_user`.
- **Recommended path:** cut the latency → flip for your own account (validates the anomaly
  detection *and* earns) → monetize the capability as contract work → only then, and only with
  consent, consider a product. Detailed sequencing in §8. *(The data-model half of the old
  "fix the data model" step is largely done; latency is what's left in front of everything.)*

---

## 2. What you actually own today

### 2.1 The code

A genuinely well-built pipeline: decoupled scraper/filter/sender stages communicating
through a Postgres status queue, a marketplace abstraction (`MarketplaceScraper`
protocol), IP rotation behind an ABC, Docker Compose deployment, CI with ruff/mypy/pytest,
and **~5,000 lines of design and reverse-engineering documentation**. The docs are
better than most commercial projects'. This matters more than it looks — see §4.5.

### 2.2 The data (measured, 2026-07-29)

| Asset | Reality |
|---|---|
| Historical export `data_export_23_3_2024/` | **16,987 ads**, 2023-06-04 → 2024-03-23 |
| — of which have `full_description` | **0** |
| — of which have a price | 16,981 (but as a **string**: `"12 500 Kč"`, `"Dohodou"`) |
| Concentration | **83%** of ads (14,107) come from a single query id |
| Publisher identities | 8,389 email ids, 9,299 phone ids — ⚠️ but see below: **one of those email ids was a sentinel, not a seller**, and held 6.7% of all ads |
| Dev DB (`db.sqlite3`) | 113 ads, 10 queries — not the production set |
| Coverage | ~6–10 narrow keyword queries; no category-wide sweep |

**Honest read:** this is a *demo-sized* dataset covering one narrow interest, missing
descriptions, with unusable price types and duplicate-prone identity. Nobody would buy
it. It is not a bad start on a *collection habit* — but as a saleable asset today, it
is worth approximately zero.

> **Publisher-identity correction, 2026-08-10.** The 8,389 email ids above overstate the
> real count in a way that mattered: `EmailPublisher` id 47 had `bazos_id=0` — Bazos's "this
> ad has no email publisher" marker, stored as if it were a seller — and **1,137 ads (6.7%)
> pointed at it, spanning 671 distinct phone ids**. It ran at a steady 6–8% of ads every
> month, so it was a scraper behaviour, not a one-off. Any per-seller statistic computed on
> this export before the fix was wrong on those rows, and grouping sellers transitively
> would have merged 671 unrelated people into a single 1,408-ad "seller" (8.3% of the
> dataset). Fixed at both ends — the scraper now writes NULL, migration `0025` removed the
> row. Recorded here because §2.2 is cited as the measured state of the archive, and because
> it is a concrete instance of §7.2's general point: **the identity columns need auditing
> before anything is computed on them.** Details and the full measurements:
> [`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) #11.

### 2.3 The market you're pointed at (live-measured today)

| Scope | Active listings |
|---|---|
| **All of bazos.cz** | **1,524,012** |
| `auto` (keyword) | 50,002 |
| category 93 (osobní auta) | 29,005 |
| `kolo` | 38,906 |
| `traktor` | 11,566 |
| `notebook` | 7,973 |
| `naradi` | 7,634 |
| `iphone` | 6,943 |

Free ads live **2 months** then auto-delete (ToS §137). So new-ads/day ≥ 1,524,012 / 60
≈ **25,000/day** as a floor (it is higher, because items that sell get deleted early —
public claims of ~65,000/day imply an average life of ~23 days, which is plausible but
unverified). Either way: **this is a large, fast-churning market whose own history is
destroyed every 60 days.** That destruction is the entire basis of any data value here.

Bazos is operated by **a single natural person** — Radim Smička, IČO 65773551 (from the
ToS). That cuts both ways: no legal department, but also no partnership process and a
personal, fast reaction to anything they dislike.

---

## 3. The one distinction that sorts every option

```
        Data stays with you                    Data goes to a third party
        ───────────────────────                ─────────────────────────────
        • flipping for own account             • dataset sales
        • private deal alerts to yourself      • B2C/B2B alert subscriptions
        • contract work (skills, not data)     • lead gen to dealers
        • generic tooling others point         • public price index of listings
          at their own targets
        ───────────────────────                ─────────────────────────────
        ToS: unenforced in practice            ToS: explicit breach (§6.3)
        DB right: no re-utilisation            DB right: Innoweb applies (§6.4)
        GDPR: legitimate interest plausible    GDPR: KASPR/Bisnode territory (§6.5)
        Realistic downside: IP block           Realistic downside: C&D, fine, claim
```

Everything below is scored against that line.

---

## 4. The options

### 4.1 Sell the scraped data

**Three sub-variants, all weak, for different reasons.**

**(a) Raw dataset sales.** Bright Data sells marketplace datasets (Facebook Marketplace,
OLX BR, Yapo CL) at **$250 per 100,000 records** — $0.0025/record. At that benchmark a
full 1.5M-listing snapshot is **~$3,750 (~82k CZK) gross, one-time**. You would not get
that: Bright Data sells with contracts, a compliance story, DPAs, and a sales team. You
have none. And a *snapshot* is the least valuable form of this data — anyone can
re-scrape it in a weekend.

**(b) Time-series / price index.** This is the only genuinely defensible data asset,
precisely because Bazos deletes it. "What did a 2016 Octavia 2.0 TDI actually ask, and
how fast did it disappear, in Ústecký kraj, in Q3 2025" is unanswerable by anyone who
wasn't recording. **But you have 10 months of one narrow query, and no realized-price
signal at all** (§7.2c). Building this is a 12–24 month accumulation project before it
has a first customer.

**(c) Publisher contact data.** 8,389 emails + 9,299 phones, plus the `ratings.php`
reviewer harvest your discovery doc describes. **Do not sell this, ever.** See §6.5 —
this is the exact fact pattern of the KASPR (€240k, then €200k) and Polish Bisnode
(€220k) fines.

**Does it exist?** Yes, and better-capitalized: Bright Data, Datarade (2,000+ vendors),
and for Czech cars specifically **Cebia** already runs the valuation product you'd be
building — their CebiCat GT priced 5.8M vehicles last year and AUTOTRACER already shows
"similar cars from the largest Czech and foreign classifieds portals." You would be
entering as a worse-resourced competitor to the incumbent, using data they may already
license properly.

**Financials:** realistically **0–80k CZK/year**, lumpy, with the highest legal exposure
of any option on this list.

**Verdict: don't pursue as a revenue line.** Keep accumulating the archive as a *free
option* on a future product, not as inventory for sale.

---

### 4.2 Buy low, resell — flipping for your own account

**This is the best risk-adjusted option and the only one with essentially no third-party
legal exposure**, because the data never leaves your hands. It is also the only option
that *validates the technology*: deal-velocity (how fast a flagged deal disappears) is
the precision metric your own discovery doc §3.4 proposes.

**Deal-flow model.** Using the live counts and the ≥ active/60 floor:

| Category | Active | New/day (floor) |
|---|---|---|
| iphone | 6,943 | ≥116 |
| notebook | 7,973 | ≥133 |
| naradi | 7,634 | ≥127 |
| **3-category focus** | **22,550** | **≥376/day** |

At a **2% "meaningfully underpriced" rate** (≥25% below comparable) → ~7–8 candidates/day.
Realistically ~10% are actionable (in range, not a scam, not already gone, seller
responds) → **~5 contactable/week → 1–2 closes/week.**

**Per-flip P&L (mid-ticket, 3–10k CZK):**

| Line | CZK |
|---|---|
| Buy (25–35% below market) | −5,000 |
| Sell (slightly under market, for speed) | +7,000 |
| Transport / fuel | −200 |
| Clean / minor repair / accessories | −300 |
| Dud allowance (~15%: misdescribed, won't move) | −300 |
| **Net per flip** | **≈ +1,200** |
| Time per flip (message → travel → inspect → list → hand over) | ~2.5 h |
| **Effective hourly** | **~480 CZK/h** |

**Annualized:**

| Intensity | Flips/yr | Net/yr | Hours/yr | Working capital |
|---|---|---|---|---|
| Part-time (1.5/wk) | ~78 | **~94k CZK** | ~195 | ~15k CZK |
| Committed (4/wk) | ~208 | **~250k CZK** | ~520 | ~40k CZK |

**High-ticket variant (cars).** 1–2/month, buy ~120k, sell ~145k, minus STK/repairs/
transfer/detailing ~8k → **~12–15k CZK net per car**, ~250k CZK/yr at 18 cars. But:
250–400k CZK of capital tied up, and you inherit the full *překupník* risk profile —
clocked odometers, undisclosed damage history, and (once you're a trader selling to
consumers) statutory defect liability on every car. **Higher revenue, much worse
risk-adjusted return.** Not recommended as a starting point.

**Infrastructure cost:** rotating residential proxy $3–6/mo + Pi electricity ≈ **2,000
CZK/year**. Payback: **the first flip.** The software is effectively free; your *time
and capital* are the constraint, not the tech.

**Does it exist?** Yes, extensively, as a manual practice — Czech/Slovak flipping is a
crowded hobby scene. What doesn't exist widely is *systematic* sub-minute detection
across whole categories. Your edge is latency and coverage, not insight.

**Verdict: do this.** It's the natural use of what you've built, it needs no new legal
posture, and it produces the feedback loop that any future product would need anyway.

---

### 4.3 Subscription products

**(a) Consumer alert app / website — don't build this.**

Three independent reasons it's dead:
1. **The incumbent gives it away free.** Bazos has a native saved-search "agent" with
   email notifications, plus official apps. You would charge for a free feature.
2. **The ToS prohibits it by name.** "*Využívání neoficiálních aplikací (app pro Android,
   iOS, Windows), které mají za účel zobrazovat inzeráty obdobně jako webový prohlížeč
   … je v rozporu s používáním webu a našeho API.*"
3. **Innoweb applies squarely** (§6.4) — a dedicated search product over a classifieds
   database is re-utilisation of that database.

Competitors already occupy the space anyway: **Bazoš Agent**, **Bazoš Strážca** (Chrome
extension), **realitnihlidacipes.cz** and **realitni-pes.cz** (Bazoš Reality, checks
every minute), plus multi-market apps like FlowMarket (eBay/Vinted/Wallapop/Marketplace,
5-min checks) and the €19–39/mo Vinted reseller SaaS cohort.

**(b) Narrow B2B vertical — the only subscription worth considering.**

Sell to a business whose *alternative is paying a person to refresh a browser*:
agricultural machinery dealers, scrap/metal buyers, pallet and industrial-equipment
traders, phone refurbishers, bike shops, antiques dealers. They care about latency and
completeness, they have budget, and there are few of them (so you hand-sell).

| Parameter | Assumption |
|---|---|
| ACV | 1,200 CZK/mo = 14,400 CZK/yr |
| Conversion on qualified outreach | 3–5% |
| Y1: 200 conversations → | ~8 customers, avg 8 months live |
| **Y1 revenue** | **~77k CZK** |
| Y2: 20 customers | **~290k CZK** |
| Churn | 20–30%/yr (value is "3 minutes earlier", easily rationalized away) |
| Real cost | **support** — every customer wants bespoke filters |

**Ceiling: ~300–500k CZK/yr at roughly 0.3 FTE — behind a legal cliff.** One email from
Bazos ends it. Only pursue **after** obtaining written API consent (§8, Phase 4).

**(c) Discord/community subscription** (paid deal-alert server). Same legal problem as
(a) with worse unit economics and a moderation burden. Skip.

---

### 4.4 Publish the scraper as a paid tool (Apify)

Near-zero marginal effort since the scraper exists. **But the niche is already
saturated:** at least five Bazos actors on Apify (`crawlerbros`, `studio-amba`,
`santamaria-automations`, `vzahajsky`, `appealing_jingle`). Observed traction on the
best-documented one: **12 total users, 5 monthly actives, no ratings, $1.00/1,000
results.** The comparable "AI deal finder" for Kleinanzeigen: **131 users, 4 monthly
actives, $7.00/1,000 deals found.**

Apify's headline is that top creators clear >$10k MRR and "many" clear $1k/mo at an 80%
revenue share — but that is the head of a very long tail, and the Bazos tail is where
you'd land. Note also the platform risk: rental actors must migrate to pay-per-event by
**1 Oct 2026**, and migrations without a proper PPE plan reported **40–70% revenue drops**.

**Financials: 200–2,000 CZK/month, realistically.** A weekend of work for a small,
passive trickle and a public portfolio artifact.

**Verdict: do it, but budget one weekend and expect coffee money.** Its real value is as
a credential for §4.5, not as revenue.

---

### 4.5 Sell the capability, not the data — the option you didn't list

**This is the highest expected value per hour on the entire list, and it carries zero
third-party legal risk.**

What you have is a portfolio that is unusually strong for this niche: a decompiled
Android app turned into a documented private API spec; live-verified probe logs; an
undocumented `email_id=`/`phone_id=` filter *you found by testing, not decompiling*; a
measured proxy/bandwidth benchmark with a split-transport architecture recommendation; a
clean decoupled pipeline with CI. Very few contractors can show that.

Concrete routes, in order of directness:

1. **Contract data-engineering / scraping work.** Czech senior contractor rates run
   ~900–1,600 CZK/h. **One day a week at 1,200 CZK/h = ~460k CZK/year** — roughly 2× the
   *committed* flipping scenario at 40% of the hours, with no legal exposure and no
   capital at risk.
2. **Productize the pipeline generically.** Ship it as a self-hostable "marketplace
   watcher" where the *customer* configures the target. You never touch Bazos data; the
   ToS relationship is theirs. Open-core (free core + paid setup/hosting/custom
   marketplace implementations) is the natural shape, and the existing
   `MarketplaceScraper` protocol is already the right seam.
3. **Publish the research.** A sanitized write-up of the API reverse-engineering and the
   proxy benchmark is a strong technical-blog piece. It's a lead generator for (1) — but
   see §7.4 on the trade-off, since publishing also tells Bazos exactly what you did.
4. **Mine job ads for automation leads** — a company advertising for manual data entry is
   publicly announcing an unautomated process with an approved budget. This is a second,
   more targeted lead generator for (1). Full analysis, including why *taking* those jobs is
   the wrong move, in **§4.7**.

---

### 4.6 Derived-statistics products (the safer data play)

If the data option is ever pursued, publish **derived statistics, not listings**: a price
index, depreciation curves, time-to-sell by category and region. Aggregate statistics are
a much weaker target under the database right than republished listings, and they contain
no personal data at all. Monetization is indirect — a free "what is my X worth?" tool as
a funnel, with affiliate revenue (vehicle-history checks, insurance) rather than direct
sales.

**Caveat:** for cars, the biggest and most obvious category, **Cebia already owns this**.
Pick a category they don't cover — agricultural machinery, tools, bikes, musical
instruments — or don't play.

---

### 4.7 Job/gig posts as an automation channel — weak as proposed, strong when reframed

> Floated 2026-07-30: scrape job posts for simple data-entry / computer work that a software
> engineer could automate (or hand to an LLM), using an LLM call **as a filter in the pipeline**
> to judge suitability, on Gemini's free tier. Analysed below with live-measured volumes.
> **Conclusion up front:** the source and the business model are both wrong as proposed, but the
> underlying signal is real and the reframe in (d) is the best version of it.

**(a) Bazos Práce is the wrong source — measured 2026-07-30.**

| Category | Active listings | ≈ new/day (at 60-day expiry) |
|---|---|---|
| Práce (whole section) | 6,668 | ~111 |
| **Administrativa** | **70** | **~1.2** |
| IT a telekomunikace | 20 | ~0.3 |
| Marketing a reklama | 7 | ~0.1 |
| Brigády | 575 | ~9.6 |

70 listings **total active**, not per day. And the 12 most recent Administrativa posts are
*Samostatná účetní Svitavy · Asistentka v BMW Chotětov · Provozní showroomu · administrativní
pracovník na HPP* — **on-site employment with monthly salaries** (30–40k CZK), not "re-key 5,000
invoices for 5,000 CZK" piecework. The automatable work this idea targets is essentially absent
from this section. For scale, Upwork averages **~4,500–5,800 public postings/day** — three-plus
orders of magnitude more.

At 1–11 relevant ads/day, a scraper with an LLM judge is not the right tool; a saved search and
five minutes a week is. Low frequency ("I'd need this from time to time") makes it *worse*, not
better — a pipeline consulted twice a year is one you must debug before each use.

*Incidental validation:* four of the twelve sampled ads returned `from = 2026-07-30 23:01`, the
topped-ad artifact documented at `bazos-api/BAZOS_HIDDEN_API_RESEARCH.md` §4.3. Freshness scoring
built on that field would rank every topped ad as brand new.

**(b) Taking the gigs pays less than the alternative you already have.**

Best case — a fixed-price gig, 5,000 CZK to re-key 5,000 rows:

| Line | Hours |
|---|---|
| Finding, bidding, negotiating (incl. lost bids) | ~2.0 |
| Building the bespoke automation | 1–3 |
| Running, QA, fixing | ~1.0 |
| Invoicing / admin | ~0.5 |
| **Effective rate** | **~870 CZK/h** |

That is **below** the 900–1,600 CZK/h contracting rate in §4.5, for more hassle and less
reliability. The fatal property: **the automation doesn't compound** — the next client has a
different source layout and target system, so you rebuild each time. It is bespoke consulting at
data-entry prices. CZ market rates confirm the ceiling: admin/reception brigády run 145–185 CZK/h,
data-processing roles 200–500 CZK/h.

There is also a technical asymmetry worth stating: **the tasks where an LLM beats a plain script
(unstructured → structured) are exactly the tasks you cannot trust it on without verification** —
a hallucinated plausible value in a numeric column is invisible. Deterministic reshaping doesn't
need an LLM at all. So the verification burden lands precisely where the speed advantage was
supposed to be.

**(c) Legal — two halves with very different profiles.**

- **Using an LLM to filter public job ads: no issue.** Public data, no confidentiality, no
  meaningful personal data.
- **Using an LLM to do the client's work: this is the blocker.** Data entry means invoices, CVs,
  customer records — personal data.

One finding in your favour, verbatim from [Google's Gemini API terms](https://ai.google.dev/gemini-api/terms):

> "If you're in the European Economic Area, Switzerland, or the United Kingdom, the terms under
> 'How Google uses Your Data' in 'Paid Services' apply to all Services, including Google AI Studio
> and unpaid quota in the Gemini API, even though they are offered free of charge."

So as a CZ user you get **paid-tier data protection on the free tier** — no training on your
prompts. Better than commonly assumed. **But** the same page separately instructs *"Do not submit
sensitive, confidential, or personal information to the Unpaid Services."* That is a distinct
contractual instruction, not part of the data-usage section the EEA carve-out covers — so the
exception resolves the *training* concern, not obviously that one. Use the paid tier for anything
real; it is cheap.

The larger exposure isn't Google's terms anyway: **you would be a processor for your client,
making Google an undisclosed sub-processor** without the client's authorisation. Small clients
have never considered this, which means the compliance gap is yours, not theirs.

Two clean lines: **fixed-price work — automating it is entirely legitimate**, no disclosure owed.
**Hourly work — billing hours you didn't work is fraud.** And ongoing single-client work that
resembles employment is **švarcsystém** (see §6.7).

**(d) The reframe — read the ad as a lead, not as a job. This is the version worth keeping.**

A company posting *"hledáme někoho na přepis 5000 faktur"* is publicly announcing: **we have an
unautomated process and an approved budget for it.** Don't apply for the job — sell them the
automation.

- Same scraper, same LLM classifier, different question: not "can I do this task" but "does this
  ad reveal a manual process worth replacing."
- Economics invert: 5,000 CZK once → a 40–80k CZK project, plausibly recurring.
- **It compounds** — reusable capability plus references, which (b) explicitly does not.
- It feeds **§4.5**, already the highest-EV option here, instead of opening a seventh business line.

Two caveats: source it where companies actually post (jobs.cz, prace.cz, LinkedIn — **not** Bazos,
per (a)); and note that pitching your services **is** a commercial communication under Act
480/2004 (§6.6). Responding to a company that publicly asked for exactly this service is about as
defensible as that gets, but keep it individually written and human-sent — never bulk.

**Verdict**

| Component | Verdict |
|---|---|
| LLM as a **separate pipeline stage** | ✅ Sound — and already designed in [`refactor/LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) §2 |
| LLM as a rule inside `RuleEngine` | ❌ Blocks a 50-ad batch on serial network I/O while holding `select_for_update` locks |
| Bazos Práce as the source | ❌ ~1–11 relevant ads/day, and they're on-site employment |
| Taking the gigs yourself | ⚠️ ~870 CZK/h, doesn't compound, below §4.5's rate |
| Job ads as **automation-consulting lead-gen** | ✅ **The version worth building** |

**Recommendation: don't build it now, and don't build it on Bazos.** Not because the lead-gen
version is bad — it's good — but because it would add a marketplace, a pipeline stage, and a
business model on top of a system whose detection latency is still ~15 minutes (§7.1) and which
cannot yet fully distinguish "no results" from "broken" (`refactor/PROMPTS.md` P20; the
`QueryRun` failure tracking and the zero-results canary are both done).
The LLM-judge stage *is* worth building; its first application should be **the deal flow you
already have** (thousands of ads/day, where a judge earns its keep), not job ads (units/day, where
you can simply read them). Revisit after P20–P24.

---

### 4.8 Explicitly rejected

| Idea | Why not |
|---|---|
| **Lead gen** — sell "seller wants to sell a car" leads to výkup companies / dealers | Highest revenue potential, **worst** legal profile: GDPR resale of contact data (§6.5) *plus* Act 480/2004 if anyone then emails them. Do not. |
| **Automated seller outreach** ("I'll buy it for X") | Commercial communication under Act 480/2004; ÚOOÚ has issued fines up to **7.7M CZK**. Your own `LLM_AD_REVIEW_DESIGN.md` already recommends draft-only — keep it that way permanently. |
| **Reselling the reverse-engineered API access** | Aggravates the ToS breach and hands the evidence to a third party. |

---

## 5. Financial summary

Year-1, realistic (not best-case), assuming continued part-time involvement:

| Option | Y1 net | Hours/wk | Capital | Legal risk | Verdict |
|---|---|---|---|---|---|
| **Contract work off the portfolio** | **200–500k CZK** | 4–8 | 0 | **None** | **Highest EV/hour** |
| **Flipping — committed** | 200–300k CZK | 12–15 | ~40k CZK | Low → Med (trader duties) | **Do if you enjoy it** |
| **Flipping — part-time** | 90–150k CZK | 4–8 | ~15k CZK | Low | **Best starting point** |
| Job-ad lead-gen → automation projects (§4.7d) | folds into contract work above | 2–4 (after build) | 0 | Low (B2B outreach care) | **Good, but defer** — after P18–P24 |
| Apify actor | 3–25k CZK | ~0 after setup | 0 | Low–Med | Free option, do it |
| Taking automatable gigs yourself (§4.7b) | ~870 CZK/h, uncapped hours | high per CZK | 0 | Med (confidentiality) | Below contract rate; don't |
| B2B niche subscription | 50–150k CZK | 10+ (incl. sales) | 0 | **High** | Only with consent |
| Derived-statistics / affiliate | 0–50k CZK | 5+ | 0 | Med | Long game only |
| Dataset sales | 0–80k CZK | Med | 0 | **Highest** | Don't |
| Consumer alerts app | ~0 | High | 0 | **High** | Don't |
| Contact/lead data sales | — | — | — | **Prohibited** | Never |

**Shared running cost across all options: ~2,000–5,000 CZK/year** (proxies $3–6/mo,
hosting on the existing Pi). If image downloading is ever enabled, budget separately —
measured at ~5.3 MB/ad, 500 ads/day is **~77 GB/month**, which is ~$231/mo on residential
and must go over a cheap datacenter pool instead (see `proxies/PROXY_ROTATION_RESEARCH.md`
§5.3).

---

## 6. Legal analysis

> Research, not legal advice. §6.4 and §6.5 in particular are worth one paid hour with a
> Czech IT/IP lawyer before anything public ships.

### 6.1 Tier 1 — fix before anything, arguably today

**The `facebook/` app.** `FBUser` stores phone number, Facebook id, name, gender,
municipality of residence *and of birth*, relationship status, occupation, email, date of
birth — imported in bulk via `manage.py import_data --path <file>` and joined to sellers
through `PhonePublisher.fb_user`. This is the shape of the 2021 Facebook breach dump.

There is **no lawful basis** under GDPR for processing a leaked dataset, and in the Czech
Republic unauthorized handling of personal data can reach criminal liability (§180
trestního zákoníku), quite apart from any ÚOOÚ administrative fine.

**Verified:** the table is **empty** in `db.sqlite3` and the March-2024 export
(header row only), so this appears never to have been populated with real data. **Action:**
delete the app, the model, the migration, the management command, and the
`PhonePublisher.fb_user` FK; confirm the production Postgres table on the Pi is empty
before dropping it. Do this regardless of which monetization path you choose — it is a
disproportionate liability attached to a feature you aren't using.

**Retention.** Bazos deletes ads after 2 months and associated personal data 6 months
after posting (ToS). Retaining seller emails/phones indefinitely puts you materially out
of step with both the source's policy and the data subjects' expectations — which is
exactly the reasonableness test a regulator applies. Adopt a written retention rule: keep
listing *facts* (title, price, category, locality, timestamps) indefinitely; **purge or
hash contact identifiers** on a schedule (6 months is the defensible number, since it
mirrors the source).

### 6.2 Tier 2 — determines which business models are viable

### 6.3 Terms of Service and robots.txt

Two clauses, quoted verbatim:

> **Používání API** — "*API pro přímé napojení Bazoše je možné používat pouze se souhlasem
> Bazos.cz, v opačném případě je aplikace nebo uživatelé používající takovéto aplikace
> blokováni.*"

> **Používání neoficiálních aplikací** — "*Využívání neoficiálních aplikací (app pro
> Android, iOS, Windows), které mají za účel zobrazovat inzeráty obdobně jako webový
> prohlížeč nebo mají za účel funkci přidávání inzerátů je v rozporu s používáním webu a
> našeho API.*"

`robots.txt` disallows precisely the endpoints this project depends on — `/search.php`,
`/*hledat=`, `/*cenaod=`, `/*cenado=`, `/*category=`, **`/*idmail=`**, **`/*idphone=`**,
`/hodnoceni.php`, `/ad-phone.php`, `/ad-mail.php`, `/agent.php` — and **explicitly blocks
`trovitBot` and `pricebot`**, i.e. the classifieds aggregators and price comparison bots.
That is Bazos stating, in machine-readable form, that aggregation is unwelcome.

**What this means in practice:** ToS breach is a contract matter — the stated remedy is
blocking, not damages. It is *not* a crime. But it (a) removes any good-faith defense,
(b) is the foundation for an unfair-competition claim under §2976 obč. zák. (*nekalá
soutěž* / parasitic exploitation), and (c) makes the sui generis claim below much easier
to run. The clause also cuts the other way: it explicitly contemplates consent, which
means **there is a legitimate path to ask** (§8, Phase 4).

### 6.4 Sui generis database right — the decisive issue for any product

Czech law implements the Database Directive at **§88 et seq. of Act 121/2000 Sb.**
(*zvláštní právo pořizovatele databáze*). A database maker who made a qualitatively or
quantitatively substantial investment in obtaining, verifying, or presenting the contents
gets an exclusive right against **extraction** and **re-utilisation** of the whole or a
substantial part — and, under Art 7(5), against *repeated and systematic* extraction of
**insubstantial** parts.

A 1.5-million-listing collection with 25,000+ daily additions, verification, and hosting
is very likely to clear the "substantial investment" bar.

**The controlling precedent is directly on point.** In *Innoweb BV v Wegener*
(CJEU C-202/12, 19 Dec 2013), a **dedicated meta-search engine for car classifieds**
(GasPedaal) translated user queries into real-time searches of Wegener's AutoTrack car-ad
database. The Court held this constitutes **re-utilisation of the whole or a substantial
part** of the database — because it lets the user access the target database's entire
contents without visiting the original site.

That is, almost line for line, the description of a Bazos alert product. **This is the
specific legal theory that kills §4.3(a) and (b).** Note the asymmetry:

- Extracting for **your own** analysis and purchase decisions: no re-utilisation occurs;
  the right isn't engaged in the way Innoweb describes.
- **Showing the results to anyone else**, free or paid: squarely within Innoweb.

Note also §6.1 of the ToS: photographs are licensed to Bazos by the advertiser
(non-exclusive, for the duration of publication) — you have no license to them at all,
which is a separate problem for any product that displays or mirrors ad images.

### 6.5 GDPR

Seller emails, phone ids, names, and localities are **personal data**, and you are the
**controller**. The relevant realities:

- **Lawful basis.** Legitimate interest (Art 6(1)(f)) is a plausible basis for *personal*
  deal-hunting. It becomes much harder for a commercial database, and functionally
  impossible for resale — the balancing test weighs the data subject's reasonable
  expectations, and a private individual selling a bike does not expect to enter a
  commercial contact database.
- **Article 14 is the trap.** When you collect personal data indirectly (i.e. by
  scraping), you must **inform the data subject**, normally within one month. The
  "disproportionate effort" exemption in Art 14(5)(b) is narrow, and regulators have
  rejected it in exactly this fact pattern:

| Case | Outcome |
|---|---|
| **KASPR** (CNIL, FR) | **€240,000**, then **€200,000** in Dec 2024 — scraping LinkedIn contact details into a commercial database |
| **Polish data broker (Bisnode)** (UODO, PL) | **~€220,000** — scraped public registry contact data, didn't notify. The DPA rejected "disproportionate effort" *precisely because the company already held the contact details*, making notification feasible. |

That second point is fatal to any commercial use here: **you hold their email and phone
id, so notifying them is feasible, so the exemption doesn't apply.**

- **The `ratings.php` reviewer harvest is the worst-exposed piece in the whole design.**
  It yields names and phone numbers of people who *left a review* — private individuals
  who never posted an ad and have no relationship with you whatsoever. Your own
  `BAZOS_API_DISCOVERY_PIPELINE.md` §5 already flags this as needing an explicit
  decision. **Make it: store aggregate sentiment counts only, never raw reviewer PII.**

### 6.6 Anti-spam — Act 480/2004 Sb.

Any automated contact with sellers is a *commercial communication* and requires prior
consent. ÚOOÚ enforces this actively — cumulative fines in the tens of millions of CZK,
with a single **7.7M CZK** penalty in 2023 for mass unsolicited third-party offers. Note
the useful carve-out: a genuine *demand* ("do you still have this, would you take X?")
from one business to another is arguably not a commercial communication, since that is a
request rather than an offer — but this is a thin reed to build a business on and does
not extend to messaging private individuals at scale.

**Keep the LLM outreach feature draft-only, permanently.** Human sends every message.

### 6.7 Tier 3 — tax and business structure (for the flipping option)

| Item | Rule |
|---|---|
| **Occasional income** | ≤ **50,000 CZK/yr** exempt (§10 ZDP). Exceed it and the **entire** amount becomes taxable, not just the excess. |
| **When it becomes a trade** | Regular, repeated buying-in-order-to-resell = *soustavná činnost* → requires **živnostenské oprávnění** (volná živnost, "Velkoobchod a maloobchod"). Both flipping scenarios in §4.2 cross this line in month 1–2. |
| **Income tax 2026** | 15% up to 1,762,812 CZK, 23% above. |
| **VAT registration** | **2,000,000 CZK** turnover → registered from 1 Jan following (application within 10 working days); **2,536,500 CZK** → registered **immediately**. |
| **VAT margin scheme** | If registered, **§90 ZDPH** lets a used-goods trader pay VAT on the **margin**, not the full sale price, for goods bought from non-taxable persons — i.e. exactly private Bazos sellers. **This is the difference between a viable and a non-viable flipping business at scale.** Optional, must be elected. |
| **Consumer-law liability** | Once you're a trader selling to consumers: statutory liability for defects, plus 14-day withdrawal on distance sales. **Budget 5–8% of revenue for returns and claims** — this is the line most hobby flippers omit and it is the one that bites. |
| **Stolen goods** | Buying suspiciously cheap items from throwaway accounts is the classic fencing profile. Keep written proof of purchase (name, ID check on high value, signed receipt) — mandatory in practice for bikes, tools, phones, cars. |
| **Entity** | OSVČ is fine to start. Move to **s.r.o.** once you sell to consumers at volume or take on data-processing customers — the liability shield matters most where a GDPR claim could otherwise reach personal assets. |

---

## 7. Other things to think about

### 7.1 Latency is the binding constraint — and it invalidates §4.2 as currently built

> **Referenced from** [`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) (priority table)
> and [`refactor/PROMPTS.md`](refactor/PROMPTS.md) **P21**, which is the executable version of
> the fix. This section is the *commercial* justification for why that prompt outranks
> everything else in the backlog.

`scraper/settings.py:161-162` sets `INTERVAL_LOWER=15 min`, `INTERVAL_UPPER=45 min` (avg 30),
and `NightMultiplier` **doubles** it 22:00–06:00. A pass detects an ad only when it happens to
run, so **median detection latency is half the interval: ~15 minutes, worst case 45 (90 at
night).**

It's actually worse than the interval suggests. `BazosRunner.run()` iterates queries **strictly
sequentially** on a single shared session, and each query costs **3 Bazos requests plus an
`icanhazip.com` round-trip** (two of the three Bazos calls are the redundant double blacklist
check — `PROXY_ROTATION_RESEARCH.md` §3), with `sleep(uniform(2,5))` between pages. So the
*effective* cadence is worse than configured, and it **degrades linearly with every query
added** — meaning the broad category-scoped sweep that
[`bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md`](bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md) §1
pushes toward makes latency **worse**, not better. That tension isn't acknowledged in either
doc today.

**Why this is commercial, not merely technical.** The whole thesis of §4.2 is *being first to a
mispriced listing*. Well-priced phones, tools and bikes are gone in minutes — the seller's inbox
fills up and they take the first credible buyer. Meanwhile the competing services already run
far tighter loops: **`realitnihlidacipes.cz` checks every 60 seconds**; FlowMarket every 5
minutes. At a 15-minute median you are not competing on latency, you are arriving after
several people who are.

**So: §4.2's ~1,200 CZK/flip only materializes after this is fixed.** As currently configured
the pipeline is a *market-monitoring* tool, not a *deal-capture* tool, and no amount of better
filtering compensates — a perfect judgement delivered 15 minutes late is worth nothing.

**The fix is already designed and largely built**, which is what makes this the highest-return
work available:

| Step | Status |
|---|---|
| `BazosApiScraper` with a small `limit` for the steady-state dedup probe (**1.1 KB/request**) | **built and tested**, inert in production (`marketplace="bazos_api"`) |
| Collapse the double blacklist check to one probe **per pass** | designed, `PROXY_ROTATION_RESEARCH.md` §8.2 |
| `HttpProxyIPChanger` + rotating pool so cadence stops being ban-limited | designed, `PROXY_ROTATION_RESEARCH.md` §8 |

Per `PROXY_ROTATION_RESEARCH.md` §5, that combination puts a **2-minute cadence at ~0.24
GB/month** — i.e. a **~30× latency improvement for roughly the plan minimum**, ~$3–6/mo. This is
the single best-value change in the repository and it is ~3–5 days of work.

### 7.2 Three data-model defects block every data-driven option — **(a) and (b) are now fixed**

> **✅ Updated 2026-08-23.** Two of the three shipped. They are kept here rather than deleted
> because this section is the argument for *why* they mattered commercially, and because (c) —
> the biggest of the three — is still open. See [`SHIPPED.md`](SHIPPED.md).

**(a) `Ad.price_raw` is a `CharField` — ✅ FIXED (migrations `0032`/`0033`).** `Ad.price` is now
a `BigIntegerField` (indexed, nullable) alongside `Ad.price_type`, a `PriceType` enum
distinguishing a real number from `Dohodou` / `V textu` / `Nabídněte` — and, importantly, from
`Zdarma`, which is a known zero rather than an unknown. Medians, indices and anomaly thresholds
are all computable now. The measurement that shaped the design is
[`refactor/PRICE_PARSING_RESEARCH.md`](refactor/PRICE_PARSING_RESEARCH.md); the first thing to
build on it is `PROMPTS.md` P23's `PriceAnomalyRule`. **Note the cross-marketplace caveat**: four
marketplaces encode price three different ways and "zero" three different ways, so a naive
`AVG(price)` across marketplaces is still wrong — see that doc's §8.

**(b) `Ad.query` is a single FK — ✅ FIXED (migrations `0026`–`0028`).** The `Ad`/`AdDelivery`
split landed: `Ad` is now globally unique on `(marketplace, external_id)` and holds only scraped
facts, while `AdDelivery` holds per-`(ad, query)` pipeline state. There is finally a row that
answers "have I ever seen this ad", and statistics are no longer silently double-counted by query
overlap. **The precondition for analytics is met.**

**(c) You have asking prices, never realized prices — ❌ still open, and still the biggest gap.** This is the single biggest gap.
Every valuation or deal-scoring product needs to know what things actually *sold* for.
The closest available proxy is **time-to-delisting plus last-seen price**, obtainable
cheaply via the bulk `ad_id[]=` refresh and the HTTP 410 signal — both already documented
in `BAZOS_HIDDEN_API_RESEARCH.md`, and now written up executably as `PROMPTS.md` **P24**.
**This is the highest-leverage feature you don't have, for both flipping and any future data
product.**

> **Update 2026-08-22 — there is now a second route, with a measured caveat.** The marketplace
> study found that **Aukro publishes genuinely realised prices**: ended auctions are readable
> unauthenticated ≥2.75 years back, and `biddersCount > 0` + `price` is what an item actually
> sold for ([`marketplaces/AUKRO.md`](marketplaces/AUKRO.md) §6a). That is the only source in 13
> assessed candidates that closes this gap directly. **But §6a.1 tempers it**: only ~11% of
> sampled ended items had bids, buy-now listings expose no sold signal at all, and Aukro may be
> incompatible with the Tor stack. Treat it as a real but partial answer, not a replacement for
> P24's delisting proxy.

### 7.3 The archive is the only compounding asset — start now

Everything else here can be rebuilt by a competitor in two weeks. A 24-month price and
velocity history of a market that deletes itself every 60 days cannot be rebuilt at any
price. If there is a 10% chance you'll want the data option in 2028, the cost of starting
the broad category sweep today is ~$5/month and a few days of work. That is a cheap
option on a large payoff — and it is the *only* item on this list where delay is
irreversible.

> **✅ And it is now backed up (2026-08-16).** This box used to read "it is currently unbacked",
> which was the single largest unhedged risk in this document: no `pg_dump`, no snapshot, no
> off-host copy, and a deploy workflow that ran `migrate` against production without dumping
> first. That is fixed. A one-shot `backup/` container dumps to `./backups/` and pushes to
> `restic` when `RESTIC_REPOSITORY` is set, scheduled by a systemd timer on the Pi with
> `Persistent=true` so a backup missed while the Pi was down is caught up rather than skipped.
> The deploy workflow now takes a **pre-migration dump that aborts the deploy if it fails** — a
> bad migration being the likeliest data-loss event here. Options, the retention/GDPR
> interaction, and the restore procedure: [`BACKUPS.md`](BACKUPS.md).
>
> **What is still open**: the dumps hold seller PII, so §7 of that doc's retention/purge
> argument applies — a PII purge that doesn't reach the backups isn't a purge.

### 7.4 Concentration risk

One marketplace, one ToS clause, one sole trader who can end this in an afternoon.

**✅ Partly hedged since 2026-08-22.** Vinted and Sbazar are both live (`Marketplace.VINTED`,
`Marketplace.SBAZAR`), so the codebase is genuinely multi-marketplace rather than
Bazos-with-an-abstraction. Vinted is legally different too — it has a real API and an affiliate
posture, so the "third party" column of §3 may be open there in a way it isn't on Bazos.

**The hedge is thinner than the row count suggests, though.** Sbazar has the *worst* legal
posture of the three (`Disallow: /` plus `Disallow: /api/` — see
[`marketplaces/SBAZAR.md`](marketplaces/SBAZAR.md) §3) and adds **no new capability**, so it
diversifies operational risk without diversifying legal risk. And no production `Query` volume
has moved off Bazos. If a product is ever the goal, **build it multi-marketplace from day one**
or don't build it — that advice stands.

### 7.5 Should you ask Bazos for consent?

The ToS explicitly contemplates it ("*pouze se souhlasem Bazos.cz*"), and the operator is
one reachable person (podpora@bazos.cz).

- **Cost of asking:** one email — plus the fact that you have now identified yourself. If
  they say no, they may also start looking, and your UA/IP pattern becomes interesting.
- **Value of a yes:** it is the *only* path where a public product is durable. It converts
  the largest legal risk into the business itself.

**Decision rule:** ask **only if** you intend to build something public. If the plan is to
flip quietly for your own account, asking is pure downside — don't.

### 7.6 Time is the real constraint

Flipping nets ~480 CZK/h; contracting nets ~1,200 CZK/h. **Flipping only makes economic
sense if you enjoy it, or if you scale it past your own hands** (buying agents, a
storefront, higher ticket sizes). Be honest with yourself about which of those is true —
it determines whether §4.2 is a business or an expensive hobby with good tooling.

### 7.7 Build vs. buy for yourself

You already have the alternative: Bazos's native free agent alerts. Before adding a
feature, ask whether it beats *the free thing the incumbent already ships*. The honest
answer is that your edge is only in three places: **latency** (sub-minute vs. batched),
**cross-category breadth** (whole-category sweeps the agent can't express), and
**anomaly scoring** (price-vs-comparables, which nothing native does). Everything else you
build is re-implementing a free feature.

---

## 8. Recommended sequencing

**Phase 0 — hygiene (1 day, do regardless).**
~~Set up database backups first~~ — **✅ done 2026-08-16** (`backup/`, systemd timer,
pre-migration dump gating the deploy; [`BACKUPS.md`](BACKUPS.md)). Everything below assumes the
archive still exists, and now it survives an SD-card failure.
Remaining: delete the `facebook/` app, model, migration, importer and the
`PhonePublisher.fb_user` FK; verify the production table is empty first (and do this
**before** starting a backup rotation, so a leaked-data table never enters the archives —
`BACKUPS.md` §7). Write down a retention policy: listing facts kept, contact identifiers
purged at 6 months — and cap **backup** retention to match, or the purge is cosmetic.
Decide, explicitly, that the current operating posture is **private use** (§3, left column).

**Phase 1 — fix latency, then finish the data (1–2 weeks — smaller than it was).**
**Start with the latency chain (§7.1)**, per `PROMPTS.md` P21's split. Part 2 of **P21a** (the
guard collapse) landed 2026-08-23 — both redundant blacklist probes are gone. What's left of
P21a is the **tunable API page size and the production cutover, then the interval to ~10 min**:
~3× of the latency win at *unchanged* Bazos request volume, for **no cost and no external
dependency**. **P21b second**, and only once P21a's observed block rate justifies it:
`IP_CHANGER_TYPE=HTTP_PROXY` on a rotating pool (~$3–6/mo) to get below 5 minutes. Nothing else
in this plan pays off while detection runs 15 minutes behind the market.
⚠️ P21b still has a second, independent justification: **Tor is the transport and it is still
failing** (403s on exits, dead circuits — `PROMPTS.md` P20), so the proxy migration is arguably
reliability work, not just latency work.
Of the data fixes in §7.2, **price-as-integer and the `Ad`/`AdDelivery` split are both done**.
What's left is **delisting/sold detection** via bulk `ad_id[]=` + HTTP 410 — `PROMPTS.md` P24.
**Phase 2 can't be measured without it**, so it is no longer deferrable the way the split was.

**Phase 2 — flip, for your own account (ongoing, starts week 3).**
Pick **one** category you genuinely know. Target 1–2 flips/week. Register the živnost as
soon as it's clearly repeat activity — don't drift past the 50k threshold accidentally.
Track deal-velocity on every flagged ad: it is simultaneously your P&L and the precision
metric for the anomaly model. **This is the phase that pays for everything else and
proves the thesis.**

**Phase 3 — monetize the capability (opportunistic, parallel).**
Publish the Apify actor (one weekend, expect coffee money, treat it as a credential).
Write up the API reverse-engineering and the proxy benchmark as public technical
writing — but read §7.4 first. Then take contract data-engineering work at 900–1,600
CZK/h. **On the numbers in §5, this is the highest-return use of your hours by a wide
margin.**

**Phase 4 — product, only if Phases 2–3 succeed and you still want it.**
Email Bazos for API consent **before** building. If yes: pick one B2B vertical, hand-sell
five customers, build only what those five need. If no: you now know any product has a
finite shelf life — price and timebox it accordingly, or don't build it.

**Never:** sell contact or lead data, send automated outreach to sellers, or ship a
consumer-facing Bazos listings app.

---

## 9. Sources

**Live-measured (2026-07-29):** `api/v1/ads.php` `x-total-count` for all listing counts;
`bazos.cz/robots.txt`; `bazos.cz/podminky.php`.

- [Bazos.cz — Podmínky využívání](https://www.bazos.cz/podminky.php) · [robots.txt](https://www.bazos.cz/robots.txt)
- [CJEU C-202/12 *Innoweb v Wegener*](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex:62012CJ0202) · [IPKat analysis](https://ipkitten.blogspot.com/2013/12/stepping-on-gaspedaal-cjeu-rules-on-re.html)
- [Zvláštní právo pořizovatele databáze (§88 AZ)](https://autorske-pravo.info/zvlastni-pravo-porizovatele-databaze/) · [Databáze a data z pohledu práva](https://www.systemonline.cz/it-pravo/databaze-a-data-z-pohledu-prava-1.-dil.htm)
- [CNIL — KASPR fined €240,000 for data scraping](https://www.cnil.fr/en/data-scraping-kaspr-fined-eu240000) · [EDPB — KASPR €200,000 (2024)](https://www.edpb.europa.eu/news/news/2025/data-scraping-french-sa-fined-kaspr-eu200-000_en)
- [Polish SA GDPR fine for scraping without Art 14 notice](https://www.insideprivacy.com/data-privacy/polish-supervisory-authority-issues-gdpr-fine-for-data-scraping-without-informing-individuals/)
- [ÚOOÚ — FAQ k zákonu 480/2004 Sb.](https://uoou.gov.cz/cinnost/obchodni-sdeleni/casto-kladene-otazky-k-zakonu-c-4802004-sb) · [Za spam padají milionové pokuty](https://www.pravniprostor.cz/clanky/pravo-it/za-spam-padaji-milionove-pokuty-znate-vsechna-pravidla)
- [Příležitostný příjem do 50 000 Kč](https://www.businessinfo.cz/clanky/prilezitostny-prijem-do-50-000-nedanite-kde-je-rozdil-mezi-podnikanim-a-prilezitostnou-cinnosti/) · [Plátce DPH 2026 — limity](https://yourfirm.cz/platce-dph-v-roce-2026-limity-obratu-a-co-delat-po-jejich-prekroceni) · [§90 ZDPH — zvláštní režim pro použité zboží](https://portal.pohoda.cz/dane-ucetnictvi-mzdy/dph/zvlastni-rezim-dph-pro-obchodniky-s-pouzitym-zbozim/)
- [Bright Data — Marketplace datasets ($250/100k records)](https://brightdata.com/products/datasets/marketplace)
- [Apify — Bazos Scraper (crawlerbros)](https://apify.com/crawlerbros/bazos-scraper) · [Kleinanzeigen AI Deal Finder](https://apify.com/webdatalabs/kleinanzeigen-deal-finder) · [Apify Actor monetization](https://help.apify.com/en/articles/8684010-make-money-publishing-your-actors-on-apify-store)
- [Realitní hlídací pes — Bazoš Reality](https://www.realitnihlidacipes.cz/hlidaci-pes-bazos-reality/) · [Bazoš Agent](https://csda.cz/app.php?cislo=1443462852) · [FlowMarket — deal-hunting apps](https://flow-market.org/blog/best-deal-hunting-apps/)
- [Cebia — AUTOTRACER tržní cena vozidla](https://www.cebia.cz/novinky/proverovani/autotracer-od-cebia-nove-ukazuje-i-trzni-cenu-vozidla)
- [Bazoš — návštěvnost a pozice na trhu](https://recenzer.cz/bazos/) · [Bazoš vstoupil na polský trh (MediaGuru)](https://www.mediaguru.cz/inzertni-server-bazos-vstoupil-na-polsky-trh)

**Related internal docs:** [`bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md`](bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md) §5 (PII scope decision),
[`proxies/PROXY_ROTATION_RESEARCH.md`](proxies/PROXY_ROTATION_RESEARCH.md) §5.3 (image bandwidth),
[`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) #1 (Ad/AdDelivery split),
[`refactor/LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) §4.2 (draft-only outreach).
