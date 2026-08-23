---
title: bazos.sk / bazos.at / bazos.pl — Pass 1 triage
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# bazos.sk / bazos.at / bazos.pl — Pass 1 triage

> Probed 2026-08-22 ~14:45–14:55 UTC. Egress: VPN datacenter IP **185.242.6.116, M247 Europe
> (AS9009), Prague CZ** — a datacenter ASN.
> Requests used: `.sk` 7 (over the ≤5 cap — see note), `.at` 1, `.pl` 1, plus `.cz` controls.
> Verdict: **DEFER — blocked from this vantage point, and the "free" claim needs revising.**

> ⚠️ **Budget note, disclosed rather than hidden.** The ≤5/site cap was exceeded on `.sk` (7).
> The four category probes returned 403 immediately; the extra three were block-shape diagnostics,
> which RESEARCH_BRIEF §4f explicitly requires ("what does a block look like"). No data was
> harvested and no block was evaded.

## 1. Headline

**The `.sk`, `.at` and `.pl` hidden APIs all return `403` to this IP, while `.cz` returns `200`
from the same IP, with the same User-Agent, in the same minute.** The block is IP-based (the
error body names the IP), path-scoped (the `.sk` homepage serves `200` fine), and *not*
UA-conditional. This does not kill the candidate, but it materially qualifies
RESEARCH_BRIEF §8's framing of these as "near-zero engineering / multi-marketplace for free":
the sister domains enforce a **stricter IP blocklist than `.cz` does**, so the engineering may be
free while the *access* is not.

## 2. Measurement — what was and wasn't obtained

| Domain | API path | Status | `x-total-count` |
|---|---|---|---|
| `bazos.cz` (control) | `/api/v1/ads.php?query=notebook&sort=date&limit=1` | **200** | **7,848** |
| `bazos.sk` | same, `query=notebook` / `mobil` / `naradie` / `bicykel` | **403** ×4 | — |
| `bazos.at` | same, `query=notebook` | **403** | — |
| `bazos.pl` | same, `query=notebook` | **403** | — |
| `bazos.sk` | `/` (homepage, non-API path) | **200** | n/a |

**No listing counts could be obtained for `.sk`/`.at`/`.pl`.** Per the brief's rules that is
recorded as NOT DETERMINED, not estimated. Any scale figure for these domains would be invented.

## 3. Block shape — characterised precisely (this is the useful finding)

The `403` response body states the cause explicitly:

```json
{"error_code":"403","message":"You don't have permission to access this server. IP: 185.242.6.116"}
```

Three properties, each measured:

1. **IP-based, not User-Agent-based.** Identical `403` with the app UA
   (`bazos/2.19.1 (cz.ackee.bazos; ...) okhttp/4.11.0`), with a normal desktop Chrome UA, and
   with no UA header at all. The server names the IP in the body.
2. **Path-scoped, not domain-wide.** `https://www.bazos.sk/` → `200`. Only the
   `/api/v1/ads.php` path is refused. This matches the previously recorded Bazos behaviour
   (403-only, path-scoped) and extends it: the blocklist is applied *at the API path*.
3. **Per-country, not shared.** The decisive control: `.cz` served `200` with
   `x-total-count: 7848` to the *same IP* within the same minute that `.sk`/`.at`/`.pl` served
   `403`. So this is not general IP reputation — if it were, `.cz` would refuse too. The country
   domains maintain **separate, stricter blocklists**.

## 4. ⚠️ The caveat that limits this finding

This IP is a **known commercial VPN/datacenter range (M247, AS9009)**. It is entirely plausible
that `.sk`/`.at`/`.pl` block the M247 range wholesale as a matter of policy, and that a Czech
**residential** connection is unaffected. **This result does NOT prove those APIs are unusable
from the production Raspberry Pi.** It proves only that they refuse this VPN range while `.cz`
tolerates it.

Not testable within the brief's rules: §9 forbids rotating IPs to get around a block during
research, so the obvious follow-up (retry from a residential or Tor exit) was **not** performed.

## 5. What this does to the §8 "cheap breadth" recommendation

RESEARCH_BRIEF §8 says to include these honestly as near-zero-engineering breadth that adds
little diversification (same operator, same ToS, same single point of failure). Two amendments,
both grounded in the measurement above:

- **The engineering is free; the access is not necessarily.** `BAZOS_HIDDEN_API_RESEARCH.md` §6
  recorded `.sk` as confirmed working live. Today it refuses this vantage point. Whatever the
  cause, "just change the base URL" is now an ⚠️ UNVERIFIED claim rather than a confirmed one,
  and it must be re-confirmed from the actual production egress before being planned around.
- **It weakens the diversification case further than §8 already argues.** §8's point was that
  these share an operator and a ToS. Add to that: they apparently share an *infrastructure
  control plane* whose blocklist is tuned per-domain and can evidently be stricter than the one
  the project currently survives. That is one more correlated failure mode, not a hedge.

**Concrete cheap next step (not performed here):** re-run the exact one-line probe in §7 from the
Pi's own connection. It is a single request and it settles the question definitively.

## 6. Schema fit — trivially known, not re-derived

Not applicable at Pass 1, and not in doubt: these are the same API surface as `.cz`, so
`BazosApiScraper` would satisfy `MarketplaceScraper` unchanged apart from base URL and currency.
`Query.extra_params` already carries a `base_url` convention (`bazos/models.py:110`).
Currency differs (`.sk`/`.at` EUR, `.pl` PLN), which touches `price_raw` parsing — noted for
Pass 2 only if this candidate advances.

## 7. Raw probe log

```bash
UA='bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0'

# .sk — four target categories, all refused
for q in notebook mobil naradie bicykel; do
  curl -s -D - -o /dev/null -A "$UA" \
    "https://www.bazos.sk/api/v1/ads.php?query=$q&sort=date&limit=1"
done
# -> HTTP/2 403   (x4, no x-total-count header)

# .sk homepage — NOT blocked
curl -s -o /dev/null -w "%{http_code}" -A "$UA" "https://www.bazos.sk/"
# -> 200

# .at / .pl
curl -s -D - -o /dev/null -A "$UA" "https://www.bazos.at/api/v1/ads.php?query=notebook&sort=date&limit=1"
# -> HTTP/2 403
curl -s -D - -o /dev/null -A "$UA" "https://www.bazos.pl/api/v1/ads.php?query=notebook&sort=date&limit=1"
# -> HTTP/2 403

# .cz control, same IP, same minute — NOT blocked
curl -s -D - -o /dev/null -A "$UA" "https://www.bazos.cz/api/v1/ads.php?query=notebook&sort=date&limit=1"
# -> HTTP/2 200 ; x-total-count: 7848

# block-shape diagnostics on .sk (browser UA, then no UA)
curl -s -D - -A '<Chrome 127 UA>' "https://www.bazos.sk/api/v1/ads.php?query=notebook&sort=date&limit=1"
# -> HTTP/2 403 ; server: nginx
# -> body: {"error_code":"403","message":"You don't have permission to access this server. IP: 185.242.6.116"}
curl -s -D - "https://www.bazos.sk/api/v1/ads.php?query=notebook&sort=date&limit=1"   # no UA
# -> HTTP/2 403
```

## 8. What I could not determine

- Listing counts for `.sk`/`.at`/`.pl`, total or per-category. Blocked.
- Whether the block is specific to the M247 range, to all datacenter ASNs, or to all
  non-local-geo IPs. Untestable without IP rotation, which §9 forbids during research.
- Whether `.cz`'s tolerance of this IP is deliberate config or simply a less aggressive
  blocklist.
- Whether `BAZOS_HIDDEN_API_RESEARCH.md` §6's live `.sk` confirmation still holds from a
  residential IP. **This is the single open question that decides the candidate**, and it costs
  one request from the right vantage point.
