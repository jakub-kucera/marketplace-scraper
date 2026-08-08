# Database Backups — Options & Recommendation

> **Question:** the Postgres archive is the only asset in this project that can't be
> rebuilt ([`MONETIZATION.md`](MONETIZATION.md) §7.3). What are the options for dumping it,
> where should the dumps go, and what does it cost?
>
> **Status of claims:** repo facts (compose config, deploy path, `.gitignore`, absence of any
> backup mechanism) are read from the code on 2026-08-08. Sizes marked *measured* come from
> `postgres_data/` and `data_export_23_3_2024/` on the dev machine; growth projections are
> **estimates** derived from those measurements and are labelled as such. No `pg_dump` was run
> against the production Pi — the numbers in §3 are projections, not observations.

---

## 1. TL;DR

- **There is no backup of any kind today.** No `pg_dump`, no snapshot, no cron, no
  off-host copy. Zero mentions of backup/restore across `docs/`, `README.md`, `deploy.sh`,
  or `docker-compose.yml`. The only copies of the archive are the live `postgres_data/`
  bind mount on the Pi and a **2.5-year-stale** CSV export (`data_export_23_3_2024/`).
- **The host makes this worse than average.** Production is a **Raspberry Pi** (`README.md`
  §Deployment) running Postgres on local storage. SD-card wear-out is the single most common
  Pi failure mode, and it fails *without warning and unrecoverably*. This is not a
  hypothetical risk profile.
- **This directly contradicts the project's own stated priority.** `MONETIZATION.md` §7.3
  argues the archive is the only compounding asset and *"cannot be rebuilt at any price"*
  because Bazos deletes itself every ~60 days — while it sits unbacked on one SD card.
  §8 Phase 0 ("hygiene, do regardless") doesn't mention backups either. **This doc closes
  that gap.**
- **It is absurdly cheap to fix.** The whole database is **83 MB on disk** (measured) and the
  dominant table compresses **3.1×** (measured). A nightly compressed dump is single-digit
  MB, and even the broad category-sweep future is well under 1 GB/year (§3). Off-host storage
  costs **cents per month**.
- **Recommendation (§8): nightly `pg_dump -Fc` from a compose sidecar → `restic` to
  Backblaze B2**, 7 daily / 4 weekly / 6 monthly retention, plus a quarterly restore test.
  ~2 hours to build. Everything else in this doc is the reasoning for that choice.
- **One non-obvious constraint: backups fight the retention policy.** The DB holds seller
  emails and phone numbers. `MONETIZATION.md` §6.1 wants contact identifiers purged at 6
  months — but a purge that doesn't reach the backups isn't a purge (§7). Decide retention
  and encryption *before* the first dump lands in a bucket, not after.

---

## 2. Current state (read from the repo, 2026-08-08)

**What exists:**

| Thing | Reality |
|---|---|
| `docker-compose.yml` `postgres` service | `postgres:15.2`, volume `./postgres_data:/var/lib/postgresql/data` — a **bind mount inside the repo dir** |
| `postgres_data/` (dev machine) | **83 MB** total, `base/` 50 MB, `PG_VERSION` = 15 *(measured)* |
| `data_export_23_3_2024/` | 19 CSVs, 10 MB, **16,987 ads**, 2023-06-04 → 2024-03-23. A one-off manual export |
| `deploy.sh` / `.github/workflows/deploy.yml` | Stop services → git pull → migrate → restart. **No dump step before migrations** |
| `.gitignore` | `postgres_data/` and `/data_export_23_3_2024/` both ignored; neither is tracked — correct, but it means git is not a copy |

**What does not exist:** any `pg_dump`, `pg_basebackup`, `manage.py dumpdata`, WAL
archiving, volume snapshot, cron entry, systemd timer, backup container, or off-host
replica. `grep -rni "backup\|pg_dump\|dumpdata\|restore"` over `docs/` and `*.md` returns
nothing.

**Note on the deploy path:** the workflow runs migrations against production with no dump
taken first. A bad migration is a *more likely* data-loss event than hardware failure,
because it happens on purpose, on a schedule, every release (§4).

---

## 3. What's at risk, and how big it is

### 3.1 Threat model

| Failure | Likelihood on this setup | Does a nightly dump help? |
|---|---|---|
| SD-card / disk wear on the Pi | **High** over multi-year runtime; the dominant Pi failure mode | ✅ only if the dump is **off-host** |
| Bad migration in the deploy workflow | **Moderate** — automated, runs every release, no pre-dump | ✅ (and a pre-deploy dump helps more, §8) |
| `docker compose down -v` / accidental `rm -rf postgres_data` | Moderate — it's a plain directory in the working tree | ✅ off-host or on-host both work |
| Postgres corruption / unclean shutdown (power cut on a Pi) | Moderate | ✅ logical dump is immune to page-level corruption |
| Theft/fire/loss of the Pi | Low | ✅ only if off-host |
| Ransomware/compromise | Low | ✅ only with **immutable or append-only** remote storage |

The column that matters is the third one: **an on-host dump only protects against three of
six**, and the two highest-likelihood rows both need the copy to leave the Pi. That single
observation is what makes "off-host destination" (§6) non-optional rather than a refinement.

### 3.2 Size, measured and projected

*Measured:*

| Item | Size |
|---|---|
| `postgres_data/` total | 83 MB |
| `postgres_data/base/` | 50 MB |
| `bazos_ad.csv` (16,987 ads) | 8.85 MB → **2.86 MB gzipped** = **3.1× compression** |
| Per-ad, CSV | ~520 B uncompressed, ~170 B compressed |

*Projected (estimates, not measured):*

| Scenario | New ads/yr | Compressed growth/yr |
|---|---|---|
| Today's ~6–12 narrow queries | ~20,000 | **~4 MB** |
| Broad category sweep, busy scope (~3,000 new/day, per `proxies/PROXY_ROTATION_RESEARCH.md` §5.2) | ~1.1M | **~190 MB** |

**Takeaway:** even the aggressive future is **under 1 GB/year compressed**. Storage cost is
irrelevant to the decision; pick on restore ergonomics and operational simplicity, not size.

⚠️ **One caveat that would change this:** `full_description` is populated on **0** of 16,987
ads today (`MONETIZATION.md` §2.2). If detail-fetching is turned on broadly, per-ad size grows
several-fold. Still small in absolute terms, but re-check the projection then rather than
assuming it holds.

---

## 4. The dump options

The core question. Ordered roughly by how well they fit *this* deployment.

### A. `pg_dump -Fc` — custom format ✅ *recommended*

```bash
pg_dump -Fc -Z6 -d "$POSTGRES_DB" -f scraper-$(date +%F).dump
```

A single compressed binary file, restored with `pg_restore`. Internally compressed, so no
separate gzip step.

- **Consistency:** a single transaction snapshot — consistent without stopping the services.
- **Size:** ~3× smaller than plain SQL (matches the measured 3.1× on the ad table).
- **Restore granularity:** the reason to prefer this format — `pg_restore -t bazos_ad` restores
  **one table**, `-l`/`-L` reorders or filters objects, `--data-only` reloads rows into an
  existing schema. Recovering "just the ads I lost to a bad migration" without flattening the
  whole database is exactly the common case here.
- **Portability:** Postgres-only, version-sensitive in one direction — a dump from PG 15
  restores into 15 or later, **not** into an earlier major version. Pin the client version to
  the server's (use the `postgres:15.2` image itself, §5).
- **Cost:** one file per night, trivially rsyncable.

### B. `pg_dump -Fp` — plain SQL

```bash
pg_dump -Fp -d "$POSTGRES_DB" | gzip > scraper-$(date +%F).sql.gz
```

- **Pro:** human-readable and greppable; restores with plain `psql`, no `pg_restore`; diffs
  usefully between days; survives a future where you have no matching PG binaries.
- **Con:** all-or-nothing restore (no selective table extraction without hand-editing an 8 MB
  SQL file), and larger before compression.
- **Verdict:** keep as a *secondary* monthly artifact if you want a maximally future-proof
  copy. Not the primary.

### C. `pg_dumpall` — cluster-wide

Captures **roles, passwords, and tablespaces** that per-database dumps omit, plus every
database. Here there is one application database and roles come from `.env`, so it adds little
— but `pg_dumpall --globals-only` is a tiny, useful companion file if you ever want a
one-command bare-metal rebuild.

### D. `manage.py dumpdata` — Django-level JSON

```bash
python manage.py dumpdata bazos senders --natural-foreign -o dump.json
```

- **Pro:** engine-independent (restores into SQLite for local analysis), schema-aware via
  Django, and it's what a notebook actually wants to consume. Nicely complements the
  `data_export_23_3_2024/` CSV habit.
- **Con:** **not a disaster-recovery tool.** Slow and memory-hungry on large tables (it
  serializes through Python objects), no transactional snapshot guarantee across the run, and
  `loaddata` restores are far slower than `pg_restore`. It also silently depends on the models
  matching the data.
- **Verdict:** valuable as a **portable analysis export**, not as the backup. Run it monthly
  if you want; don't rely on it.

### E. Cold filesystem copy of `postgres_data/`

Stop the container, `tar` the directory, restart.

- **Pro:** simplest possible mental model; a byte-exact restore.
- **Con:** requires **downtime** (a copy taken while Postgres is running is inconsistent and
  may be unrestorable); the result is tied to the exact PG major version *and* architecture;
  and it's ~8× larger than a compressed dump for the same content.
- **Verdict:** no. It's strictly worse than A on this workload. The one exception is a
  filesystem-level snapshot (LVM/btrfs/ZFS) taken atomically — not available on a stock Pi
  setup.

### F. PITR — `pg_basebackup` + WAL archiving

Continuous archiving; restore to any point in time.

- **Pro:** the only option with a **recovery point objective near zero** — recover to the
  second before a bad `DELETE`, rather than losing up to 24 hours.
- **Con:** materially more machinery — `archive_command`, a WAL destination that must never
  fill, base backups on a schedule, and a restore procedure you must actually rehearse. On a
  Pi with SD-card I/O, continuous WAL shipping is also real sustained write load.
- **Verdict:** **overkill here, and the reason is the workload, not laziness.** Losing up to
  24 h of scraped listings costs one re-scrape of a market that's still live; it isn't
  financial-transaction data. Revisit only if the archive ever becomes a product (`MONETIZATION.md`
  §4.6), where a 24 h hole in a price index is a defect rather than a nuisance.

### G. Move Postgres to a managed host

Neon / Supabase / RDS — backups and PITR become someone else's job.

- **Pro:** removes the whole problem; free tiers exist at this data size.
- **Con:** the scraper and DB stop being co-located, so every pipeline stage takes a network
  round-trip per query from a home connection; adds an external dependency and an account; and
  it puts seller PII on a third-party processor, which drags in `MONETIZATION.md` §6.5
  (controller/processor terms). Contradicts the "keep the data inside your own hands"
  posture that §3 of that doc says sorts the entire option list.
- **Verdict:** no — but worth naming, because it's the option that makes this doc unnecessary,
  and it's the right answer for a hypothetical future product deployment.

### H. Streaming replica on a second machine

- **Pro:** near-zero RPO *and* a warm standby.
- **Con:** needs a second always-on host; and it faithfully replicates a bad migration or a
  `DELETE` in seconds — **replication is not a backup**, it's availability. Would need A
  alongside it anyway.
- **Verdict:** no, for a single-Pi hobby deployment.

### Comparison

| | Consistent w/o downtime | Selective restore | Engine-portable | Size | Ops burden |
|---|---|---|---|---|---|
| **A · `pg_dump -Fc`** | ✅ | ✅ per-table | ❌ PG only | **smallest** | **low** |
| B · `pg_dump -Fp` | ✅ | ❌ | ~ (SQL, PG dialect) | small | low |
| C · `pg_dumpall` | ✅ | ❌ | ❌ | small | low |
| D · `dumpdata` | ❌ | ✅ per-app | ✅ | medium | low |
| E · cold copy | ❌ needs stop | ❌ | ❌ version+arch | large | low |
| F · PITR | ✅ | ✅ point-in-time | ❌ | medium | **high** |
| G · managed | ✅ | ✅ | ❌ | n/a | none (but §6.5) |
| H · replica | ✅ | ❌ | ❌ | n/a | high |

---

## 5. Where to run it

Three options, given the Pi already runs systemd (`deploy.sh` drives
`marketplace-docker.service`) and Docker Compose:

1. **Compose sidecar** ✅ *recommended* — a `backup` service built from `postgres:15.2` (the
   same image, so client and server versions match by construction), running a loop or invoked
   by the host scheduler. Inherits `env_file: .env`, so credentials aren't duplicated. Its
   lifecycle is described in the same file as everything else, which matters when the Pi is
   re-provisioned.
2. **Host cron / systemd timer** — simplest, but needs a `postgres-client-15` install on the
   Pi and a second copy of the DB credentials outside `.env`. Version skew between host client
   and container server is a real trap on a long-lived Pi.
3. **A `Job` in the future job queue** (`refactor/JOB_QUEUE_DESIGN.md`) — ❌ deliberately not.
   Backups must keep working when the application is broken; coupling them to the app's own
   worker means an app that won't start also stops backing up. Same reasoning `PROMPTS.md` P24
   step 5 uses to keep `check_delisted` out of the `Job` model for now.

**Also add a pre-deploy dump.** Per §3.1, a bad migration is the most likely loss event, and
`.github/workflows/deploy.yml` currently runs migrations with no dump first. One `pg_dump -Fc`
step before `migrate`, kept for a few releases, converts the scariest routine operation into a
reversible one. This is arguably higher value per line than the nightly job.

---

## 6. Where the dumps go

On-host only protects against 3 of the 6 failures in §3.1 — the copy has to leave the Pi.

| Destination | Cost at <1 GB | Notes |
|---|---|---|
| **Backblaze B2** ✅ | **~$0.006/GB/mo** — effectively free; 10 GB free tier | S3-compatible, works with `restic`/`rclone`. Cheapest credible option |
| Cloudflare R2 | Free tier 10 GB, **no egress fees** | Good if restores might be large/frequent |
| AWS S3 (+ Glacier IR) | ~$0.023/GB/mo | Fine, more account overhead than it's worth here |
| Another machine on the LAN (`scp`/`rsync`) | free | ⚠️ Does **not** cover fire/theft, and tends to rot silently — no one notices when it stops |
| A repo/GitHub | — | ❌ Never. PII in git history is unremovable in practice (§7) |

**Tooling:** prefer **`restic`** over raw `rclone copy` — it gives deduplication (consecutive
dumps of a mostly-append-only DB dedupe extremely well), **client-side encryption by default**
(which §7 requires), integrity verification via `restic check`, and `forget --prune` implements
the retention policy in one command. `borg` is equivalent but weaker on cloud backends.

---

## 7. Retention, PII, and encryption — read before the first dump

This is the part that's easy to get wrong permanently.

- **Backups defeat retention policies.** `MONETIZATION.md` §6.1 commits to purging contact
  identifiers at ~6 months to mirror Bazos's own policy. If dumps are kept for 2 years, the
  emails and phone numbers you "purged" still exist in 24 monthly archives. Under GDPR the
  backup copy is still processing. **Set backup retention ≤ the PII retention window, or
  strip PII from the dumps.**
- **Concretely:** cap retention at **7 daily / 4 weekly / 6 monthly** (≈6 months, matching
  §6.1's number) rather than keeping monthlies forever. If you later want a *long*-horizon
  archive for the §7.3 compounding-asset argument, take that as a **separate, PII-stripped
  export** (listing facts only — title, price, category, locality, timestamps) with unlimited
  retention. Two different artifacts with two different policies, because they answer two
  different questions.
- **Encrypt at rest off-host.** `restic` does this by default. Store the repo password in a
  password manager, **not** in `.env` on the Pi — an attacker with the Pi shouldn't inherit the
  backup history.
- **`facebook/` app interaction:** `MONETIZATION.md` §6.1 says delete the `FBUser` model and
  importer. Verified empty everywhere checked — but if it were ever populated, dropping the
  table would **not** remove it from existing backups. Do the deletion **before** starting a
  backup rotation, so the question never arises.

---

## 8. Recommendation

1. **Nightly `pg_dump -Fc -Z6`** from a `backup` compose sidecar built on `postgres:15.2`,
   writing to `./backups/` on the Pi. *(~30 min)*
2. **`restic` to Backblaze B2** immediately after each dump, encrypted, with
   `forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`. *(~45 min)*
3. **Add a pre-`migrate` dump step** to `.github/workflows/deploy.yml`, retained for the last
   few releases. *(~15 min — highest value per line, see §5)*
4. **Alert on failure.** A silent backup failure is indistinguishable from a working one —
   the exact pathology `PROMPTS.md` P19 identifies in the scraper. Reuse the existing
   `Discord(for_logging=True)` channel: post on failure, and post a weekly "last good backup:
   <date>, <size>" heartbeat so silence is itself informative. *(~20 min)*
5. **Test one restore into a throwaway container**, and write the exact commands into this
   doc's §9. An untested backup is a hypothesis. Re-test quarterly. *(~30 min)*
6. **Optional:** monthly `manage.py dumpdata` + `pg_dumpall --globals-only` as portable
   secondary artifacts (§4 D/C).

**Total ~2 hours**, ~$0/mo at current size. Given §3.1's threat model and a 2.5-year-stale
last-known-good copy, this outranks every feature item in
[`refactor/PROMPTS.md`](refactor/PROMPTS.md) on expected value — not because it's important
work, but because the downside it removes is total and irreversible, and the cost is two
hours.

---

## 9. Restore procedure

⚠️ **Not yet written — this section is the deliverable of §8 step 5.** It must contain the
literal, copy-pasteable commands, verified against a real restore, not a sketch. Placeholder
shape:

```bash
# 1. Spin up a throwaway PG 15 instance (NOT the production compose stack)
# 2. pg_restore -d <scratch_db> --clean --if-exists scraper-YYYY-MM-DD.dump
# 3. Verify: row counts for bazos_ad / bazos_query / bazos_queryrun vs. expectations
# 4. Selective case: pg_restore -d <db> -t bazos_ad --data-only <dump>
```

Fill this in the first time it's actually run.

---

## 10. Open questions

- **Is the Pi on an SD card or a USB SSD?** Changes the likelihood of the top row in §3.1 by
  roughly an order of magnitude — but not the recommendation.
- **How big is the *production* database really?** The 83 MB in §2 is the dev machine. The Pi's
  is the one that matters and hasn't been measured. Run `du -sh postgres_data/` and one
  `pg_dump -Fc` there to replace §3.2's projections with observations.
- **Is `data_export_23_3_2024/` (Mar 2024) actually the newest full copy?** If production has
  been running since, there is 2+ years of unbacked data — which would make this considerably
  more urgent than §8's calm tone implies.
- **Should the long-horizon PII-stripped archive (§7) be its own management command?** It's
  close to what `MONETIZATION.md` §4.6 (derived-statistics products) would need anyway, so
  there may be one artifact serving both.

---

**Related docs:** [`MONETIZATION.md`](MONETIZATION.md) §7.3 (the archive as the only
compounding asset), §6.1/§6.5 (retention and GDPR constraints on what may sit in a dump);
[`refactor/JOB_QUEUE_DESIGN.md`](refactor/JOB_QUEUE_DESIGN.md) (why backups deliberately stay
outside it, §5); [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P19 (the silent-failure pattern
§8 step 4 avoids repeating).
