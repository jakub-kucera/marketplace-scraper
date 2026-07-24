# LLM Ad Review & Seller Outreach — Exploration & Proposal

> Status: **proposal, not scheduled**. Not wired into `PIPELINE_REFACTOR.md`'s stage list or
> `PROMPTS.md` — this needs an explicit decision (especially on outreach, §4) before either
> happens. Nothing here has been built.
>
> **See also**: [`DISCORD_BOT_DESIGN.md`](./DISCORD_BOT_DESIGN.md) (2026-07-24) — its Tier 3
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

---

## 3. Interaction with the cross-query dedup backlog item

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
  `BAZOS_HIDDEN_API_RESEARCH.md` §3.3) proxies the email — the seller's real address is never
  exposed to us, which is actually good (least additional exposure), but this endpoint is listed
  under **auth-gated, account-required** operations. Whether it needs only a token or the same
  phone-verification gate that blocks `ad-phone.php`/`agents.php` (confirmed `403
  {"message":"Číslo je neověřené"}` in that doc's §3.2/§6.4e) **hasn't been tested** — this needs
  its own probe before anything else here is designed, the same way the search API itself did.
- **Real phone/email harvested from ad text or `ratings.php`** — technically available (per
  `BAZOS_API_DISCOVERY_PIPELINE.md` §6.4b/§3.3), but messaging a private individual on
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
  (`BAZOS_HIDDEN_API_RESEARCH.md` §6.2 point 4) — automated outbound contact is a further step,
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
| LLM judge as its own stage (§2) | Build, but as a new `run_llm_review` process + `AWAITING_LLM_REVIEW` status, **not** a `FilterRule` — needs a cost-cap/rate-limit spike first (§2f) |
| Draft-and-suggest outreach via Discord (§4.2) | Build — low risk, reuses existing infra, human stays in the loop for actual contact |
| Auto-send via email/WhatsApp/SMS (§4.1/§4.3) | **Do not build without a separate, explicit decision** — real ToS/compliance/spam exposure, ill-defined contact-channel access, qualitatively different from everything else this project does |

If this moves forward, a reasonable sequencing: ~~§1 (filter registry)~~ done → §2 (LLM judge
stage, after its own small cost/rate-limit spike, mirroring how the Bazos API got probed before
`BazosApiScraper` was built) → §4.2 (draft-only outreach). Treat §4.3 as its own future
conversation, not a checkbox on this list.
