---
title: Composing a Query — what the search can and cannot express
status: active
updated: 2026-09-18
verified: 2026-09-18
---

# Composing a Query — what the search can and cannot express

> How a `Query` row turns into results, and which conditions are expressible. Written
> 2026-08-26 after trying to express "M3 Pro or better, ≥32GB RAM, ≥1TB storage" as one
> query and discovering it is **not exactly expressible**. The approximation that is, and
> why, is §5.
>
> Bazos search-operator measurements live in
> `HIDDEN_API.md` §4.1a–4.1b — that is the outside-world
> reference. This doc is about composing our own rows against it.

## 1. The two filtering stages

A `Query` filters twice, and the stages have **different matching semantics**:

| | Where | Field | Semantics |
|---|---|---|---|
| **Stage 1 — Bazos** | `hledat=` on the live site | `Query.text` | word-based, order-independent, implicit AND, real `OR` |
| **Stage 2 — ours** | `run_filter`, `bazos/filters.py` | `filter_required` / `filter_blocklist` | **substring**, case-insensitive, diacritics-sensitive |

They compose as an AND: an ad must survive Bazos's search *and* every filter rule.

`Query.price_lower`/`price_upper` act in **both** stages — they go into the URL as
`cenaod`/`cenado` (so they cut scrape volume server-side) *and* are re-checked by
`PriceRangeRule`. `0`/`0` means "no filter" in both.

## 2. Stage 1 — what Bazos's own search does

Measured live; see `HIDDEN_API.md` §4.1a–4.1b.

- **Multiple words = implicit AND.** `macbook pro` → 1 101, narrower than `macbook` → 1 615.
- **`OR` is a real union operator.** `iphone OR traktor` returns the sum of both. Case-insensitive, works with 3+ terms.
- **`AND` as a keyword is fake.** It becomes a fourth required literal word and silently guts results (`macbook AND pro` → 71, not 1 101). Never write it.
- **`OR` binds looser than the implicit AND.** `m3 pro` → 1 237, `m3 max` → 437, `m3 pro OR m3 max` → 1 492. The parse is `(m3 AND pro) OR (m3 AND max)`, which is what you want.
- **There is no phrase search, and word order is ignored.** `pro m3` → 1 237, identical to `m3 pro`. Quotes are accepted but change nothing.

That last point is the one that bites. **Bazos cannot distinguish "M3 Pro" the chip from
"MacBook Pro … M3" the base model** — both contain the words `m3` and `pro`. Any condition
that depends on two words being *adjacent* has to be enforced in stage 2.

`Query.text` is `max_length=120`, so an `OR` chain has a practical ceiling of roughly a
dozen terms.

## 3. Stage 2 — what our filter rules do

Seven rules are registered in `bazos/filters.py`, and an eighth - `reference_price` - is
registered by the `refprice` app from its `AppConfig.ready()`. Six apply by default; two are
opt-in (`OPT_IN_RULE_NAMES`). Re-checked against `RULE_REGISTRY` on 2026-09-18.

| Rule | Logic | Applies by default |
|---|---|---|
| `price_range` | reject if `ad.price` outside the range. PASSes on `0-0` and on a null price | yes |
| `required_keyword` | reject unless **at least one** phrase in `filter_required` appears — one OR-group | yes |
| `blocklist_keyword` | reject if **any** phrase in `filter_blocklist` appears — a NOR | yes |
| `publisher_blocklist` | reject if the email/phone publisher is flagged | yes |
| `price_drop` | re-notifications only: reject a `PRICE_CHANGED` ad whose newest `PriceChange` did not go down | yes |
| `location_distance` | reject if the ad's PSČ is further than `filter_location_radius` km from `filter_location_center`. PASSes when either field is unset (**the default**) or the ad carries no postal code - which is every Sbazar and Vinted ad | yes |
| `price_model` | **inverted** - rejects unless a price model calls the ad a deal | **no, opt in** |
| `reference_price` | **inverted** - rejects unless the asking price is ≤60% of a persisted catalogue median. Never calls Zboží; it reads only `RefProductLink` rows an explicit lookup already wrote, so an ad nobody looked up PASSes | **no, opt in** |

`filter_rule_names` selects which apply, and **empty means all the *default* rules — which is
not all of them.** The two inverted rules have to be named explicitly, because a rule that
rejects everything it does not actively like would mute an existing query the day it was
switched on by default.

**The shape of what you can express is therefore fixed:**

```
(price in range) AND (none of blocklist) AND (any of required)
```

**One positive OR-group. That is the whole budget.** You cannot AND two OR-groups —
there is no second `filter_required`, and no grouping syntax inside the one there is.
A condition like "(chip is A or B) AND (RAM is C or D)" needs two, so it does not fit.

Two rules sit outside that shape. `location_distance` ANDs an independent `(within N km)`
term once a centre and a radius are set. And the two inverted rules replace the conjunction
rather than extending it: on a query that names one, the channel sees only what the model or
the catalogue median liked. `reference_price` is also the one rule that can return **APPROVE**
rather than PASS, so when it fires it short-circuits every rule after it in the list - order
inside `filter_rule_names` is therefore not cosmetic.

### 3.1 Matching is substring, not word

`phrase.lower() in f"{ad.name} {ad.short_description}".lower()`. Three consequences:

- **Adjacency works** — `"m3 pro"` matches `MacBook Pro M3 Pro 36GB` and does *not* match
  `MacBook Pro 14 M3 8GB` (there the order is `pro … m3`). This is the phrase matching
  Bazos itself lacks, and it is the reason chip tier belongs here.
- **Substrings collide.** `"8gb"` is inside `"48gb"` and `"128gb"`, so blocklisting 8GB
  silently rejects 48GB and 128GB machines. Check every blocklist term against the larger
  values it might be a substring of.
- **Diacritics are not stripped.** `"nefunkční"` and `"nefunkcni"` are different phrases;
  list both or neither.

### 3.2 Two traps worth stating outright

**Czech negation defeats a blocklist.** `bez poškození` ("without damage") contains
`poškozen`, so blocklisting damage words rejects the ads that explicitly say they are
undamaged. Prefer terms that have no common negated form.

**The haystack is truncated.** `short_description` is capped at 254 characters by the
listing page, and most ads hit that cap, so anything stated later in a long description
is invisible to both keyword rules. `load_full_description` does **not** help — the rules
read `short_description` only.

*Re-measured on the production DB, 2026-09-18:* **20,483 of 27,568 Bazos ads (74.3%) are
exactly 254 characters**; six rows exceed it and none by much. The cap is real, the fraction
depends on the corpus.

**And on the other marketplaces the haystack may be the title alone.** Sbazar populates
`short_description` on **0 of 734** ads, and Vinted on **0 of the 1,124** scraped before the
2026-09-16 transport rewrite against **186 of 186** after it. Since the haystack is
`name + short_description` and `name` is always populated, a blocklist or required list on
those queries degrades to title-only matching rather than failing - silently, and in opposite
directions for the two rules: `blocklist_keyword` rejects less, `required_keyword` rejects more.

## 4. Which side to put a condition on

| Condition shape | Where | Why |
|---|---|---|
| Broad topic narrowing | `Query.text` | cuts scrape volume server-side, before any request cost |
| Two words that must be **adjacent** | `filter_required` | Bazos ignores word order |
| A set of acceptable values (the one OR-group) | `filter_required` | its only semantics |
| A set of *unacceptable* values | `filter_blocklist` | as many disjoint groups as you like, since they AND together |
| Numeric threshold on a **spec** (RAM, storage, mileage) | neither — see §5 | no rule compares a parsed spec; every number any rule reads is a price |

Note the asymmetry that makes §5 work: **`filter_blocklist` is not limited to one group.**
Every blocklisted phrase is an independent "and not this", so exclusions can encode several
conditions at once, while inclusions can encode only one.

## 5. Worked example — "M3 Pro or better, ≥32GB, ≥1TB"

Three conditions, each a set membership:

1. chip ∈ {M3, M4, M5} × {Pro, Max}
2. RAM ≥ 32 GB
3. storage ≥ 1 TB

That is three AND-ed OR-groups against a budget of one. **It is not exactly expressible.**
The approximation flips two of them into exclusions, which the blocklist can hold together:

- **Chip → `filter_required`.** It needs adjacency (§3.1), which only stage 2 provides, so
  it must take the single positive group.
- **RAM → `filter_blocklist`.** For a Pro/Max chip the only sub-32 options are 16, 18 and
  24 GB, all substring-safe. (8 GB is *not* safe — `8gb` ⊂ `48gb` — but no Pro/Max ships
  with 8 GB, so it never needs listing.)
- **Storage → `filter_blocklist`.** Sub-1TB means 256 and 512 GB, both substring-safe.
- **`"macbook air"` → `filter_blocklist`.** No Air has ever shipped a Pro or Max chip, so
  any Air matching a chip term is matching it in prose ("cheaper than an M5 Pro"). Measured
  cost: zero legitimate rejections (§5.3).

**This approximation fails open, not closed.** An ad that never states its RAM or storage
passes both exclusions. That is the right direction for deal-hunting — a missed rejection
costs one glance, a wrong rejection costs the find — but it is an approximation, not the
condition. It also mis-rejects an ad that mentions a smaller number incidentally
("upgradováno z 512GB").

### 5.1 The row

```python
# python manage.py shell
from bazos.models import Query, Category, Marketplace
from senders.models import Discord

Query.objects.create(
    marketplace=Marketplace.BAZOS,
    category=Category.objects.get(pk=191),        # Notebooky
    text="macbook m3 OR macbook m4 OR macbook m5",  # 38 chars; site-wide this is 221 ads vs 1 627 for "macbook"
    price_lower=15_000, price_upper=200_000,      # floor cuts cases/chargers/parts; no real Pro/Max sits below it
    filter_required=[                             # the one OR-group: chip tier, needs adjacency
        "m3 pro", "m3pro", "m3 max", "m3max",
        "m4 pro", "m4pro", "m4 max", "m4max",
        "m5 pro", "m5pro", "m5 max", "m5max",
    ],
    filter_blocklist=[                            # exclusions AND together, so two conditions fit
        "16gb", "16 gb", "18gb", "18 gb", "24gb", "24 gb",       # RAM < 32
        "256gb", "256 gb", "512gb", "512 gb", "256ssd", "512ssd",  # storage < 1TB
        "macbook air",                                            # no Air has a Pro/Max chip
    ],
    filter_rule_names=[],                         # empty = all rules
    sender=Discord.objects.get(pk=3),             # bazos-alert (notify=True)
    new_query=True,
    ignore_first_run=False,                       # backfill IS sent — you want today's market, up to NEW_PRODUCT_LOAD_MAX=50
    load_full_description=True,                   # enriches the archive; does NOT affect filtering (§3.2)
    enabled=True,
)
```

`text` deliberately does **not** carry the chip tier: `macbook m3` is `macbook AND m3`,
which by §2 also matches every base-M3 MacBook Pro. It is a volume pre-narrow only
(221 site-wide against 1 627 for bare `macbook`); the tier is decided in stage 2.

### 5.2 Validated against the corpus

Replayed over the 2 038 Bazos MacBook ads of 2026-05-17 → 08-23:

| | |
|---|---|
| matched the chip tier (`filter_required`) | 108 |
| of those, excluded by `filter_blocklist` | 78 |
| **delivered** | **30 — about 2.1/week** |
| **wrongly rejected** (real RAM ≥32 *and* storage ≥1TB) | **0** |
| wrongly delivered | 1 |

The single leak is `MacBook Pro 14” M5 Pro 24/2TB` — 24 GB written as `24/2TB`, so no
`24gb` substring exists to block. Slash notation is not worth chasing: `24/` would also
match `24/7` and date strings, and per §5 a false pass costs one glance while a false
rejection costs the find.

Before `"macbook air"` was added the count was 32 with three leaks, two of them M5 **Airs**
matching `m5 pro` in their description prose. Adding it removed exactly those two and
nothing else.

### 5.3 What would make it exact

A numeric rule. `Ad` already stores a parsed `price`, but RAM, storage and chip live only
in free text — the extraction exists offline
([`MACBOOK_PRICE_MODEL.md`](research/MACBOOK_PRICE_MODEL.md) §2), and no rule compares them.

*Updated 2026-09-18 - "never persisted" is no longer true, but nothing reads them either.*
Two tables now hold extracted specs: `AdPriceScore.features` (migration `0041`) stores the
parsed inputs a prediction was made from, and `AdSpecExtraction` (migration `0049`) stores what
an LLM read out of an ad's prose. Neither is a filter input. `features` exists only for ads a
registered model claimed - one product, `macbook` - and `AdSpecExtraction` **ships inert**, so
the gap is no longer "the numbers are not stored" but "nothing compares them, and coverage
equals scoring coverage". Landing a threshold rule over those would turn all three conditions
into real comparisons and free the `filter_required` group for something else. Until then
the §5 approximation is the honest ceiling.
