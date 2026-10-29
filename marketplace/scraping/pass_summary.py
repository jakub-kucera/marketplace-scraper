"""End-of-pass scrape digest: what every query found, grouped by marketplace.

Kept out of both `ScrapeRunner` and `DiscordSender` on purpose. The runner has enough
responsibilities, and the sender is marketplace-agnostic — it must not learn what a
`Query` is. What lives here is pure: dataclasses in, one monospace string out, no DB and
no network, so the layout can be tested without either.

Two things the numbers here do *not* mean:

* **Discovered, not notified.** The filter is a separate process polling `PENDING`, so at
  the moment this is built nothing in the pass has been APPROVED or REJECTED yet. A query
  can discover 12 ads and have all 12 rejected seconds later. That gap is useful signal —
  it is how an over-eager `filter_blocklist` becomes visible — but the column is labelled
  "new", never "sent", so it is not read against the notification channel.
* **Failures report no rows.** A failed query contributes `rows_seen=0` even if it parsed
  pages before dying, matching what `_check_zero_results_canary` already counts. The
  canary's question is "did the successful queries see anything", and a half-finished
  walk is not evidence either way.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Sequence

import pytz

from marketplace.models import Marketplace, Query

#: Discord rejects a message over 2000 characters outright, and `wrap_multi_line` spends 6
#: of those on the code fence. The rest is margin: a digest that fails to send is worse
#: than one that says "+ 12 more".
MAX_MESSAGE_CHARS: Final[int] = 1900
MAX_LABEL_CHARS: Final[int] = 48
MAX_ERROR_CHARS: Final[int] = 60

#: Same zone as `NightMultiplier`. The pass timestamps are UTC internally; a human reading
#: the channel wants the wall clock they scrape in.
DISPLAY_TZ: Final = pytz.timezone("Europe/Prague")

#: Line kinds, so `_fit` can trim rows without pattern-matching rendered text.
FIXED: Final[str] = "fixed"    # never trimmed
GROUP: Final[str] = "group"    # marketplace header, dropped if its rows all go
ROW: Final[str] = "row"        # one query
BLANK: Final[str] = "blank"


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def query_label(query: Query) -> str:
    """Short human label for one query — no marketplace, that's the group header.

    The price band is included when set because it is the only thing distinguishing two
    otherwise identical queries watching different bands of the same search.
    """
    name = (query.text or "").strip() or str(query.category or query.section or "").strip()
    if not name:
        name = f"query #{query.pk}"
    if query.price_upper:
        # `price_lower <= price_upper` is a DB constraint, so a set lower bound implies a
        # set upper one and there is no "≥" case to render.
        band = f"≤{query.price_upper}" if not query.price_lower else f"{query.price_lower}-{query.price_upper}"
        name = f"{name} ({band})"
    return _truncate(name, MAX_LABEL_CHARS)


@dataclass(frozen=True)
class QueryResult:
    """One query's outcome in one pass. `error` empty means it succeeded."""

    label: str
    marketplace: str
    new_ads: int = 0
    rows_seen: int = 0
    error: str = ""
    exit_ip: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)

    @classmethod
    def success(cls, query: Query, rows_seen: int, new_ads: int) -> "QueryResult":
        return cls(
            label=query_label(query),
            marketplace=query.marketplace,
            new_ads=new_ads,
            rows_seen=rows_seen,
        )

    @classmethod
    def failure(cls, query: Query, error: str, exit_ip: str = "") -> "QueryResult":
        return cls(
            label=query_label(query),
            marketplace=query.marketplace,
            error=_truncate(error, MAX_ERROR_CHARS),
            exit_ip=exit_ip,
        )


def _marketplace_label(value: str) -> str:
    try:
        return Marketplace(value).label.upper()
    except ValueError:
        # A Query row written before a choice was removed, or hand-edited in the DB.
        # Rendering the raw value beats losing the group.
        return value.upper()


def _format_duration(delta: timedelta) -> str:
    total = max(int(delta.total_seconds()), 0)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@dataclass(frozen=True)
class PassSummary:
    """Every query result from one scrape pass, renderable as a Discord message."""

    started: datetime
    finished: datetime
    results: Sequence[QueryResult]

    @property
    def total_new_ads(self) -> int:
        return sum(r.new_ads for r in self.results)

    @property
    def failures(self) -> list[QueryResult]:
        return [r for r in self.results if r.failed]

    @property
    def quiet(self) -> bool:
        """Nothing found and nothing broke — the pass that needs one line, not a table."""
        return not self.total_new_ads and not self.failures

    def format(self) -> str:
        """Render the digest as plain monospace text. The caller wraps it for Discord."""
        if self.quiet:
            return f"{self._header()} · no new ads"
        return "\n".join(text for _, text in self._fit(self._lines()))

    def _header(self) -> str:
        started = self.started.astimezone(DISPLAY_TZ)
        finished = self.finished.astimezone(DISPLAY_TZ)
        header = (
            f"Pass {started:%H:%M} → {finished:%H:%M} "
            f"({_format_duration(self.finished - self.started)}) "
            f"· {len(self.results)} queries"
        )
        if self.quiet:
            return header
        header += f" · {self.total_new_ads} new"
        if self.failures:
            header += f" · {len(self.failures)} FAILED"
        return header

    def _lines(self) -> list[tuple[str, str]]:
        """The whole message as (kind, text) pairs, so `_fit` can trim it unambiguously."""
        lines: list[tuple[str, str]] = [(FIXED, self._header())]
        for marketplace, results in self._groups():
            lines.append((BLANK, ""))
            lines.append((GROUP, _marketplace_label(marketplace)))
            lines.extend((ROW, self._row(r)) for r in results)

        quiet_count = sum(1 for r in self.results if not r.failed and not r.new_ads)
        if quiet_count:
            lines.append((BLANK, ""))
            lines.append((FIXED, f"  + {quiet_count} queries, no new ads"))
        return lines

    def _groups(self) -> list[tuple[str, list[QueryResult]]]:
        """Marketplaces that have something to show, busiest first.

        A query that succeeded with zero new ads gets no row — it is the overwhelming
        majority of every pass, and listing it is what would push the message past
        Discord's limit and train the reader to skip the whole thing.
        """
        buckets: dict[str, list[QueryResult]] = {}
        for result in self.results:
            if result.failed or result.new_ads:
                buckets.setdefault(result.marketplace, []).append(result)

        groups = []
        for marketplace, results in buckets.items():
            # Failures first: they are the reason to read the message at all.
            results.sort(key=lambda r: (not r.failed, -r.new_ads, r.label))
            groups.append((marketplace, results))
        groups.sort(
            key=lambda g: (
                -sum(r.new_ads for r in g[1]),
                -sum(1 for r in g[1] if r.failed),
                _marketplace_label(g[0]),
            )
        )
        return groups

    @staticmethod
    def _row(result: QueryResult) -> str:
        if result.failed:
            row = f"{'FAIL':>5}  {result.label} — {result.error}"
            if result.exit_ip:
                row += f" ({result.exit_ip})"
            return row
        return f"{result.new_ads:>5}  {result.label}"

    @staticmethod
    def _fit(lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Drop rows from the end until the message fits, saying how many went.

        Rows are already sorted failures-and-busiest-first, so what falls off the end is
        what matters least. Only ROW lines count as dropped; a GROUP header or BLANK left
        stranded by the trim goes too, silently — a header with nothing under it reads
        like a bug. FIXED lines (the header, the quiet-query tail) are never trimmed,
        which is what keeps the message meaningful at any length.
        """
        def rendered(candidate: list[tuple[str, str]], notice: str = "") -> int:
            texts = [text for _, text in candidate] + ([""] + [notice] if notice else [])
            return len("\n".join(texts))

        if rendered(lines) <= MAX_MESSAGE_CHARS:
            return lines

        kept = list(lines)
        dropped = 0
        while rendered(kept, f"  … + {dropped} more rows") > MAX_MESSAGE_CHARS:
            trimmable = [i for i, (kind, _) in enumerate(kept) if kind == ROW]
            if not trimmable:
                break
            kept.pop(trimmable[-1])
            dropped += 1

        # Sweep up any group header the trim emptied, then the blank lines that headers
        # left behind — done in separate passes because popping while walking backwards
        # over the same list skips entries.
        swept = [
            line for index, line in enumerate(kept)
            if line[0] != GROUP or (index + 1 < len(kept) and kept[index + 1][0] == ROW)
        ]
        collapsed: list[tuple[str, str]] = []
        for line in swept:
            if line[0] == BLANK and (not collapsed or collapsed[-1][0] == BLANK):
                continue
            collapsed.append(line)
        while collapsed and collapsed[-1][0] == BLANK:
            collapsed.pop()

        return collapsed + [(BLANK, ""), (FIXED, f"  … + {dropped} more rows")]
