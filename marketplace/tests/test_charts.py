"""Tests for `bazos/charts.py`.

One definition of a chart now feeds two renderers, and the failure mode that motivated the
module is silent: QuickChart accepts `var(--color-primary-500)`, cannot resolve it, and
draws grey without erroring. So the colour assertions here are the point, not decoration.
"""
import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from marketplace.charts import (
    CHART_DAYS,
    MAX_CHART_URL_CHARS,
    Series,
    chart_json,
    quickchart_url,
    series,
)

TODAY = date(2026, 9, 21)


def test_a_day_with_no_rows_is_a_zero_not_a_gap():
    labels, values = series([{"day": TODAY, "n": 5}], "day", CHART_DAYS, TODAY)

    assert len(labels) == len(values) == CHART_DAYS
    assert values[-1] == 5
    assert values[:-1] == [0] * (CHART_DAYS - 1)
    assert labels[0] == (TODAY - timedelta(days=CHART_DAYS - 1)).strftime("%d.%m")


def test_the_admin_keeps_css_variables_so_the_chart_follows_the_theme():
    data = json.loads(chart_json(["01.01"], [Series("primary", "New ads", [1])]))

    assert data["datasets"][0]["backgroundColor"].startswith("var(")


def test_no_css_variable_ever_reaches_quickchart():
    """The one failure this module exists to prevent: a server-rendered chart that is grey
    everywhere because nothing there can resolve a CSS custom property, and nothing
    complains about it either."""
    url = quickchart_url(["01.01"], [Series("primary", "New ads", [1]),
                                     Series("danger", "Failed", [2])])

    assert "var(" not in url
    config = json.loads(parse_qs(urlparse(url).query)["c"][0])
    assert all(d["backgroundColor"].startswith("#") for d in config["data"]["datasets"])


def test_the_chart_js_major_version_is_pinned():
    """The public endpoint defaults to an older Chart.js whose axis options are spelled
    differently (`scales.xAxes[]`), so a default bump would quietly render wrong axes."""
    params = parse_qs(urlparse(quickchart_url(["01.01"], [Series("primary", "x", [1])])).query)

    assert params["v"] == ["4"]
    assert params["bkg"] == ["white"]


def test_a_single_series_hides_the_legend_and_two_show_it():
    def legend(items):
        url = quickchart_url(["01.01"], items)
        return json.loads(parse_qs(urlparse(url).query)["c"][0])["options"]["plugins"]["legend"]

    assert legend([Series("primary", "x", [1])])["display"] is False
    assert legend([Series("primary", "x", [1]), Series("muted", "y", [2])])["display"] is True


def test_stacking_is_applied_to_both_axes_or_neither():
    url = quickchart_url(["01.01"], [Series("primary", "x", [1], stack="p")], stacked=True)
    scales = json.loads(parse_qs(urlparse(url).query)["c"][0])["options"]["scales"]

    assert scales["x"]["stacked"] is True and scales["y"]["stacked"] is True


def test_an_oversized_config_yields_no_url_rather_than_a_bad_one():
    """The caller drops the image and keeps the panel — a 90-day chart must degrade, not
    produce a URL nobody has tested the length of."""
    labels = [f"{d:02d}.01" for d in range(1, 90)]
    huge = [Series("primary", f"series {i}", list(range(89))) for i in range(6)]

    assert quickchart_url(labels, huge) is None


def test_the_normal_two_week_chart_is_well_inside_the_cap():
    url = quickchart_url([f"{d:02d}.09" for d in range(1, 15)],
                         [Series("primary", "Drops", list(range(14)), stack="p"),
                          Series("muted", "Rises", list(range(14)), stack="p")], stacked=True)

    assert url is not None and len(url) < MAX_CHART_URL_CHARS
