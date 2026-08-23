---
title: Discord Bot — Exploration & Proposal
status: proposal
updated: 2026-07-24
verified: 2026-07-24
---

# Discord Bot — Exploration & Proposal

> **Nothing here has been built, and it is not scheduled.** Not wired into `PIPELINE_REFACTOR.md`'s stage list or
> `PROMPTS.md`. Nothing here has been built. This is a thorough exploration, written the same
> way `BAZOS_API_DISCOVERY_PIPELINE.md` and `LLM_AD_REVIEW_DESIGN.md` were — grounded in what
> the code actually does today, not a generic "add a Discord bot" writeup.

## 0. The idea, as floated

Today, Discord is purely an outbound notification channel: `DiscordSender` fires a one-way
webhook POST (`senders/services/discord_sender.py`, via the `discord_notify` library) and never
hears back. The idea: make it two-way. Turn specific notifications into actionable objects —
watch an ad for updates, ask for its full description, message the seller, enable/disable a
query — triggered from Discord itself, not the Django admin.

This is a bigger architectural addition than anything else explored so far in `docs/refactor/`,
so this doc is organized around one central question first (§1: how does the bot actually
receive commands — this decision shapes everything downstream), then the feature catalog (§2),
then data model changes (§3), then security (§4), then how this connects to *every other*
open proposal in this repo (§5) — there's more convergence here than expected — then a phased
build recommendation (§6).

---

## 1. The architecture decision: how does Discord talk back to this project?

This is worth getting right before anything else, because it determines whether this needs a
whole new class of long-running process or just a few new views/commands.

### 1.1 Two fundamentally different mechanisms

Discord offers two ways for a bot to receive interactions (slash commands, button clicks,
messages):

**A. Gateway bot** (traditional — `discord.py`, `hikari`, `nextcord`). The bot process opens a
persistent outbound WebSocket connection *to* Discord and receives events (messages, button
clicks, slash commands) over that socket. No inbound network surface at all — Discord never
connects to you.

**B. HTTP Interactions endpoint** (the newer, "serverless-friendly" model). You register a
public HTTPS URL with Discord; Discord POSTs interaction payloads (slash commands, button
clicks) to it, and you respond synchronously (must ACK within 3 seconds) or defer and follow up
later via a separate webhook call within 15 minutes.

### 1.2 Why this matters *specifically for this project*

Check `docker-compose.yml`: `marketplace_server` runs `python manage.py runserver 0.0.0.0:8000`
— Django's development server, no TLS, and nothing in the current stack exposes it to the
public internet (no reverse proxy, no cert management, `tor_proxy`/`postgres`/`adminer` are all
internal-network services too). **This project currently has zero public HTTPS surface.**
Discord requires HTTPS for Interactions endpoints — self-signed certs aren't accepted.

So Option B isn't "add one view" — it's "stand up a production WSGI/ASGI server, get a TLS
cert, expose a port publicly (or run a tunnel), and implement Ed25519 request-signature
verification (`PyNaCl`) so random internet traffic can't hit your interaction handler." That's
real new infrastructure this project has never needed before.

Option A needs *no* inbound network exposure at all — it's an outbound connection, exactly like
`TorIPChanger`'s connection to the Tor control port, or `run_scraper`'s requests to Bazos. It
also slots into the existing deployment shape almost exactly: `docker-compose.yml` already runs
three other always-on containers (`marketplace_scraper`, `marketplace_filter`,
`marketplace_sender`) as long-lived polling/connected processes. A fourth — `marketplace_bot`
running `python manage.py run_discord_bot` — is the same shape, not a new one.

**A secondary nuance that resolves the choice further**: once you have a real gateway-connected
bot, it receives *both* slash commands *and* button-click interactions over the same socket —
there's no separate "buttons need Option B" requirement. The common assumption that "buttons
require setting up an Interactions endpoint" is true only if you *don't* already have a gateway
bot; if you do, buttons/components arrive as ordinary gateway events, same as everything else.

### 1.3 Recommendation

**Build a real gateway bot** (`discord.py` — mature, huge community, native slash-command
support via `app_commands`, actively maintained). It fits this project's actual deployment
reality (self-hosted, no existing public ingress) far better than standing up a public HTTPS
endpoint would. If a tunnel (Cloudflare Tunnel, Tailscale Funnel) or reverse proxy is *already*
part of some future deployment plan, Option B becomes more attractive and this recommendation
should be revisited — but as of today's `docker-compose.yml`, Option A is the lower-total-new-
infrastructure choice.

One more reason this fits well: `discord.py`'s bot loop is `asyncio`-native. `BACKLOG_IDEAS.md`
#2 already noted that Django 4.1's async ORM methods (`afilter`, `acreate`, `aget`, ...) exist
but are unused anywhere in this codebase. The bot process is the natural first place to actually
use them, rather than wrapping every DB call in `sync_to_async`.

### 1.4 What changes in `DiscordSender` once a real bot exists

Today, `Discord.url` is a per-channel **webhook URL**, and `DiscordSender` posts anonymously
through it (`discord_notify`'s `Notifier(url).send(...)`) — plain text only, no message ID
returned, no components/buttons possible.

Once a bot Application exists, the cleaner design is for the bot to **send messages as itself**
(`POST /channels/{channel_id}/messages` with the bot token) rather than through a disconnected
webhook — same entity sends the message and receives its button-click interactions, no
webhook/bot indirection to reason about. This means:
- `Discord.url` (webhook URL) → `Discord.channel_id` (the bot must be invited to that channel).
- `DiscordSender` gains the ability to attach `components` (buttons) and use real embeds instead
  of plain text — which, notably, is **also** exactly what `BACKLOG_IDEAS.md` #3a (thumbnail
  embed, promoted as `PROMPTS.md` P16) and `LLM_AD_REVIEW_DESIGN.md` §4.2 (draft-message
  delivery) independently need. See §5 — building this once serves three proposals at once.
- Message IDs become capturable at send time, which is what makes per-ad button actions (§2)
  possible at all — you need to know *which ad* a given message's buttons refer to.

This is a real migration (new field, new send path, existing webhook configs need
re-registering as bot channel access) — not a drop-in — but it's the one all three "richer
Discord message" proposals converge on, so it's worth treating as shared infrastructure rather
than building three overlapping partial versions.

---

## 2. Feature catalog

Organized by risk tier — lower tiers are safe defaults, higher tiers need the same kind of
explicit sign-off `LLM_AD_REVIEW_DESIGN.md` §4 already flagged for seller outreach. The bot
*changes the trigger UX* for some existing proposals; it does not change their risk calculus.

### Tier 0 — read-only, no side effects

| Command | What it does |
|---|---|
| `/query list` | Enabled queries, last run time, recent `new_ads_count` — reuses `QueryAdmin`'s existing `last_run` annotation logic. |
| `/stats` | Digest: ads found today/this week, price drops, most active queries — currently only visible by eyeballing `QueryRun` rows in Django admin. |
| Per-ad button: **"🔍 Check seller"** | Calls `ratings.php`/`user_ads_count` (`BAZOS_HIDDEN_API_RESEARCH.md` §6.4b) for the ad's seller and posts a summary (review count, sentiment breakdown, `user_ads_count` "is this a dealer" signal) back as a reply. **User-triggered, per-seller-of-interest** — a materially safer way to use this capability than the automated background seller-graph scanning `BAZOS_API_DISCOVERY_PIPELINE.md` §5 flagged as needing a deliberate decision. This sidesteps that concern entirely: nothing runs unless a human clicks it for one specific ad they're already looking at. |
| Per-ad button: **"📦 Seller's other listings"** | Same reasoning, using the confirmed `ads.php?email_id=`/`phone_id=` filter (§6.4g of the same doc) — pulls a specific seller's current inventory on demand, not as a background sweep. |
| Per-ad button: **"📈 Price history"** | Formats and posts `ad.price_history.all()` — the `PriceChange` records P1 already builds. Zero new API calls, pure DB read; pairs naturally with the watcher (§2.1), which is what keeps this populated for ads no longer in a query's normal scan window. |
| Per-ad button: **"📊 Price context"** | Where this ad's price falls against a rolling median/percentile for similar recent listings in the same category — the internal baseline `BAZOS_API_DISCOVERY_PIPELINE.md` §2 Stage 2 already designed for filtering, surfaced on demand instead of only running silently in the background. "Is this actually a good deal" as an answerable question, not just a filter's internal signal. |
| Per-ad button: **"🕵️ Repost check"** | Has this seller posted this same item before, under a different `external_id`? Matches title/price/locality similarity against your own accumulated `Ad` archive for the same publisher — `BAZOS_API_DISCOVERY_PIPELINE.md` §3.3's same-seller-repost detection, fully designed, never built, and free — it only touches data already collected. |
| Per-ad button: **"❓ Why rejected"** | For a `REJECTED` ad, surface `ad.filter_reason` (already a field, currently only visible in Django admin) directly. Makes the Stage 9 rules (`PROMPTS.md` P5, done) debuggable from the notification itself instead of needing to open admin every time a filter seems to have made a wrong call. |
| Per-ad button: **"📍 Distance"** | Using `zip.php` geocoding (`BAZOS_HIDDEN_API_RESEARCH.md` §6.4d, designed/unused) plus a configured home location, show actual distance instead of just the raw locality string. |

### Tier 1 — self-directed state changes (affects only your own scraper config/data)

| Command | What it does |
|---|---|
| Per-ad button: **"👁 Watch this ad"** | See §2.1 below — the user's own first idea, worth its own section. |
| Per-ad button: **"📖 Full description"** | On-demand `scraper.load_full_description(ad)` for one ad, for queries that don't have `load_full_description=True` by default (saves the request cost site-wide, still available per-ad when actually interesting). |
| Per-ad button: **"🔇 Mute"** | Stop further re-notifications for *this ad* (e.g. `PRICE_CHANGED` re-alerts) without touching the whole query. |
| Per-ad button: **"⭐ Favorite"** | Personal bookkeeping flag — no pipeline effect, just lets `/stats`-type queries and admin filtering surface "ads I cared about." |
| Per-ad button: **"🚫 Blocklist seller"** | Sets `EmailPublisher.blocked`/`PhonePublisher.blocked` — already wired into `PublisherBlocklistRule` (`PROMPTS.md` P5, done). Turns a manual Django-admin action into one click from the ad you're looking at. |
| `/query enable <id>` / `/query disable <id>` | Mirrors `QueryAdmin`'s existing `enable_queries`/`disable_queries` admin actions — same effect, faster access. |
| `/force-run [query_id]` | Global form mirrors the existing admin "Force run" button (`bazos/admin.py`'s `force_run_now`, touching `settings.FORCE_RUN_FLAG_PATH`). A **per-query** form is new — today's flag is a single global sentinel that wakes the whole runner; scoping it to one query needs a small addition (§3.3). |

### 2.1 The watcher — worth detailing, since it's the strongest idea in the original ask

**Why it's not redundant with the existing dedup/re-poll logic**: `run_existing_query`'s price-
change detection (just built, `PROMPTS.md` P1) only fires when a query's *normal* scrape
happens to re-surface that exact ad — which requires it to still be within the query's
newest-first scan window. An ad that scrolls off that window (plausible for anything but a very
narrow query) never gets re-checked again, even though P1's price-change machinery would handle
it perfectly well if it were. **A watcher is the only way to get updates for a specific ad once
it's fallen out of its query's normal reach** — a real, load-bearing use case, not a nice-to-have.

**Design**: a new `AdWatch(ad FK, active, requested_by, last_checked)` model plus a new polling
process `run_ad_watch`, structurally identical to every other stage in this pipeline
(`select_for_update(skip_locked=True)`, poll interval, tighter than the parent query's normal
cadence since it's a small, deliberately-chosen set of ads). Each tick:
1. Re-fetch the ad via whichever scraper matches `ad.marketplace` (the existing
   `_build_scrapers`-style registry) — either a full `load_full_description` refresh, or, if
   `BazosApiScraper` is in production use by then, the cheap bulk `ads.php?ad_id[]=` recheck
   (`BAZOS_HIDDEN_API_RESEARCH.md` §5.3) for price/still-listed status at near-zero cost.
2. Reuse the **exact same price-change detection path** built for P1 — diff `price_raw`, create
   a `PriceChange`, flip to `AdStatus.PRICE_CHANGED` — no new logic needed there, just a new
   trigger source.
3. **Sold/removed detection**: `ad-detail-2.php` returning `410 {"status":"deleted"}` is fully
   documented (`BAZOS_HIDDEN_API_RESEARCH.md` §6.4a) but has **no consumer anywhere in the
   codebase today** — it's a capability that's been researched and never used. The watcher is
   the natural first consumer: a new `AdStatus.REMOVED` (or similar), set when a watched ad
   404s/410s, with a Discord notification ("this one sold or was removed").

This is a good example of something worth calling out explicitly: **P1 (price history) and the
Bazos API research were both already built/researched with unused capacity** — P1's diffing
logic has no way to run on-demand, and the API doc's sold-detection has no caller at all. The
watcher isn't a new capability so much as a *trigger* that finally uses two already-finished
pieces of work together.

### 2.2 Operational health & the heartbeat idea

A different category from per-ad actions: pipeline health, surfaced through the same bot.

- **`/health`** — last successful run per query, current `PENDING`/`APPROVED` backlog depth,
  recent blacklist events, `FAILED` send count. All of this exists today (`QueryRun`, `Ad.status`
  counts, `django-db-logger`'s table) but is admin-only; this is a quick-check command, not new
  data collection.
- **Proactive alerts** on repeated blacklist hits or a run of `FAILED` sends — surfacing exactly
  the kind of thing that today just increments a counter silently, no different in spirit from
  the `Ad.send_attempts`/`MAX_SEND_ATTEMPTS` machinery already there, just given a voice.
- **A daily heartbeat** ("still alive, N ads processed today") is worth calling out specifically,
  because it's a *dead-man's-switch* rather than an alert — absence of the heartbeat is the
  signal, not its content. This connects directly back to the very first thing this project's
  Sentry setup was fixed for (see §5): `run_scraper`'s crashes were being silently swallowed by
  its outer `except Exception` and only visible by tailing container logs, until that got wired
  into `logger.exception` so Sentry would catch it. A heartbeat is a second, independent, and
  faster channel for "something's broken" that doesn't depend on remembering to check Sentry —
  genuinely redundant in the way health monitoring should be, not a duplicate of the same signal.

### 2.3 Interaction UX alternatives

Worth considering alongside plain buttons, not instead of them:

- **Reactions as shortcuts** (👀 = watch, 🔇 = mute, ⭐ = favorite) — faster on mobile than
  tapping a button, and they work on *any* message, including ones sent before the bot existed
  or before components were added to `DiscordSender` (§1.4).
- **Threads per ad** — auto- or on-demand-create a thread under an ad's notification for
  notes/negotiation history, so a drafted seller message (Tier 3) and how it went doesn't
  clutter the main channel.
- **Ephemeral responses** — for anything only the requester cares about (seller lookups, price
  history, "why rejected"), an interaction response can be visible only to the person who
  triggered it. This is a property of interaction *responses*, not of the gateway-vs-HTTP
  transport choice in §1, so it composes fine with the gateway-bot recommendation without
  requiring Option B.

### Tier 2 — creates new scraping scope

| Command | What it does |
|---|---|
| `/watch <free text>` | LLM-assisted `Query` creation from natural language — e.g. "macbook m1 under 20k in Prague." Grounded in an existing, confirmed capability: `suggestionsnew.php` already resolves free text to matched `section`/`category` ids (`BAZOS_HIDDEN_API_RESEARCH.md` §6.4c), so this isn't speculative LLM-guesses-a-category — it's LLM-extracts-price/location-intent, API-resolves-the-taxonomy. Needs a confirmation step before creating the `Query` (show the parsed result, require a 👍 reaction) rather than creating it silently — LLM parsing of user intent into a live, running scraper config is exactly the kind of thing that should have a human confirm the interpretation once, cheaply, before it starts consuming requests indefinitely. |

### Tier 3 — third-party-facing (same gate as `LLM_AD_REVIEW_DESIGN.md` §4)

| Command | What it does |
|---|---|
| Per-ad button: **"✉️ Draft message to seller"** | This *is* `LLM_AD_REVIEW_DESIGN.md` §4.2, just delivered on demand instead of automatically for every `llm_outreach_enabled` query. Arguably an even better fit for that idea than the original design — it's explicitly one human, deciding about one ad they're already looking at, asking for a draft they will send themselves. Recommend building this **as** the outreach feature's actual delivery mechanism, rather than a separate background "post a suggestion for every approved ad" pass. |
| Reaction on a sent draft: **outcome tracking** | More speculative, and only meaningful once the draft-message button exists: let the user mark what happened after sending a drafted message manually — responded / no reply / deal fell through — via reaction. Builds a lightweight per-seller responsiveness signal over time, feeding back into the seller-reputation enrichment idea (Tier 0) instead of the action being a one-off with no memory. Needs somewhere to record the outcome (a field on whatever model ends up tracking sent drafts — not designed yet, since it depends on Tier 3 landing first). |
| Auto-send via email/WhatsApp/SMS | **Still not recommended**, same reasoning as `LLM_AD_REVIEW_DESIGN.md` §4.1/§4.3 — unresolved contact-channel access (`ad-mail.php`'s auth gate untested), ToS exposure, and spam/compliance risk for unsolicited contact via harvested numbers. The bot changes *how a human requests* a draft; it does not change whether auto-sending on their behalf without review is a good idea. If this is ever reconsidered, it's the same separate decision already flagged, not a natural extension of the bot. |

---

## 3. Data model changes

### 3.1 `Ad` additions
```python
favorite = models.BooleanField(default=False)
muted = models.BooleanField(default=False)  # suppress re-notifications (e.g. PRICE_CHANGED) for this ad
discord_message_id = models.CharField(max_length=32, null=True, blank=True)
discord_channel_id = models.CharField(max_length=32, null=True, blank=True)
```

**Caveat worth stating plainly**: `discord_message_id`/`discord_channel_id` on `Ad` directly
assumes one ad → one delivery. `BACKLOG_IDEAS.md` #1 (the `Ad`/`AdDelivery` split) already
exists precisely because that assumption breaks once the same real-world ad matches two
queries with two different senders/channels — this is the **third** proposal in this repo's
`docs/refactor/` (after `LLM_AD_REVIEW_DESIGN.md` §3 and the discovery-pipeline doc) to bump
into that same gap. Not a blocker for a first version (still true today that query overlap is
rare in practice), but at this point it's less "an idea in the backlog" and more "the thing
three unrelated features all want" — worth weighting that when `#1` gets prioritized.

### 3.1a What the new Tier 0 buttons do and don't need

Worth noting explicitly since it's easy to assume every new button needs new schema: "price
history," "why rejected," and "repost check" (§2) need **no new fields at all** — they read
`PriceChange`, `Ad.filter_reason`, and the existing `Ad` table respectively. "Distance" needs
one new piece of config (a home location — a setting, e.g. `HOME_ZIP_CODE`, not a model field,
since it's a property of the deployment/user, not of any `Ad`/`Query` row). "Price context"
needs no new fields either, just a query over existing `Ad.price_raw`/`created`/`query.category`
— parsing `price_raw` into a comparable number can reuse `parse_price` (`bazos/filters.py`,
`PROMPTS.md` P5, done).

### 3.2 New `AdWatch` model
```python
class AdWatch(TimeStampedModel):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="watches")
    active = models.BooleanField(default=True)
    requested_by = models.CharField(max_length=64, blank=True)  # Discord user id, for audit
    last_checked = models.DateTimeField(null=True, blank=True)
```

### 3.3 Per-query force-run (extends the existing global mechanism)
Today: one sentinel file (`settings.FORCE_RUN_FLAG_PATH`), read by
`BazosRunner._interruptible_sleep`, wakes the *entire* runner for its next full pass. A
per-query version needs either a `Query.force_run_requested` boolean (checked at the top of
each query's turn in `BazosRunner.run()`'s loop, independent of the interruptible-sleep
mechanism) or a small dedicated queue table if this needs an audit trail (who/when requested
it). The boolean is simpler and matches this project's general preference for minimal state.

### 3.4 Deferred/slow action queue
Not every bot action finishes instantly — `load_full_description`, a seller lookup, or an LLM
draft all involve a real network round-trip (through Tor, for Bazos calls). `discord.py`'s
interaction handling can simply `await` these inline (unlike an HTTP Interactions endpoint, it
has no 3-second ACK deadline to worry about) as long as the bot process isn't blocked on
something slow enough to visibly stall other users' commands — for a single-user/personal-scale
bot this is very likely fine to do inline. If it ever isn't (e.g. an LLM call that's slow or
rate-limited), the existing polling-queue pattern (a status field + a `run_*` command) is right
there to reuse — no new pattern needs inventing, same as everywhere else in this pipeline.

---

## 4. Security — the one thing that must not be an afterthought

A bot that can enable/disable queries, blocklist sellers, or (if Tier 3 is ever revisited)
initiate contact with third parties is a **remote-control surface for this project**, reachable
by anyone who can see it in a shared Discord server. This needs an explicit allowlist check —
compare the invoking user's Discord id against a configured owner/trusted-user list — on every
mutating command and button, not just "the bot is invited to a semi-private server so it's
probably fine." Read-only commands (`/query list`, `/stats`, seller lookups) are lower-stakes
but should probably still be gated the same way by default, tightened later only if there's an
actual reason to share them more broadly.

If Option B (HTTP Interactions) is ever chosen instead of the gateway-bot recommendation in
§1.3, this section gains a second, unrelated requirement: verifying Discord's Ed25519 request
signature (`PyNaCl`) on every incoming HTTP call, since that endpoint is otherwise open to
anyone on the internet who finds the URL — a gateway bot doesn't have this exposure at all
(no inbound surface to spoof), which is a further point in its favor for this project.

---

## 5. Convergence with everything else already proposed in this repo

Worth being explicit about this, since it changes the efficient build order:

- **`PROMPTS.md` P16** (Discord thumbnail embed) and **`LLM_AD_REVIEW_DESIGN.md` §4.2** (draft-
  message delivery) and **this doc** all independently need the same underlying thing: moving
  `DiscordSender` off plain-text `discord_notify` webhooks onto real embeds/components, ideally
  sent via a bot token (§1.4). Building that once — as part of standing up the bot — serves all
  three, instead of three overlapping partial implementations landing separately.
- **`BACKLOG_IDEAS.md` #1** (`Ad`/`AdDelivery` split) keeps coming up — this is the third
  proposal to want per-(ad, query, channel) granularity that today's single `Ad` row can't
  cleanly represent (§3.1).
- **`BAZOS_HIDDEN_API_RESEARCH.md`**'s sold/removed detection (§6.4a, `410 deleted`) and seller-
  reputation lookup (§6.4b, `ratings.php`) are both fully researched and confirmed live, but
  have **zero consumers** in the codebase today. The watcher (§2.1) and the "check seller"
  button (Tier 0) are the first concrete use for each, respectively.
- **`BACKLOG_IDEAS.md` #2** (asyncio) noted Django's async ORM is unused in this codebase. The
  bot process (necessarily `asyncio`-native if built on `discord.py`) is the natural first
  adopter, not a forced retrofit.
- **`LLM_AD_REVIEW_DESIGN.md` §4** (seller outreach) — the bot doesn't introduce a new decision
  here, it just changes the trigger from "automatic for opted-in queries" to "on-demand per ad."
  The recommendation from that doc (draft-and-suggest yes, auto-send needs a separate decision)
  carries over unchanged.
- **The `run_scraper` Sentry-logging fix** (this project's very first pipeline-reliability fix
  this cycle: the outer `except Exception` in `run_scraper.py` now calls `logger.exception` so
  Sentry actually sees crashes, instead of only `print()`) is the direct precedent for the
  heartbeat idea (§2.2) — same problem (silent failure, no one notices until they happen to
  check), different, redundant channel for noticing it.
- **`PROMPTS.md` P5** (done) built `parse_price` for `PriceRangeRule` — the "price context" button
  (§2) can reuse it directly for comparing prices numerically, no new parsing needed.

---

## 6. Phased build recommendation

| Phase | Scope | Risk |
|---|---|---|
| 1 | Bot infra (`discord.py`, `run_discord_bot`, allowlist auth) + `DiscordSender` migration to bot-token sends with components + Tier 0/1 commands (`/query list`, `/stats`, `/health`, daily heartbeat, watch/mute/favorite/blocklist buttons, seller-lookup buttons, price-history/why-rejected/distance buttons, per-query force-run) | Low — all self-directed or read-only, and none of these need new data beyond what's already collected |
| 2 | `AdWatch` + `run_ad_watch` process, wiring in sold/removed detection; repost-check and price-context buttons (`parse_price` already available from P5) | Low — extends already-built P1 logic and existing archive data |
| 3 | `/watch <free text>` LLM-assisted query creation, with a confirm-before-create step | Medium — LLM interpreting intent into a live config, mitigated by requiring confirmation |
| 4 | Draft-seller-message button (`LLM_AD_REVIEW_DESIGN.md` §4.2's actual delivery mechanism); outcome-tracking reaction as a follow-on once drafts exist | Medium — third-party-facing content, but human-drafted-and-reviewed, human-sent |
| — | Auto-send via email/WhatsApp/SMS | **Explicitly not part of this plan** — same separate decision as `LLM_AD_REVIEW_DESIGN.md` §4.3 |

Phases 1–2 are the strongest, lowest-risk core of this idea and stand on their own even if
Phases 3–4 never happen. Phase 3/4 should each get their own confirmation before starting, same
as the LLM proposal's own sequencing.
