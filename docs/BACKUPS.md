---
title: Database Backups — Options & Recommendation
status: shipped
updated: 2026-08-16
verified: 2026-08-23
shipped_in: 1cb0178 (backup/, systemd timer, pre-migration dump in deploy.yml)
---

# Database Backups — Options & Recommendation

> **Question:** the Postgres archive is the only asset in this project that can't be
> rebuilt ([`MONETIZATION.md`](MONETIZATION.md) §7.3). What are the options for dumping it,
> where should the dumps go, and what does it cost?
>
> **Provenance of claims:** repo facts (compose config, deploy path, `.gitignore`, absence of any
> backup mechanism) are read from the code on 2026-08-08. Sizes marked *measured* come from
> `postgres_data/` and `data_export_23_3_2024/` on the dev machine; growth projections are
> **estimates** derived from those measurements and are labelled as such. No `pg_dump` was run
> against the production Pi — the numbers in §3 are projections, not observations.

---

## 1. TL;DR

- ✅ **Implemented 2026-08-15** (§8). Everything below §2 is written in the present tense of
  *before* that — it is the reasoning that produced the design, kept because the trade-offs
  still explain why the thing looks the way it does. **One step remains: creating the B2 bucket
  and setting `RESTIC_REPOSITORY`.** Until that is done the dumps never leave the Pi, which
  covers only 3 of the 6 failures in §3.1.
- **There was no backup of any kind before that.** No `pg_dump`, no snapshot, no cron, no
  off-host copy. Zero mentions of backup/restore across `docs/`, `README.md`, `deploy.sh`,
  or `docker-compose.yml`. The only copies of the archive were the live `postgres_data/`
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

## 2. State before this doc (read from the repo, 2026-08-08)

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

**Note on the deploy path:** the workflow ran migrations against production with no dump
taken first. A bad migration is a *more likely* data-loss event than hardware failure,
because it happens on purpose, on a schedule, every release (§4). ✅ Fixed — `deploy.yml` now
dumps before `migrate` and aborts the deploy if the dump fails.

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

1. **One-shot compose container, scheduled by a systemd timer** ✅ *chosen* — the two options
   below turn out not to be exclusive, and the combination avoids the drawback of each.
   The container is a `backup` service built from `postgres:15.2` (same image, so client and
   server versions match by construction) that dumps and **exits**; `backup/systemd/` holds a
   timer that runs `docker compose run --rm backup` nightly. Credentials still come from
   `env_file: .env`, and no Postgres client is installed on the host, so option 2's objections
   don't apply. The service sits behind a compose `profiles:` key so `docker compose up -d`
   never starts it.
   - ⚠️ **`docker compose build` skips profiled services.** `deploy.yml` therefore builds with
     `--profile backup`; without it the backup image silently never updates.
2. **Long-running sidecar with an internal sleep loop** ❌ — the obvious way to do #1 with no
   host state, and what this doc originally recommended. Rejected on reflection: it is a
   hand-rolled scheduler with **no catch-up**, so a Pi that is rebooting or mid-deploy at 03:30
   simply skips that night and nothing reports it. `Persistent=true` on a systemd timer runs
   the missed backup on next boot instead. Resource cost was *not* the reason — measured at
   1.1 MiB RSS and 0% CPU idle, with ~32 MB of image layers on top of the `postgres:15.2` the
   Pi already has.
3. **Host cron with a host-installed `pg_dump`** ❌ — needs `postgres-client-15` on the Pi and
   a second copy of the DB credentials outside `.env`. Version skew between host client and
   container server is a real trap on a long-lived Pi. This is the option #1 replaces by
   keeping the client in the container and letting the host only *schedule*.
4. **A `Job` in the future job queue** (`refactor/JOB_QUEUE_DESIGN.md`) — ❌ deliberately not.
   Backups must keep working when the application is broken; coupling them to the app's own
   worker means an app that won't start also stops backing up. Same reasoning `PROMPTS.md` P24
   step 5 uses to keep `check_delisted` out of the `Job` model for now.

**Also add a pre-deploy dump.** ✅ Done. Per §3.1, a bad migration is the most likely loss
event, and `.github/workflows/deploy.yml` used to run migrations with no dump first. One
`pg_dump -Fc` step before `migrate`, kept for the last 5 releases, converts the scariest
routine operation into a reversible one. This is arguably higher value per line than the
nightly job. It is independent of the timer above — it runs inside the deploy, so it works
whether or not the timer is installed.

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

**Tooling:** prefer **`restic`** over raw `rclone copy` — **client-side encryption by default**
(which §7 requires), integrity verification via `restic check`, deduplication across nights, and
`forget --prune` implements the retention policy in one command. `borg` is equivalent but weaker
on cloud backends.

### 6.1 Dedup only works if `pg_dump` does *not* compress

⚠️ This determines a flag in §8 and was measured, not assumed (2026-08-15, restic 0.17.3,
a 53 MB table, one night's delta ≈ 2,000 new ads):

| dump flag | night 1 stored | night 2 stored | repo after 2 nights |
|---|---|---|---|
| **`-Z0`** (restic compresses) | 14.7 MiB | **5.5 MiB** | **22 MB** |
| `-Z6` (pg_dump compresses) | 15.3 MiB | **15.5 MiB** | **32 MB** |

`pg_dump`'s own compression produces a different byte stream every night even when the data
barely moved, so restic's content-defined chunking finds nothing in common and re-uploads the
whole dump — visible above as night 2 costing full price. Dumping **`-Z0`** and letting restic
apply its own zstd gets compression *and* dedup instead of one or the other, and the gap widens
every night.

Two caveats on that table. Restic's chunker averages ~1 MiB, so a dump **smaller than a few MB
is a single chunk** and dedups not at all regardless of flags — the effect only appears at real
database size. And this reverses for the pre-deploy dumps in §5: those stay on the Pi and never
reach restic, so there `-Z6` is a pure win.

### 6.2 Closing the ransomware row in §3.1

§3.1 lists compromise as covered only by **immutable or append-only** storage — but `forget
--prune` needs delete rights, so the Pi holds credentials that can erase the backup history
along with the live DB. Either:

- **B2 Object Lock** (governance mode), or a lifecycle rule retaining prior versions ~30 days,
  so deletes are soft; or
- **split the keys** — a write-only application key on the Pi, and run `forget --prune`
  occasionally from a laptop with a separate key.

Either is sufficient at this scale. Neither is done by default, so it is a deliberate choice
to make, not something the §8 setup gives you.

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
- **Encrypt at rest off-host.** `restic` does this by default. Keep the repo password in a
  password manager — **because losing it makes every backup permanently unreadable**, which is
  the failure this actually defends against. An unattended nightly job necessarily has the
  password on the Pi, so "keep it off the Pi" is not achievable; limit what a compromised Pi can
  *destroy* via §6.2 instead of pretending the password isn't there.
- **`facebook/` app interaction:** `MONETIZATION.md` §6.1 says delete the `FBUser` model and
  importer. Verified empty everywhere checked — but if it were ever populated, dropping the
  table would **not** remove it from existing backups. Do the deletion **before** starting a
  backup rotation, so the question never arises.

---

## 8. Recommendation

**Implemented on 2026-08-15** — `backup/Dockerfile`, `backup/backup.sh`,
`backup/systemd/`, the profiled `backup` service in `docker-compose.yml`, and the
*Pre-migration backup* step in `.github/workflows/deploy.yml`.

1. ✅ **Nightly `pg_dump -Fc -Z0`** from a one-shot `backup` container built on `postgres:15.2`,
   writing to `./backups/` on the Pi. `-Z0`, not `-Z6` — see §6.1. Scheduled by a systemd timer
   with `Persistent=true`, not a sleep loop — see §5. **Installing the timer is a manual step on
   the Pi** (`backup/systemd/README.md`); until it is installed, only the pre-deploy dump runs.
2. ✅ **`restic`** immediately after each dump, encrypted, with
   `forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`. Off-host is **opt-in at
   runtime**: with `RESTIC_REPOSITORY` empty the backup still takes and rotates local dumps and
   logs that nothing left the host, so it can ship before a B2 account exists.
   **Creating the B2 bucket and setting the credentials is still outstanding** —
   until then this covers only 3 of the 6 failures in §3.1.
3. ✅ **Pre-`migrate` dump** in `deploy.yml`, last 5 releases retained. A failed dump aborts the
   deploy — that is the point. *(Highest value per line, see §5.)*
4. ✅ **Alert on failure**, plus a Monday heartbeat so silence is itself informative — the
   pathology `PROMPTS.md` P19 identifies in the scraper. Via `BACKUP_DISCORD_WEBHOOK_URL`
   (falling back to `DISCORD_LOGGER_WEBHOOK_URL`), **not** the `Discord(for_logging=True)` row
   this doc originally suggested: an alert that has to read Postgres cannot report that Postgres
   is broken.
5. ✅ **Restore tested** end to end against throwaway containers; verified commands in §9.
   Re-test quarterly.
6. ⬜ **Optional:** monthly `manage.py dumpdata` + `pg_dumpall --globals-only` as portable
   secondary artifacts (§4 D/C).

**Not yet decided:** §6.2 (immutability) is unaddressed — the Pi's credentials can currently
delete the backup history.

**Total ~2 hours**, ~$0/mo at current size. Given §3.1's threat model and a 2.5-year-stale
last-known-good copy, this outranks every feature item in
[`refactor/PROMPTS.md`](refactor/PROMPTS.md) on expected value — not because it's important
work, but because the downside it removes is total and irreversible, and the cost is two
hours.

---

## 9. Restore procedure

Verified 2026-08-15 against throwaway `postgres:15.2` containers (arm64, same as the Pi), on a
252,000-row dataset. Every command below was run; the row counts are real output.

**Never restore into the production database as the first step.** Restore into a scratch
database, verify counts, then decide.

### 9.1 Get a dump file

Local copies are in `./backups/` (nightly) and `./backups/pre-deploy/` (per release). If the Pi
is gone, pull one out of restic instead:

```bash
export RESTIC_REPOSITORY=... RESTIC_PASSWORD=...
restic snapshots                                  # pick one
restic restore <short_id> --target /tmp/restored  # dump lands under /tmp/restored/backups/
```

Pre-deploy dumps are `-Z6` compressed and nightly ones are `-Z0`; `pg_restore` reads both with
no extra step.

### 9.2 Full restore into a scratch database

```bash
docker compose up -d postgres
docker compose exec postgres psql -U "$POSTGRES_USER" -c "CREATE DATABASE scratch;"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d scratch \
    --clean --if-exists --no-owner < ./backups/scraper-YYYY-MM-DD-HHMMSS.dump
```

Verify before trusting it:

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d scratch -c \
  "select (select count(*) from bazos_ad)  as ads,
          (select count(*) from bazos_query) as queries,
          (select count(*) from bazos_queryrun) as runs,
          (select max(created) from bazos_ad) as newest_ad;"
```

`newest_ad` is the one that matters — it tells you how much you actually lost.

### 9.3 Selective restore — the bad-migration case

Recovering one table without flattening the database is the reason for `-Fc` (§4 A):

```bash
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -t bazos_ad -t bazos_ad_id_seq --data-only --no-owner < ./backups/<dump>
```

⚠️ **`-t bazos_ad` alone is a trap.** `--data-only` restores rows but *not* the sequence, so the
sequence stays where it was and the scraper's next insert dies:

```
ERROR:  duplicate key value violates unique constraint "bazos_ad_pkey"
DETAIL:  Key (id)=(1) already exists.
```

Naming the sequence in a second `-t` (above) fixes it. If you already restored without it:

```sql
SELECT setval(pg_get_serial_sequence('bazos_ad','id'), (SELECT MAX(id) FROM bazos_ad));
```

Both were tested; both leave `last_value` = `max(id)` and inserts working. The table must be
emptied first (`DELETE FROM bazos_ad;`) — `--data-only` appends and will collide otherwise.

### 9.4 Check the backups without restoring

```bash
sudo systemctl start marketplace-backup.service      # force a backup now
systemctl list-timers marketplace-backup.timer       # when is the next one
journalctl -u marketplace-backup -n 50 --no-pager    # what happened last time
docker compose run --rm --entrypoint restic backup check   # repo integrity
```

⚠️ Watched-for failure mode: `restic backup` exits **3** when a source file can't be read but
**still saves a snapshot** — an empty one. `backup.sh` propagates that exit code so the Discord
alert fires, but if you ever run restic by hand, a "successful"-looking snapshot listing is not
proof the data is in it. `restic ls <id>` to be sure.

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
