"""Chart data, rendered two ways from one definition.

The admin draws charts with Chart.js in the browser, where unfold resolves CSS variables
and the picture follows the light/dark theme. The daily digest cannot: Discord shows an
image, and the image is rendered by QuickChart on a server that has never heard of
`var(--color-primary-500)` — it falls back to Chart.js grey **without erroring**, which is
the worst way for a colour to be wrong.

So a series names a colour *token* and the renderer picks the palette. One definition of
"primary means new ads, danger means a real error", two outputs.
"""
import json
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

#: How far back the trends look. Two weeks covers a weekend dip plus the weekly jobs.
CHART_DAYS = 14

#: Above this the image is dropped and the panel ships without it. Discord proxies the URL
#: through its own CDN and a very long one is not worth testing the edge of; a 14-point,
#: 2-series config encodes to ~900 characters, so this is roughly 2x headroom.
MAX_CHART_URL_CHARS = 1800

#: unfold resolves these in the browser, so the admin follows the viewer's theme.
CSS_PALETTE = {
    "primary": "var(--color-primary-500)",
    "muted": "var(--color-base-400)",
    "danger": "var(--color-red-500)",
    "info": "var(--color-blue-500)",
}

#: Literal equivalents for server-side rendering. QuickChart cannot resolve a CSS variable
#: and does not complain about one, so passing CSS_PALETTE there silently produces grey
#: bars — `test_charts.py` asserts no `var(` ever reaches a QuickChart URL.
HEX_PALETTE = {
    "primary": "#a855f7",
    "muted": "#9ca3af",
    "danger": "#ef4444",
    "info": "#3b82f6",
}


@dataclass(frozen=True)
class Series:
    """One dataset, colour named rather than specified."""

    token: str
    label: str
    values: list
    stack: str | None = None


def series(rows, key, days, today):
    """Dense daily series — a day with no rows is a zero, not a gap.

    Chart.js joins across missing labels, so a sparse queryset would draw a line that
    implies activity on days when nothing happened.
    """
    counts = {row[key]: row["n"] for row in rows}
    start = today - timedelta(days=days - 1)
    labels, values = [], []
    for offset in range(days):
        day = start + timedelta(days=offset)
        labels.append(day.strftime("%d.%m"))
        values.append(counts.get(day, 0))
    return labels, values


def _datasets(items, palette):
    out = []
    for item in items:
        dataset = {
            "label": item.label,
            "data": item.values,
            "backgroundColor": palette[item.token],
            "borderRadius": 4,
        }
        if item.stack:
            dataset["stack"] = item.stack
        out.append(dataset)
    return out


def chart_json(labels, items):
    """Chart.js `data`, JSON-encoded for unfold's `data-value` attribute."""
    return json.dumps({"labels": labels, "datasets": _datasets(items, CSS_PALETTE)})


def quickchart_url(labels, items, *, stacked=False, width=640, height=260):
    """A QuickChart image URL, or None when the config is too long to be worth sending.

    **Discord fetches this, not us.** The URL goes in `embeds[].image.url` and Discord's
    CDN retrieves and caches the PNG server-side, so the Pi makes no extra request and the
    digest cannot be made late by a slow image.

    `v=4` is pinned deliberately: the public endpoint defaults to an older Chart.js whose
    option names differ (`scales.xAxes[]` vs `scales.x`), and a default bump would quietly
    render the wrong axes. `bkg=white` because a transparent PNG is illegible in one of
    Discord's two themes, and white reads as a printed panel in both.

    Note the URL is content-addressed by Discord's cache: two days with byte-identical
    configs would show the same picture. The `%d.%m` labels rotate daily, so this is safe —
    do not "optimise" them to indices.
    """
    axis = {"ticks": {"maxTicksLimit": 7}}
    config = {
        "type": "bar",
        "data": {"labels": labels, "datasets": _datasets(items, HEX_PALETTE)},
        "options": {
            "plugins": {"legend": {"display": len(items) > 1}},
            "scales": {
                "x": {**axis, "stacked": stacked},
                "y": {"beginAtZero": True, "stacked": stacked},
            },
        },
    }
    url = "https://quickchart.io/chart?" + urlencode({
        "c": json.dumps(config, separators=(",", ":")),
        "w": width,
        "h": height,
        "bkg": "white",
        "devicePixelRatio": 2,
        "v": 4,
    })
    return url if len(url) <= MAX_CHART_URL_CHARS else None
