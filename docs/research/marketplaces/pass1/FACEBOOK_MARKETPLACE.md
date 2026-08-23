---
title: Facebook Marketplace — Pass 1 triage
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Facebook Marketplace — Pass 1 triage

> Probed 2026-08-22. Requests used: 1/5. Egress: VPN datacenter IP (M247 AS9009, Prague CZ, 185.242.6.116).
> Verdict: **REJECT.** Assessed per RESEARCH_BRIEF §3d, which pre-authorises a short
> "assessed, recommend against, here's why" file unless something surprising turns up.
> Nothing surprising turned up.

## 1. Headline

Meta's `robots.txt` is a blanket `Disallow: /` for every user-agent not explicitly whitelisted,
prefaced by a notice stating that automated collection is prohibited without **express written
permission**. That is categorically stricter than any other candidate in this study — Bazos
disallows specific search paths, Meta disallows everything and says so in prose. Combined with
the account-ban risk and the anti-bot posture flagged in §3d, this fails the legal gate (§3)
before scale is even worth measuring. **No further requests were spent.**

## 2. Scale — NOT MEASURED, deliberately

Not measured. §3d says not to spend meaningful time here, and the legal gate is dispositive, so
spending Pass-1 budget on listing counts would have been wasted. It is ⚠️ ASSUMED (not measured)
that Czech FB Marketplace volume is material — that assumption does not change the verdict.

## 3. Legal — measured, verbatim

`curl https://www.facebook.com/robots.txt` → `200`, 46,687 bytes. File header, verbatim:

```
# Notice: Collection of data on Facebook through automated means is
# prohibited unless you have express written permission from Facebook
# and may only be conducted for the limited purpose contained in said
# permission.
# All authorized user-agents listed on this page must comply with Meta's
# Automated Data Collection Terms available at:
# https://www.facebook.com/legal/automated_data_collection_terms
```

The catch-all rule, at line 1253, after ~1,250 lines of per-agent blocks:

```
User-agent: *
Disallow: /
```

Note the file explicitly names and blocks scraping frameworks by user-agent, including:

```
User-agent: Scrapy
Disallow: /

User-agent: PetalBot
Disallow: /
```

**Assessment against MONETIZATION.md §3's private-use posture:** §3 sorts uses by whether data
stays with you or goes to a third party, and private deal-hunting is the defensible end of that
spectrum. That defence does not rescue this candidate. The other marketplaces here are cases of
*ToS ambiguity*; Meta's is an explicit, unambiguous, prominently-stated prohibition plus a named
contractual instrument. Additionally §3d's account-ban risk means the realistic failure mode is
losing a **personal Facebook account**, which is a cost the other candidates cannot impose.

## 4. Additional reasons, not measured here

⚠️ ASSUMED (consistent with §3d, not probed in this pass): aggressive anti-bot, and an
account requirement to view most Marketplace listings. Per anti-goal §9 ("do not create accounts,
log in, or accept ToS"), an account requirement would itself have ended the assessment.

## 5. Note on the `facebook/` Django app

Unrelated. As RESEARCH_BRIEF §2a says, `facebook/` in this repo is an `FBUser` leaked-profile PII
importer joined to ads via `PhonePublisher.fb_user`. It has nothing to do with FB Marketplace and
is not evidence of any existing Marketplace capability.

## 6. Raw probe log

```bash
curl -s --max-time 20 -A '<browser UA>' https://www.facebook.com/robots.txt
# -> status=200 size=46687
grep -n -A3 '^User-agent: \*' robots.txt
# -> 1253:User-agent: *
#    1254-Disallow: /
```

## 7. What I could not determine

- Actual Czech Marketplace listing volume (not measured; deliberately).
- Whether listings are viewable without auth (not probed — would risk tripping anti-bot, and
  the legal gate already decided it).
- Whether Meta's Automated Data Collection Terms contain a carve-out for private personal use
  (the linked terms were not fetched; ⚠️ unverified, and unlikely to change the verdict).
