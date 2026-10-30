// Shared summary formatter for both k6 scripts of this lab.
//
// k6 calls handleSummary() once at the end of a run. Returning { stdout: ... }
// replaces the default wall of metrics with the tables below, so a live demo
// ends on numbers that can be read from across the room.

const RUNTIME_BY_PORT = { 3000: 'Node.js', 8080: 'Go' };

const WORKLOAD_BY_PATH = {
  '/io': 'I/O',
  '/cpu': 'CPU (послідовно)',
  '/cpu-goroutines': 'CPU (goroutines)',
};

const COLOR = __ENV.NO_COLOR ? null : {
  bold: (s) => `\x1b[1m${s}\x1b[0m`,
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
};

const plain = (s) => s;

export const bold = COLOR ? COLOR.bold : plain;
export const dim = COLOR ? COLOR.dim : plain;
export const red = COLOR ? COLOR.red : plain;
export const green = COLOR ? COLOR.green : plain;

export function runtimeOf(baseUrl) {
  const port = Number((baseUrl.match(/:(\d+)/) || [])[1]);
  return RUNTIME_BY_PORT[port] || baseUrl;
}

export function workloadOf(endpoint) {
  return WORKLOAD_BY_PATH[endpoint] || endpoint;
}

// Milliseconds are rounded to whole numbers once they pass a second, because
// a tenth of a millisecond on a six-second value is noise on a slide.
export function ms(value) {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return value >= 1000 ? `${value.toFixed(0)}` : `${value.toFixed(1)}`;
}

// 2000000000 reads as noise in a title; "2 млрд" reads from the back row.
export function shortNum(raw) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return String(raw);
  if (value >= 1e9) return `${(value / 1e9).toFixed(value % 1e9 ? 1 : 0)} млрд`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(0)} млн`;
  return String(value);
}

export function trend(data, name) {
  const metric = data.metrics[name];
  return metric ? metric.values : {};
}

export function counter(data, name) {
  const metric = data.metrics[name];
  return metric ? metric.values.count : 0;
}

// ANSI escapes must not be counted when padding a cell to the column width.
function visibleLength(text) {
  return text.replace(/\x1b\[[0-9;]*m/g, '').length;
}

function pad(text, width, align) {
  const gap = ' '.repeat(Math.max(0, width - visibleLength(text)));
  return align === 'right' ? gap + text : text + gap;
}

/**
 * Renders a boxed two-column table.
 * `rows` are [label, value] pairs; a null row draws a separator.
 */
export function box(title, rows, notes = []) {
  const visible = rows.filter(Boolean);
  const labelWidth = Math.max(...visible.map((r) => visibleLength(r[0])));
  const valueWidth = Math.max(
    visibleLength(title),
    ...visible.map((r) => visibleLength(r[1])),
  );
  const inner = labelWidth + valueWidth + 3;

  const lines = [
    `┌${'─'.repeat(inner + 2)}┐`,
    `│ ${pad(bold(title), inner)} │`,
    `├${'─'.repeat(inner + 2)}┤`,
  ];

  for (const row of rows) {
    if (!row) {
      lines.push(`├${'─'.repeat(inner + 2)}┤`);
      continue;
    }
    lines.push(`│ ${pad(row[0], labelWidth)}   ${pad(row[1], valueWidth, 'right')} │`);
  }

  lines.push(`└${'─'.repeat(inner + 2)}┘`);
  for (const note of notes) {
    lines.push(`  ${note}`);
  }
  return lines.join('\n');
}

// The row is printed ready to be pasted straight into RESULTS.md.
export function markdownRow(cells) {
  return `| ${cells.join(' | ')} |`;
}

/**
 * Builds the object k6 expects back from handleSummary: our table on stdout,
 * plus the raw metrics as JSON when JSON_OUT points somewhere (run-all.ps1
 * sets it and creates the directory first).
 */
export function output(text, data, extra = {}) {
  const result = { stdout: `\n${text}\n\n` };
  if (__ENV.JSON_OUT) {
    result[__ENV.JSON_OUT] = JSON.stringify({ ...extra, metrics: data.metrics }, null, 2);
  }
  return result;
}
