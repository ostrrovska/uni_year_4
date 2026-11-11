"""Lab5 - turn docs/loadtest/lab5/*.json into the report, in both languages.

Same contract as the Lab 3 and Lab 4 renderers: the raw JSON is the record, the document is
generated from it, and no number in the report is typed by hand. Clause 3 asks for the tables,
the graphs and the baseline card to be in the repository; this is what puts them there, and
re-running it after another measurement rewrites every figure that changed.

Three outputs from one pass, so they can never disagree with each other:

    docs/lab5-results.md      the report, English
    docs/lab5-results-ua.md   the same report, Ukrainian
    ui/data/lab5.json         the same data shaped for ui/lab5-report.html

All prose lives in scripts/lab5_text.py. This file holds the structure and the arithmetic and
no sentences at all, which is the only way two language versions stay in step: a figure that
moves, moves in both.

Charts come from scripts/render_lab5_charts.py, which reads the same ui/data/lab5.json. Run it
first, or run `lab5_run.ps1 -Only render`, which does both in order.

Every section degrades to empty when its input is missing, so a partial matrix still renders -
`lab5_run.ps1 -Only scaling` followed by this script produces a report with just that section
rather than an exception.

    python -m scripts.render_lab5_results
"""

import csv
import json
import platform
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.lab5_text import check_parity, translator

RESULTS = Path("docs/loadtest/lab5")
RAW = Path("load-tests/results")
UI_DATA = Path("ui/data/lab5.json")
OUTPUTS = {"en": Path("docs/lab5-results.md"), "uk": Path("docs/lab5-results-ua.md")}
CHARTS = Path("lab5-charts")  # relative to docs/, which is where the reports live

LADDER = [10, 25, 50, 100, 200]
SCENARIOS = ["a", "b", "c"]
SHORT = {"a": "A", "b": "B", "c": "C"}
P95_BUDGET_MS = 500

# Lab 3's scale-out measurement, for comparison. The raw JSON was lost with the rest of the
# Lab 3/4 harness; these are the figures recorded in docs/context/10, and they are labelled as
# Lab 3's wherever they appear rather than mixed into Lab 5's own rows.
LAB3_SCALING = {1: 98.4, 2: 170.8, 3: 208.5, 4: 222.3}


# --------------------------------------------------------------------------- helpers
def load(name: str) -> Any | None:
    """Read one result file. utf-8-sig because PowerShell writes BOMs."""
    path = RESULTS / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def num(value: Any, digits: int = 2) -> str:
    """Format a number, or a dash when the instrument reported nothing.

    A missing sample renders as a gap, never as a zero: a zero is a measurement and would be
    read as one.
    """
    if value is None or value == "":
        return "-"
    try:
        return f"{round(float(value), digits):g}"
    except (TypeError, ValueError):
        return str(value)


def docker_version() -> str:
    try:
        proc = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=15, check=False
        )
        return proc.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def flat(summary: dict) -> dict:
    latency = summary.get("latency_ms") or {}
    return {
        "vus": summary.get("stage_vus"),
        "requests": summary.get("requests"),
        "rps": summary.get("rps") or 0,
        "avg": latency.get("mean"),
        "p50": latency.get("p50"),
        "p90": latency.get("p90"),
        "p95": latency.get("p95"),
        "p99": latency.get("p99"),
        "max": latency.get("max"),
        "errors": summary.get("errors"),
        "error_rate": summary.get("error_rate_percent"),
        "cache_hit_ratio": summary.get("cache_hit_ratio_percent"),
        "config": summary.get("config"),
    }


# The rendered English takeaways, collected as the report is built and handed to
# ui/data/lab5.json so that ui/lab5-report.html shows the same sentence under the same chart.
# Collecting the *rendered* string rather than the key keeps the formatted numbers in it, and
# means the page cannot drift from the document any more than the two documents can drift from
# each other.
TAKEAWAYS: dict[str, str] = {}


def figure(t, name: str, caption_key: str, conclusion_key: str, lang: str) -> list[str]:
    """A chart plus the sentence that says what to see in it.

    Clause 3 asks for graphs; a graph with no reading is decoration. Every chart in this report
    carries its caption and a `What this shows` paragraph, in the report's own language.
    """
    path = f"{CHARTS}/{lang}/{name}.png"
    if not (Path("docs") / CHARTS / lang / f"{name}.png").exists():
        return []
    if lang == "en":
        TAKEAWAYS[conclusion_key] = t(conclusion_key)
    return [
        "",
        f"![{t(caption_key)}]({path})",
        "",
        f"*{t(caption_key)}*",
        "",
        f"{t('doc.means')} {t(conclusion_key)}",
    ]


def means(t, key: str, lang: str = "", **kwargs) -> list[str]:
    rendered = t(key, **kwargs)
    if lang == "en":
        TAKEAWAYS[key] = rendered
    return ["", f"{t('doc.means')} {rendered}"]


# --------------------------------------------------------------------------- environment
def environment(t, lang: str) -> tuple[list[str], dict]:
    applied: dict[str, dict] = {}
    for path in sorted(RESULTS.glob("*.resources.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        for name, info in (data.get("containers") or {}).items():
            applied.setdefault(name, info)

    lines = [
        "",
        f"## {t('env.title')}",
        "",
        t("env.lead"),
        "",
        "| | |",
        "|---|---|",
        f"| Generated | {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} |",
        f"| Host | {platform.platform()} |",
        f"| Python | {platform.python_version()} |",
        f"| Docker | {docker_version()} |",
        "| Load generator | k6, host-native |",
        "| System under test | 3 x API + nginx :8080 + Redis 7 + PostgreSQL 16 |",
        "| Entry point | `http://127.0.0.1:8080` |",
        "| Balancer pool | `pools/3-lab5.conf`, round-robin, `max_fails=0` |",
        "| Connection pool | `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10`, `DB_POOL_TIMEOUT=10s` |",
        "| PostgreSQL | `max_connections=100`, `shared_buffers=256MB`, `pg_stat_statements` |",
        "| Redis | `allkeys-lru`, 256 MB, no persistence; route TTL 10 s, stats TTL 30 s |",
        "| Warm-up | 20 s @ 5 VUs, tagged `phase:warmup`, excluded |",
        "| Measured window | 60 s @ constant concurrency, tagged `phase:measure` |",
    ]

    if applied:
        lines += [
            "",
            t("env.limits_lead"),
            "",
            "| Container | CPUs | Memory | OOM-killed |",
            "|---|---:|---:|---|",
        ]
        for name in sorted(applied):
            info = applied[name]
            short = name.replace("cdn-control-plane-", "").removesuffix("-1")
            oom = "yes" if _any_oom(name) else "no"
            lines.append(
                f"| `{short}` | {num(info.get('cpu_limit'))} | "
                f"{num(info.get('mem_limit_mib'), 0)} {t('unit.mib')} | {oom} |"
            )
    lines += means(t, "env.conclusion", lang=lang)
    return lines, applied


def _any_oom(container: str) -> bool:
    for path in RESULTS.glob("*.resources.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if ((data.get("containers") or {}).get(container) or {}).get("oom_killed"):
            return True
    return False


# --------------------------------------------------------------------------- calibration
def calibration(t, lang: str) -> tuple[list[str], list[dict]]:
    ms, rps = t("unit.ms"), t("unit.rps")
    rows = []
    for label, what in (
        ("calib-lb-200vu", "nginx `/lb-health`"),
        ("calib-health-200vu", "`/health`"),
    ):
        data = load(label)
        if data:
            rows.append({"label": label, "what": what, **flat(data)})
    if not rows:
        return [], []

    lines = [
        "",
        f"## {t('calib.title')}",
        "",
        t("calib.lead"),
        "",
        "| Target | Throughput | p50 | p95 | p99 | Errors |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['what']} | **{num(row['rps'])} {rps}** | {num(row['p50'])} {ms} | "
            f"{num(row['p95'])} {ms} | {num(row['p99'])} {ms} | {row['errors']} |"
        )
    if len(rows) >= 2 and rows[1]["rps"]:
        headroom = rows[0]["rps"] / rows[1]["rps"]
        key = "calib.conclusion_ok" if headroom >= 2 else "calib.conclusion_bad"
        lines += means(
            t,
            key,
            lang=lang,
            headroom=f"{headroom:.1f}",
            lb_rps=num(rows[0]["rps"]),
            app_rps=num(rows[1]["rps"]),
        )
    return lines, rows


# --------------------------------------------------------------------------- clause 2.4
def ladder_tables(t, lang: str) -> tuple[list[str], dict]:
    data: dict[str, list[dict]] = {}
    body: list[str] = []

    for key in SCENARIOS:
        rows = []
        for vus in LADDER:
            summary = load(f"{key}-warm-{vus}vu")
            if not summary:
                continue
            row = flat(summary)
            row["vus"] = vus
            # The ratio is clause 2.4's question made into a number: how much worse is the
            # unluckiest percentile than the median one.
            row["tail_ratio"] = (
                round(row["p99"] / row["p50"], 1) if row["p50"] and row["p99"] else None
            )
            row["pg"] = load(f"{key}-warm-{vus}vu.pg") or {}
            row["resources"] = load(f"{key}-warm-{vus}vu.resources") or {}
            row["iteration_ms"] = summary.get("iteration_ms")
            row["requests_by_op"] = summary.get("requests_by_op") or {}
            statuses = summary.get("status_counts") or {}
            real = sum(
                count
                for code, count in statuses.items()
                if code == "0" or (code.isdigit() and int(code) >= 500 and code != "503")
            )
            row["real_errors"] = real
            row["real_error_rate"] = (
                round(100 * real / row["requests"], 2) if row["requests"] else 0
            )
            rows.append(row)
        if not rows:
            continue
        data[SHORT[key]] = rows

        body += [
            "",
            f"### {t(f'ladder.scenario_{key}')}",
            "",
            t("ladder.headers"),
            t("ladder.align"),
        ]
        for row in rows:
            body.append(
                f"| {row['vus']} | {num(row['rps'])} | {num(row['avg'])} | {num(row['p50'])} | "
                f"{num(row['p95'])} | **{num(row['p99'])}** | {num(row['tail_ratio'], 1)}x | "
                f"{num(row.get('real_error_rate'))} % |"
            )
        body += ["", _ladder_commentary(t, rows)]
        body += _workflow_note(t, rows)

    if not data:
        return [], {}

    lines = ["", f"## {t('ladder.title')}", "", t("ladder.lead")] + body
    lines += figure(t, "throughput", "ladder.chart_caption", "ladder.chart_conclusion", lang)
    lines += figure(
        t, "latency", "ladder.latency_chart_caption", "ladder.latency_chart_conclusion", lang
    )
    return lines, data


def _workflow_note(t, rows: list[dict]) -> list[str]:
    """Scenario C's real number.

    One iteration of the workflow is several HTTP requests, so a per-request percentile
    describes the slowest single call rather than the slowest release. Only emitted where an
    iteration really is more than one request - for A and B the two are the same thing and the
    note would be noise.
    """
    top = rows[-1]
    block = top.get("iteration_ms")
    per_iteration = sum((top.get("requests_by_op") or {}).values())
    iterations = top.get("requests") or 0
    if not block or not per_iteration or not iterations:
        return []
    ratio_base = top.get("p99")
    requests_per_iteration = round(per_iteration / max(iterations, 1), 2)
    if requests_per_iteration < 1.5:
        return []
    return [
        "",
        t(
            "ladder.workflow",
            requests=round(requests_per_iteration),
            p50=num(block.get("p50")),
            p95=num(block.get("p95")),
            p99=num(block.get("p99")),
            vus=top["vus"],
            ratio=num(block["p99"] / ratio_base, 1) if ratio_base and block.get("p99") else "-",
        ),
    ]


def _ladder_commentary(t, rows: list[dict]) -> str:
    first, last = rows[0], rows[-1]
    if not (first["p50"] and last["p50"] and first["rps"]):
        return ""
    rps_growth = last["rps"] / first["rps"]
    text = t(
        "ladder.commentary",
        first_vus=first["vus"],
        last_vus=last["vus"],
        vu_growth=f"{last['vus'] / first['vus']:.0f}",
        rps_growth=f"{rps_growth:.2f}",
        p50_growth=f"{last['p50'] / first['p50']:.1f}",
        p99_growth=(f"{last['p99'] / first['p99']:.1f}" if first["p99"] and last["p99"] else "-"),
    )
    suffix = "ladder.commentary_saturated" if rps_growth < 2 else "ladder.commentary_linear"
    return text + t(suffix)


# --------------------------------------------------------------------------- clause 2.5
def saturation(t, ladder: dict, lang: str) -> tuple[list[str], dict]:
    """Two numbers per scenario, because clause 2.5 asks for two conditions at once.

    The clause defines saturation as the load at which throughput stops growing linearly *and*
    latency and errors begin to climb. On this system those are not the same rung: the
    bottleneck resource is already busy at 10 VUs, so throughput plateaus immediately, while a
    saturated resource with a short queue is still fast and latency stays acceptable far above
    it. Quoting only the plateau would claim the system falls over at 10 VUs; quoting only the
    ceiling would hide that everything past the plateau is pure queueing.
    """
    if not ladder:
        return [], {}

    found = {}
    lines = [
        "",
        f"## {t('sat.title')}",
        "",
        t("sat.lead"),
        "",
        f"* {t('sat.bullet_plateau')}",
        f"* {t('sat.bullet_ceiling', budget=P95_BUDGET_MS)}",
        "",
        t("sat.headers"),
        t("sat.align"),
    ]
    for short, rows in ladder.items():
        plateau = None
        for previous, current in zip(rows, rows[1:], strict=False):
            if not previous["rps"]:
                continue
            gain = (current["rps"] - previous["rps"]) / previous["rps"]
            if gain < 0.10:
                plateau = (previous, gain)
                break
        if plateau is None:
            plateau = (rows[-1], None)
        row, gain = plateau

        usable = None
        for candidate in rows:
            clean = (candidate.get("real_error_rate") or 0) == 0
            if (candidate["p95"] or 1e9) <= P95_BUDGET_MS and clean:
                usable = candidate
        worst_row = max(rows, key=lambda r: r.get("real_error_rate") or 0)
        worst_error = worst_row.get("real_error_rate") or 0

        found[short] = {
            "vus": row["vus"],
            "rps": row["rps"],
            "p95": row["p95"],
            "p99": row["p99"],
            "error_rate": row["error_rate"],
            "next_gain_percent": round(100 * gain, 1) if gain is not None else None,
            "usable_vus": usable["vus"] if usable else None,
            "usable_rps": usable["rps"] if usable else None,
            "usable_p95": usable["p95"] if usable else None,
            "usable_p99": usable["p99"] if usable else None,
            "worst_error_rate": worst_error,
            "worst_error_vus": worst_row["vus"] if worst_error else None,
        }
        lines.append(
            f"| {short} | **{row['vus']} VU** | {num(row['rps'])} {t('unit.rps')} | "
            f"{'+' + num(100 * gain, 1) + ' %' if gain is not None else '-'} | "
            f"**{str(usable['vus']) + ' VU' if usable else '-'}** | "
            f"{num(usable['p95']) if usable else '-'} / "
            f"{num(usable['p99']) if usable else '-'} {t('unit.ms')} | "
            f"{num(worst_error)} % |"
        )

    lines += means(t, "sat.conclusion", lang=lang)
    lines += figure(t, "saturation", "sat.chart_caption", "sat.chart_conclusion", lang)
    lines += _resources(t, ladder, lang)
    return lines, found


def _resources(t, ladder: dict, lang: str) -> list[str]:
    rows = []
    for short, entries in ladder.items():
        top = entries[-1]
        resources = (top.get("resources") or {}).get("resources") or {}
        limits = (top.get("resources") or {}).get("containers") or {}
        for name, usage in sorted(resources.items()):
            limit = (limits.get(name) or {}).get("cpu_limit")
            ceiling = round(100 * limit, 1) if limit else None
            used = usage.get("cpu_percent_mean")
            rows.append(
                {
                    "scenario": short,
                    "container": name.replace("cdn-control-plane-", "").removesuffix("-1"),
                    "cpu_mean": used,
                    "cpu_max": usage.get("cpu_percent_max"),
                    "ceiling": ceiling,
                    "saturation": round(100 * used / ceiling, 1) if used and ceiling else None,
                    "mem_max": usage.get("mem_used_mib_max"),
                }
            )
    if not rows:
        return []

    out = ["", f"### {t('res.title')}", "", t("res.lead"), "", t("res.headers"), t("res.align")]
    for row in rows:
        out.append(
            f"| {row['scenario']} | `{row['container']}` | {num(row['cpu_mean'])} % | "
            f"{num(row['cpu_max'])} % | {num(row['ceiling'])} % | "
            f"**{num(row['saturation'])} %** | {num(row['mem_max'], 0)} {t('unit.mib')} |"
        )

    api = [r for r in rows if r["container"].startswith("api") and r["saturation"]]
    pg = [r for r in rows if r["container"] == "postgres" and r["saturation"]]
    if api and pg:
        out += means(
            t,
            "res.conclusion",
            lang=lang,
            api=num(max(r["saturation"] for r in api)),
            pg=num(max(r["saturation"] for r in pg)),
        )
    return out


# --------------------------------------------------------------------------- clause 2.6
def scaling(t, lang: str) -> tuple[list[str], list[dict]]:
    rows = []
    for count in (1, 3):
        for vus in (50, 100, 200):
            summary = load(f"scale-{count}inst-{vus}vu")
            if not summary:
                continue
            row = flat(summary)
            row["instances"] = count
            row["vus"] = vus
            row["pg"] = load(f"scale-{count}inst-{vus}vu.pg") or {}
            rows.append(row)
    if not rows:
        return [], []

    by_vus: dict[int, dict[int, dict]] = {}
    for row in rows:
        by_vus.setdefault(row["vus"], {})[row["instances"]] = row

    lines = [
        "",
        f"## {t('scale.title')}",
        "",
        t("scale.lead"),
        "",
        t("scale.sef_lead"),
        "",
        t("scale.headers"),
        t("scale.align"),
    ]
    series, speedups = [], []
    for vus in sorted(by_vus):
        base = by_vus[vus].get(1)
        for count in sorted(by_vus[vus]):
            row = by_vus[vus][count]
            speedup = row["rps"] / base["rps"] if base and base["rps"] else None
            sef = 100 * speedup / count if speedup else None
            if count == 3 and speedup:
                speedups.append(speedup)
            conns = (row["pg"].get("connections_after") or {}).get("total")
            lines.append(
                f"| {vus} | {count} | {num(row['rps'])} {t('unit.rps')} | "
                f"{num(speedup, 2) + 'x' if speedup else '-'} | **{num(sef, 1)} %** | "
                f"{num(row['p50'])} | {num(row['p95'])} | {num(row['p99'])} | {row['errors']} | "
                f"{num(conns, 0)} |"
            )
            series.append(
                {
                    "vus": vus,
                    "instances": count,
                    "rps": row["rps"],
                    "p50": row["p50"],
                    "p95": row["p95"],
                    "p99": row["p99"],
                    "errors": row["errors"],
                    "speedup": round(speedup, 3) if speedup else None,
                    "sef_percent": round(sef, 1) if sef else None,
                    "pg_connections": conns,
                }
            )
    if speedups:
        lines += means(
            t, "scale.conclusion", lang=lang, speedup=f"{sum(speedups) / len(speedups):.2f}"
        )
    lines += figure(t, "scaling", "scale.chart_caption", "scale.chart_conclusion", lang)
    return lines, series


def caching(t, lang: str) -> tuple[list[str], list[dict]]:
    arms = [
        ("cache-off-100vu", "Disabled"),
        ("cache-cold-100vu", "Cold"),
        ("cache-warm-100vu", "Warm"),
    ]
    rows = []
    for label, state in arms:
        summary = load(label)
        if not summary:
            continue
        row = flat(summary)
        row["state"] = state
        row["pg"] = load(f"{label}.pg") or {}
        row["by_cache"] = summary.get("latency_ms_by_cache") or {}
        row["server_by_cache"] = summary.get("server_ms_by_cache") or {}
        rows.append(row)
    if not rows:
        return [], []

    lines = [
        "",
        f"## {t('cache.title')}",
        "",
        t("cache.lead"),
        "",
        t("cache.headers"),
        t("cache.align"),
    ]
    for row in rows:
        lines.append(
            f"| **{row['state']}** | {num(row['rps'])} {t('unit.rps')} | {num(row['p50'])} | "
            f"{num(row['p95'])} | {num(row['p99'])} | {num(row['cache_hit_ratio'])} % | "
            f"{row['errors']} |"
        )

    pg_rows = [r for r in rows if r["pg"].get("rows_per_request") is not None]
    if pg_rows:
        lines += [
            "",
            f"### {t('cache.db_title')}",
            "",
            t("cache.db_lead"),
            "",
            t("cache.db_headers"),
            t("cache.db_align"),
        ]
        for row in pg_rows:
            pg, delta = row["pg"], row["pg"].get("database_delta") or {}
            lines.append(
                f"| {row['state']} | {pg.get('requests')} | {delta.get('tup_returned')} | "
                f"**{num(pg.get('rows_per_request'))}** | "
                f"{num(pg.get('buffer_hit_percent'))} % | "
                f"{num(pg.get('tuples_inserted_per_request'), 3)} |"
            )
        off = next((r for r in pg_rows if r["state"] == "Disabled"), None)
        warm = next((r for r in pg_rows if r["state"] == "Warm"), None)
        if off and warm and off["pg"].get("rows_per_request") and off["rps"]:
            reduction = 100 * (1 - warm["pg"]["rows_per_request"] / off["pg"]["rows_per_request"])
            lines += means(
                t,
                "cache.db_conclusion",
                lang=lang,
                reduction=f"{reduction:.1f}",
                throughput=f"{warm['rps'] / off['rps']:.2f}",
            )
    lines += ["", t("cache.caveat")]
    lines += figure(t, "cache", "cache.chart_caption", "cache.chart_conclusion", lang)

    warm = next((r for r in rows if r["state"] == "Warm"), None)
    if warm and warm["by_cache"]:
        lines += [
            "",
            f"### {t('cache.hitmiss_title')}",
            "",
            t("cache.hitmiss_lead"),
            "",
            t("cache.hitmiss_headers"),
            t("cache.hitmiss_align"),
        ]
        for outcome in ("HIT", "MISS", "BYPASS"):
            block = warm["by_cache"].get(outcome)
            if not block:
                continue
            server = (warm["server_by_cache"].get(outcome) or {}).get("p50")
            lines.append(
                f"| `{outcome}` | {block.get('count')} | {num(block.get('p50'))} | "
                f"{num(block.get('p95'))} | {num(block.get('p99'))} | "
                f"{num(block.get('max'))} | {num(server)} |"
            )

    series = [
        {
            "state": r["state"],
            "rps": r["rps"],
            "p50": r["p50"],
            "p95": r["p95"],
            "p99": r["p99"],
            "errors": r["errors"],
            "cache_hit_ratio": r["cache_hit_ratio"],
            "rows_per_request": r["pg"].get("rows_per_request"),
            "buffer_hit_percent": r["pg"].get("buffer_hit_percent"),
            "by_cache": r["by_cache"],
        }
        for r in rows
    ]
    return lines, series


# --------------------------------------------------------------------------- pool probe
def pool_probe(t, lang: str) -> tuple[list[str], list[dict]]:
    ms = t("unit.ms")
    series = []
    for config, prefix in (("10 + 10", "pool10"), ("2 + 0", "pool2")):
        for vus in LADDER:
            summary = load(f"{prefix}-{vus}vu")
            if not summary:
                continue
            ops = summary.get("latency_ms_by_op") or {}
            live, ready = ops.get("live") or {}, ops.get("ready") or {}
            if not live or not ready:
                continue
            series.append(
                {
                    "config": config,
                    "vus": vus,
                    "live_p95": live.get("p95"),
                    "ready_p95": ready.get("p95"),
                    "gap_p95": round((ready.get("p95") or 0) - (live.get("p95") or 0), 2),
                    "live_p99": live.get("p99"),
                    "ready_p99": ready.get("p99"),
                    "gap_p99": round((ready.get("p99") or 0) - (live.get("p99") or 0), 2),
                    "rps": summary.get("rps"),
                    "error_rate": summary.get("error_rate_percent"),
                }
            )
    if not series:
        return [], []

    lines = [
        "",
        f"## {t('pool.title')}",
        "",
        t("pool.lead"),
        "",
        t("pool.lead2"),
        "",
        t("pool.headers"),
        t("pool.align"),
    ]
    for row in series:
        lines.append(
            f"| {row['config']} | {row['vus']} | {num(row['live_p95'])} {t('unit.ms')} | "
            f"{num(row['ready_p95'])} {t('unit.ms')} | **{num(row['gap_p95'])} {t('unit.ms')}** | "
            f"{num(row['gap_p99'])} {t('unit.ms')} | {num(row['error_rate'])} % |"
        )

    shipped = [r for r in series if r["config"].startswith("10")]
    if shipped:
        worst = max(shipped, key=lambda r: r["gap_p95"])
        lines += means(
            t,
            "pool.conclusion",
            lang=lang,
            live_low=num(min(r["live_p95"] for r in shipped)),
            live_high=num(max(r["live_p95"] for r in shipped)),
            ready_high=num(worst["ready_p95"]),
            gap=num(worst["gap_p95"]),
        )
    lines += figure(t, "pool", "pool.chart_caption", "pool.chart_conclusion", lang)

    real = [(v, load(f"a-pool2-{v}vu")) for v in (50, 100, 200)]
    real = [(v, s) for v, s in real if s]
    if real:
        lines += ["", t("pool.real_lead"), "", t("pool.real_headers"), t("pool.real_align")]
        for vus, summary in real:
            pg = load(f"a-pool2-{vus}vu.pg") or {}
            conns = (pg.get("connections_after") or {}).get("total")
            row = flat(summary)
            lines.append(
                f"| {vus} | `/routing/resolve` | {num(row['rps'])} {t('unit.rps')} | "
                f"{num(row['p95'])} {ms} | {num(row['p99'])} {ms} | {row['errors']} | "
                f"{num(conns, 0)} |"
            )
    return lines, series


def conn_release(t, lang: str) -> tuple[list[str], list[dict]]:
    """The early-release experiment, both arms measured on the same host minutes apart."""
    rows = []
    for vus in (25, 100, 200):
        on, off = load(f"release-on-{vus}vu"), load(f"release-off-{vus}vu")
        if not on or not off:
            continue
        gap = lambda s: (  # noqa: E731 - a two-line helper would read worse than this
            ((s.get("latency_ms_by_op") or {}).get("ready") or {}).get("p95", 0)
            - ((s.get("latency_ms_by_op") or {}).get("live") or {}).get("p95", 0)
        )
        rows.append(
            {
                "vus": vus,
                "hold_gap": round(gap(off), 2),
                "release_gap": round(gap(on), 2),
                "hold_rps": off.get("rps"),
                "release_rps": on.get("rps"),
            }
        )
    if not rows:
        return [], []

    lines = [
        "",
        f"## {t('connrel.title')}",
        "",
        t("connrel.lead"),
        "",
        t("connrel.lead2"),
        "",
        t("connrel.headers"),
        t("connrel.align"),
    ]
    ms = t("unit.ms")
    for row in rows:
        change = (
            100 * (row["release_gap"] - row["hold_gap"]) / row["hold_gap"]
            if row["hold_gap"]
            else None
        )
        lines.append(
            f"| {row['vus']} | {num(row['hold_gap'])} {ms} | {num(row['release_gap'])} {ms} | "
            f"**{'+' if change and change > 0 else ''}{num(change, 1)} %** |"
        )
    lines += means(t, "connrel.conclusion", lang=lang)
    return lines, rows


# --------------------------------------------------------------------------- open model
def open_model(t, ladder: dict, lang: str) -> tuple[list[str], dict]:
    rps = t("unit.rps")
    found = None
    for path in sorted(RESULTS.glob("open-*rps.json")):
        try:
            found = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
    if not found:
        return [], {}

    target = found.get("target_rps")
    closed = None
    for row in ladder.get("A") or []:
        if closed is None or abs((row["rps"] or 0) - (target or 0)) < abs(
            (closed["rps"] or 0) - (target or 0)
        ):
            closed = row
    if not closed:
        return [], {}

    opened = flat(found)
    lines = [
        "",
        f"## {t('open.title')}",
        "",
        t("open.lead"),
        "",
        t("open.lead2", target=target),
        "",
        t("open.headers"),
        t("open.align"),
        f"| `ramping-vus` | {closed['vus']} VU | {num(closed['rps'])} {t('unit.rps')} | "
        f"{num(closed['p50'])} | {num(closed['p95'])} | **{num(closed['p99'])}** | "
        f"{closed['errors']} |",
        f"| `constant-arrival-rate` | {target} {rps} | {num(opened['rps'])} {rps} | "
        f"{num(opened['p50'])} | {num(opened['p95'])} | **{num(opened['p99'])}** | "
        f"{opened['errors']} |",
    ]
    dropped = found.get("dropped_iterations")
    if dropped:
        lines += ["", t("open.dropped", dropped=dropped)]
    if closed.get("p99") and opened.get("p99") and target and opened.get("rps"):
        lines += means(
            t,
            "open.conclusion",
            lang=lang,
            ratio=f"{opened['p99'] / closed['p99']:.2f}",
            target=target,
            achieved=num(opened["rps"]),
            shortfall=f"{100 * (1 - opened['rps'] / target):.0f}",
            errors=opened["errors"],
            closed_rps=num(closed["rps"]),
        )
        lines += ["", t("open.conclusion2")]
    lines += figure(t, "open-model", "open.chart_caption", "open.chart_conclusion", lang)
    return lines, {
        "target_rps": target,
        "closed": {k: closed[k] for k in ("vus", "rps", "p50", "p95", "p99", "errors")},
        "open": {k: opened[k] for k in ("rps", "p50", "p95", "p99", "errors")},
        "dropped_iterations": dropped,
    }


# --------------------------------------------------------------------------- timelines
def timeline_section(t, series: dict, lang: str) -> list[str]:
    if not series:
        return []
    out = ["", f"## {t('tl.title')}", "", t("tl.lead")]
    out += figure(t, "timeline", "tl.chart_caption", "tl.chart_conclusion", lang)
    return out


def timelines() -> dict:
    """Per-second series from the ramp runs' raw CSV.

    Read by header name with csv.DictReader, never by column position: k6 has reordered these
    columns between releases, and a positional parser fails silently by producing plausible
    nonsense rather than an error.
    """
    out: dict[str, list[dict]] = {}
    for key in SCENARIOS:
        path = RAW / f"{key}-ramp.csv"
        if not path.exists():
            continue
        buckets: dict[int, dict] = {}
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                # setup() runs outside the measured window and its requests are not load.
                if row.get("group") == "::setup":
                    continue
                try:
                    stamp = int(row["timestamp"])
                    value = float(row["metric_value"])
                except (KeyError, TypeError, ValueError):
                    continue
                bucket = buckets.setdefault(stamp, {"reqs": 0, "errors": 0, "lat": [], "vus": None})
                metric = row.get("metric_name")
                if metric == "http_reqs":
                    bucket["reqs"] += int(value)
                    status = row.get("status") or ""
                    if not status or (status.isdigit() and int(status) >= 400):
                        bucket["errors"] += 1
                elif metric == "req_ms":
                    bucket["lat"].append(value)
                elif metric == "vus":
                    bucket["vus"] = int(value)
        if not buckets:
            continue
        start = min(buckets)
        series = []
        for stamp in sorted(buckets):
            bucket = buckets[stamp]
            lat = sorted(bucket["lat"])
            series.append(
                {
                    "t": stamp - start,
                    "vus": bucket["vus"],
                    "rps": bucket["reqs"],
                    "errors": bucket["errors"],
                    "p50": _pct(lat, 50),
                    "p95": _pct(lat, 95),
                    "p99": _pct(lat, 99),
                }
            )
        out[SHORT[key]] = _fill_vus(series)
    return out


def _pct(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    return round(statistics.quantiles(values, n=100, method="inclusive")[pct - 1], 2)


def _fill_vus(series: list[dict]) -> list[dict]:
    """k6 emits `vus` on its own cadence, so some seconds have no sample. Carrying the last
    value forward is correct - the VU count is a step function - whereas a null would put a
    hole in the x-axis of every chart."""
    last = None
    for point in series:
        if point["vus"] is None:
            point["vus"] = last
        else:
            last = point["vus"]
    return series


# --------------------------------------------------------------------------- verdicts
def verdicts(t, ladder: dict, pool: list[dict], cache: list[dict], ladder_res: dict) -> list[str]:
    lines = [
        "",
        f"## {t('verdict.title')}",
        "",
        t("verdict.lead"),
        "",
        t("verdict.headers"),
        t("verdict.align"),
    ]

    def row(n: int, pred: str, result: str, evidence: str) -> None:
        lines.append(f"| {n} | {pred} | {result} | {evidence} |")

    rows_a, rows_b, rows_c = ladder.get("A") or [], ladder.get("B") or [], ladder.get("C") or []

    if rows_b:
        top = rows_b[-1]
        row(
            1,
            t("verdict.v1"),
            t("verdict.v1_result"),
            t(
                "verdict.v1_evidence",
                vus=top["vus"],
                p50=num(top["p50"]),
                p99=num(top["p99"]),
                ratio=num(top.get("tail_ratio"), 1),
            ),
        )
        hb = next(
            (load(f"b-warm-{v}vu.pg") for v in reversed(LADDER) if load(f"b-warm-{v}vu.pg")), None
        )
        edge = ((hb or {}).get("table_delta") or {}).get("edge_nodes") or {}
        if edge:
            row(
                2,
                t("verdict.v2"),
                t("verdict.v2_result"),
                t(
                    "verdict.v2_evidence",
                    hot=num(edge.get("hot_update_percent"), 1),
                    updates=edge.get("upd"),
                    dead=edge.get("dead_tuples_now"),
                ),
            )

    warm = next((c for c in cache if c["state"] == "Warm"), None)
    off = next((c for c in cache if c["state"] == "Disabled"), None)
    api_pg = ladder_res or {}
    if warm and off and off.get("rows_per_request") and off.get("rps"):
        reduction = 100 * (1 - (warm.get("rows_per_request") or 0) / off["rows_per_request"])
        row(
            3,
            t("verdict.v3"),
            t("verdict.v3_result"),
            t(
                "verdict.v3_evidence",
                reduction=f"{reduction:.1f}",
                speedup=f"{warm['rps'] / off['rps']:.2f}",
                api=num(api_pg.get("api")),
                pg=num(api_pg.get("pg")),
            ),
        )

    if pool:
        w10 = max(
            (p for p in pool if p["config"].startswith("10")),
            key=lambda p: p["gap_p95"],
            default=None,
        )
        w2 = max(
            (p for p in pool if p["config"].startswith("2")),
            key=lambda p: p["gap_p95"],
            default=None,
        )
        if w10 and w2:
            row(
                4,
                t("verdict.v4"),
                t("verdict.v4_result"),
                t(
                    "verdict.v4_evidence",
                    gap10=num(w10["gap_p95"]),
                    vus10=w10["vus"],
                    gap2=num(w2["gap_p95"]),
                    vus2=w2["vus"],
                ),
            )

    if rows_c and rows_a:
        statuses: dict[str, int] = {}
        for vus in LADDER:
            summary = load(f"c-warm-{vus}vu")
            if summary:
                for status, count in (summary.get("status_counts") or {}).items():
                    if status == "0" or int(status) >= 400:
                        statuses[status] = statuses.get(status, 0) + count
        pg_c = load("c-warm-200vu.pg") or {}
        delta = pg_c.get("table_delta") or {}
        replica = (delta.get("asset_replicas") or {}).get("upd")
        publishes = (delta.get("purge_events") or {}).get("ins")
        row(
            5,
            t("verdict.v5"),
            t("verdict.v5_result"),
            t(
                "verdict.v5_evidence",
                breakdown=", ".join(f"{c}x HTTP {s}" for s, c in sorted(statuses.items())),
                a_errors=sum(r["errors"] or 0 for r in rows_a),
                b_errors=sum(r["errors"] or 0 for r in rows_b),
                replica_updates=num(replica, 0),
                publishes=num(publishes, 0),
                per_publish=num(replica / publishes, 1) if replica and publishes else "-",
            ),
        )

    ops = (load("a-warm-200vu") or {}).get("latency_ms_by_op") or {}
    cat, stats_op, res = ops.get("catalogue"), ops.get("stats"), ops.get("resolve")
    if cat and stats_op and res:
        row(
            6,
            t("verdict.v6"),
            t("verdict.v6_result"),
            t(
                "verdict.v6_evidence",
                cat_p50=num(cat["p50"]),
                cat_p99=num(cat["p99"]),
                res_p50=num(res["p50"]),
                stats_p50=num(stats_op["p50"]),
            ),
        )

    lines += ["", t("verdict.unpredicted")]
    return lines


# --------------------------------------------------------------------------- clause 2.7
def baseline_card(t, ladder, sat, cache, applied, pool, lang: str):
    if not ladder or not sat:
        return [], {}

    # The critical scenario is the one that saturates at the lowest throughput: it is the first
    # thing to fail as real traffic grows, which is what makes it critical rather than slowest.
    critical_key, critical = min(sat.items(), key=lambda kv: kv[1]["rps"] or float("inf"))

    stable = None
    for rows in ladder.values():
        for row in rows:
            acceptable = (row["p95"] or 1e9) <= P95_BUDGET_MS and (
                row.get("real_error_rate") or 0
            ) == 0
            if acceptable and (stable is None or (row["rps"] or 0) > (stable["rps"] or 0)):
                stable = row

    worst_key, worst_entry = max(sat.items(), key=lambda kv: kv[1].get("worst_error_rate") or 0)
    worst_error = worst_entry.get("worst_error_rate") or 0
    worst_where = (
        f" @ {worst_entry['worst_error_vus']} VU" if worst_entry.get("worst_error_vus") else ""
    )
    worst_gap = max(pool, key=lambda p: p["gap_p95"], default=None) if pool else None

    api = applied.get("cdn-control-plane-api1-1") or {}
    pg = applied.get("cdn-control-plane-postgres-1") or {}
    ceilings = ", ".join(f"{k} {v.get('usable_vus') or '-'}" for k, v in sat.items())

    card = {
        "environment_config": (
            f"{num(api.get('cpu_limit'))} CPU / {num(api.get('mem_limit_mib'), 0)} MiB x 3 API "
            f"+ nginx; PostgreSQL {num(pg.get('cpu_limit'))} CPU / "
            f"{num(pg.get('mem_limit_mib'), 0)} MiB, max_connections 100; Redis 256 MB "
            f"allkeys-lru; pool 10+10 per instance"
        ),
        "stable_throughput": (
            f"{num(stable['rps'])} req/s @ {stable['vus']} VU "
            f"(p95 {num(stable['p95'])} ms, 0 errors)"
            if stable
            else "-"
        ),
        "saturation_point": (
            f"plateau {critical['vus']} VU / {num(critical['rps'])} req/s (Scenario "
            f"{critical_key}); usable ceiling by scenario: {ceilings} VU"
        ),
        "p95_p99_latency": (
            f"p95 {num(stable['p95'])} ms / p99 {num(stable['p99'])} ms" if stable else "-"
        ),
        "error_rate": (
            f"{num(worst_error)} % worst on the ladder (Scenario {worst_key}{worst_where})"
        ),
        "critical_scenario": f"{critical_key}",
        "primary_bottleneck": (
            "SQLAlchemy connection pool wait on the API tier"
            + (f" (up to {num(worst_gap['gap_p95'])} ms of p95)" if worst_gap else "")
        ),
    }

    width = 21
    block = [
        "=== SYSTEM PERFORMANCE BASELINE ===",
        f"{'Environment Config:':<{width}}{card['environment_config']}",
        f"{'Stable Throughput:':<{width}}{card['stable_throughput']}",
        f"{'Saturation Point:':<{width}}{card['saturation_point']}",
        f"{'p95 / p99 Latency:':<{width}}{card['p95_p99_latency']}",
        f"{'Error Rate:':<{width}}{card['error_rate']}",
        f"{'Critical Scenario:':<{width}}{card['critical_scenario']}",
        f"{'Primary Bottleneck:':<{width}}{card['primary_bottleneck']}",
    ]
    lines = ["", f"## {t('base.title')}", "", "```", *block, "```"]
    lines += means(t, "base.conclusion", lang=lang)
    lines += means(t, "base.error_caveat", lang=lang)
    warm = next((c for c in cache if c["state"] == "Warm"), None)
    off = next((c for c in cache if c["state"] == "Disabled"), None)
    if warm and off:
        lines += ["", t("base.cache_note", warm=num(warm["rps"]), off=num(off["rps"]))]
    lines += ["", f"## {t('limits.title')}", "", t("limits.body")]
    return lines, card


# --------------------------------------------------------------------------- main
def main() -> None:
    problems = check_parity()
    if problems:
        raise SystemExit("lab5_text.py is not in parity:\n  " + "\n  ".join(problems))

    series = timelines()
    model = {}

    for lang, output in OUTPUTS.items():
        t = translator(lang)
        env_lines, applied = environment(t, lang)
        calib_lines, calib = calibration(t, lang)
        ladder_lines, ladder = ladder_tables(t, lang)
        sat_lines, sat = saturation(t, ladder, lang)
        scale_lines, scale = scaling(t, lang)
        cache_lines, cache = caching(t, lang)
        pool_lines, pool = pool_probe(t, lang)
        connrel_lines, connrel = conn_release(t, lang)
        open_lines, open_data = open_model(t, ladder, lang)
        tl_lines = timeline_section(t, series, lang)

        # The API-vs-PostgreSQL saturation pair is computed inside the resources table; verdict
        # #3 needs the same two numbers, so they are recovered here rather than recomputed.
        api_pg = _api_pg(ladder)
        verdict_lines = verdicts(t, ladder, pool, cache, api_pg)
        card_lines, card = baseline_card(t, ladder, sat, cache, applied, pool, lang)

        parts = [
            "<!-- Lab5 -->",
            f"# {t('doc.title')}",
            "",
            t("doc.lead"),
            "",
            t("doc.links"),
            *env_lines,
            *calib_lines,
            *ladder_lines,
            *sat_lines,
            *scale_lines,
            *cache_lines,
            *pool_lines,
            *tl_lines,
            *open_lines,
            *verdict_lines,
            *card_lines,
            "",
        ]
        output.write_text("\n".join(parts) + "\n", encoding="utf-8")
        print(f"wrote {output}")

        if lang == "en":
            model = {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "host": platform.platform(),
                "limits": applied,
                "calibration": calib,
                "ladder": {
                    k: [{x: r[x] for x in r if x not in ("pg", "resources")} for r in rows]
                    for k, rows in ladder.items()
                },
                "saturation": sat,
                "scaling": scale,
                "caching": cache,
                "pool": pool,
                "conn_release": connrel,
                "open_model": open_data,
                "timelines": series,
                "baseline": card,
                "lab3_scaling": LAB3_SCALING,
                "takeaways": dict(TAKEAWAYS),
            }

    UI_DATA.parent.mkdir(parents=True, exist_ok=True)
    UI_DATA.write_text(json.dumps(model, indent=2), encoding="utf-8")
    print(f"wrote {UI_DATA}")


def _api_pg(ladder: dict) -> dict:
    api, pg = [], []
    for entries in ladder.values():
        resources = entries[-1].get("resources") or {}
        limits = resources.get("containers") or {}
        for name, usage in (resources.get("resources") or {}).items():
            limit = (limits.get(name) or {}).get("cpu_limit")
            used = usage.get("cpu_percent_mean")
            if not (limit and used):
                continue
            share = 100 * used / (100 * limit)
            short = name.replace("cdn-control-plane-", "").removesuffix("-1")
            (api if short.startswith("api") else pg if short == "postgres" else []).append(share)
    return {"api": round(max(api), 1) if api else None, "pg": round(max(pg), 1) if pg else None}


if __name__ == "__main__":
    main()
