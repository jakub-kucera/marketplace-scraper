---
title: Public Ad Pages
status: proposal
updated: 2026-08-24
verified: 2026-09-18
---

# Public Ad Pages

> **Nothing here has been built and it is not scheduled.** What *did* ship from this
> thread is the much smaller half — the admin self-link in every Discord notification
> (see [`SHIPPED.md`](../SHIPPED.md)). This doc records the rest: why a purpose-built
> ad page was deferred, and what would have to change before it is worth starting.

## 0. The idea, as floated

Every Discord notification carries the marketplace URL. Add a second link, to a page
this project serves itself — so an ad can be inspected, and its price history and seller
context read, without going back to Bazos. The open question was whether that page should
be **public** (unauthenticated, internet-reachable) or simply a link into the **Django
admin**.

## 1. The question is three decisions, not one

"Public vs admin" bundles three things that are independent, and separating them is what
made the cheap half shippable on its own:

| | Options | Shipped |
|---|---|---|
| **What the link renders** | the admin change view · a purpose-built page | admin change view |
| **Who can reach it** | LAN only · VPN/tailnet · public internet | whatever `SITE_BASE_URL` names |
| **Whether it's authenticated** | Django session · open | session |

A purpose-built page can be login-gated; the admin could (badly) be exposed. Only the
third row is what "public" actually means.

## 2. What shipped, and why it was enough for now

`Ad.admin_url` + `SITE_BASE_URL`, appended by `DiscordSender._format_product_message`.
The admin change view is already the richest view of an ad in this project — the
`AdDelivery` and `PriceChange` inlines, the seller-history readonly field, the publisher
partner tables and their block/unblock actions (`bazos/admin.py`). A read-only public
page would have started *worse* than what already exists, and none of it is actionable:
clicking through to block a publisher is most of why the link is useful at all.

## 3. The argument that was expected to carry it, and doesn't

The strongest case for an unauthenticated page is **Discord unfurls**: Discord's crawler
fetches link targets server-side and will not authenticate, so a rich preview card
requires a genuinely public URL.

That case is weak here, because **`Ad` has no image field** (`bazos/models.py`). An OG
card would render name, price and description — which is exactly what `Ad.message`
already puts in the message body. The unfurl would duplicate the notification rather than
add to it.

**This is the thing to re-check before reopening the proposal.** If ad images are ever
scraped and stored (`backlog/BACKLOG_IDEAS.md` carries an images/CV line), the unfurl
argument becomes real and this doc's conclusion should be revisited.

## 4. The PII problem — the actual blocker

This database is not a set of listings. It is listings **joined to seller identity**:

- `Ad.publisher_name`, `EmailPublisher.email`, `PhonePublisher.phone`;
- `SellerAdCounts`, which resolves the email↔phone graph transitively — i.e. it
  deliberately reconstructs *one person* across the pairings the marketplace keeps
  separate;
- `PhonePublisher.fb_user` → the `facebook/` app's bulk-imported **leaked Facebook
  dataset**.

Scraping public listings for private research is one posture, argued in
`MONETIZATION.md` §6. Serving a cross-referenced identity database
of Czech sellers on a public IP is a different one, and the repo already treats this data
accordingly — `./backups/` is gitignored precisely because dumps hold seller PII
([`BACKUPS.md`](../BACKUPS.md)).

**Consequence for any future design:** a public page cannot be "the admin view without
login". It needs a field allowlist decided explicitly, per field, defaulting to excluded —
and everything in the list above is excluded. What is left is roughly `name`, `price*`,
`location`, `publish_date`, the description, and the price history.

## 5. Prerequisites before *any* internet exposure

Both apply to exposing the admin too, and both are cheap to fix but are genuinely blocking:

- **`scraper/settings.py`: `DEBUG = True`, hardcoded.** The `env` default declared in the
  `environ.Env(...)` block is dead — the later module-level assignment overrides it
  unconditionally. Any unhandled 500 or a 404 on a public host renders a full traceback
  with settings, SQL and local variables.
- **`docker-compose.yml`: `marketplace_server` runs `manage.py runserver 0.0.0.0:8000`** —
  the dev server, plaintext HTTP, which Django documents as never for production.
  Port-forwarding it means sending an admin session cookie in the clear.

A third, softer one: every render of `Ad.message` fires the `seller_ad_counts()` COUNT
queries, and CLAUDE.md already warns against calling it in a loop. Public means crawlers,
which is that loop, unauthenticated, against the Pi's Postgres.

## 6. Reachability is the real problem, and it is separable

The thing that actually limits the shipped link is not authentication — it is that
`raspberrypi5.local` is mDNS and does not resolve off the LAN, so a notification opened on
mobile data has a dead link. That is a *reachability* problem, and solving it does not
require anything in this doc.

**Recommended: a tailnet (Tailscale or equivalent), not port-forwarding.** It gives the Pi
a stable hostname that resolves from a phone anywhere, needs no certificate, no reverse
proxy and no open port, and leaves §5's two items harmless because nothing is public. Set
`SITE_BASE_URL` to the tailnet name and the already-shipped link works from anywhere,
unchanged. The static IPv4 + port-forward path only becomes necessary if something outside
the tailnet has to reach the page — which, for a single-user tool, it does not.

## 7. What would have to be true to start this

All three, not any one:

1. **Images exist on `Ad`** — otherwise the unfurl argument is still empty (§3).
2. **A concrete view the admin cannot serve** — a mobile-shaped ad card, a price-history
   chart, a gallery across queries. "Nicer than the admin" is not one.
3. **§5's two items fixed**, if the page is to be reachable from outside a tailnet.

## 8. If it is ever built — the shape that stays cheap

- One view at a stable route (`/ad/<pk>/`), added to `scraper/urls.py` — which today holds
  `admin/` and nothing else, so this is the app's first non-admin surface.
- Ship it `@staff_member_required` **first**. Public vs private then stays a one-decorator
  decision instead of a rewrite, and the field allowlist from §4 can be written and
  reviewed while nothing is exposed.
- Give `Ad` a `public_url` property alongside `admin_url`, built with `reverse` off the
  same `SITE_BASE_URL` — never string-concatenated (`Section.full_url` / `Query.url` set
  the precedent).
- Read it via `getattr` in the sender, the way `admin_url` is, so no `Sendable` gains a
  required member.
- If a *single* ad ever needs sharing without an account, an HMAC-signed unlisted token
  (`?t=…`) is a smaller change than making the route public, and leaks one row instead of
  the table.

## 9. Relationship to the other proposals

[`DISCORD_BOT.md`](DISCORD_BOT.md) §1 reaches the same conclusion from the opposite
direction: it chooses a gateway bot specifically to **avoid** exposing an inbound HTTP
surface. A public page would reintroduce exactly what that proposal is structured to
dodge. If both were ever built, they should share one decision about what this deployment
exposes — not make it twice.
