---
title: Generic Job Queue — Exploration & Proposal
status: proposal
updated: 2026-07-26
verified: 2026-07-26
---

# Generic Job Queue — Exploration & Proposal

> **Nothing here has been built, and it is not scheduled.** Not wired into `PIPELINE_REFACTOR.md`'s stage list or
> `PROMPTS.md`. Nothing here has been built.
>
> **See also**: [`BACKLOG_IDEAS.md`](../backlog/BACKLOG_IDEAS.md) #8 (full-listing rescan flag) and
> [`DISCORD_BOT.md`](DISCORD_BOT.md) §2.1/§3.2 (`AdWatch`/`run_ad_watch`) — both
> already describe *new recurring processes* that would need their own docker-compose service
> and hand-rolled sleep loop under today's architecture. This doc is the response to "do we
> keep doing that per job type, or build one generic thing." `DISCOVERY_PIPELINE.md`
> (seller enrichment, repost detection) and `LLM_AD_REVIEW.md` (per-ad LLM judge) add
> further candidates — see §4.

## 0. The idea, as floated

Today, `run_scraper` (`bazos/management/commands/run_scraper.py`) is a single monolithic loop:
`ScrapeRunner.run()` (`runner.py:29-64`) iterates every enabled `Query` sequentially, sharing
one Tor session/`IPChanger` for the whole pass, then sleeps one shared interval
(`NightMultiplier`, `get_next_interval`) — interruptible only by a single global sentinel file
(`_interruptible_sleep`, `settings.FORCE_RUN_FLAG_PATH`). There is no persistence of individual
units of work beyond `QueryRun` (a metrics record, not a work item), no per-item retry/backoff,
no priority, no way to give one kind of work a different cadence than another.

`run_filter`/`run_sender` are already a step better — both poll a status column with
`select_for_update(skip_locked=True)` on a fixed interval (`FILTER_POLL_INTERVAL`,
`SENDER_POLL_INTERVAL`, `bazos/const.py`), and `run_sender` already has a real retry/backoff
counter (`Ad.send_attempts` vs. `MAX_SEND_ATTEMPTS`, `run_sender.py:47-59`). This is a real DB-
backed job queue in miniature — just scoped to one hardcoded status enum (`AdStatus`) and one
hardcoded piece of work (filter, send) per process.

Meanwhile, several already-written proposals each describe *another* new recurring or on-demand
background process, each of which would otherwise mean another hand-rolled sleep loop and another
`docker-compose.yml` service: `run_ad_watch` (`DISCORD_BOT.md` §2.1), a full-listing
rescan per opted-in query (`BACKLOG_IDEAS.md` #8), a sold/removed sweep
(`HIDDEN_API.md` §6.4a/§8), seller-reputation enrichment
(`DISCOVERY_PIPELINE.md` Stage 4), and more (§4). The idea: generalize the
`run_filter`/`run_sender` DB-queue pattern into an actual generic job system, so each of these
lands as a new *job type*, not a new *process*.

---

## 1. The architecture decision: how should scheduled/on-demand work run?

### 1.1 Baseline — what exists today, and what it's missing

| Have today | Missing |
|---|---|
| DB-status-column polling (`AdStatus`, `select_for_update(skip_locked=True)`) | Generalized to arbitrary work, not just filter/send |
| Retry counter (`Ad.send_attempts`/`MAX_SEND_ATTEMPTS`) | Backoff scheduling (retry *when*, not just *how many times*) |
| One shared interval + night multiplier (`NightMultiplier`) | Per-job-type cadence |
| One global force-run sentinel file | Per-job/per-query priority bump |
| One process per pipeline stage (`docker-compose.yml`: scraper/filter/sender) | A way to add a new job type without adding a new always-on service |

No task-queue library exists in `pyproject.toml` today (no Celery, no Redis, no django-q,
no APScheduler) — the only infrastructure is Postgres and Tor.

### 1.2 Option A — Generic `Job` model + registry + one `run_jobs` worker *(recommended)*

Extends a pattern this codebase already uses **three times**: a `Protocol` + name-keyed registry
(`MarketplaceScraper`/`_build_scrapers()`, `Sendable`, `RULE_REGISTRY`/`build_rule_engine`, see
`CLAUDE.md`'s "Adding a marketplace" coding pattern), plus the `select_for_update(skip_locked=True)`
DB-queue idiom already proven by `run_filter`/`run_sender`. Full design in §3.

**Why this is the front-runner**: zero new infrastructure (still just Postgres), the codebase
already has three working precedents for exactly this shape, and new `run_jobs` worker processes
can be scaled horizontally like `run_filter`/`run_sender` already are — so a new job *type* no
longer implies a new docker-compose *service*.

### 1.3 Option B — A Postgres-native queue library (e.g. `Procrastinate`, `django-q2`)

Same infrastructure footprint as A (still just Postgres — `Procrastinate` in particular is built
specifically around `LISTEN`/`NOTIFY` and has built-in periodic-task/cron support; `django-q2` is
ORM-backed with a Django-admin view for free), at the cost of a new dependency to learn and pin.
The trade-off against A: less code to own and battle-tested retry/scheduling semantics, but this
project's bespoke bits — the interruptible-sleep-with-force-run-flag pattern, `NightMultiplier`,
and the shared-Tor-session lock (§2) — would need to be fitted into someone else's executor model
rather than owned outright. Worth a real look if hand-rolling A turns out more fiddly than
expected, but not the first move.

### 1.4 Option C — Celery + Redis + Celery Beat

The industry-standard answer — mature priority/rate-limit support, Flower for monitoring, huge
ecosystem. Overkill *right now*: it adds a whole new broker service to `docker-compose.yml`
(today's stack has none) and a new failure mode ("broker down = nothing runs at all") for a
project whose total background-process count today is three. Worth revisiting only if job
volume/diversity grows enough that A's simplicity stops paying for itself — not a first step.

### 1.5 Option D — No new model: one process, N in-process schedules

Cheapest possible change: collapse job dispatch into a single Python process holding a min-heap of
`(next_run_at, job)` pairs (stdlib `sched`, or hand-rolled), running whichever is due. No schema
change, no migration. Loses persistence across restarts (an in-flight schedule resets to "now" on
crash — probably fine for most of the recurring jobs in §4, less fine for one-off/event-triggered
ones) and horizontal scaling (can't add worker replicas to share load). A reasonable stopgap if a
full `Job` model feels premature, or a way to validate the job catalog in §4 cheaply before
committing to A's schema.

### 1.6 Recommendation

**Option A.** It's the smallest true generalization of a pattern already proven three separate
times in this codebase, requires no new infrastructure, and directly solves the motivating
problem (§0): new job types stop requiring new docker-compose services. Keep B (`Procrastinate`)
in mind as the "stop hand-rolling this" escape hatch, and C (Celery) as the answer if job
volume/complexity outgrows A later — not before.

---

## 2. The blocker that applies no matter which option is picked

`IPChanger`/the shared `requests.Session` (one Tor circuit, created once in `ScrapeRunner.__init__`)
is not designed for concurrent callers — already flagged in `BACKLOG_IDEAS.md` idea #2:
*"needs either a lock around IP rotation or a stop-the-world, rotate, resume checkpoint model, not
concurrent races on the same circuit change."* The moment job dispatch stops being "one sequential
loop" — which A, B, and C all imply once `run_jobs` workers can run concurrently — any job type
that touches Bazos over that shared session needs mutual exclusion.

Concretely: give each job-type registry entry a `requires_bazos_session: bool` (§3.2). Job types
that set it (scrape pass, `AdWatch` recheck, full-rescan, seller-reputation `ratings.php` pull)
serialize through a single lock (a Postgres advisory lock, or simply constraining them to a
single-concurrency `run_jobs` worker/queue partition); job types that don't (interval-tuning
analysis, sold/removed bookkeeping once the network call is already made, taxonomy-sync
bookkeeping) run fully concurrent across as many `run_jobs` workers as are running. This is not
optional plumbing — it's the same problem idea #2 already identified, inherited by construction
by any of §1's options.

One naming note: don't call the new scheduling field `priority` in a way that collides with
`Query.priority` (`PIPELINE_REFACTOR.md` Stage 5) — that field controls Discord ping level
(`@here` or not), a completely different concept from job-dispatch ordering.

A more distant payoff worth flagging: job types that fan out internally to many small independent
calls (`AdWatch`'s bulk `ad_id[]=` recheck, seller-reputation `ratings.php` pulls) are exactly the
workload `BACKLOG_IDEAS.md` #2 already flagged as ideal for `asyncio`. A generic job system is a
natural place to eventually add that concurrency *inside* one job's execution, even while the
outer `run_jobs` dispatch loop stays synchronous — not a reason to block on idea #2 first.

---

## 3. The recommended design in detail (Option A)

### 3.1 `Job` model

```python
class JobStatus(models.TextChoices):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE    = "DONE"
    FAILED  = "FAILED"

class Job(TimeStampedModel):
    job_type = models.CharField(max_length=50, db_index=True)   # JOB_REGISTRY key
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(choices=JobStatus.choices, default=JobStatus.PENDING)
    priority = models.IntegerField(default=0)
    scheduled_at = models.DateTimeField(default=timezone.now)
    interval_seconds = models.IntegerField(null=True, blank=True)  # recurring if set
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=1)
    last_error = models.TextField(blank=True)
```

### 3.2 `JobHandler` protocol + registry

Same shape as `MarketplaceScraper`/`_build_scrapers()`:

```python
class JobHandler(Protocol):
    requires_bazos_session: bool
    def run(self, job: Job) -> None: ...

JOB_REGISTRY: dict[str, JobHandler] = {
    "scrape_query": ScrapeQueryJob(),
    "ad_watch_recheck": AdWatchRecheckJob(),
    "full_rescan": FullRescanJob(),
    # ...
}
```

Adding a job type means writing a handler and registering it here — never special-casing it in
`run_jobs`, mirroring `CLAUDE.md`'s existing "Adding a marketplace" rule.

### 3.3 `run_jobs` worker

Structurally identical to `run_filter.py`, generalized:

```python
while True:
    with transaction.atomic():
        jobs = list(
            Job.objects
            .select_for_update(skip_locked=True)
            .filter(status=JobStatus.PENDING, scheduled_at__lte=timezone.now())
            .order_by("-priority", "scheduled_at")[:JOB_BATCH_SIZE]
        )
        for job in jobs:
            handler = JOB_REGISTRY[job.job_type]
            try:
                handler.run(job)
                job.status = JobStatus.DONE
                if job.interval_seconds:
                    Job.objects.create(job_type=job.job_type, payload=job.payload,
                                        scheduled_at=timezone.now() + timedelta(seconds=job.interval_seconds),
                                        interval_seconds=job.interval_seconds)
            except Exception as e:
                job.attempts += 1
                job.last_error = str(e)
                job.status = JobStatus.FAILED if job.attempts >= job.max_attempts else JobStatus.PENDING
                job.scheduled_at = timezone.now() + backoff(job.attempts)  # mirrors MAX_SEND_ATTEMPTS idiom
            job.save()
    if not jobs:
        sleep(JOB_POLL_INTERVAL)
```

Multiple `run_jobs` processes can run concurrently (same `skip_locked` safety `run_filter`/
`run_sender` already rely on) — this is what replaces "one docker-compose service per job type"
with "N generic worker replicas."

### 3.4 Recurring vs. event-triggered scheduling

Two patterns, both needed (see §4's split):

- **Self-requeue** (shown above): a recurring job re-inserts its own next occurrence on success.
  Simplest option, good for "every N seconds/minutes" jobs with no external trigger.
- **Enqueue-on-event**: some other code path (a Discord bot interaction handler, `run_filter`
  transitioning an ad, a management command) calls `Job.objects.create(job_type=..., payload=...)`
  directly, once, with no `interval_seconds`. This is how event-triggered jobs (§4.2) get created
  — no separate scheduler needed, just a call site.

A dedicated cron-style `JobSchedule` table (job_type, interval, next_run_at) is *not* proposed
here — self-requeue is simpler and sufficient for every recurring job identified in §4. Revisit
only if a job needs a schedule independent of its own run history (e.g. "always at 3am" rather
than "every 24h from whenever it last finished").

### 3.5 What replaces the global force-run flag

`Query.force_run_requested` (or bumping the matching `Job.scheduled_at` to now, `priority` to max)
subsumes `DISCORD_BOT.md` §3.3's proposed per-query force-run *and* simplifies today's
global sentinel file (`settings.FORCE_RUN_FLAG_PATH`) — "run this specific thing now" becomes a
one-row update instead of a filesystem flag plus an `_interruptible_sleep` polling loop.

---

## 4. Candidate jobs

### 4.1 Interval/cron-style (self-requeuing, `interval_seconds` set)

| Job | `requires_bazos_session` | Source |
|---|---|---|
| Per-query scrape pass (today's `run_scraper`, decomposed to one job per `Query` instead of one big sequential loop) | yes | current code |
| `AdWatch` bulk recheck | yes | `DISCORD_BOT.md` §2.1/§3.2 |
| Sold/removed sweep of `SENT`/`APPROVED` ads (`410` detection) | yes | `HIDDEN_API.md` §6.4a, §8 Stage D |
| Full-listing rescan (per opted-in `Query`) | yes | `BACKLOG_IDEAS.md` #8 |
| Posting-time-of-day interval-tuning analysis (pure DB, no network) | no | `BACKLOG_IDEAS.md` #6 / `PROMPTS.md` P14 |
| Repost/duplicate detection sweep | no (reads existing `Ad` archive) | `DISCOVERY_PIPELINE.md` §3.3 |
| Taxonomy sync (`sections.php`/`categories.php`, replacing the one-off `create_sections`/`create_categories` commands) | yes | `HIDDEN_API.md` §8 Stage D |
| Health/heartbeat + proactive alerts | no | `DISCORD_BOT.md` §2.2 |

### 4.2 Event/on-demand-triggered (enqueued once, by a call site — not by a clock)

| Job | Trigger | `requires_bazos_session` | Source |
|---|---|---|---|
| Seller reputation/volume enrichment (`ratings.php`) | a seller gets flagged suspicious | yes | `DISCOVERY_PIPELINE.md` Stage 4 |
| LLM ad review | a new PENDING/APPROVED ad | no (LLM API, not Bazos — own concurrency cap instead) | `LLM_AD_REVIEW.md` |
| Seller outreach draft generation | a Discord "✉️ Draft message" button press | no | `LLM_AD_REVIEW.md` §4.2 / `DISCORD_BOT.md` Tier 3 |
| Per-query force-run | user request | n/a (just a `scheduled_at`/`priority` bump on the existing scrape job, §3.5) | `DISCORD_BOT.md` §3.3 |

### 4.3 Not a fit — don't force these into the job system

One-off, human-run spikes like the AND/OR probe (`BACKLOG_IDEAS.md` #7) or a data migration don't
belong here. Worth stating explicitly so "make everything a job" doesn't become the next
over-engineering trap this project falls into.

---

## 5. Convergence with everything else already proposed

- **`BACKLOG_IDEAS.md` #2** (asyncio) — its conclusion ("don't retrofit onto the HTML scraper,
  build the eventual API scraper async-native") gains a second natural landing spot: job handlers
  that fan out internally (§2), independent of whether `run_jobs`'s outer loop is async.
- **`BACKLOG_IDEAS.md` #6** (interval tuning) and **#8** (full rescan) — both already describe
  "give this a different cadence than the rest of the fleet"; a generic job's `interval_seconds`
  is exactly that knob, per job instance rather than a global setting.
- **`DISCORD_BOT.md`** §2.1 (`AdWatch`/`run_ad_watch`), §2.2 (health/heartbeat), and §3.3
  (per-query force-run) each independently proposed a new always-on process or a new sentinel
  mechanism — all three collapse into job types under this design instead of separate processes.
- **`DISCOVERY_PIPELINE.md`** Stage 4 (seller enrichment) and §3.3 (repost detection) —
  both already-designed, never-built enrichment passes; natural job types, one event-triggered,
  one periodic.
- **`LLM_AD_REVIEW.md`** — the per-ad LLM judge and the draft-outreach delivery mechanism
  are both good fits for event-triggered jobs with their own rate/cost-sensitive concurrency cap,
  distinct from the Bazos-session lock in §2.

---

## 6. Phased build recommendation

| Phase | Scope | Risk |
|---|---|---|
| 1 | `Job` model + migration, `JOB_REGISTRY`/`JobHandler` protocol, `run_jobs` worker, admin registration (list/filter by status/type, manual retry action — matches `PROMPTS.md` P9's admin-polish spirit). No behavior change yet — nothing is migrated onto it. | Low — additive, nothing consumes it yet |
| 2 | Migrate one low-stakes existing loop onto it as a proof of concept — the posting-time-of-day analysis (`BACKLOG_IDEAS.md` #6/P14) is a good first candidate: no network, no `requires_bazos_session`, easy to verify. | Low |
| 3 | Add the Bazos-session lock (§2) and migrate a `requires_bazos_session=True` job — `AdWatch`/`run_ad_watch` (`DISCORD_BOT.md` §2.1) or the sold/removed sweep are good candidates, both already fully designed elsewhere. | Medium — first real test of the concurrency lock |
| 4 | Decompose `run_scraper` itself into one job per `Query`, retiring `ScrapeRunner.run()`'s monolithic loop; wire per-query force-run (§3.5) as a side effect. | Medium/High — touches the core, most-load-bearing loop in the project |
| — | Full-listing rescan (#8), seller enrichment, repost detection, LLM review — layer in as new job types once Phase 3/4 validate the pattern under real Bazos-network load. | Low once Phase 3 lands — these are "just another job type" at that point |

Phases 1–2 are low-risk and validate the design without touching anything load-bearing. Phase 4
(migrating `run_scraper` itself) is the biggest step and should only happen once Phase 3 has
proven the concurrency lock actually works under real traffic — not before.
