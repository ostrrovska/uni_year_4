// Lab3 + Lab4 — dashboard logic.
//
// Everything is same-origin with the API, because nginx serves this page and proxies /api/.
// That is what lets JS read X-Instance-ID, X-Cache, X-Response-Time-ms and X-LB-Algorithm with
// no Access-Control-Expose-Headers, and it is also the encapsulation proof: the browser has no
// instance address to talk to even if it wanted one.

const RESOLVE_PATH = "/static/app.bundle.js";
const RESOLVE_URL = `/api/v1/routing/resolve?path=${encodeURIComponent(RESOLVE_PATH)}&client_region=eu-central`;
const LOG_LIMIT = 50;
const STRIP_LIMIT = 60;

const SERIES_CLASS = ["s1", "s2", "s3"];

const state = {
  log: [],
  strip: [],
  cache: { HIT: 0, MISS: 0, BYPASS: 0 },
  latencies: { HIT: [], MISS: [] },
  // Instance -> series slot, assigned on first sight and never reassigned, so a filtered or
  // failed instance never repaints the survivors.
  slots: new Map(),
  commands: [],
};

const $ = (id) => document.getElementById(id);

function slotFor(instance) {
  if (!state.slots.has(instance)) {
    state.slots.set(instance, state.slots.size % SERIES_CLASS.length);
  }
  return SERIES_CLASS[state.slots.get(instance)];
}

function percentile(values, pct) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.max(0, Math.ceil((pct / 100) * sorted.length) - 1);
  return sorted[rank];
}

const round1 = (value) => (value === null ? "—" : Math.round(value * 10) / 10);

// ---------------------------------------------------------------- command echo
//
// Every action names the command that reproduces it from a terminal. The page runs no shell and
// never could: it is served by nginx and can reach nothing but its own origin. The echo exists
// so a panel can be defended as evidence rather than taken on trust — press the button, read
// the request, run the same thing in PowerShell and get the same answer.

const ENTRY = location.origin; // the balancer, and the only address this page can reach
const RESOLVE_CURL_URL = `${ENTRY}/api/v1/routing/resolve?path=${RESOLVE_PATH}&client_region=eu-central`;
const HEADER_FILTER = 'Select-String "X-Cache|X-Instance-ID|X-Response-Time-ms|X-LB-Algorithm"';
const RESOLVE_CMD = `curl.exe -s -D - -o NUL "${RESOLVE_CURL_URL}" | ${HEADER_FILTER}`;

const CMD_LIMIT = 25;

const escapeHtml = (text) =>
  String(text).replace(
    /[&<>"]/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character],
  );

// `label` is what the command is for; `text` is the command. Shown in the target <pre> and
// pushed onto the history card, so the whole demo can be replayed from one list at the end.
function showCmd(targetId, label, text) {
  const target = $(targetId);
  target.textContent = text;
  target.classList.remove("muted");

  state.commands.unshift({ at: new Date(), label, text });
  state.commands.length = Math.min(state.commands.length, CMD_LIMIT);
  renderCommands();
}

function renderCommands() {
  const box = $("cmd-log");
  if (!state.commands.length) {
    box.innerHTML = `<p class="cmd-empty">No actions yet — press a button above.</p>`;
    return;
  }
  box.innerHTML = state.commands
    .map(
      (item) => `<div class="cmd-row">
          <span class="cmd-time">${item.at.toLocaleTimeString()} · ${escapeHtml(item.label)}</span>
          <div class="cmd-box"><pre class="cmd">${escapeHtml(item.text)}</pre>
            <button class="copy" type="button">Copy</button></div>
        </div>`,
    )
    .join("");
}

function burstCmd(total, concurrency) {
  return [
    `# this button: ${total} requests, ${concurrency} in parallel from the browser.`,
    `# sequential equivalent from a terminal:`,
    `1..${total} | ForEach-Object { curl.exe -s -o NUL -w "%{http_code} " "${RESOLVE_CURL_URL}" }`,
    ``,
    `# where they landed, recomputed from the balancer's own access log:`,
    `docker compose @ca logs --no-log-prefix --tail ${total} lb | Select-String "instance=cdn" | Group-Object { ($_ -split "instance=")[1].Split(" ")[0] } | Select-Object Count, Name`,
  ].join("\n");
}

async function call(url, options = {}) {
  const started = performance.now();
  let response;
  try {
    response = await fetch(url, { cache: "no-store", ...options });
  } catch (error) {
    const record = {
      at: new Date(),
      label: `${options.method || "GET"} ${url}`,
      status: 0,
      instance: "—",
      cache: "—",
      serverMs: null,
      wallMs: performance.now() - started,
      ok: false,
    };
    record.error = String(error);
    return record;
  }

  const wallMs = performance.now() - started;
  const serverHeader = response.headers.get("X-Response-Time-ms");
  const record = {
    at: new Date(),
    label: `${options.method || "GET"} ${url.split("?")[0]}`,
    status: response.status,
    instance: response.headers.get("X-Instance-ID") || "—",
    cache: response.headers.get("X-Cache") || "—",
    serverMs: serverHeader === null ? null : Number(serverHeader),
    wallMs,
    ok: response.ok,
  };
  try {
    record.body = await response.json();
  } catch {
    record.body = null;
  }
  return record;
}

function record(entry, { strip = true } = {}) {
  state.log.unshift(entry);
  state.log.length = Math.min(state.log.length, LOG_LIMIT);

  if (entry.cache in state.cache) {
    state.cache[entry.cache] += 1;
  }
  if (entry.ok && entry.serverMs !== null && (entry.cache === "HIT" || entry.cache === "MISS")) {
    state.latencies[entry.cache].push(entry.serverMs);
  }
  if (strip) {
    state.strip.push(entry);
    if (state.strip.length > STRIP_LIMIT) state.strip.shift();
  }
}

// ---------------------------------------------------------------- balancer status

async function pollStatus() {
  try {
    const health = await fetch("/lb-health", { cache: "no-store" });
    const pill = $("lb-health");
    pill.classList.toggle("up", health.ok);
    pill.classList.toggle("down", !health.ok);
    $("lb-health-text").textContent = health.ok ? "balancer up" : "balancer down";
  } catch {
    $("lb-health").classList.add("down");
    $("lb-health-text").textContent = "balancer unreachable";
  }

  try {
    const status = await fetch("/lb-status", { cache: "no-store" });
    if (status.ok) {
      const body = await status.json();
      $("alg-name").textContent = `${body.algorithm} · pool ${body.pool}`;
      return;
    }
  } catch {
    /* fall through */
  }
  $("alg-name").textContent = "unknown";
}

// ---------------------------------------------------------------- burst + distribution

async function burst(total, concurrency) {
  const results = [];
  let issued = 0;

  async function worker() {
    while (issued < total) {
      issued += 1;
      const entry = await call(RESOLVE_URL);
      results.push(entry);
      record(entry);
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));
  return results;
}

function renderDistribution(results) {
  const byInstance = new Map();
  for (const entry of results) {
    if (!entry.ok) continue;
    if (!byInstance.has(entry.instance)) byInstance.set(entry.instance, []);
    byInstance.get(entry.instance).push(entry.wallMs);
  }

  const names = [...byInstance.keys()].sort();
  const succeeded = names.reduce((sum, name) => sum + byInstance.get(name).length, 0);
  const max = Math.max(1, ...names.map((name) => byInstance.get(name).length));

  // Every bar carries a visible direct label, which is also the relief the light-mode
  // contrast warning on the third slot requires.
  $("dist-bars").innerHTML =
    names
      .map((name) => {
        const count = byInstance.get(name).length;
        const share = succeeded ? ((100 * count) / succeeded).toFixed(1) : "0.0";
        return `<div class="bar-row">
            <span class="bar-name">${name}</span>
            <div class="bar-track">
              <div class="bar-fill ${slotFor(name)}" style="width:${(100 * count) / max}%"
                   title="${name}: ${count} requests, ${share} %"></div>
              <span class="bar-value">${count} · ${share} %</span>
            </div>
          </div>`;
      })
      .join("") || `<p class="strip-empty">No successful responses.</p>`;

  $("dist-table").querySelector("tbody").innerHTML =
    names
      .map((name) => {
        const values = byInstance.get(name);
        const share = succeeded ? ((100 * values.length) / succeeded).toFixed(1) : "0.0";
        return `<tr><td>${name}</td><td>${values.length}</td><td>${share} %</td>
            <td>${round1(percentile(values, 50))}</td><td>${round1(percentile(values, 99))}</td></tr>`;
      })
      .join("") || `<tr class="empty"><td colspan="5">No successful responses.</td></tr>`;

  const all = results.filter((entry) => entry.ok).map((entry) => entry.wallMs);
  const failed = results.length - all.length;
  $("burst-total").textContent = results.length;
  $("burst-p50").textContent = round1(percentile(all, 50));
  $("burst-p99").textContent = round1(percentile(all, 99));
  $("burst-err").textContent = failed;
  $("burst-err-tile").classList.toggle("alarm", failed > 0);
  $("burst-err-tile").classList.toggle("good", failed === 0 && results.length > 0);
}

// ---------------------------------------------------------------- cache panel

function renderCache() {
  const { HIT, MISS, BYPASS } = state.cache;
  const consulted = HIT + MISS;

  $("cache-tally").textContent = `${HIT} / ${MISS} / ${BYPASS}`;
  $("hit-ratio").textContent = consulted ? Math.round((100 * HIT) / consulted) : "—";

  const mean = (values) =>
    values.length ? round1(values.reduce((a, b) => a + b, 0) / values.length) : "—";
  $("hit-ms").textContent = mean(state.latencies.HIT);
  $("miss-ms").textContent = mean(state.latencies.MISS);

  const legend = [
    ["good", "HIT · served from Redis"],
    ["warning", "MISS · computed and stored"],
    ["text-muted", "BYPASS · cache not consulted"],
    ["critical", "error"],
  ];
  $("cache-legend").innerHTML = legend
    .map(
      ([token, label]) =>
        `<span><span class="swatch" style="background:var(--${token})"></span>${label}</span>`,
    )
    .join("");

  if (!state.strip.length) {
    $("lat-chart").innerHTML = `<span class="strip-empty">No requests yet.</span>`;
    return;
  }

  const peak = Math.max(...state.strip.map((entry) => entry.wallMs), 1);
  $("lat-chart").innerHTML = state.strip
    .map((entry) => {
      const cls = !entry.ok ? "err" : (entry.cache || "bypass").toLowerCase();
      const height = Math.max(3, (100 * entry.wallMs) / peak);
      const title = `${entry.cache} · ${Math.round(entry.wallMs)} ms wall · ${entry.instance} · HTTP ${entry.status}`;
      return `<div class="strip-bar ${cls}" style="height:${height}%" title="${title}"></div>`;
    })
    .join("");
}

function renderLog() {
  const body = $("log-body");
  if (!state.log.length) {
    body.innerHTML = `<tr class="empty"><td colspan="7">No requests yet.</td></tr>`;
    return;
  }
  body.innerHTML = state.log
    .map((entry) => {
      const cacheClass = entry.cache === "HIT" ? "hit" : entry.cache === "MISS" ? "miss" : "";
      const statusClass = entry.ok ? "" : "err";
      return `<tr>
          <td>${entry.at.toLocaleTimeString()}</td>
          <td><code>${entry.label}</code></td>
          <td><span class="tag ${statusClass}">${entry.status || "ERR"}</span></td>
          <td>${entry.instance}</td>
          <td><span class="tag ${cacheClass}">${entry.cache}</span></td>
          <td>${entry.serverMs === null ? "—" : round1(entry.serverMs)}</td>
          <td>${round1(entry.wallMs)}</td>
        </tr>`;
    })
    .join("");
}

function repaint() {
  renderCache();
  renderLog();
}

// ---------------------------------------------------------------- invalidation demo

function randomHash() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function invalidationDemo(status) {
  status.textContent = "reading twice…";
  showCmd(
    "cache-cmd",
    "Lab 4 · invalidation, step 1 — warm the key",
    [`# twice: MISS, then HIT`, RESOLVE_CMD].join("\n"),
  );
  record(await call(RESOLVE_URL));
  record(await call(RESOLVE_URL));
  repaint();

  status.textContent = "finding the asset…";
  showCmd(
    "cache-cmd",
    "Lab 4 · invalidation, step 2 — find the asset",
    `curl.exe -s "${ENTRY}/api/v1/assets?path_prefix=${RESOLVE_PATH}"`,
  );
  const lookup = await call(`/api/v1/assets?path_prefix=${encodeURIComponent(RESOLVE_PATH)}`);
  record(lookup, { strip: false });
  const asset = lookup.body?.items?.[0];
  if (!asset) {
    status.textContent = "no seeded asset at that path — run the seed service first";
    repaint();
    return;
  }

  status.textContent = `publishing version ${asset.version + 1}…`;
  showCmd(
    "cache-cmd",
    `Lab 4 · invalidation, step 3 — publish v${asset.version + 1}`,
    [
      `# PowerShell 5.1 mangles a JSON body passed to curl.exe, so use Invoke-RestMethod:`,
      `$hash = -join ((1..64) | ForEach-Object { "0123456789abcdef"[(Get-Random -Max 16)] })`,
      `Invoke-RestMethod -Method Post -ContentType "application/json" -Uri "${ENTRY}/api/v1/assets/${asset.id}/versions" -Body "{""content_hash"":""$hash"",""size_bytes"":${asset.size_bytes + 1},""requested_by"":""dashboard"",""reason"":""invalidation demo""}"`,
    ].join("\n"),
  );
  const published = await call(`/api/v1/assets/${asset.id}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content_hash: randomHash(),
      size_bytes: asset.size_bytes + 1,
      requested_by: "dashboard",
      reason: "invalidation demo",
    }),
  });
  record(published, { strip: false });

  status.textContent = "reading again…";
  showCmd(
    "cache-cmd",
    "Lab 4 · invalidation, step 4 — the mutation dropped the key",
    [
      `# first read after the publish is a MISS with the new version, the next one a HIT:`,
      RESOLVE_CMD,
      ``,
      `# and the instance that dropped it said so:`,
      `docker compose @ca logs --no-log-prefix --tail 400 api1 api2 api3 | Select-String "cache.invalidated"`,
    ].join("\n"),
  );
  const after = await call(RESOLVE_URL);
  record(after);
  const confirm = await call(RESOLVE_URL);
  record(confirm);
  repaint();

  status.textContent =
    after.cache === "MISS"
      ? `published v${after.body?.version ?? "?"} → next read was a MISS, then ${confirm.cache}`
      : `published, but the read reported ${after.cache} (cache disabled?)`;
}

// ---------------------------------------------------------------- wiring

// Delegated, because the history card re-renders its Copy buttons on every action.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button.copy");
  if (!button) return;
  const source = button.closest(".cmd-box")?.querySelector(".cmd");
  if (!source) return;

  const restore = button.textContent;
  try {
    await navigator.clipboard.writeText(source.textContent.trim());
    button.textContent = "copied";
  } catch {
    // The clipboard API needs a secure context. http://localhost is one, but a page opened by
    // host name over plain HTTP is not — select the text instead so Ctrl+C still works.
    const range = document.createRange();
    range.selectNodeContents(source);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    button.textContent = "selected";
  }
  setTimeout(() => (button.textContent = restore), 1200);
});

async function withBusy(work) {
  // Copy buttons stay live: a burst takes seconds and the command is the thing being read.
  const buttons = [...document.querySelectorAll("button:not(.copy)")];
  buttons.forEach((element) => (element.disabled = true));
  try {
    await work();
  } finally {
    buttons.forEach((element) => (element.disabled = false));
  }
}

$("burst-go").addEventListener("click", () =>
  withBusy(async () => {
    const total = Math.max(3, Number($("burst-n").value) || 120);
    const concurrency = Math.max(1, Number($("burst-c").value) || 8);
    showCmd("burst-cmd", `Lab 3 · burst ${total}×, concurrency ${concurrency}`, burstCmd(total, concurrency));
    $("burst-state").textContent = `sending ${total} requests…`;
    const results = await burst(total, concurrency);
    renderDistribution(results);
    repaint();
    const instances = new Set(results.filter((entry) => entry.ok).map((entry) => entry.instance));
    $("burst-state").textContent = `${results.length} requests across ${instances.size} instance(s)`;
  }),
);

$("read-once").addEventListener("click", () =>
  withBusy(async () => {
    showCmd("cache-cmd", "Lab 4 · one resolve, headers only", RESOLVE_CMD);
    const entry = await call(RESOLVE_URL);
    record(entry);
    repaint();
    $("cache-state").textContent = `${entry.cache} from ${entry.instance} in ${round1(entry.wallMs)} ms`;
  }),
);

$("read-ten").addEventListener("click", () =>
  withBusy(async () => {
    showCmd(
      "cache-cmd",
      "Lab 4 · ten resolves — first a MISS, the rest HIT",
      [
        `1..10 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code} " "${RESOLVE_CURL_URL}" }`,
        ``,
        `# the cache outcome of the last one:`,
        RESOLVE_CMD,
      ].join("\n"),
    );
    for (let i = 0; i < 10; i += 1) {
      record(await call(RESOLVE_URL));
    }
    repaint();
    const { HIT, MISS, BYPASS } = state.cache;
    $("cache-state").textContent = `tally now HIT ${HIT} / MISS ${MISS} / BYPASS ${BYPASS}`;
  }),
);

$("demo-invalidate").addEventListener("click", () =>
  withBusy(() => invalidationDemo($("cache-state"))),
);

$("clear-log").addEventListener("click", () => {
  state.log = [];
  state.strip = [];
  state.cache = { HIT: 0, MISS: 0, BYPASS: 0 };
  state.latencies = { HIT: [], MISS: [] };
  state.commands = [];
  $("cache-state").textContent = "";
  $("cache-cmd").textContent = "Press a button to see the request it issues.";
  $("cache-cmd").classList.add("muted");
  repaint();
});

repaint();
renderCommands();
pollStatus();
setInterval(pollStatus, 3000);
