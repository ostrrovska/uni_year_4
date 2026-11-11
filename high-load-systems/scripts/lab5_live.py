"""Lab5 - the little HTTP runner behind the "Run live" button on the Lab 5 report page.

A defence prop, and scoped like one. The graded measurements come from scripts/lab5_run.ps1;
this exists so that a 60-second slice of the same k6 script can be started from the browser and
watched filling in, instead of the defence being a reading of numbers measured an hour earlier.

What it is NOT: part of the control plane. It lives in scripts/, never in app/, it is not in the
image, no compose file starts it, and nothing in the system depends on it. Three deliberate
limits, because a browser-triggered subprocess deserves them:

  * exactly one hardcoded profile. The browser sends no arguments at all - no script path, no VU
    count, no URL - so there is nothing for a request to inject into a command line.
  * one run at a time, and it refuses while one is in flight.
  * it writes to memory only. The committed results under docs/loadtest/lab5/ are never touched,
    so a live demo cannot overwrite the measurements the report is built from.

How the live numbers arrive: k6 is started with `--out json=-` and its stdout is read line by
line on a background thread. Each line is one metric point with a timestamp, so bucketing by
second gives requests/s, the latency percentiles and the VU count as the run proceeds. That is
the same data `--out csv` writes for the ramp runs, read live instead of afterwards.

    python -m scripts.lab5_live            # listens on 127.0.0.1:8099
    python -m scripts.lab5_live --port 9000 --base-url http://127.0.0.1:8080
"""

import argparse
import json
import shutil
import statistics
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The one profile the button can start. 10 -> 50 -> 100 VUs, 15 s each, no warm-up scenario, so
# the whole thing is about 55 s of wall clock - short enough to watch, long enough for the
# ramp's shape to be the point.
PROFILE = {
    "name": "short ladder 10 -> 50 -> 100 VUs, 15 s each",
    "script": "load-tests/scenario-a-read.js",
    "stages": [(10, 15), (50, 15), (100, 15)],
}

ROOT = Path(__file__).resolve().parent.parent


class Runner:
    """Owns the subprocess and the rolling per-second state. One instance, guarded by a lock."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.lock = threading.Lock()
        self.state = "idle"
        self.buckets: dict[int, dict] = {}
        self.started_at: float | None = None
        self.process: subprocess.Popen | None = None
        self.message = ""

    # ------------------------------------------------------------------ public
    def snapshot(self) -> dict:
        with self.lock:
            points = self._points()
            requests = sum(b["reqs"] for b in self.buckets.values())
            errors = sum(b["errors"] for b in self.buckets.values())
            return {
                "state": self.state,
                "profile": PROFILE["name"],
                "message": self.message,
                "points": points,
                "requests": requests,
                "errors": errors,
                "peak_rps": max((p["rps"] for p in points), default=0),
                "summary": {"requests": requests, "errors": errors},
            }

    def start(self) -> tuple[bool, str]:
        with self.lock:
            if self.state == "running":
                return False, "a run is already in flight"
            if not shutil.which("k6"):
                return False, "k6 is not on PATH"
            self.buckets = {}
            self.state = "running"
            self.message = ""
            self.started_at = time.time()
        threading.Thread(target=self._run, daemon=True).start()
        return True, "started"

    # ------------------------------------------------------------------ internals
    def _points(self) -> list[dict]:
        if not self.buckets:
            return []
        # The newest second is still being filled, so its request count is an undercount and
        # would draw as a dip at the right-hand edge of every chart. Drop it while running.
        stamps = sorted(self.buckets)
        if self.state == "running" and len(stamps) > 1:
            stamps = stamps[:-1]
        start = stamps[0]
        out = []
        last_vus = None
        for stamp in stamps:
            bucket = self.buckets[stamp]
            latencies = sorted(bucket["lat"])
            if bucket["vus"] is not None:
                last_vus = bucket["vus"]
            out.append(
                {
                    "t": stamp - start,
                    "rps": bucket["reqs"],
                    "errors": bucket["errors"],
                    "vus": bucket["vus"] if bucket["vus"] is not None else last_vus,
                    "p50": _pct(latencies, 50),
                    "p95": _pct(latencies, 95),
                }
            )
        return out

    def _command(self) -> list[str]:
        stages = ",".join(f"{vus}:{seconds}" for vus, seconds in PROFILE["stages"])
        return [
            "k6",
            "run",
            PROFILE["script"],
            "-e",
            f"BASE_URL={self.base_url}",
            "-e",
            "LABEL=live-demo",
            "-e",
            "CONFIG=live",
            # No warm-up scenario and no committed summary: SUMMARY_DIR points into a scratch
            # folder so handleSummary cannot land on top of a measured result.
            "-e",
            "WARMUP_SECONDS=0",
            "-e",
            f"MEASURE_SECONDS={sum(s for _, s in PROFILE['stages'])}",
            # LIVE_STAGES is what makes this a ladder; STAGE is never sent, so the flat-run
            # path in lib/config.js cannot be reached from the browser.
            "-e",
            "SUMMARY_DIR=load-tests/results/live",
            "-e",
            f"LIVE_STAGES={stages}",
            "--out",
            "json=-",
            "--no-usage-report",
            "--quiet",
        ]

    def _run(self) -> None:
        (ROOT / "load-tests" / "results" / "live").mkdir(parents=True, exist_ok=True)
        try:
            process = subprocess.Popen(
                self._command(),
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, FileNotFoundError) as exc:
            with self.lock:
                self.state = "failed"
                self.message = f"could not start k6: {exc}"
            return

        self.process = process
        for line in process.stdout:
            self._ingest(line)
        process.wait()
        with self.lock:
            self.state = "finished" if process.returncode in (0, 99) else "failed"
            if self.state == "failed":
                self.message = f"k6 exited {process.returncode}"

    def _ingest(self, line: str) -> None:
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if event.get("type") != "Point":
            return
        metric = event.get("metric")
        data = event.get("data") or {}
        value = data.get("value")
        stamp = data.get("time")
        if value is None or not stamp:
            return
        tags = data.get("tags") or {}
        if tags.get("group") == "::setup":
            return
        try:
            # ISO-8601 with sub-second precision; the second is all this needs.
            second = int(time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")))
        except (ValueError, TypeError):
            return

        with self.lock:
            bucket = self.buckets.setdefault(
                second, {"reqs": 0, "errors": 0, "lat": [], "vus": None}
            )
            if metric == "http_reqs":
                bucket["reqs"] += int(value)
                status = str(tags.get("status") or "")
                if not status or (status.isdigit() and int(status) >= 400):
                    bucket["errors"] += 1
            elif metric == "req_ms":
                bucket["lat"].append(float(value))
            elif metric == "vus":
                bucket["vus"] = int(value)


def _pct(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    return round(statistics.quantiles(values, n=100, method="inclusive")[pct - 1], 2)


class Handler(BaseHTTPRequestHandler):
    runner: Runner

    # nginx proxies /lab5/ here so the page stays same-origin, but the header is sent anyway:
    # opening ui/lab5-report.html straight off disk is a reasonable thing to do while
    # developing, and without it the fetch fails with a message about CORS rather than about
    # whatever actually went wrong.
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's interface
        path = self.path.rstrip("/") or "/"
        if path in ("/status", "/"):
            self._send(200, {"ok": True, "profile": PROFILE["name"], "state": self.runner.state})
        elif path == "/live":
            self._send(200, self.runner.snapshot())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/run":
            self._send(404, {"error": "not found"})
            return
        # The body is not read and not parsed. There is one profile and the browser cannot
        # choose anything, which is the whole security model.
        started, message = self.runner.start()
        self._send(202 if started else 409, {"started": started, "message": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, *_args) -> None:
        """Silence the per-request access log: the page polls twice a second."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Live k6 runner for the Lab 5 defence page.")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    Handler.runner = Runner(args.base_url)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"lab5 live runner on http://{args.host}:{args.port} -> SUT {args.base_url}")
    print(f"profile: {PROFILE['name']}")
    print("the Lab 5 report page reaches this through nginx at /lab5/ - press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
