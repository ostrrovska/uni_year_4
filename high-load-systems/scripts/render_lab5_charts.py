"""Lab5 - render the report charts as PNG from the measured JSON.

Clause 3 asks for graphs of throughput, latency percentiles and error rates in the repository,
not only on a page that needs the stack running. These are generated from exactly the same
ui/data/lab5.json that scripts/render_lab5_results.py reads, so a chart and the table beside it
can never disagree - and like every other number in this lab, nothing here is typed by hand.

Two language variants, because docs/lab5-results.md and docs/lab5-results-ua.md are the same
report and a chart with English axes inside a Ukrainian document is half-translated work.

    python -m scripts.render_lab5_charts              # both languages
    python -m scripts.render_lab5_charts --lang uk

Design follows the same rules as the web page, and for the same reasons:

* One y-axis per panel. Two measures of different units get two stacked panels sharing the
  x-axis - never two scales on one frame, which invites a comparison that means nothing.
* Colour follows the entity: Scenario A is always the blue slot, B orange, C green; p50/p95/p99
  keep their slots in every chart they appear in.
* A legend whenever two or more series are plotted, plus a direct label at the end of each line.
  The green slot measures 2.74:1 against this surface, below the 3:1 contrast floor, so identity
  may never rest on hue alone - that direct label is the required relief.
* Grid lines on the value axis only, recessive; no top or right spine.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

# Before pyplot, always: the renderer must work headless, in CI and over SSH.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

DATA = Path("ui/data/lab5.json")
OUT_ROOT = Path("docs/lab5-charts")

# The repo's validated palette, from ui/styles.css. Light mode only: these are embedded in
# Markdown, and a chart that assumes the reader's theme gets it wrong half the time.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#77756e"
GRID = "#ececea"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
CRITICAL = "#d03b3b"

SCENARIO_SLOT = {"A": 0, "B": 1, "C": 2}
PCT_SLOT = {"p50": 0, "p95": 1, "p99": 2}

TEXT = {
    "en": {
        "vus": "virtual users (VUs)",
        "rps": "requests / second",
        "latency": "latency, ms",
        "latency_log": "latency, ms (log scale)",
        "errors": "error rate, %",
        "linear": "linear",
        "knee": "plateau",
        "scenario": "Scenario",
        "throughput_title": "Throughput against offered concurrency",
        "latency_title": "Median against tail latency",
        "knee_title": "Saturation: throughput above, errors below",
        "scaling_title": "One instance against three (cache disabled)",
        "scaling_y": "throughput, req/s",
        "sef_title": "Scalability Efficiency Factor at three instances",
        "sef_y": "efficiency, % (100 % = linear)",
        "cache_title": "Latency by cache state, 100 VUs",
        "cache_db_title": "Load on PostgreSQL, from its own counters",
        "cache_db_y": "rows returned per request",
        "pool_title": "Pool-acquire latency, isolated by the control pair",
        "pool_live": "/health - no pool",
        "pool_ready": "/health/ready - one pooled SELECT 1",
        "pool_y": "p95, ms",
        "timeline_title": "The staged ramp, second by second",
        "timeline_x": "seconds into the run",
        "open_title": "Closed model against open model",
        "open_closed": "closed (ramping-vus)",
        "open_open": "open (constant-arrival-rate)",
        "instances_1": "1 instance",
        "instances_3": "3 instances",
        "cache_off": "Disabled",
        "cache_cold": "Cold",
        "cache_warm": "Warm",
        "pool_shipped": "pool 10+10 (shipped)",
        "pool_starved": "pool 2+0 (starved)",
    },
    "uk": {
        "vus": "віртуальні користувачі, VU",
        "rps": "запитів / секунду",
        "latency": "затримка, мс",
        "latency_log": "затримка, мс (лог. шкала)",
        "errors": "частка помилок, %",
        "linear": "лінійне",
        "knee": "плато",
        "scenario": "Сценарій",
        "throughput_title": "Пропускна здатність залежно від навантаження",
        "latency_title": "Медіана проти хвоста затримок",
        "knee_title": "Насичення: пропускна здатність угорі, помилки внизу",
        "scaling_title": "Один інстанс проти трьох, кеш вимкнено",
        "scaling_y": "пропускна здатність, запитів/с",
        "sef_title": "Ефективність масштабування на трьох інстансах",
        "sef_y": "ефективність, % (100 % = лінійне)",
        "cache_title": "Затримка за станом кешу, 100 VU",
        "cache_db_title": "Навантаження на PostgreSQL за його лічильниками",
        "cache_db_y": "рядків повернуто на запит",
        "pool_title": "Очікування з'єднання з пулу, виділене контрольною парою",
        "pool_live": "/health - без пулу",
        "pool_ready": "/health/ready - один SELECT 1 з пулу",
        "pool_y": "p95, мс",
        "timeline_title": "Ступеневе нарощування навантаження, посекундно",
        "timeline_x": "секунд від початку прогону",
        "open_title": "Закрита модель проти відкритої",
        "open_closed": "закрита (ramping-vus)",
        "open_open": "відкрита (constant-arrival-rate)",
        "instances_1": "1 інстанс",
        "instances_3": "3 інстанси",
        "cache_off": "Вимкнено",
        "cache_cold": "Холодний",
        "cache_warm": "Теплий",
        "pool_shipped": "пул 10+10 (штатний)",
        "pool_starved": "пул 2+0 (звужений)",
    },
}


def style(ax, *, title=None, xlabel=None, ylabel=None, grid_axis="y"):
    """The house chart frame: recessive grid on the value axis, no top or right spine."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=MUTED, labelsize=9, length=3, width=0.8)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=INK, fontsize=11, loc="left", pad=10, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_2, fontsize=9)


def direct_label(ax, x, y, text, colour):
    """A label at the end of a line. The legend says which colour is which; this says it again
    in text, which is what keeps identity off colour alone for the low-contrast slot."""
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(5, 0),
        textcoords="offset points",
        color=INK_2,
        fontsize=8.5,
        va="center",
        fontweight="bold",
    )


def save(fig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"  {out}")


def bar_values(ax, bars, fmt="{:.0f}"):
    for bar in bars:
        height = bar.get_height()
        if height is None:
            continue
        ax.annotate(
            fmt.format(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            color=INK_2,
        )


# --------------------------------------------------------------------------- charts
def chart_throughput(data, t, out: Path) -> None:
    ladder = data.get("ladder") or {}
    if not ladder:
        return
    fig, ax = plt.subplots(figsize=(7.2, 3.6), facecolor=SURFACE)
    for key, rows in ladder.items():
        colour = SERIES[SCENARIO_SLOT[key]]
        xs = [r["vus"] for r in rows]
        ys = [r["rps"] for r in rows]
        ax.plot(
            xs,
            ys,
            color=colour,
            linewidth=2,
            marker="o",
            markersize=5,
            markeredgecolor=SURFACE,
            markeredgewidth=1.2,
            label=f"{t['scenario']} {key}",
        )
        direct_label(ax, xs[-1], ys[-1], key, colour)

    first_key = next(iter(ladder))
    base = ladder[first_key][0]
    xs = [r["vus"] for r in ladder[first_key]]
    ref = [(base["rps"] / base["vus"]) * x for x in xs]
    ceiling = max(r["rps"] for rows in ladder.values() for r in rows) * 1.15
    # Keep the first point past the ceiling as well, so the line is drawn all the way to the
    # top edge and is then clipped by the axis limit. Dropping it left a single point and no
    # line at all: linear scaling from the first rung reaches 20x the measured peak by 200 VUs,
    # so every projected point but the first is off the chart.
    ref_x, ref_y = [], []
    for x, y in zip(xs, ref, strict=False):
        ref_x.append(x)
        ref_y.append(y)
        if y > ceiling:
            break
    if len(ref_x) >= 2:
        ax.plot(ref_x, ref_y, color=MUTED, linewidth=1, linestyle=(0, (4, 4)), clip_on=True)
        label_y = min(ref_y[-1], ceiling * 0.97)
        direct_label(ax, ref_x[-1], label_y, t["linear"], MUTED)

    ax.set_ylim(0, ceiling)
    style(ax, title=t["throughput_title"], xlabel=t["vus"], ylabel=t["rps"])
    ax.set_xticks(xs)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="lower right")
    save(fig, out)


def chart_latency(data, t, out: Path) -> None:
    ladder = data.get("ladder") or {}
    if not ladder:
        return
    fig, axes = plt.subplots(1, len(ladder), figsize=(10.5, 3.4), facecolor=SURFACE, sharey=True)
    axes = axes if hasattr(axes, "__len__") else [axes]
    for ax, (key, rows) in zip(axes, ladder.items(), strict=False):
        xs = [r["vus"] for r in rows]
        for pct in ("p50", "p95", "p99"):
            colour = SERIES[PCT_SLOT[pct]]
            ys = [r[pct] for r in rows]
            ax.plot(
                xs,
                ys,
                color=colour,
                linewidth=2,
                marker="o",
                markersize=4,
                markeredgecolor=SURFACE,
                markeredgewidth=1,
                label=pct,
            )
            direct_label(ax, xs[-1], ys[-1], pct, colour)
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        style(
            ax,
            title=f"{t['scenario']} {key}",
            xlabel=t["vus"],
            ylabel=t["latency_log"] if ax is axes[0] else None,
        )
        ax.set_xticks(xs)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper left")
    fig.suptitle(
        t["latency_title"], color=INK, fontsize=11.5, x=0.005, ha="left", fontweight="bold"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, out)


def chart_knee(data, t, out: Path) -> None:
    ladder = data.get("ladder") or {}
    sat = data.get("saturation") or {}
    if not ladder:
        return
    # Two stacked panels sharing the x-axis rather than one frame with two y-scales: req/s and
    # per cent are unrelated units and overlaying them would invite a meaningless comparison.
    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(7.2, 4.8),
        facecolor=SURFACE,
        sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    for key, rows in ladder.items():
        colour = SERIES[SCENARIO_SLOT[key]]
        xs = [r["vus"] for r in rows]
        top.plot(
            xs,
            [r["rps"] for r in rows],
            color=colour,
            linewidth=2,
            marker="o",
            markersize=5,
            markeredgecolor=SURFACE,
            markeredgewidth=1.2,
            label=f"{t['scenario']} {key}",
        )
        bottom.plot(
            xs,
            [r.get("real_error_rate", r["error_rate"]) for r in rows],
            color=colour,
            linewidth=2,
            marker="o",
            markersize=4,
            markeredgecolor=SURFACE,
            markeredgewidth=1,
        )
    knee = (sat.get(next(iter(ladder))) or {}).get("vus")
    if knee:
        for ax in (top, bottom):
            ax.axvline(knee, color=CRITICAL, linewidth=1, linestyle=(0, (3, 3)))
        top.annotate(
            t["knee"],
            xy=(knee, top.get_ylim()[1]),
            xytext=(4, -12),
            textcoords="offset points",
            color=CRITICAL,
            fontsize=8.5,
        )
    style(top, title=t["knee_title"], ylabel=t["rps"])
    style(bottom, xlabel=t["vus"], ylabel=t["errors"])
    bottom.set_xticks([r["vus"] for r in next(iter(ladder.values()))])
    top.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="lower right")
    fig.tight_layout()
    save(fig, out)


def chart_scaling(data, t, out: Path) -> None:
    rows = data.get("scaling") or []
    if not rows:
        return
    vus = sorted({r["vus"] for r in rows})
    one = [next((r["rps"] for r in rows if r["vus"] == v and r["instances"] == 1), 0) for v in vus]
    three = [
        next((r["rps"] for r in rows if r["vus"] == v and r["instances"] == 3), 0) for v in vus
    ]
    sef = [
        next((r["sef_percent"] for r in rows if r["vus"] == v and r["instances"] == 3), 0)
        for v in vus
    ]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 3.6), facecolor=SURFACE)
    width = 0.36
    idx = range(len(vus))
    b1 = left.bar(
        [i - width / 2 for i in idx],
        one,
        width,
        color=SERIES[0],
        label=t["instances_1"],
        edgecolor=SURFACE,
        linewidth=1.5,
    )
    b2 = left.bar(
        [i + width / 2 for i in idx],
        three,
        width,
        color=SERIES[1],
        label=t["instances_3"],
        edgecolor=SURFACE,
        linewidth=1.5,
    )
    bar_values(left, b1)
    bar_values(left, b2)
    left.set_xticks(list(idx))
    left.set_xticklabels([f"{v} VU" for v in vus])
    style(left, title=t["scaling_title"], ylabel=t["scaling_y"])
    left.legend(frameon=False, fontsize=9, labelcolor=INK_2)

    b3 = right.bar(list(idx), sef, 0.5, color=SERIES[2], edgecolor=SURFACE, linewidth=1.5)
    bar_values(right, b3, "{:.1f}")
    right.axhline(100, color=MUTED, linewidth=1, linestyle=(0, (4, 4)))
    right.set_ylim(0, 115)
    right.set_xticks(list(idx))
    right.set_xticklabels([f"{v} VU" for v in vus])
    style(right, title=t["sef_title"], ylabel=t["sef_y"])
    fig.tight_layout()
    save(fig, out)


def chart_cache(data, t, out: Path) -> None:
    rows = data.get("caching") or []
    if not rows:
        return
    names = {"Disabled": t["cache_off"], "Cold": t["cache_cold"], "Warm": t["cache_warm"]}
    labels = [names.get(r["state"], r["state"]) for r in rows]
    idx = range(len(rows))

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 3.6), facecolor=SURFACE)
    width = 0.26
    for offset, pct in zip((-width, 0, width), ("p50", "p95", "p99"), strict=False):
        bars = left.bar(
            [i + offset for i in idx],
            [r[pct] for r in rows],
            width,
            color=SERIES[PCT_SLOT[pct]],
            label=pct,
            edgecolor=SURFACE,
            linewidth=1.2,
        )
        bar_values(left, bars)
    left.set_xticks(list(idx))
    left.set_xticklabels(labels)
    style(left, title=t["cache_title"], ylabel=t["latency"])
    left.legend(frameon=False, fontsize=9, labelcolor=INK_2)

    db = [r.get("rows_per_request") or 0 for r in rows]
    bars = right.bar(list(idx), db, 0.5, color=SERIES[1], edgecolor=SURFACE, linewidth=1.5)
    bar_values(right, bars, "{:.1f}")
    right.set_xticks(list(idx))
    right.set_xticklabels(labels)
    style(right, title=t["cache_db_title"], ylabel=t["cache_db_y"])
    fig.tight_layout()
    save(fig, out)


def chart_pool(data, t, out: Path) -> None:
    rows = data.get("pool") or []
    if not rows:
        return
    configs = []
    for row in rows:
        if row["config"] not in configs:
            configs.append(row["config"])
    names = {configs[0]: t["pool_shipped"]}
    if len(configs) > 1:
        names[configs[1]] = t["pool_starved"]

    fig, axes = plt.subplots(1, len(configs), figsize=(10.5, 3.5), facecolor=SURFACE, sharey=True)
    axes = axes if hasattr(axes, "__len__") else [axes]
    for ax, config in zip(axes, configs, strict=False):
        subset = sorted([r for r in rows if r["config"] == config], key=lambda r: r["vus"])
        xs = [r["vus"] for r in subset]
        live = [r["live_p95"] for r in subset]
        ready = [r["ready_p95"] for r in subset]
        ax.plot(
            xs,
            live,
            color=SERIES[0],
            linewidth=2,
            marker="o",
            markersize=4,
            markeredgecolor=SURFACE,
            markeredgewidth=1,
            label=t["pool_live"],
        )
        ax.plot(
            xs,
            ready,
            color=SERIES[1],
            linewidth=2,
            marker="o",
            markersize=4,
            markeredgecolor=SURFACE,
            markeredgewidth=1,
            label=t["pool_ready"],
        )
        # The gap is the measurement, so it is drawn rather than left to be inferred.
        ax.fill_between(xs, live, ready, color=SERIES[1], alpha=0.12)
        direct_label(ax, xs[-1], live[-1], "/health", SERIES[0])
        direct_label(ax, xs[-1], ready[-1], "/ready", SERIES[1])
        style(
            ax,
            title=names.get(config, config),
            xlabel=t["vus"],
            ylabel=t["pool_y"] if ax is axes[0] else None,
        )
        ax.set_xticks(xs)
    axes[0].legend(frameon=False, fontsize=8.5, labelcolor=INK_2, loc="upper left")
    fig.suptitle(t["pool_title"], color=INK, fontsize=11.5, x=0.005, ha="left", fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    save(fig, out)


def chart_timeline(data, t, out: Path) -> None:
    timelines = data.get("timelines") or {}
    if not timelines:
        return
    key = next(iter(timelines))
    points = timelines[key]
    fig, (a, b, c) = plt.subplots(
        3,
        1,
        figsize=(7.6, 6.0),
        facecolor=SURFACE,
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1.4, 1.6]},
    )
    xs = [p["t"] for p in points]
    a.step(xs, [p["vus"] for p in points], color=SERIES[2], linewidth=1.6, where="post")
    style(a, title=f"{t['timeline_title']} - {t['scenario']} {key}", ylabel="VU")
    b.plot(xs, [p["rps"] for p in points], color=SERIES[0], linewidth=1.2)
    style(b, ylabel=t["rps"])
    for pct in ("p50", "p95", "p99"):
        c.plot(xs, [p[pct] for p in points], color=SERIES[PCT_SLOT[pct]], linewidth=1.2, label=pct)
    c.set_yscale("log")
    c.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    style(c, xlabel=t["timeline_x"], ylabel=t["latency_log"])
    c.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper left")
    fig.tight_layout()
    save(fig, out)


def chart_open(data, t, out: Path) -> None:
    model = data.get("open_model") or {}
    closed, opened = model.get("closed"), model.get("open")
    if not closed or not opened:
        return
    fig, ax = plt.subplots(figsize=(6.4, 3.6), facecolor=SURFACE)
    idx = range(3)
    width = 0.36
    pcts = ("p50", "p95", "p99")
    b1 = ax.bar(
        [i - width / 2 for i in idx],
        [closed[p] for p in pcts],
        width,
        color=SERIES[0],
        label=t["open_closed"],
        edgecolor=SURFACE,
        linewidth=1.5,
    )
    b2 = ax.bar(
        [i + width / 2 for i in idx],
        [opened[p] for p in pcts],
        width,
        color=SERIES[1],
        label=t["open_open"],
        edgecolor=SURFACE,
        linewidth=1.5,
    )
    bar_values(ax, b1)
    bar_values(ax, b2)
    ax.set_xticks(list(idx))
    ax.set_xticklabels(pcts)
    style(ax, title=t["open_title"], ylabel=t["latency"])
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper left")
    fig.tight_layout()
    save(fig, out)


CHARTS = {
    "throughput": chart_throughput,
    "latency": chart_latency,
    "saturation": chart_knee,
    "scaling": chart_scaling,
    "cache": chart_cache,
    "pool": chart_pool,
    "timeline": chart_timeline,
    "open-model": chart_open,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Lab 5 charts from the measured JSON.")
    parser.add_argument("--lang", choices=["en", "uk", "both"], default="both")
    args = parser.parse_args()

    if not DATA.exists():
        print(f"{DATA} is missing - run ./scripts/lab5_run.ps1 first", file=sys.stderr)
        return 1
    data = json.loads(DATA.read_text(encoding="utf-8-sig"))

    languages = ["en", "uk"] if args.lang == "both" else [args.lang]
    for lang in languages:
        print(f"{lang}:")
        for name, fn in CHARTS.items():
            fn(data, TEXT[lang], OUT_ROOT / lang / f"{name}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
