"""`DigestData` in, Discord embeds out. Pure — no DB, no network, no clock.

Same contract as `bazos/scraping/pass_summary.py` and for the same reason: the layout is
the part most likely to be wrong, and a pure function can be asserted against adversarial
input instead of eyeballed.

Two deliberate departures from the pass summary's house style:

* **Markdown, not a code fence.** A fence buys `:>N` alignment and kills links, and these
  rows exist to be tapped. Prices go through `comparables.kc` for the reason that module
  gives: this is read on a phone.
* **Links point at the marketplace, never the admin.** `SITE_BASE_URL` is a LAN name and
  those links are dead on mobile data, which is exactly when a digest gets read.
"""
from marketplace.charts import Series, quickchart_url
from marketplace.comparables import kc
from senders.services import discord_webhook as limits

GREEN = 0x22C55E
AMBER = 0xF59E0B
RED = 0xEF4444

MAX_NAME_CHARS = 44
MAX_ANOMALY_ROWS = 8

#: Stands in for whatever `_fit` had to drop. Recognised on sight so a second trim does not
#: append a second one.
TRIMMED = "• …"


def _truncate(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _colour(data):
    if any(anomaly.severity == "alert" for anomaly in data.anomalies):
        return RED
    if data.anomalies:
        return AMBER
    return GREEN


def _headline_fields(data):
    def pair(name, value, note):
        return {"name": name, "value": f"**{value}**\n{note}", "inline": True}

    fields = [
        pair("New ads", f"{data.found}", f"7 d avg {data.found_avg:g}"),
        pair("Notified", f"{data.notified}", f"7 d avg {data.notified_avg:g}"),
        pair("Rejected", f"{data.rejected}", "by the filters"),
        pair("Price drops", f"{data.drops_down} ↓", f"{data.drops_up} ↑ in 14 d"),
        pair("Delisted", f"{data.delisted}", "gone from the source"),
    ]
    if data.latency_median is not None:
        fields.append(pair("Cycle time", f"{data.latency_median:g} min",
                           f"p90 {data.latency_p90:g} min"))
    if data.fail_rate is not None:
        usual = "no baseline yet" if data.fail_baseline is None else f"usual {data.fail_baseline}%"
        fields.append(pair("Attempts failing", f"{data.fail_rate}%", usual))
    return fields


def _drops_description(drops):
    return "\n".join(
        f"**−{drop.pct:g}%** {kc(drop.old)} → {kc(drop.new)} · "
        f"[{_truncate(drop.name, MAX_NAME_CHARS)}]({drop.url}) · {drop.marketplace}"
        for drop in drops
    )


def _flags_description(flags):
    lines = []
    for flag in flags:
        # Whether it was notified is the shadow-mode decision: a flag nobody heard about is
        # exactly what turning the rule on would have added.
        heard = "notified anyway" if flag.notified else "**never surfaced**"
        lines.append(
            f"**z {flag.z_score:+.1f}** {kc(flag.price)} vs {kc(flag.predicted)} expected · "
            f"[{_truncate(flag.name, MAX_NAME_CHARS)}]({flag.url}) · {heard}"
        )
    return "\n".join(lines)


def render(data, *, charts=True):
    """Build the embed list. `charts=False` drops the images, for tests and dry runs."""
    headline = {
        "title": f"Daily digest · {data.generated:%a %d.%m}",
        "color": _colour(data),
        "fields": _headline_fields(data),
        # The window is stated rather than assumed: with `catch_up: False` a 13:00 slot
        # missed while the Pi was down fires once on return, so this can arrive at 16:40.
        "footer": {"text": f"{data.window_hours} h to {data.generated:%H:%M} · "
                           f"the last chart bar is today, still filling"},
    }
    if charts and data.ads_values:
        image = quickchart_url(data.ads_labels, [Series("primary", "New ads", data.ads_values)])
        if image:
            headline["image"] = {"url": image}
    embeds = [headline]

    if data.drops:
        drops = {
            "title": f"Biggest drops · {data.window_hours} h",
            "color": GREEN,
            "description": _drops_description(data.drops),
        }
        if charts and any(data.drop_values):
            image = quickchart_url(
                data.drop_labels,
                [Series("primary", "Drops", data.drop_values, stack="p"),
                 Series("muted", "Rises", data.rise_values, stack="p")],
                stacked=True,
            )
            if image:
                drops["image"] = {"url": image}
        embeds.append(drops)

    # Absent when healthy. A section that reliably says "nothing wrong" is a section you
    # stop reading, and then it is worth nothing on the day it says something else.
    if data.anomalies:
        shown = data.anomalies[:MAX_ANOMALY_ROWS]
        lines = [f"{'🔴' if a.severity == 'alert' else '🟡'} {a.text}" for a in shown]
        if len(data.anomalies) > len(shown):
            lines.append(f"{TRIMMED} + {len(data.anomalies) - len(shown)} more")
        embeds.append({"title": "Anomalies", "color": RED, "description": "\n".join(lines)})

    if data.flags:
        embeds.append({
            "title": "The price model would have flagged",
            "color": AMBER,
            "description": _flags_description(data.flags),
        })

    return _fit(embeds)


def _fit(embeds):
    """Force the payload inside Discord's limits, dropping the least important rows first.

    Same job as `pass_summary._fit`, over embeds rather than lines. Two invariants: the
    headline is never trimmed, so the totals still describe the whole day even when detail
    was dropped; and every iteration removes one line or one embed, so the loop terminates
    whatever the input — a trim that can grow the payload (the marker is longer than the
    row it replaced) must not be able to spin.
    """
    for embed in embeds:
        embed["title"] = _truncate(embed.get("title", ""), limits.MAX_TITLE_CHARS)
        if "description" in embed:
            embed["description"] = _truncate(embed["description"], limits.MAX_DESCRIPTION_CHARS)
        if "footer" in embed:
            embed["footer"]["text"] = _truncate(embed["footer"]["text"], limits.MAX_FOOTER_CHARS)
        fields = embed.get("fields", [])[: limits.MAX_FIELDS]
        for field in fields:
            field["name"] = _truncate(field["name"], limits.MAX_FIELD_NAME_CHARS)
            field["value"] = _truncate(field["value"], limits.MAX_FIELD_VALUE_CHARS)
        if fields:
            embed["fields"] = fields

    while len(embeds) > 1 and limits.embed_chars(embeds) > limits.MAX_EMBED_CHARS_TOTAL:
        tail = embeds[-1]
        lines = [
            line for line in tail.get("description", "").split("\n")
            if line and not line.startswith(TRIMMED)
        ]
        if len(lines) > 1:
            tail["description"] = "\n".join(lines[:-1] + [TRIMMED])
        else:
            embeds.pop()

    return embeds[: limits.MAX_EMBEDS_PER_MESSAGE]
