---
title: LLM Ad Review & Seller Outreach — Exploration & Proposal
status: proposal
updated: 2026-09-18
verified: 2026-09-18
---

# LLM Ad Review & Seller Outreach — Exploration & Proposal

> **Neither headline capability has been built, and neither is scheduled.** There is no
> `AWAITING_LLM_REVIEW` status, no `run_llm_review`, no `Query.llm_review_enabled`, and nothing
> drafts or sends a message to a seller. Both still need an explicit decision (especially
> outreach, §4) before either happens.
>
> ⚠️ **Re-checked 2026-09-18: two of the things this doc says are missing now exist.** §1's
> multiple-filters-per-query shipped as P17 (2026-07-25) and is marked ✅ below. And §2f's
> undesigned cost/ops layer was built for a different consumer: `llm/` ships a provider-agnostic
> `LLMProvider` Protocol + registry, `NullProvider` as the default, `LLM_API_KEY`,
> `LLM_MONTHLY_BUDGET_USD` as a hard pre-call stop, versioned prompt files, a response cache and
> an `LLMCall` audit row per call - with **Gemini picked on this doc's own §2f measurement** of
> the free tier and its EEA carve-out. So a judge stage would no longer have to invent any of
> that; what remains unbuilt is the *stage* (§2a–§2e) and outreach (§4). Design:
> [`PRICE_REFERENCE_SERVICE.md`](PRICE_REFERENCE_SERVICE.md) §2.
>
> **See also**: [`DISCORD_BOT.md`](DISCORD_BOT.md) (2026-07-24) — its Tier 3
> "draft message to seller" button is effectively this doc's §4.2 delivery mechanism, triggered
> on-demand per ad instead of automatically for every `llm_outreach_enabled` query. The §4.1/4.3
> recommendation against auto-sending carries over unchanged.

## 0. The idea, as floated

Two related but separable capabilities:

1. After an ad passes the existing (cheap, deterministic) filter rules from Stage 9 (✅ done —
   `PIPELINE_REFACTOR.md`, `bazos/filters.py`), run it through an LLM for a subtler judgment
   call — "is this actually what I'm looking for," "does this look legit," "is this genuinely
   a good deal." This implies **multiple filters need to apply per query**, since the LLM
   check is presumably expensive/opt-in, not something every query wants.
2. If a query has a flag set, and the ad passes *that* too, have an LLM draft a message to the
   seller (ask for more photos, negotiate price, ask about delivery) and send it — by email,
   WhatsApp, or SMS.

This doc takes both seriously, but treats them as different risk categories. (1) is a
straightforward, if architecturally interesting, feature. (2) is a real step up in what this
project does — from monitoring public listings to initiating outbound contact with real
people — and deserves its own explicit sign-off, not a quiet default.

---

## ✅ 1. Multiple filters per query — a real, useful generalization — done

> **Promoted to `PROMPTS.md` as P17** (2026-07-24), **done** (2026-07-25) — implemented exactly
> as designed below. This section remains the fuller rationale.

**Built**: `bazos/filters.py` has `RULE_REGISTRY` (name → instance for all five Stage 9 rules)
and `DEFAULT_RULE_NAMES = list(RULE_REGISTRY)`, plus `build_rule_engine(query)`:

```python
# bazos/filters.py
RULE_REGISTRY: dict[str, FilterRule] = {
    "price_range": PriceRangeRule(),
    "blocklist_keyword": BlocklistKeywordRule(),
    "required_keyword": RequiredKeywordRule(),
    "publisher_blocklist": PublisherBlocklistRule(),
    "price_drop": PriceDropRule(),
}
DEFAULT_RULE_NAMES: list[str] = list(RULE_REGISTRY)  # all cheap rules on by default

def build_rule_engine(query: Query) -> RuleEngine:
    names = query.filter_rule_names or DEFAULT_RULE_NAMES
    rules = [RULE_REGISTRY[name] for name in names]  # raises KeyError on a typo/removed name
    return RuleEngine(rules)
```

`Query.filter_rule_names` (`JSONField(default=list, blank=True)`, migration
`0022_query_filter_rule_names.py`) — empty means "all the free, default rules," matching the
existing "empty config → permissive" convention P5 already uses for
`filter_blocklist`/`filter_required`. `run_filter`'s loop calls `build_rule_engine(ad.query)`
per ad instead of using a module-level singleton — cheap (just dict lookups, no I/O), so no
performance concern doing it per ad inside the existing `transaction.atomic()` block. An unknown
rule name raises `ValueError` rather than silently no-opping. Tests in
`bazos/tests/test_filters.py`.

This was worth doing independent of the LLM idea — it's the mechanism that makes *any* future
optional/expensive rule (LLM or otherwise) something a query opts into explicitly, rather than
something that silently runs (and costs money) for every ad site-wide. The LLM judge stage
proposed below (§2) can now build on this directly instead of needing it built first.

*(2026-09-18: the snapshot above has moved on, and in the direction this section predicted.
`RULE_REGISTRY` now holds seven rules - `location_distance` and `price_model` joined the five
quoted, and `refprice`'s `reference_price` registers itself from another app through
`register_rule`. `DEFAULT_RULE_NAMES` is no longer `list(RULE_REGISTRY)`: it is the registry
minus `OPT_IN_RULE_NAMES`, because the two newest rules are **inverted** - they answer "is there
a reason to send this?" - so defaulting one on would mute every existing query. That is exactly
the slot an LLM judge would occupy if it were ever made a rule, which §2 argues it should not
be.)*

---

## 2. The LLM judge — why it shouldn't be a `FilterRule`

It's tempting to implement this as `LLMJudgeRule(FilterRule)` and drop it into the registry
above. **Don't** — the reason `run_filter` and `run_sender` are separate processes in the first
place (`PIPELINE_REFACTOR.md`'s "Problem" section) is that slow, rate-limited, retryable
external calls don't belong inside a tight polling loop that holds
`select_for_update(skip_locked=True)` locks for the batch's duration. An LLM API call has
exactly the characteristics that justified that split for Discord: real latency (seconds, not
milliseconds), rate limits, transient failures worth retrying, and real per-call cost. Putting
it inside `run_filter`'s `with transaction.atomic():` block would hold DB locks open for as
long as the slowest LLM call in the batch — the same anti-pattern the pipeline refactor was
built to avoid.

**Proposal**: a new pipeline stage, structurally closer to `run_sender` (which already has the
"external call, retry, per-item outcome" shape) than to `run_filter`.

### 2a. New `AdStatus` value

```python
AWAITING_LLM_REVIEW = "AWAITING_LLM_REVIEW"  # passed cheap rules, awaiting LLM judgment
```

`run_filter`'s existing logic changes only at the margin: on APPROVE, check
`ad.query.llm_review_enabled` — if set, transition to `AWAITING_LLM_REVIEW` instead of
`APPROVED`; if not set, behave exactly as today. REJECT is unaffected either way. This is
additive and opt-in — a query that never sets the flag sees zero behavior change.

### 2b. New `Query` fields

```python
llm_review_enabled = models.BooleanField(default=False)
llm_review_criteria = models.TextField(blank=True, help_text="Free-text judging criteria for the LLM, e.g. 'reject anything with visible case damage'")
```

### 2c. New management command: `run_llm_review`

Mirrors `run_sender`'s shape (fetch under lock, release, do the slow call, save individually),
not `run_filter`'s (everything inside one transaction):

```python
while True:
    with transaction.atomic():
        ads = list(
            Ad.objects
            .select_for_update(skip_locked=True)
            .filter(status=AdStatus.AWAITING_LLM_REVIEW)
            .select_related("query")
            .order_by("created")[:LLM_REVIEW_BATCH_SIZE]
        )
    # LLM calls happen OUTSIDE the lock — the key structural difference from run_filter.
    for ad in ads:
        try:
            verdict = judge.review(ad)  # prompt built from ad fields + query.llm_review_criteria
        except LLMRateLimitError:
            ad.llm_review_attempts += 1
            if ad.llm_review_attempts >= MAX_LLM_REVIEW_ATTEMPTS:
                ad.status = AdStatus.REJECTED   # fail closed — see §2e
                ad.filter_reason = "LLM review failed after max attempts"
            ad.save(update_fields=["status", "filter_reason", "llm_review_attempts"])
            continue
        ad.status = AdStatus.APPROVED if verdict.approve else AdStatus.REJECTED
        ad.filter_reason = verdict.reason
        ad.save(update_fields=["status", "filter_reason"])
    if not ads:
        sleep(LLM_REVIEW_POLL_INTERVAL)
```

`Ad.llm_review_attempts` (new field) mirrors `send_attempts`; `MAX_LLM_REVIEW_ATTEMPTS` mirrors
`MAX_SEND_ATTEMPTS` in `bazos/const.py`. The retry/backoff shape already exists in this codebase
for exactly this kind of external, rate-limited call — reuse it rather than inventing a new
pattern.

*(2026-09-18: **this sketch is written against a schema that no longer exists.** Migrations
0026–0028 moved every piece of pipeline state off `Ad`: the poll is on `AdDelivery`
(`status`, `filter_reason`, `send_attempts`, plus the `query` FK), and `Ad` carries scraped facts
only. So the loop locks `AdDelivery.objects.select_for_update(skip_locked=True, of=("self",))`,
`llm_review_attempts` belongs there too, and §3's caveat below is answered rather than
outstanding. The `of=("self",)` is not optional - the queryset `select_related`s, and without it
the joined `Query` row is locked as well. A second option now exists that did not when this was
written: the whole stage could be a django-q2 job instead of a fourth compose service, which is
what [`JOB_QUEUE.md`](JOB_QUEUE.md) §4.2 already lists it as.)*

### 2d. Audit trail

LLM verdicts are non-deterministic and prompts will need tuning. Worth a dedicated table rather
than only `Ad.filter_reason`:

```python
class LLMReview(TimeStampedModel):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="llm_reviews")
    prompt = models.TextField()
    raw_response = models.TextField()
    approved = models.BooleanField()
    reason = models.TextField(blank=True)
```

Lets you replay/inspect what the model actually saw and said, separate from the terse
`filter_reason` string already used for the cheap rules.

### 2e. Open decision: fail open or fail closed?

If the LLM call fails permanently (`MAX_LLM_REVIEW_ATTEMPTS` exhausted), should the ad end up
`REJECTED` (safe default — never notify on an unreviewed ad) or `APPROVED` (permissive — don't
lose a genuine deal to an API outage)? I'd default to fail-closed (shown above) since the whole
point of the review is quality control, but this is a real judgment call, not something to
decide silently.

### 2f. Cost/ops, not yet designed

> ✅ **Designed and built 2026-09-16, for `refprice/` rather than for this stage** - but it is
> the same layer, so a judge would consume it rather than repeat it. Every bullet below has an
> answer in code: the setting is `LLM_API_KEY` (plus provider-specific keys), blank disables via
> a `NullProvider` that declines every call and opens no socket, exactly the `SENTRY_DSN`
> convention this section asks for; the cap is `LLM_MONTHLY_BUDGET_USD`, enforced **before**
> reaching the provider rather than reported after; and every call, cached or failed, writes an
> `LLMCall` row with tokens, cost and the resolved prompt version. What is **not** built is a
> *per-query* cap - the ceiling is global. The measured figures below are what led to picking
> Gemini as the second provider.

- New setting, e.g. `LLM_API_KEY` (or reuse `ANTHROPIC_API_KEY` if using Claude directly) —
  empty disables the feature entirely, matching the existing `SENTRY_DSN` convention.
- No rate-limit/cost-cap research has been done yet (unlike the Bazos API, which got a full
  probe doc before anything was built) — worth its own small spike: actual per-call cost, actual
  latency, and a sanity check on request volume if `llm_review_enabled` is set on a
  broadly-scoped query (the discovery-pipeline doc's "fewer, broader category queries" direction
  makes this more likely to matter, not less — a broad query with LLM review on could mean
  hundreds of paid calls a day).
- A per-query or global daily LLM-call cap is worth having from day one as a safety valve —
  this is the first stage in the whole pipeline with a real, uncapped monetary cost per item
  processed (Discord sends are free; LLM calls are not).

**Partial answer to the cost spike, researched 2026-07-30** (prompted by the job-ad idea in
`MONETIZATION.md` §4.7, which independently arrived at this doc's §2
conclusion — a second vote for "own stage, not a `FilterRule`"; the concrete figure is that
`FILTER_BATCH_SIZE = 50`, so a rule-based judge would hold `select_for_update` locks for
50 serial LLM round-trips):

- **A free tier can genuinely carry this workload.** Gemini's free tier allows on the order of
  **~1,500 requests/day** — comfortably above a filtered candidate stream, though *not* above an
  unfiltered broad-category one, which is exactly the blow-up scenario flagged above. Cheap rules
  must run first; the LLM sees survivors only (same filter-before-enrich principle as `PROMPTS.md`
  P13 and `DISCOVERY_PIPELINE.md` stages 2→3).
- **The EEA carve-out removes the usual free-tier objection.** Per
  [Google's Gemini API terms](https://ai.google.dev/gemini-api/terms), for users in the EEA,
  Switzerland or the UK the **paid-tier data terms apply to the free tier too** — so free-tier
  prompts are *not* used to train models. For scraped **public ad text** this makes the free tier
  viable rather than merely tempting.
- **Caveat that doesn't apply here but would elsewhere:** the same terms instruct "do not submit
  sensitive, confidential, or personal information to the Unpaid Services." Public listing text is
  fine. Anything involving a third party's data is not — see `MONETIZATION.md` §4.7c for why that
  distinction matters if this machinery is ever pointed at non-public content.
- **Sequencing note:** whenever this stage is built, its first corpus should be the existing ad
  deal-flow (thousands/day, where a judge earns its keep), not a low-volume experiment.

---

## 3. Interaction with the cross-query dedup backlog item

> ✅ **Resolved 2026-09-18.** The split shipped in migrations 0026–0028. "Reviewed for query A,
> not for query B" is representable now: the review status, reason and attempt counter all
> belong on `AdDelivery`, and `Ad` keeps only the scraped facts. Rule rows already take an
> `AdDelivery`, so an LLM stage would inherit the right grain rather than argue for it. The
> paragraph below is kept as the reasoning that helped prioritise the split.

`BACKLOG_IDEAS.md` #1 (`Ad`/`AdDelivery` split) becomes more relevant here, not less: "should
this ad get an LLM review" and "should we draft an outreach message" are really properties of
*this query's* interest in the ad, not global facts about it. If the same real-world ad matches
two queries — one with `llm_review_enabled`, one without — today's single-`Ad`-row model can't
represent "reviewed for query A, not for query B" cleanly. Not a blocker for a first version
(query overlap is rare today per that doc's own assessment), but worth flagging as a reason to
revisit #1 sooner if this feature and broader category-scoped queries both move forward.

---

## 4. Seller outreach — the bigger jump, needs a deliberate decision

This is qualitatively different from everything else in this project. Every existing capability
(scraper, filter, sender) is about **monitoring public listings and notifying the user** — a
one-directional, passive flow. Auto-generating and sending messages to sellers is **initiating
outbound contact with real third parties**, on channels this project doesn't currently touch at
all. Worth being explicit about that shift before designing around it.

### 4.1 The contact channels aren't as simple as "call an API"

- **Bazos's own reply mechanism** (`POST api/v1/ad-mail.php`, per
  `HIDDEN_API.md` §3.3) proxies the email — the seller's real address is never
  exposed to us, which is actually good (least additional exposure), but this endpoint is listed
  under **auth-gated, account-required** operations. Whether it needs only a token or the same
  phone-verification gate that blocks `ad-phone.php`/`agents.php` (confirmed `403
  {"message":"Číslo je neověřené"}` in that doc's §3.2/§6.4e) **hasn't been tested** — this needs
  its own probe before anything else here is designed, the same way the search API itself did.
- **Real phone/email harvested from ad text or `ratings.php`** — technically available (per
  `DISCOVERY_PIPELINE.md` §6.4b/§3.3), but messaging a private individual on
  WhatsApp/SMS using a number scraped from a classifieds site — not given to us through any
  channel they consented to for this purpose — is a materially bigger step than the "should we
  even store this PII" question already flagged for the reviewer-graph idea. This reads as cold
  outreach, not "replying to your own ad," even if the *content* is benign ("is this still
  available?").
- **WhatsApp Business API / Twilio SMS** are both real integrations with their own account setup,
  per-message cost, and — more importantly — their own anti-spam/opt-in compliance rules that
  exist specifically because unsolicited automated messaging to individuals is regulated in most
  jurisdictions including the EU/Czech Republic, regardless of how the message is worded.
- **Bazos's ToS** almost certainly prohibits automated seller messaging — most classifieds sites
  do, precisely to prevent their users from being spammed by scrapers. This is a different
  posture than "scraping public pages," which the project already accepts as its baseline
  (`HIDDEN_API.md` §6.2 point 4) — automated outbound contact is a further step,
  not the same one restated.

### 4.2 A meaningfully lower-risk MVP that keeps most of the value

Rather than auto-sending anything, have the LLM **draft** the message and deliver it to the
*user* via Discord — the channel this project already uses, that the user has already
consented to and controls:

> 🎯 New match: *MacBook Pro 13" 2020* — 18 000 Kč
> Suggested message to the seller: *"Dobrý den, je notebook stále k dispozici? Zajímalo by mě,
> zda je možná osobní odběr a jestli je cena ještě k jednání. Děkuji."*

The user copies it, sends it however they'd normally contact a seller (Bazos's own site, their
own phone), or edits it first. This gets the actual practical value (not staring at a blank
message box, negotiating angle suggested for you) without:
- needing Bazos account credentials or phone verification at all,
- needing WhatsApp/SMS infrastructure or its compliance overhead,
- crossing from "notify me" into "act as me" without a human in the loop for the one step
  (contacting a stranger) that most needs one.

This only needs one new `Query` flag (`llm_outreach_enabled`) and reuses the existing
`DiscordSender` — no new send channel, no new external account, no ToS question. I'd treat this
as the only part of §4 worth building without a further explicit conversation.

### 4.3 If full automation is wanted later

That's a separate decision, not a natural next increment from 4.2. It would need, at minimum: a
probe of whether `ad-mail.php` is usable without phone verification (per 4.1), a considered
choice on whether "through Bazos's own reply system" (closer to a real buyer's message) vs.
"direct SMS/WhatsApp to a harvested number" (closer to cold contact) are even comparable in risk
— they aren't — and an explicit call on rate-limiting outbound messages per seller/day
regardless of channel, to avoid this looking like a bulk-messaging operation from the seller's
side no matter how it's built. Flagging this, not designing it — building it without that
conversation first is the one thing I'd actively push back on.

---

## 5. Summary / recommendation

| Piece | Recommendation |
|---|---|
| Multiple filters per query (§1) | ✅ Done — built independent of the LLM feature |
| LLM judge as its own stage (§2) | Build, but as a new `run_llm_review` process + `AWAITING_LLM_REVIEW` status, **not** a `FilterRule` — needs a cost-cap/rate-limit spike first (§2f). *(2026-09-18: the spike is no longer a prerequisite - `llm/` ships the provider layer, the budget ceiling and the `LLMCall` audit; and the stage is now more plausibly a django-q2 job than a fourth compose service.)* |
| Draft-and-suggest outreach via Discord (§4.2) | Build — low risk, reuses existing infra, human stays in the loop for actual contact |
| Auto-send via email/WhatsApp/SMS (§4.1/§4.3) | **Do not build without a separate, explicit decision** — real ToS/compliance/spam exposure, ill-defined contact-channel access, qualitatively different from everything else this project does |

If this moves forward, a reasonable sequencing: ~~§1 (filter registry)~~ done → §2 (LLM judge
stage, after its own small cost/rate-limit spike, mirroring how the Bazos API got probed before
`BazosApiScraper` was built) → §4.2 (draft-only outreach). Treat §4.3 as its own future
conversation, not a checkbox on this list.
