"""Task functions for the django-q2 cluster, and the schedules that drive them.

A task here is a thin, importable callable — django-q2 stores a *dotted path*, so a task must
stay importable at that path or its schedule silently stops firing. Renaming one of these is
a migration, not a refactor.

Two rules this module keeps:

- **A task returns a short string and lets exceptions escape.** django-q2 records the return
  value on `Success` and the traceback on `Failure`, so the admin becomes the run log for
  free. Swallowing an exception to "be safe" would turn a failure into a green row, which is
  the one thing a run log must never do. **One carve-out, and it is written down rather than
  discovered**: `@defers_when_blocked` turns `AllCircuitsBlocked` into a green row *plus a
  pending `Schedule`*, because a blocked exit is backpressure and the retry is visible in
  Scheduled tasks. It still ends in a red row if the deferrals run out.
- **Nothing here holds the Tor session open across tasks.** Each task builds what it needs
  and drops it, so the single worker's serialisation (`Q_CLUSTER["workers"] = 1`) is the
  only concurrency control required — see JOB_QUEUE.md §2.
"""
import logging
from datetime import time, timedelta
from dataclasses import dataclass
from functools import wraps
from random import randint

from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from bazos.const import JOB_BLOCK_MAX_DEFERRALS, JOB_BLOCK_RETRY_DELAY
from bazos.scraping.session import AllCircuitsBlocked
from senders.models import Discord
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)

#: Dotted paths, because that is what django-q2 persists in a `Schedule` row. Defined once
#: here so a rename breaks an import rather than silently orphaning a schedule.
SWEEP_DELISTED = "bazos.jobs.sweep_delisted"
HEARTBEAT = "bazos.jobs.heartbeat"
PIPELINE_WATCHDOG = "bazos.jobs.pipeline_watchdog"
DAILY_DIGEST = "bazos.jobs.daily_digest"
PRUNE_STATUS_LOGS = "bazos.jobs.prune_status_logs"
PRUNE_QUERY_RUNS = "bazos.jobs.prune_query_runs"
SCORE_AD = "bazos.jobs.score_ad"
RESCORE_ADS = "bazos.jobs.rescore_ads"
SYNC_VINTED_CATALOGS = "bazos.jobs.sync_vinted_catalogs"
COMPARE_BAZOS_SCRAPERS = "bazos.jobs.compare_bazos_scrapers"
GEOCODE_POSTAL_CODE = "bazos.jobs.geocode_postal_code"
FETCH_FULL_DESCRIPTION = "bazos.jobs.fetch_full_description"
REFRESH_AD = "bazos.jobs.refresh_ad"
FETCH_SELLER_RATINGS = "bazos.jobs.fetch_seller_ratings"
FETCH_SELLER_LISTINGS = "bazos.jobs.fetch_seller_listings"
DETECT_REPOSTS = "bazos.jobs.detect_reposts"


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
#
# Declared here rather than in the management command so another app can contribute one
# without `bazos` importing it. `refprice` already registers a filter rule this way; a
# schedule is the same seam for the same reason — deleting that app must break nothing here.

@dataclass(frozen=True)
class ScheduleSpec:
    func: str
    schedule_type: str
    minutes: int | None = None
    kwargs: dict | None = None
    #: Local wall-clock time of the FIRST run, read only when the row is created.
    #:
    #: Everything else here fires "every N from whenever the deploy happened", which is
    #: fine for a prune and useless for a digest someone reads with lunch. django-q2
    #: re-applies a DST correction on every advance (`Schedule.calculate_next_run`
    #: compares the local wall clock before and after and subtracts the difference), so a
    #: row anchored to 13:00 Prague stays at 13:00 across the clock change.
    #:
    #: `Schedule.CRON` would be the more general answer and is deliberately not used:
    #: croniter is an optional django-q2 extra that is not installed, and the scheduler
    #: runs every row inside one transaction with one try/except — so a CRON row on an
    #: image built without croniter raises ImportError and abandons the whole iteration,
    #: stopping the delisting sweep and the heartbeat with it. A digest must not be able
    #: to do that. Note DAILY also cannot express "weekdays only" or "twice a day".
    at: time | None = None


#: name -> spec. Cadence is editable in the admin afterwards; this only declares the row.
SCHEDULES: dict[str, ScheduleSpec] = {
    "delisting-sweep": ScheduleSpec(
        SWEEP_DELISTED,
        Schedule.DAILY,
        # Daily is the right resolution: `removed_at` is stamped when the sweep notices, so
        # finer cadence buys precision the question ("how many days to disappear") cannot
        # use, at a linear cost in requests.
        #
        # No `limit` in kwargs, which is what puts the task in chunked mode: it works a
        # slice, yields the single worker, and re-enqueues itself while ads remain due. A
        # backlog run as one task would make every other job wait for the whole backfill.
    ),
    "cluster-heartbeat": ScheduleSpec(HEARTBEAT, Schedule.MINUTES, minutes=60),
    # The heartbeat proves the cluster is alive; this proves the pipeline is. They are
    # different questions: on 2026-10-16 the first was green for all 22 hours of the outage.
    "pipeline-watchdog": ScheduleSpec(PIPELINE_WATCHDOG, Schedule.MINUTES, minutes=60),
    # 13:00 rather than "24h after the deploy": this one is read by a person, at a time
    # they chose. Safe to anchor because 13:00 is never inside Prague's DST gap (02:00-03:00).
    "daily-digest": ScheduleSpec(DAILY_DIGEST, Schedule.DAILY, at=time(13, 0)),
    # Weekly, not daily: both prunes are by age, so running more often deletes the same rows
    # a few days earlier at the cost of a long DELETE competing with the scraper for locks.
    "prune-status-logs": ScheduleSpec(PRUNE_STATUS_LOGS, Schedule.WEEKLY),
    "prune-query-runs": ScheduleSpec(PRUNE_QUERY_RUNS, Schedule.WEEKLY),
    # Monthly. Vinted's taxonomy is ~2 920 nodes that move rarely, and the whole tree
    # arrives in ONE request — so this is not about cost, it is about not finding out a
    # catalog id was retired by watching a query quietly return nothing.
    "sync-vinted-catalogs": ScheduleSpec(SYNC_VINTED_CATALOGS, Schedule.MONTHLY),
    # Weekly, matching contract-check.yml's cadence for the same kind of question. Read-only
    # and cheap — a handful of queries against both transports.
    "compare-bazos-scrapers": ScheduleSpec(COMPARE_BAZOS_SCRAPERS, Schedule.WEEKLY),
}


# ---------------------------------------------------------------------------
# The catalog — what the admin's "Run a job" page offers
# ---------------------------------------------------------------------------
#
# A job is reachable three ways: a changelist action (when you are already looking at the
# row), a schedule (when it is periodic), and this catalog (when all you have is an id).
#
# It exists because the generic alternative is bad. django-q2's own Schedule admin will
# enqueue anything — type a dotted path, type `args`, set "Once" — but nothing checks the
# path, so a typo becomes a Failure row in a worker nobody is watching, which is the exact
# trap the dotted-path constants above exist to avoid. Nothing checks the id either, so a
# wrong one fails the same way. Here the path comes from the registry and **the argument is
# resolved before anything is queued**, so a mistake is a form error rather than a silent
# failure ten seconds later.

#: Argument kinds. The value is what the admin form knows how to validate.
NO_ARG, AD_PK, PUBLISHER_REF, POSTAL_CODE = "", "ad", "publisher", "postal_code"


@dataclass(frozen=True)
class JobSpec:
    func: str
    label: str
    arg: str = NO_ARG
    help: str = ""


#: func -> spec. Other apps add theirs at `AppConfig.ready()`, same seam as schedules.
JOB_CATALOG: dict[str, JobSpec] = {}


def register_job(spec: JobSpec) -> None:
    """Offer a job on the admin's Run-a-job page. Registering twice is a no-op."""
    JOB_CATALOG.setdefault(spec.func, spec)


def _register_own_jobs() -> None:
    for spec in (
        JobSpec(SWEEP_DELISTED, "Delisting sweep (chunked)",
                help="Works a slice and re-queues itself while ads remain due."),
        JobSpec(HEARTBEAT, "Cluster heartbeat"),
        JobSpec(PIPELINE_WATCHDOG, "Check every pipeline stage is moving",
                help="Posts to the for_logging channels only when a stage has stalled."),
        JobSpec(DAILY_DIGEST, "Post the daily Discord digest",
                help="The same message the 13:00 schedule sends. Safe to run repeatedly."),
        JobSpec(PRUNE_STATUS_LOGS, "Prune log rows"),
        JobSpec(PRUNE_QUERY_RUNS, "Prune query runs"),
        JobSpec(RESCORE_ADS, "Re-score every stored price score",
                help="The backfill after a persisted field is added. Walks every scored ad."),
        JobSpec(SYNC_VINTED_CATALOGS, "Sync Vinted catalog tree"),
        JobSpec(COMPARE_BAZOS_SCRAPERS, "Compare HTML vs API scrapers"),
        JobSpec(SCORE_AD, "Score one ad", AD_PK),
        JobSpec(FETCH_FULL_DESCRIPTION, "Fetch an ad's full description", AD_PK),
        JobSpec(REFRESH_AD, "Re-read an ad's listing", AD_PK,
                help="Bazos only — the other marketplaces have no bulk-id endpoint."),
        JobSpec(GEOCODE_POSTAL_CODE, "Geocode a postal code", POSTAL_CODE),
        JobSpec(FETCH_SELLER_RATINGS, "Fetch a seller's ratings", PUBLISHER_REF),
        JobSpec(FETCH_SELLER_LISTINGS, "Fetch a seller's current listings", PUBLISHER_REF,
                help="Creates Ad rows with no delivery, marked source='seller_sweep'."),
        JobSpec(DETECT_REPOSTS, "Find a seller's relisted items", PUBLISHER_REF),
    ):
        register_job(spec)


_register_own_jobs()


def register_schedule(name: str, spec: ScheduleSpec) -> None:
    """Add a schedule from another app, at that app's `AppConfig.ready()`.

    Mutating the registry rather than importing into it is what keeps the dependency
    pointing inward — `bazos` never has to know which other apps exist. Registering twice is
    a no-op so a double `ready()` (Django calls it once, test harnesses are less reliable)
    cannot produce two rows for one job.
    """
    SCHEDULES.setdefault(name, spec)


def defers_when_blocked(func_path: str):
    """Turn a spent rotation budget into a retry later, rather than a dead task.

    `with_rotation` spends `MAX_BLACKLIST_RETRIES` rotations in about fifteen seconds, and the
    exits it draws in that window are **not independent** - the eight that failed a ratings
    fetch on 2026-09-20 included four in 185.220.100.0/22 and two in 204.8.96.0/24, two of the
    largest Tor exit operators, both blocked wholesale. So the answer to a spent budget is not
    more rotations against the same poisoned sample; it is the same request in ten to twenty
    minutes, when Tor's path selection has genuinely moved. That is why this waits at the
    *job* level and `with_rotation` is left alone: a sleep inside it would slow the 91-batch
    delisting sweep for every caller and still re-draw from an identical consensus.

    A decorator rather than five copies of the same try/except, for the reason
    `bazos/scraping/session.py` gives about its own extraction: a policy with a budget, an
    index and an `ack_failure` flag in it should exist once. The cost is that `deferral` does
    not appear in the five signatures - it is keyword-only, defaults to 0, and only the
    scheduler ever passes it.

    **The give-up raises rather than returning.** By then the run is one this module enqueued
    with `ack_failure`, so the red row is final; a green row saying "gave up" would be the
    exact lie the module docstring forbids.
    """
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, deferral: int = 0, **kwargs):
            try:
                return fn(*args, **kwargs)
            except AllCircuitsBlocked as exc:
                return _defer_blocked(func_path, args, deferral, exc)

        return wrapper

    return decorate


def _defer_blocked(func_path: str, args: tuple, deferral: int, exc: Exception) -> str:
    """Re-enqueue `func_path` later, or give up if the budget is spent."""
    from django_q.tasks import schedule

    if deferral >= JOB_BLOCK_MAX_DEFERRALS:
        raise exc

    delay = randint(*JOB_BLOCK_RETRY_DELAY)
    next_run = timezone.now() + timedelta(seconds=delay)
    schedule(
        func_path,
        *args,
        schedule_type=Schedule.ONCE,
        next_run=next_run,
        deferral=deferral + 1,
        # `django_q/monitor.py:52` acknowledges a task only when it succeeded or carries
        # this. Without it the cluster's own retry (`retry: 60*60`, `max_attempts: 3`) would
        # re-run each give-up and start a fresh chain of deferrals underneath it - three
        # attempts by three deferrals is twelve runs and ninety-six blocked requests.
        q_options={"ack_failure": True},
        # NOT `repeats`: `django_q/scheduler.py:130-137` deletes a fired ONCE schedule only
        # when `repeats < 0`, and sets it to 0 and saves otherwise, leaving a dead row. The
        # field default is -1, so the correct value is the one we do not pass.
    )
    logger.info("%s: deferred to %s (deferral %d of %d)",
                exc, next_run.strftime("%H:%M"), deferral + 1, JOB_BLOCK_MAX_DEFERRALS)
    return (f"{exc} - retrying at {next_run.strftime('%H:%M')} "
            f"(deferral {deferral + 1} of {JOB_BLOCK_MAX_DEFERRALS})")


def sweep_delisted(limit: int | None = None, rounds_left: int | None = None) -> str:
    """Run the delisting sweep. See `bazos/delisting.py` for what it does and does not mean.

    Wraps the management command rather than reimplementing it: the command is the documented
    entry point and stays usable by hand (`--dry-run`, `--limit`) for the one-off backfill.

    **Two modes, chosen by `limit`.**

    - `limit` given — do exactly that much and stop. The explicit one-off.
    - `limit` omitted — work in chunks of `DELIST_CHUNK_SIZE` and **re-enqueue itself** while
      ads remain due. This is what the schedule uses.

    Chunking is not throughput tuning; it is what stops a backfill monopolising the cluster.
    `Q_CLUSTER["workers"] = 1` is a correctness constraint (the Tor session is not safe for
    concurrent callers), so *every* other job waits behind this one. A ~29 000-ad backlog run
    as a single task means an admin-triggered lookup sits behind the whole thing; run as
    chunks, it waits about a minute.

    No offset is threaded through, and that is deliberate: a swept ad has `last_seen_at`
    stamped, so it drops out of `due_for_check()` on its own. Paginating instead would skip
    exactly as many rows as the previous chunk removed from the result set.

    **Two independent stops**, because a re-enqueueing task that cannot finish is a loop that
    looks like progress: the round budget, and "this chunk cleared nothing". The second is
    the one that matters — a chunk whose every batch was blocked leaves its ads due, and
    without it the job would re-queue itself against a marketplace that is refusing us.
    """
    from io import StringIO

    from django_q.tasks import async_task

    from bazos.const import DELIST_CHUNK_SIZE, DELIST_MAX_CHUNK_ROUNDS
    from bazos.delisting import due_for_check

    one_off = limit is not None
    chunk = limit if one_off else DELIST_CHUNK_SIZE
    rounds_left = DELIST_MAX_CHUNK_ROUNDS if rounds_left is None else rounds_left

    due_before = 0 if one_off else due_for_check().count()

    out = StringIO()
    call_command("check_delisted", limit=chunk, stdout=out)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Delisting sweep finished: %s", summary)

    if one_off:
        return summary

    due_after = due_for_check().count()
    if due_after == 0:
        return f"{summary} | nothing left due"
    if due_after >= due_before:
        # Every batch was skipped — blocked circuits, or a transport that cannot answer.
        # Re-queueing would spend the round budget asking the same question.
        logger.warning("Delisting chunk cleared nothing; %d still due", due_after)
        return f"{summary} | {due_after} still due, chunk made no progress — stopping"
    if rounds_left <= 1:
        return f"{summary} | {due_after} still due, round budget spent — stopping"

    async_task(SWEEP_DELISTED, rounds_left=rounds_left - 1)
    return f"{summary} | {due_after} still due, next chunk queued"


def daily_digest() -> str:
    """Post the daily digest to every `for_daily_digest` channel.

    Split deliberately at one line: **collecting and rendering may raise**, because a bug
    there is a real defect and a `Failure` row with a traceback is the right report — but
    **the POST may not**. A rate limit from Discord must not turn a correct digest into a
    red row, and must not burn `max_attempts` re-running the whole collection for a
    message that was already built.
    """
    from bazos.digest.collect import collect
    from bazos.digest.render import render
    from senders.models import Discord
    from senders.services.discord_webhook import post_embeds

    channels = list(Discord.objects.filter(for_daily_digest=True))
    if not channels:
        # Not an error: a misconfiguration should be visible on the Success row rather
        # than as a red Failure nobody can act on.
        return "no for_daily_digest channel configured"

    embeds = render(collect())

    posted = failed = 0
    for channel in channels:
        try:
            post_embeds(channel.url, embeds)
            posted += 1
        except Exception:
            logger.exception("Could not post the daily digest to %s", channel.channel_name)
            failed += 1
    return f"posted to {posted} channel(s)" + (f", {failed} failed" if failed else "")


def heartbeat() -> str:
    """Prove the cluster is alive, so silence becomes a signal.

    Moving every scheduled job behind one `qcluster` process concentrates failure: if it
    dies, everything stops and nothing says so. That is the same shape as the Vinted outage
    that ran unnoticed for eight days, and the per-query failure alert does not cover it —
    it only fires when a *pass* runs and fails.

    This is deliberately trivial. It exists so that the absence of a recent `Success` row,
    or of this line in the log channel, is itself evidence.
    """
    now = timezone.now()
    logger.info("Job cluster heartbeat at %s", now.isoformat(timespec="seconds"))
    return f"alive at {now:%Y-%m-%d %H:%M:%S}"


def pipeline_watchdog() -> str:
    """Say out loud when a pipeline stage has stopped moving.

    A stall is not raised: the watchdog itself worked, and a red row would read as the
    watchdog being broken. It is logged at ERROR (Sentry) and posted to the `for_logging`
    channels every hour until it clears, and a refusing webhook must not hide it.
    """
    from bazos.watchdog import find_stalls

    stalls = find_stalls()
    if not stalls:
        return "healthy"

    message = "🚨 Pipeline stalled:\n" + "\n".join(f"• {s}" for s in stalls)
    for stall in stalls:
        logger.error("Pipeline stalled - %s", stall)
    for channel in Discord.objects.filter(for_logging=True):
        try:
            DiscordSender.from_model(channel).send_plain(message)
        except Exception:
            logger.exception("Could not post the watchdog alert to %s", channel.channel_name)
    return f"{len(stalls)} stall(s): " + "; ".join(stalls)


# ---------------------------------------------------------------------------
# Housekeeping — the two tables that grow with the clock, not with the market
# ---------------------------------------------------------------------------

def prune_status_logs(days: int | None = None, error_days: int | None = None) -> str:
    """Drop log rows past their horizon. See `bazos/housekeeping.py` for the two horizons."""
    from bazos.housekeeping import prune_status_logs as prune

    routine, serious = prune(days, error_days)
    logger.info("Pruned %d routine and %d warning+ log rows", routine, serious)
    return f"deleted {routine} routine, {serious} warning+"


def prune_query_runs(days: int | None = None) -> str:
    """Drop `QueryRun` rows past their horizon.

    ⚠️ This is the table every block-rate measurement is computed from, and a deleted row is
    gone — `exit_ip` is the only record of which egress the marketplace actually rejected.
    """
    from bazos.housekeeping import prune_query_runs as prune

    deleted = prune(days)
    logger.info("Pruned %d query runs", deleted)
    return f"deleted {deleted} query runs"


# ---------------------------------------------------------------------------
# Price scoring — CPU only, so these cannot be stuck behind a Bazos job
# ---------------------------------------------------------------------------

def score_ad(ad_pk: int) -> str:
    """Predict what one ad is worth and persist the `AdPriceScore`.

    `PriceModel.predict` is CPU-only by contract — no network, no pacing, no block
    handling — so this is one of the few tasks that never waits on a circuit.

    `refresh=True`: the only reason to ask for one ad by hand is that the stored answer is
    suspect or absent, and `score_ad`'s freshness check keys on the *artifact* version, so
    without this a row written by older code short-circuits and comes back unchanged.

    Three outcomes, all reported rather than collapsed to "done": no registered model claims
    the ad, a model declined (gates, damage words, a non-EXACT price), or a real number.
    "A model looked and had no opinion" is a different fact from "nothing looked".
    """
    from bazos.models import Ad
    from bazos.pricing.scoring import score_ad as predict

    ad = Ad.objects.get(pk=ad_pk)
    score = predict(ad, refresh=True)
    if score is None:
        return f"ad {ad_pk}: no model claims it"
    if score.declined_reason:
        return f"ad {ad_pk}: {score.model_name} declined — {score.declined_reason}"
    return f"ad {ad_pk}: {score.model_name} predicts {score.predicted} ({score.discount_pct:+.0f}%)"


def rescore_ads(model: str | None = None, missing_features: bool = False) -> str:
    """Re-predict every stored score. The backfill after a persisted field is added.

    Wraps `manage.py rescore_ads` rather than reimplementing it — that command is the
    documented entry point and carries the `--dry-run` and `--missing-features` narrowing.

    ⚠️ Not scheduled, and should not be: it walks every scored ad, and there is nothing
    periodic about "the code that writes these columns changed".
    """
    from io import StringIO

    out = StringIO()
    kwargs: dict[str, object] = {"missing_features": missing_features}
    if model is not None:
        kwargs["model"] = model
    call_command("rescore_ads", stdout=out, **kwargs)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Rescore finished: %s", summary)
    return summary


def sync_vinted_catalogs() -> str:
    """Re-seed `MarketplaceCategory` from Vinted's live category tree.

    One request for the whole tree, `update_or_create`, and **nothing is ever deleted** —
    the command reports a retired node instead, along with any `Query` whose `extra_params`
    still reference it. That report is the entire point of scheduling this: `catalog_ids`
    live in a JSONField and are not an FK, so a retired id fails as an empty result rather
    than as an error. Vinted queries have already gone silently dead for eight days once.
    """
    from io import StringIO

    out = StringIO()
    call_command("create_vinted_catalogs", stdout=out)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Vinted catalog sync: %s", summary)
    return summary


def compare_bazos_scrapers(limit: int | None = None) -> str:
    """Do the HTML and the hidden-API scraper still see the same listings?

    Read-only — it never writes an `Ad`. This is the standing drift check for **P21a's
    cutover**: `BazosApiScraper` is registered but no `Query` selects it, so today nothing
    would notice if it quietly stopped agreeing with the HTML scraper, and the cutover is a
    step nobody wants to take on a scraper last validated by hand weeks earlier.

    The command rotates circuits per scrape, which matters more here than anywhere else: a
    403 returns nothing, and "nothing" from one of the two transports reads exactly like the
    drift this is looking for.
    """
    from io import StringIO

    out = StringIO()
    kwargs: dict[str, object] = {}
    if limit is not None:
        kwargs["limit"] = limit
    call_command("compare_bazos_scrapers", stdout=out, **kwargs)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Scraper parity check: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Jobs that need the Bazos session — these serialise behind the delisting sweep
# ---------------------------------------------------------------------------

@defers_when_blocked(GEOCODE_POSTAL_CODE)
def geocode_postal_code(code: str) -> str:
    """Resolve one postal code into the `PostalCode` cache.

    The gap this closes: `Query.filter_location_center` is typed by hand in the admin and
    may name a code no listing has ever come from, so it has no creation moment of its own.
    Until something geocodes it, `location_distance` PASSes for that whole query — which is
    indistinguishable from "no filter configured". `ScrapeRunner` warms centres once per
    pass, so the window is up to 45 minutes of a filter the admin says is on and isn't.

    Returns "already cached" without a request when the row exists. That is the common case
    when the action is used on a selection, and a no-op that says so is better than one that
    looks like a lookup.
    """
    from bazos.geo import geocode_postal_code as geocode, normalize_postal_code
    from bazos.models import PostalCode
    from bazos.scraping.session import build_ip_changer, with_rotation

    normalized = normalize_postal_code(code)
    if not normalized:
        # Not an exception: a code the parser cannot read is a data problem to report, not a
        # transport failure to retry, and a Failure row would say the wrong thing about it.
        return f"{code!r}: not a usable postal code"
    if PostalCode.objects.filter(code=normalized).exists():
        return f"{normalized}: already cached"

    changer = build_ip_changer()
    row = with_rotation(
        changer,
        lambda session: geocode(normalized, session, pace=True, raise_on_block=True),
        what=f"Geocoding {normalized}",
    )
    if row is None:
        # zip.php genuinely not knowing a code is a real answer, and a different one from
        # "we were blocked" — which `with_rotation` raises rather than returns.
        return f"{normalized}: unresolved (zip.php has no entry)"
    return f"{normalized}: {row.city} ({row.latitude:.4f}, {row.longitude:.4f})"


@defers_when_blocked(FETCH_FULL_DESCRIPTION)
def fetch_full_description(ad_pk: int) -> str:
    """Fetch one ad's full description on demand, whatever its marketplace.

    Makes `Query.load_full_description` per-ad instead of per-query: today the choice is
    "every ad on this query pays a detail request, or none do", and the question is always
    about one listing.
    """
    from bazos.enrichment import fetch_full_description as fetch
    from bazos.models import Ad
    from bazos.scraping.session import build_ip_changer, with_rotation

    ad = Ad.objects.get(pk=ad_pk)
    changer = build_ip_changer()
    fetched = with_rotation(
        changer,
        lambda session: fetch(ad, session),
        what=f"Detail fetch for ad {ad_pk}",
    )
    if not fetched.full_description:
        # A 410 on the API path, or a detail page that carried nothing. Not a failure — the
        # request worked and the answer was "nothing here" — so it must not raise.
        return f"ad {ad_pk}: no description returned"
    seller = "seller resolved" if fetched.email_publisher or fetched.phone_publisher else "no seller ids"
    return f"ad {ad_pk}: {len(fetched.full_description)} chars, {seller}"


@defers_when_blocked(REFRESH_AD)
def refresh_ad(ad_pk: int) -> str:
    """Re-read one listing's row — still up, and has the price moved?

    This is `PROMPTS.md` P26 #2 (`_resolve_ad` never refreshes a rediscovered ad) turned
    into something triggerable for a single listing. The price path goes through the
    delisting sweep's `apply_batch`, so a change found here writes `PriceChange` history and
    re-enters the filter exactly as one found by the sweep does.
    """
    from bazos.enrichment import refresh_ad as refresh
    from bazos.models import Ad
    from bazos.scraping.session import build_ip_changer, with_rotation

    ad = Ad.objects.get(pk=ad_pk)
    changer = build_ip_changer()
    return with_rotation(
        changer,
        lambda session: refresh(ad, session),
        what=f"Refresh of ad {ad_pk}",
    )


@defers_when_blocked(FETCH_SELLER_RATINGS)
def fetch_seller_ratings(publisher_kind: str, publisher_pk: int) -> str:
    """Read one seller's ratings and store the counts. See `bazos/ratings.py` for the
    reviewer-PII decision, which is the whole design of this one.

    `publisher_kind` is "email" or "phone" — a seller on Bazos is a *pair* of opaque ids and
    each is queried separately, so the pk alone would not say which table to look in.
    """
    from bazos.ratings import fetch_seller_ratings as fetch
    from bazos.scraping.session import build_ip_changer, with_rotation

    publisher = _publisher(publisher_kind, publisher_pk)
    changer = build_ip_changer()
    counts = with_rotation(
        changer,
        lambda session: fetch(publisher, session),
        what=f"Ratings for {publisher_kind} id {publisher.bazos_id}",
    )
    return f"{publisher_kind} id {publisher.bazos_id}: {counts}"


@defers_when_blocked(FETCH_SELLER_LISTINGS)
def fetch_seller_listings(publisher_kind: str, publisher_pk: int) -> str:
    """Pull one seller's whole current inventory in a single request.

    Creates `Ad` rows with **no `AdDelivery`** and `source=SELLER_SWEEP` — no query asked
    for them, so they must not enter anyone's notification stream, and the provenance column
    is what keeps "ads we have" tellable from "ads our queries found" afterwards.

    Also the missing input for repost detection: a seller's past-versus-current inventory is
    what catches the same item relisted under a new `external_id`.
    """
    from bazos.enrichment import fetch_seller_listings as fetch
    from bazos.scraping.session import build_ip_changer, with_rotation

    publisher = _publisher(publisher_kind, publisher_pk)
    changer = build_ip_changer()
    result = with_rotation(
        changer,
        lambda session: fetch(publisher, session),
        what=f"Inventory for {publisher_kind} id {publisher.bazos_id}",
    )
    return f"{publisher_kind} id {publisher.bazos_id}: {result}"


def detect_reposts(publisher_kind: str, publisher_pk: int) -> str:
    """Link this seller's ads to the earlier listings they appear to relist.

    CPU-only — it reads our own archive and talks to nothing — so it never waits on a
    circuit. Its usefulness depends on `fetch_seller_listings` having been run for the same
    seller: a relist is only visible if both attempts are in the database, and before the
    inventory pull existed a seller's past listings were only here by luck.
    """
    from bazos.reposts import detect_reposts as detect

    publisher = _publisher(publisher_kind, publisher_pk)
    linked = detect(publisher)
    return f"{publisher_kind} id {publisher.bazos_id}: {linked} relist(s) linked"


def _publisher(kind: str, pk: int):
    """Resolve "email"/"phone" plus a pk to a publisher row.

    A seller on Bazos is a *pair* of opaque ids living in two tables, so a pk alone does not
    say which one to read. Branched rather than looked up in a dict because the two managers
    are what is wanted, and a dict of model classes erases both to their shared abstract base.
    """
    from bazos.models import EmailPublisher, PhonePublisher

    if kind == "email":
        return EmailPublisher.objects.get(pk=pk)
    if kind == "phone":
        return PhonePublisher.objects.get(pk=pk)
    raise ValueError(f"unknown publisher kind {kind!r}")
