---
title: E2E / record-and-replay testing for the scraper — research
status: shipped
updated: 2026-08-23
verified: 2026-08-23
shipped_in: 60a7873
---

# E2E / record-and-replay testing for the scraper — research

**Status:** research written 2026-08-23. **All four steps in §8 have since been built** — see the
four commits following this document. What landed differs from the plan in two places, both
recorded below: §4.8 (a `vcr_config` trap found during implementation) and §4.9 (Bazos serves
page 1 of a category search with a 404). The §1a bug the research surfaced is fixed.
**Question asked:** *"Can we record real requests and replay them 1:1, so a refactor that breaks
something fails a test?"*

**Short answer: yes, and `vcrpy` is the right recorder — but the recording layer is the easy half.**
The hard half is that "replay 1:1" only produces a *stable* test once six sources of
non-determinism are pinned (§6), and the pipeline currently has **no way to run one batch**
(§5) — both pollers are bare `while True` loops. Those two, not the HTTP mocking, are the
actual work.

Everything in §4 is **measured** on this repo's exact pinned stack, not inferred. Experiments
were run in a throwaway venv (`requests==2.28.2`, `urllib3==1.26.15`, Python 3.11.2) — the same
versions `poetry.lock` pins today.

---

## 1. What the suite covers today, and the shape of the hole

24 test files, ~5,200 lines. Coverage is genuinely good, but it is **uniformly above the
transport layer**:

| Layer | Covered? | By what |
|---|---|---|
| HTML → `dict` parsing | ✅ strong | `test_parse_product.py` — hand-built HTML from `dedent()` |
| JSON → `Ad` (API/Vinted/Sbazar) | ✅ strong | `test_bazos_api_scraper.py`, `test_vinted_scraper.py`, `test_sbazar_scraper.py` — recorded fixture dicts + `MagicMock` session |
| dedup / price-change logic | ✅ strong | `test_deduplication.py` — `patch.object(runner.scraper, "run_query", return_value=iter([...]))` |
| filter rules | ✅ strong | `test_filters.py`, `test_run_filter.py` |
| sender state machine | ✅ strong | `test_run_sender.py` |
| runner guards / canary | ✅ strong | `test_bazos_runner_blacklist.py`, `test_zero_results_canary.py` |
| **`requests` → `Response` → `BeautifulSoup`** | ❌ **none** | — |
| **URL sequence actually requested** | ⚠️ partial | `test_gen_url.py` checks generators, nothing checks what gets fetched |
| **scraper → filter → sender as one flow** | ❌ **none** | every stage is tested in isolation |

Concretely, **every existing test stops at `run_query`** — either by mocking it wholesale or by
feeding `_parse_product` a string. Nothing exercises `run_request`, `get_page_products`,
pagination termination, the 403 → `BazosBlacklistedError` path, gzip/charset decoding, or
`response.url` → `urljoin` for relative hrefs.

**The refactor risks that live in that hole:**

1. `create_url_general` / `create_url_category` drift — the generator still yields *a* URL, the
   URL is just wrong. `test_gen_url.py` is 16 lines and pins one case.
2. Pagination stop conditions. `run_query` breaks on `if not products` — and carries a `TODO`
   saying it looks broken. Nothing tests it.
3. `urljoin(response.url, product.url)` — relative→absolute promotion depends on the *response's*
   final URL (i.e. redirects). Invisible to every current test.
4. Anything that changes **how many requests** are made (e.g. P13 filter-before-detail-fetch,
   P21's API cutover). Today no test would notice a doubling of request volume against Bazos.
5. `MAX_ATTEMPTS` retry behaviour in `run_request` — the `except (TimeoutException, URLError)`
   clause has a `# todo correct exception` on it, and `requests` raises neither of those.

That last one is worth calling out on its own: **`run_request` catches the wrong exceptions.**
`session.get` raises `requests.exceptions.RequestException` subclasses; `URLError` is `urllib`'s
and `TimeoutException` is Selenium's. A transport-level test is exactly what surfaces it.

### 1a. This research already found one live bug in that hole

**Measured 2026-08-23.** `create_url_general` (the path taken when a `Query` has neither
`section` nor `category`) builds its URL from `query.url`, which falls back to
`BAZOS_BASE_URL = "https://bazos.cz"` — a bare origin with no path. Bazos **redirects that to the
homepage and drops the query string entirely**:

| URL built | final URL after redirect | ad blocks parsed |
|---|---|---|
| `https://bazos.cz?hledat=macbook&...&crz=0` *(current behaviour)* | `https://www.bazos.cz` | **0** |
| `https://www.bazos.cz/search.php?hledat=macbook&...&crz=0` | *(no redirect)* | **21** |

So a section-less, category-less Bazos `Query` scrapes **nothing, silently** — `run_query` finds no
`class="inzeraty"` elements, hits `if not products: break`, and yields zero ads on every pass.
`const.py` already defines the correct constant, `BAZOS_URL = "https://bazos.cz/search.php"`; it is
simply not what `Query.url` returns.

The sharp part: `test_url_generation.py::test_create_url_general_uses_base_url_without_category`
**asserts this behaviour is correct** (`assert first_url.startswith(BAZOS_BASE_URL)`). The test
suite pins the bug, because no test has ever asked what that URL *returns*. This is the entire
argument for T1 in one example — and it is the first regression test PR 2 should write.

(Impact depends on how many production `Query` rows have both FKs null; every query with a section
or category takes `create_url_category` and is unaffected. Worth a one-line check against the Pi's
DB before deciding urgency.)

---

## 2. Four things "E2E" could mean here — pick deliberately

They are not alternatives; they are nested rings, and they cost very differently.

| # | Scope | Seam | What it catches | Cost |
|---|---|---|---|---|
| **T1** | `BazosScraper.run_query(query)` → `list[Ad]` | HTTP transport | parser drift, URL construction, pagination, 403, encodings | **low** |
| **T2** | `BazosQueryRunner.run()` → DB rows | HTTP transport | T1 + dedup break, price-change detection, `AdDelivery` creation, detail-fetch gating | low-medium |
| **T3** | scrape → filter → send → DB + captured Discord text | HTTP transport + Discord stub | T2 + rule engine wiring, status machine, `Ad.message` rendering | **medium** (needs §5) |
| **T4** | `BazosRunner.run()` full pass incl. IP guards | HTTP + IPChanger | T3 + blacklist rotation, `QueryRun` metrics, canary counters | medium-high |

**Recommendation: build T1 first, then T3.** T1 is where the untested code actually is and pays
for itself in an afternoon. T3 is the "did my refactor break anything" test the question is really
about. T4 duplicates `test_zero_results_canary.py` and `test_bazos_runner_blacklist.py`, which
already mock the guards well — skip it.

---

## 3. The recording layer — five options

### A. `vcrpy` + `pytest-recording` (VCR cassettes) — **recommended**

Patches `httplib`/`urllib3` connections, serialises every interaction to YAML, replays on
subsequent runs. `pytest-recording` adds `@pytest.mark.vcr`, `--record-mode`, and a
`--block-network` guard.

- ✅ **Recording is the feature.** Point it at Bazos once with `--record-mode=once`; the cassette
  writes itself. This is literally what was asked for.
- ✅ **Highest fidelity of any option** — real `requests` → real `urllib3` → real gzip decode →
  real `Response` object. The only fake thing is the socket.
- ✅ **Unrecorded requests raise** (measured, §4.3). A refactor that fetches a *different* URL, or
  fetches one *more time*, fails loudly rather than silently passing.
- ✅ Refresh = `rm cassette.yaml && pytest --record-mode=once`.
- ⚠️ Needs config to be usable (§4.2, §4.5). Defaults are wrong for this repo.
- ⚠️ One new dev dependency, version-pinned by the old HTTP stack (§4.1).

### B. Saved raw `.html`/`.json` + a hand-rolled fake transport

Save pages to `bazos/tests/fixtures/bazos_html/`, mount a fake `HTTPAdapter` (or subclass
`requests.Session`) that maps URL → file.

- ✅ Zero dependencies; fixtures are plain readable HTML, trivial to hand-edit for edge cases.
- ✅ Continues the repo's **existing pattern** (`fixtures/bazos_api/*.json`).
- ✅ Easiest to scrub of personal data — it's just a file.
- ❌ **You still have to write the recorder**, which is the thing you wanted for free.
- ❌ Loses headers, status codes, redirect chains, request *counts* — i.e. loses most of what
  makes it "1:1".
- Verdict: **good complement, not a replacement.** Use it for hand-crafted edge cases (empty page,
  malformed ad block, 403 body) that you can't conveniently provoke live.

### C. `responses` / `requests-mock` — hand-written stubs

- ❌ Every response is written by hand. That is a *worse* version of what `test_sbazar_scraper.py`
  already does with `MagicMock`, and it re-encodes your assumptions about the site rather than
  recording reality. **Rejected** — it adds a dependency and buys nothing over the status quo.

### D. Local replay HTTP server (`pytest-httpserver`, or stdlib `http.server`)

Serve the saved fixtures over real HTTP on `127.0.0.1`.

- ✅ Exercises the genuine socket path, TLS aside. Immune to every mocking-library quirk.
- ✅ Immune to the proxy trap in §4.6.
- ❌ Requires the base URL to be injectable — `Section.full_url` / `Category.full_url` /
  `BAZOS_BASE_URL` are hard-wired to `bazos.cz`. Making them configurable is a production change
  purely for testing.
- Verdict: keep in the back pocket. If vcrpy ever fights the stack, this is the fallback.

### E. Proxy-level recording (`mitmproxy --server-replay`) or a recording `HTTPAdapter`

Every request in this app flows through **one** `requests.Session`, handed down from
`IPChanger.session` → `BazosQueryRunner` → scraper. That is an unusually clean injection point:
a `RecordingHTTPAdapter` mounted on that session could capture **real production traffic**,
including the pages that actually broke the parser at 3am.

- ✅ Captures reality, not a curated fetch — the highest-value corpus you could have.
- ✅ Pairs naturally with the existing zero-results canary: canary fires → you already have the
  page that caused it.
- ❌ Meaningfully more machinery (storage, rotation, PII, size) and mitmproxy is heavyweight for
  a single-session Python app.
- Verdict: **not now, but note it.** If parser drift keeps happening, "capture the last N pages on
  a canary trip" is a better investment than more cassettes. Worth a `BACKLOG_IDEAS.md` entry.

---

## 4. Measured findings

All measured 2026-08-23 in an isolated venv pinned to this repo's versions.

### 4.1 Version compatibility — **vcrpy 7.0.0, not 8.x**

`vcrpy 8.0.0` dropped urllib3 v1. This repo cannot install it today:

| Package | Pinned | Constraint it imposes |
|---|---|---|
| `requests` | 2.28.2 | `urllib3 >=1.21.1,<1.27` |
| `selenium` | 4.8.2 | `urllib3[socks] >=1.26,<2.0` |
| resolved | `urllib3` **1.26.15** | — |

So urllib3 2.x needs **both** `requests≥2.30` and `selenium≥4.11` bumped first. Note `selenium`
is still a *main* dependency even though `selenium_driver.py` is dead code — `bazos_scraper.py`
imports `TimeoutException` from it (in the `except` clause that catches the wrong exception, §1).

**Measured:** `vcrpy==7.0.0` + `pytest-recording==0.13.4` install cleanly against
`requests 2.28.2` / `urllib3 1.26.15` / `pytest 7.2.2` on Python 3.11.2, and record+replay works.
vcrpy 7's marker is `urllib3; python_version >= "3.10"` — unbounded, so 1.26.15 satisfies it.

> Pin `vcrpy = "^7.0"` in `[tool.poetry.group.dev.dependencies]`. Revisit when the HTTP stack
> is bumped — that is also a prerequisite for P21's proxy work, so the two travel together.

### 4.2 Cassettes are **binary and undiffable by default**

A real `bazos.cz` search page (50,173 chars, gzip on the wire) recorded with default settings
produced a **17,960-byte cassette whose body is `!!binary` base64 of the gzip stream**. Not
readable, not greppable, not reviewable in a diff.

With `decode_compressed_response=True`:

| | bytes | readable |
|---|---|---|
| default | 17,960 | ❌ `!!binary` |
| `decode_compressed_response=True` | **61,740** | ✅ plain YAML |
| (source page) | 50,173 | — |

→ **1.23× inflation over the raw HTML**, ~62 KB per page, so a realistic 3-page query cassette
lands around **185 KB**. Acceptable, but it means cassettes are a *deliberate* git-weight decision,
and `decode_compressed_response=True` is **not optional** — without it you cannot review, scrub,
or hand-edit the fixture.

### 4.3 Unrecorded requests fail loudly ✅

```
CannotOverwriteExistingCassetteException: No match for the request ... in record mode 'none'
Matchers succeeded : ['method', 'scheme', 'path']
Matchers failed : query - assertion failure: crz=999 != crz=0
```

This is the single most valuable property for the stated goal. A refactor that changes the URL,
the parameter order, or the number of requests **cannot pass silently**. The error message even
names which matcher failed.

### 4.4 403 replays correctly ✅

A recorded `403` replays as a `403`, so `run_query`'s `raise BazosBlacklistedError()` branch and
`check_blacklisted()`'s `status_code == 403` check are both testable from a cassette. (Consistent
with the live-verified note in memory that the Bazos block is 403-only and path-scoped.)

### 4.5 `filter_headers` scrubs **requests only** — responses leak ⚠️

Measured: a response `Set-Cookie: session=SECRET_TOKEN_123` was written to the cassette **6 times**
despite `filter_headers=["cookie", "user-agent"]`. That option only touches the request side.

Response scrubbing needs an explicit hook:

```python
def scrub_response(response):
    response["headers"].pop("Set-Cookie", None)
    return response

vcr.VCR(before_record_response=scrub_response, ...)
```

### 4.6 A configured proxy **breaks host/port matching** ⚠️⚠️

Replaying a direct-recorded cassette through a session with `session.proxies` set fails:

```
No match for the request (<Request (GET) https://127.0.0.1:1/search.php?...>)
host - assertion failure : 127.0.0.1 != www.bazos.cz
port - assertion failure : 1 != 443
```

vcrpy sees the **proxy's** host:port, not the target's. Consequences for this repo:

- Cassettes **must be recorded without Tor** (`IP_CHANGER_TYPE=DUMMY`, plain `requests.Session`),
  or they get keyed to the Tor SOCKS address and rot the moment it changes.
- Tests must construct a **non-proxied** session. `DummyIPChanger.renew_session` already does
  exactly that (`requests.Session()`, no `.proxies`) — use it, don't hand-roll.
- Alternatively drop `host`/`port` from `match_on`, which works but weakens the guarantee.

This costs an hour to discover the hard way. It is the main reason to write the recording
procedure down rather than leaving it to whoever needs it next.

### 4.7 Cassettes are request-**count** sensitive

vcrpy records one interaction per call. A test helper that called `session.get(u)` twice per URL
recorded **8 interactions for 4 URLs**, and replay consumed them pairwise. Default
`allow_playback_repeats=False` means each is played once.

This cuts both ways: it's precisely the property that catches "my refactor now fetches the detail
page twice", and it's a source of churn when a legitimate change alters request counts. **Keep
the default** — the strictness is the point.

### 4.8 `vcr_config`'s `record_mode` silently overrides `--record-mode` ⚠️

Found while building the tests, not during the survey. Setting `"record_mode": "none"` in the
`vcr_config` fixture — the obvious way to express "never touch the network" — makes
`pytest --record-mode=once` a **no-op**: every request fails with
`CannotOverwriteExistingCassetteException` and no cassette is ever written, with nothing in the
output pointing at the fixture as the cause.

pytest-recording already defaults to `none` when no CLI flag is given, so the fix is to **leave
`record_mode` out of `vcr_config` entirely** and let the plugin own it. The default is what you
wanted anyway.

### 4.9 Bazos serves page 1 of a category search with a **404** status

Measured: `https://pc.bazos.cz/notebook/0/?hledat=...` returns **`404`** with a complete, correct
listing body — the same ads, in the same order, as the `200` you get from
`https://pc.bazos.cz/notebook/?hledat=...`. Page 2 (`/notebook/20/?...`) returns `200` normally.

`create_url_category` starts its `itertools.count` at 0, so **every category query's first page is
a 404** today. It works only because `run_request` ignores status codes apart from 403. Adding a
`raise_for_status()` or a `status_code == 200` guard — an obviously-correct-looking hardening —
would silently break page 1 of every query in production.

`test_first_page_404_is_still_parsed` exists to make that change fail loudly.

### 4.10 Measured cassette footprint of the real suite

**1.0 MB total** across 16 cassettes — 9 for the transport tests (408 KB), 6 for the pipeline
tests, plus one hand-written 403. Individually 30–70 KB, all plain readable YAML.

The pipeline cassettes dominate because each test re-records the same pages under
pytest-recording's per-test naming. Sharing one cassette across the module would cut it by
roughly two thirds; per-test cassettes were kept because a failing test then points at exactly
the traffic it replayed. Revisit if the directory becomes a nuisance in diffs.

### 4.11 A cassette scrubber has two failure modes that both fail *open*

Found by review after the tests had shipped, and worth more than the leak that surfaced them.

**The YAML emitter folds long lines, so regexes over the raw file lie.** PyYAML wraps long
scalars — **measured at 444 mid-token line breaks in a single cassette**. The same regex run over
the raw file text and over the decoded body:

```
matches on RAW yaml text: 0    on DECODED body: 2
```

Any hygiene check that reads `cassette.read_text()` can therefore report a clean file that
contains the thing it was looking for. The first version of this repo's guard did exactly that,
for a real seller name. **Parse the YAML and scan the decoded bodies.**

**A guard that restates the scrubber's patterns can only confirm the scrubber.** The first version
of `test_cassette_carries_no_personal_data` re-parsed the same `odeslatakci('rating', …)` arguments
the scrubber had just written, so the scrub and the assertion shared one blind spot and the test
could never catch that class of miss. The fix is for the test to **import the patterns from the
scrubber** rather than restate them, so the two cannot drift.

The concrete miss, for the record: the seller's name appears twice on a Bazos *detail* page — once
in the rating onclick's argument list, and once as the span's visible text. Only the argument was
scrubbed.

**And prefer default-deny.** The obvious repair — "replace the visible text when it equals the name
in the onclick" — still fails open twice: it misses any rendering that differs from the argument,
and it cannot repair a cassette whose onclick has *already* been scrubbed, because the name it
needs to compare against is gone. Replacing everything except a small allowlist of known UI labels
fails closed instead, and a new label shows up as a test failure rather than as a leak. (The
allowlist cannot simply be dropped: `BazosScraper._parse_action_args` finds its span *by that
visible text*, so rewriting the labels breaks the parser.)

**Repairing beats re-recording.** Re-recording fixes a leak but pulls fresh ads and invalidates
every snapshot. Re-running the corrected scrubber over the cassettes already on disk keeps the
recorded traffic and the snapshots intact.

**And the coupling comes back one level down.** Importing the scrubber's patterns into the guard
fixes drift, but it also means the guard only inspects what the scrubber's *regex* matches. Any
markup that regex stops matching is invisible to both sides at once — the scrubber falls through
to its weaker fallback, and the guard never looks. Measured, with the guard as first written:

| markup variant | scrubbed | guard sees it |
|---|---|---|
| today's shape | ✅ | ✅ |
| `; return false;` (one extra space) | ❌ | ❌ **leaks, guard green** |
| `<b>` nested inside the span | ❌ | ❌ **leaks, guard green** |
| single-quoted attributes | ❌ | ❌ **leaks, guard green** |

The rule that generalises: **a redaction guard must not share a detection mechanism with the
redactor — only its vocabulary.** Sharing the list of strings known to be safe is fine and
desirable; sharing *how a secret is located* means one markup change disables both. The second
check here keys off the `paction` class and a real HTML parse instead of the onclick regex, so all
three variants fail loudly. A meta-test pins that independence, so a later refactor cannot quietly
re-couple them.

---

## 5. The blocker: neither poller can run a single batch

`run_filter` and `run_sender` are both:

```python
def handle(self, *args, **options):
    while True:
        with transaction.atomic():
            deliveries = list(AdDelivery.objects.select_for_update(...)[:BATCH])
            for delivery in deliveries: ...
        if not deliveries:
            sleep(POLL_INTERVAL)
```

There is no `--once`, no `--max-batches`, and the batch body is inline in `handle`. A T3 test
therefore cannot call `call_command("run_filter")` — it would hang forever. `BazosRunner.run()`
has the same shape (`test_zero_results_canary.py` escapes it by patching `_interruptible_sleep`
to raise a sentinel — workable, but it is a workaround, not a seam).

**And the existing tests already pay for this.** `test_run_filter.py` and `test_run_sender.py`
each open with a private helper — `_run_filter_once` / `_run_sender_once` — that **reimplements
the loop body from `handle()`** so the tests have something callable. Both files say so in their
docstrings ("Exercises the filter loop logic directly (not via the management command
entrypoint)"). The consequence is that ~13 tests assert against a *copy* of the production logic:

- `run_filter`'s real `.filter(status__in=[PENDING, PRICE_CHANGED])` is **never executed** — the
  test helper takes a pre-built list, and two tests hand-filter the queryset themselves under the
  comment `# Simulate the filter loop only picking up PENDING/PRICE_CHANGED`.
- Neither `select_for_update(skip_locked=True, of=("self",))` nor the `select_related(...)` chains
  are ever called, so an N+1 regression or a dropped relation is invisible.
- `ORDER BY created` and `[:BATCH_SIZE]` are untested.
- Editing `handle()` cannot fail either test file.

So PR 1 is **not** merely an E2E enabler: extracting `_run_once()` deletes ~40 lines of duplicated
test logic and repoints 13 existing tests at the code that actually runs in production. That is
worth doing even if the rest of this document is never built.

**This is the prerequisite PR, and it is worth doing on its own merits:**

```python
def _run_once(self) -> int:
    """One batch. Returns the number of deliveries processed."""
    ...

def handle(self, *args, **options):
    while True:
        if self._run_once() == 0:
            sleep(FILTER_POLL_INTERVAL)
        if options["once"]:
            return
```

Small, mechanical, and it also makes the pipeline runnable from the admin force-run button and
from `JOB_QUEUE.md`'s eventual worker without a process-per-stage.

---

## 6. Determinism inventory — what must be pinned for a stable replay

"Replay 1:1" is necessary but not sufficient. Everything below varies per run and must be frozen
or excluded from assertions, or the test is flaky:

| # | Source | Where | Fix |
|---|---|---|---|
| 1 | `sleep(uniform(*BAZOS_PAGE_WAIT_TIME))` — **2–5 s per page** | `BazosScraper.run_query` | patch `sleep`; a 3-page cassette otherwise costs up to 15 s |
| 2 | `sleep(uniform(0.5, 2))` per Discord message | `DiscordSender._send` | stub the sender (T3 must not POST to Discord anyway) |
| 3 | `Query.objects.filter(enabled=True).order_by('?')` | `BazosRunner.run` | seed one query, or patch the ordering (T4 only) |
| 4 | `NightMultiplier` reads **wall-clock Europe/Prague** — returns 2.0 between 22:00–06:00 | `interval_multiplier.py` | never assert on intervals, or freeze the clock |
| 5 | `timezone.now()` on `created`/`modified`/`sent_at`/`PriceChange.created` | models | exclude from snapshots, or freeze time |
| 6 | SQLite `:memory:` silently drops `select_for_update(skip_locked=True)` | root `conftest.py` | a known, documented gap — T3 tests *logic*, not locking |

(4) deserves emphasis: a test asserting on sleep intervals **passes all day and fails at
23:00**. Assert on state transitions, never on timing.

`Ad.publish_date` is parsed from the HTML, so it is stable — but note it will be **frozen at the
recording date**, which makes any future date-relative rule (`PriceDropRule` is fine; a
hypothetical "posted in the last hour" rule would not be) untestable from an aging cassette.

Also worth flagging for T3: `Ad.message` embeds `seller_ad_counts().summary`, which fires several
`COUNT` queries walking the email↔phone identity graph. Snapshotting rendered messages is a
*good* test of that code, but it means the snapshot depends on the whole seeded DB, not just the
one ad. Seed deliberately.

---

## 7. Cassettes contain other people's data

A recorded Bazos page carries seller usernames (`publisher_name`), opaque email/phone publisher
ids, locations, and full ad text. The repo's own `.gitignore` is explicit about the principle:

```
# Dumps contain seller emails and phone numbers — never commit. PII in git
# history is unremovable in practice (docs/BACKUPS.md §7).
backups/
```

Three mitigating facts: the repo is **private**; the page is **public**; and the publisher ids are
**opaque**, not emails or phone numbers (per `CLAUDE.md`'s seller-identity section). So this is
materially lower-risk than a `pg_dump` — but it is the same category of decision, and "unremovable
in practice" still applies if the repo is ever shared or opened.

**Posture as built:** commit cassettes, with a `before_record_response` scrub that rewrites the
seller's display name to `Seller<email_id>` and redacts email addresses and phone numbers. The
cassette stays structurally 1:1, which is all the parser cares about, and the decision stays
consistent with the policy already written down.

This paragraph originally also proposed remapping **the two publisher ids**. The implementation
deliberately does not, and that is the better call: the ids are opaque integers, not emails or
phone numbers, they are exactly what the parser is supposed to extract, and remapping them would
make the publisher assertions test the scrub rather than the scraper. See the rationale in
`bazos/tests/conftest.py`.

**It costs more than "one regex", which is the part this section got wrong.** Two things only
became visible once it was built, both now in §4.11.

---

## 8. Recommended plan

Four PRs, ordered by dependency. Roughly 1–2 days total.

**PR 1 — `--once` on both pollers** (~1 h, no new deps)
Extract `_run_once()` from `run_filter` / `run_sender`; add `--once`. Unit-test that `--once`
returns. Independently useful; unblocks T3.

**PR 2 — T1: cassette-backed `BazosScraper` transport tests** (~3 h)
- `vcrpy = "^7.0"`, `pytest-recording` in dev deps.
- `bazos/tests/conftest.py` gains a `vcr_config` fixture:
  ```python
  @pytest.fixture(scope="module")
  def vcr_config():
      return {
          "record_mode": "none",
          "decode_compressed_response": True,     # §4.2 — non-negotiable
          "filter_headers": ["cookie", "user-agent", "authorization"],
          "before_record_response": scrub_response,  # §4.5 + §7
          "match_on": ["method", "scheme", "host", "port", "path", "query"],
      }
  ```
- Cassettes in `bazos/tests/cassettes/`, recorded with `IP_CHANGER_TYPE=DUMMY` (§4.6).
- Tests: full-page parse count; pagination across 3 pages then stop; `403` →
  `BazosBlacklistedError`; `check_blacklisted()` true/false; relative→absolute `url` promotion;
  `load_full_description`.
- Patch `time.sleep` module-wide in these tests (§6.1).
- **Write `docs/` recording instructions in the same PR** — §4.6 alone justifies it.

**PR 3 — T3: the pipeline golden-master** (~4 h, depends on PR 1 + 2)
Seed `Section`/`Category`/`Query`/`Discord` → run `BazosQueryRunner` against the cassette →
`call_command("run_filter", once=True)` → `call_command("run_sender", once=True)` with
`DiscordSender._send` captured to a list → assert on a **snapshot**:
```
Ad rows:        external_id, name, price_raw, url, topped, publisher ids
AdDelivery:     (external_id, query) → status, filter_reason
Discord output: the exact rendered message strings
```
Serialize that to a sorted, timestamp-free structure and compare against a committed
`.json`/`.txt`. Hand-rolled comparison is fine (~30 lines); `syrupy` is the library option if you
want `--snapshot-update` ergonomics, but it's a second dependency for a single test — **start
without it.**

Run the same scenario twice in one test (second pass over the same cassette) to pin the
**dedup break** end-to-end. That is the single most refactor-sensitive behaviour in the codebase
and currently only has mock-level coverage.

**PR 4 — freshness** *(built: `bazos/tests/live/`, `.github/workflows/contract-check.yml`)*
Cassettes rot silently: the site changes, the cassette doesn't, tests stay green while production
breaks. Two complementary answers:
- A `@pytest.mark.live` suite, **deselected by default** and excluded from CI, that re-records and
  diffs the parsed `Ad` field set against the committed cassette. Run manually before a refactor,
  or on a manual-dispatch GitHub Action. There is a precedent for this shape in `old_tests/live/`.
- Production-side, the **zero-results canary already covers the catastrophic case** — this only
  adds earlier warning for partial drift (e.g. `view_count` stops parsing while everything else
  works).

---

## 9. What this will *not* catch — be honest about it

1. **Cassette rot.** Green tests prove "the code still handles the HTML from 2026-08-23", not
   "the code handles bazos.cz". Only PR 4 or the canary closes this.
2. **Postgres-specific behaviour.** Tests run on SQLite `:memory:`, which drops
   `select_for_update(skip_locked=True)` from the SQL entirely (documented in `CLAUDE.md`). Every
   concurrency property of the queue remains untested, E2E or not.
3. **Tor / IP rotation / blacklist recovery under real conditions.** Cassettes are recorded
   un-proxied by necessity (§4.6).
4. **Rate limits, bans, and the site's behaviour under load** — the failure modes that actually
   take this scraper down in production.
5. **Vinted.** `VintedScraper` ignores the injected session and builds its own `httpx` client
   inside the `vinted-scraper` package. vcrpy supports httpx, but 7.x's support predates the 8.0
   httpcore rewrite and is the shakiest part of the library. Bazos and Sbazar (both plain
   `requests`) are the good targets; leave Vinted on its current fixture-dict tests.

---

## 10. Verdict

Build **T1 + T3 on `vcrpy 7.0.0` cassettes**, gated behind the `--once` refactor.

The instinct in the original question is right — record/replay at the transport layer is the
correct seam, and it is the only option that catches "this refactor changed which requests we
make", which is the failure mode a mock-based suite is structurally blind to. What the research
changes is the shape of the work: the mocking is an afternoon, and the value is concentrated in
(a) the `--once` seam, (b) the six determinism pins in §6, and (c) writing down the recording
procedure so §4.6 is discovered once instead of every time.

---

### Appendix — reproducing the measurements

The throwaway venv and scripts used for §4 are not committed. To reproduce:

```bash
python3.11 -m venv /tmp/vcrtest
/tmp/vcrtest/bin/pip install "requests==2.28.2" "urllib3==1.26.15" \
                             "pytest==7.2.2" "vcrpy==7.0.0" pytest-recording
```

Then: record against a local `http.server` (pagination + a 403 path), replay against a **dead
port** to prove the cassette is doing the work, and assert an unrecorded URL raises
`CannotOverwriteExistingCassetteException`. Sizes in §4.2 come from one live
`GET https://www.bazos.cz/search.php?hledat=macbook&rubriky=www&...` recorded both ways.

One incidental confirmation from that page: the live markup is
`class="inzeraty inzeratyflex"`, i.e. **multi-valued**. `soup.find_all(class_='inzeraty')` matches
it correctly (BeautifulSoup matches individual class tokens), and the page yielded 20
`inzeratyakce` blocks — the parser's assumptions hold as of 2026-08-23.
