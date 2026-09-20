"""Tests for the digest renderer (`bazos/digest/render.py`).

The renderer is pure, so it can be handed the inputs production will never conveniently
produce: nothing wrong, everything wrong, and a payload far over Discord's budget. The
last one is the reason `_fit` exists — a 400 from an oversized payload would come back as
a job failure with a body nobody reads.
"""
from datetime import datetime, timezone as dt_timezone

import pytest

from bazos.digest.collect import DigestData, Drop, Flag
from bazos.digest.render import RED, TRIMMED, render
from bazos.health import Anomaly
from senders.services.discord_webhook import (
    MAX_EMBED_CHARS_TOTAL,
    MAX_EMBEDS_PER_MESSAGE,
    check_payload,
    embed_chars,
)

GENERATED = datetime(2026, 9, 21, 13, 0, tzinfo=dt_timezone.utc)


def _data(**overrides):
    base = dict(
        generated=GENERATED, window_hours=24,
        found=412, found_avg=380.5, notified=17, notified_avg=12.0,
        rejected=395, delisted=64, drops_down=31, drops_up=9,
        latency_median=18.5, latency_p90=44.0, fail_rate=56, fail_baseline=51,
        ads_labels=[f"{d:02d}.09" for d in range(8, 22)], ads_values=list(range(14)),
        drop_labels=[f"{d:02d}.09" for d in range(8, 22)],
        drop_values=list(range(14)), rise_values=[1] * 14,
    )
    base.update(overrides)
    return DigestData(**base)


def _drop(n=1, pct=22.5):
    return Drop(f"MacBook Pro M1 {n}", f"https://pc.bazos.cz/inzerat/{n}/x.php",
                "bazos", 61_000, 47_000, pct)


def _flag(n=1, notified=False):
    return Flag(f"ThinkPad {n}", f"https://pc.bazos.cz/inzerat/{n}/x.php",
                12_000, 21_000, -2.4, notified)


def test_a_healthy_day_says_nothing_about_anomalies():
    """A section that reliably renders "nothing wrong" is a section you stop reading."""
    embeds = render(_data(), charts=False)

    assert not any(e["title"] == "Anomalies" for e in embeds)


def test_an_alert_colours_the_headline_red():
    embeds = render(_data(anomalies=[Anomaly("queue_stalled", "alert", "Cluster stalled")]),
                    charts=False)

    assert embeds[0]["color"] == RED
    assert "Cluster stalled" in embeds[1]["description"]


def test_a_warning_alone_does_not_read_as_an_emergency():
    headline = render(_data(anomalies=[Anomaly("queue_failures", "warn", "1 job failure")]),
                      charts=False)[0]

    assert headline["color"] != RED


def test_drops_link_to_the_marketplace_not_the_admin():
    """`SITE_BASE_URL` is a LAN name, and this is read on a phone — an admin link is dead
    exactly when the message matters."""
    embeds = render(_data(drops=[_drop()]), charts=False)
    description = embeds[1]["description"]

    assert "(https://pc.bazos.cz/inzerat/1/x.php)" in description
    assert "/admin/" not in description
    assert "61k → 47k" in description


def test_a_flag_nobody_heard_about_is_marked_as_such():
    """That split is the shadow-mode decision input: what enabling the rule would add."""
    embeds = render(_data(flags=[_flag(notified=False), _flag(2, notified=True)]), charts=False)
    description = embeds[-1]["description"]

    assert "never surfaced" in description
    assert "notified anyway" in description


def test_charts_are_attached_as_images_and_can_be_switched_off():
    with_charts = render(_data(), charts=True)
    without = render(_data(), charts=False)

    assert with_charts[0]["image"]["url"].startswith("https://quickchart.io/chart?")
    assert "image" not in without[0]


def test_a_day_with_no_price_changes_gets_no_empty_chart():
    embeds = render(_data(drops=[_drop()], drop_values=[0] * 14, rise_values=[0] * 14))

    assert "image" not in embeds[1]


@pytest.mark.parametrize(
    ("field", "omitted"),
    [("latency_median", "Cycle time"), ("fail_rate", "Attempts failing")],
)
def test_a_number_that_cannot_be_computed_is_omitted_rather_than_shown_as_zero(field, omitted):
    """A fresh install has no cycles and no baseline. "0 min" would be a claim; a missing
    field is the truth."""
    names = [f["name"] for f in render(_data(**{field: None}), charts=False)[0]["fields"]]

    assert omitted not in names
    assert len(names) == 6


def test_an_oversized_payload_is_trimmed_to_fit_and_keeps_the_headline():
    """Everything at once, each row as long as Discord allows a field to be. Without the
    trim this is a 400 that looks like a network failure."""
    long_name = "x" * 400
    data = _data(
        drops=[Drop(long_name, "https://pc.bazos.cz/inzerat/1/x.php", "bazos", 61_000, 4_000, 93.1)
               for _ in range(40)],
        flags=[Flag(long_name, "https://pc.bazos.cz/inzerat/2/x.php", 1, 2, -9.9, False)
               for _ in range(40)],
        anomalies=[Anomaly("other_errors", "alert", long_name) for _ in range(40)],
    )

    embeds = render(data, charts=False)

    check_payload(embeds)
    assert embed_chars(embeds) <= MAX_EMBED_CHARS_TOTAL
    assert len(embeds) <= MAX_EMBEDS_PER_MESSAGE
    assert embeds[0]["title"].startswith("Daily digest")
    assert any(TRIMMED in e.get("description", "") for e in embeds[1:])


def test_the_totals_survive_a_trim():
    """Detail is droppable; the headline is not. A digest that trimmed its own counts
    would describe a day nobody can reconstruct."""
    data = _data(drops=[Drop("y" * 400, "https://x/1", "bazos", 61_000, 4_000, 93.1)
                        for _ in range(40)])

    fields = {f["name"]: f["value"] for f in render(data, charts=False)[0]["fields"]}

    assert fields["New ads"].startswith("**412**")
    assert fields["Notified"].startswith("**17**")
