// Dashboard renderer. Fetches JSON files written by analysis/run.py
// (and committed to docs/data/ by the GitHub Actions workflow) and paints
// the page. No build step, no framework — vanilla DOM.

const FILES = {
  scoreboard: "data/scoreboard.json",
  signals: "data/signals.json",
  backtest: "data/backtest.json",
  predictions: "data/predictions.json",
  weights: "data/weights.json",
};

const fmtPct = (x) => x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const fmtPctSigned = (x) => x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`;
const fmtNum = (x) => x == null ? "—" : x.toLocaleString();
const fmtUsd = (x) => x == null ? "—" : `$${Number(x).toLocaleString(undefined, {maximumFractionDigits: 2})}`;

async function loadJson(path) {
  try {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    console.warn("Could not load", path, e);
    return null;
  }
}

function setText(id, txt) {
  const el = document.getElementById(id);
  if (el) el.textContent = txt;
}

function confidenceCell(conf) {
  const pct = Math.max(0, Math.min(1, (conf - 0.5) / 0.5));
  return `
    <span class="confidence-bar"><span class="fill" style="width:${pct * 100}%"></span></span>
    ${conf.toFixed(3)}
  `;
}

function tag(text, klass) { return `<span class="tag ${klass}">${text}</span>`; }

function dirTag(direction) {
  if (direction === "up") return tag("UP", "up");
  if (direction === "down") return tag("DOWN", "down");
  return tag("—", "neutral");
}

function renderScoreboard(sb) {
  if (!sb) { setText("scoreboard-context", "(no data yet)"); return; }
  setText("updated-at", `updated ${sb.updated_at || ""}`);
  setText("overall-accuracy", fmtPct(sb.overall_accuracy));
  setText("overall-counts", `${sb.total_correct ?? 0} correct / ${(sb.total_resolved ?? 0) - (sb.total_correct ?? 0)} wrong (${sb.total_resolved ?? 0} resolved)`);
  setText("total-correct", fmtNum(sb.total_correct ?? 0));
  setText("total-wrong", fmtNum((sb.total_resolved ?? 0) - (sb.total_correct ?? 0)));
  setText("open-count", fmtNum(sb.open_predictions ?? 0));

  const b = sb.bullish || {};
  setText("bullish-accuracy", fmtPct(b.accuracy));
  setText("bullish-correct", fmtNum(b.correct ?? 0));
  setText("bullish-wrong", fmtNum((b.n ?? 0) - (b.correct ?? 0)));

  const r = sb.bearish || {};
  setText("bearish-accuracy", fmtPct(r.accuracy));
  setText("bearish-correct", fmtNum(r.correct ?? 0));
  setText("bearish-wrong", fmtNum((r.n ?? 0) - (r.correct ?? 0)));

  if ((sb.total_resolved ?? 0) === 0) {
    setText("scoreboard-context", "— no resolved predictions yet, check back as horizons elapse");
  } else {
    setText("scoreboard-context", "");
  }
}

function renderSignals(payload) {
  const tbody = document.querySelector("#signals-table tbody");
  tbody.innerHTML = "";
  const sigs = (payload?.signals || []).slice().sort((a, b) => b.confidence - a.confidence);
  if (sigs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted">No signals yet — first run hasn't completed or watchlist is empty.</td></tr>`;
    return;
  }
  for (const s of sigs) {
    const patterns = (s.fired_patterns || []).map(p =>
      `<span class="pattern-chip" title="${p.note || ''}">${p.name} (${p.direction[0].toUpperCase()})</span>`
    ).join("");
    const sizing = s.sizing;
    const opts = s.options;
    const optsText = opts && opts.use_options
      ? `${opts.strategy.replaceAll('_', ' ')}<br><span class="muted small">long ${opts.long_strike ?? "?"}${opts.short_strike ? " / short " + opts.short_strike : ""}, ${opts.target_dte_days}d</span>`
      : `<span class="muted">equity only</span>`;
    const rowClass = s.direction === "up" ? "row-up" : s.direction === "down" ? "row-down" : "";
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${rowClass}">
        <td><strong>${s.ticker}</strong><br><span class="muted small">${s.as_of}</span></td>
        <td>${dirTag(s.direction)}</td>
        <td>${confidenceCell(s.confidence)}</td>
        <td>${fmtUsd(s.price)}</td>
        <td><div class="patterns-list">${patterns || '<span class="muted">none fired</span>'}</div></td>
        <td>${sizing ? fmtNum(sizing.shares) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.stop) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.risk_usd) : "—"}</td>
        <td>${optsText}</td>
      </tr>
    `);
  }
}

function renderBacktest(bt) {
  if (!bt) return;
  const ens = bt.ensemble || {};
  setText("bt-accuracy", fmtPct(ens.accuracy));
  setText("bt-counts", `${ens.correct ?? 0} correct / ${(ens.total ?? 0) - (ens.correct ?? 0)} wrong of ${ens.total ?? 0}`);
  setText("bt-bullish", fmtPct(ens.by_direction?.up?.accuracy));
  setText("bt-bearish", fmtPct(ens.by_direction?.down?.accuracy));

  const calBody = document.querySelector("#calibration-table tbody");
  calBody.innerHTML = "";
  for (const row of ens.calibration || []) {
    calBody.insertAdjacentHTML("beforeend", `
      <tr>
        <td>${(row.confidence_lo * 100).toFixed(0)}% – ${(row.confidence_hi * 100).toFixed(0)}%</td>
        <td>${row.n}</td>
        <td>${row.correct}</td>
        <td>${fmtPct(row.accuracy)}</td>
      </tr>
    `);
  }
}

function renderPatterns(bt, weights) {
  const patterns = bt?.patterns || {};
  const w = weights?.weights || {};
  const tbody = document.querySelector("#patterns-table tbody");
  tbody.innerHTML = "";

  // union of patterns we know about (from backtest, from weights)
  const names = new Set([...Object.keys(patterns), ...Object.keys(w)]);
  const rows = Array.from(names).map(n => ({
    name: n, stats: patterns[n] || {}, weight: w[n]
  }));
  rows.sort((a, b) => (b.stats.fires || 0) - (a.stats.fires || 0));

  for (const r of rows) {
    const s = r.stats;
    tbody.insertAdjacentHTML("beforeend", `
      <tr>
        <td><code>${r.name}</code></td>
        <td>${fmtNum(s.fires ?? 0)}</td>
        <td>${fmtNum(s.correct ?? 0)}</td>
        <td>${fmtPct(s.raw_accuracy)}</td>
        <td>${fmtPct(s.shrunk_accuracy)}</td>
        <td><span class="green">${fmtNum(s.by_up ?? 0)}</span></td>
        <td><span class="red">${fmtNum(s.by_down ?? 0)}</span></td>
        <td>${r.weight != null ? r.weight.toFixed(3) : "—"}</td>
      </tr>
    `);
  }
}

function renderPredictions(payload) {
  const preds = (payload?.predictions || []).slice().sort((a, b) =>
    (b.made_at || "").localeCompare(a.made_at || "")
  ).slice(0, 100);
  const tbody = document.querySelector("#predictions-table tbody");
  tbody.innerHTML = "";
  if (preds.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">No predictions logged yet.</td></tr>`;
    return;
  }
  for (const p of preds) {
    const isResolved = p.status === "resolved";
    const rowClass = !isResolved
      ? "row-open"
      : p.correct ? "row-correct" : "row-wrong";
    const result = !isResolved
      ? tag("OPEN", "open")
      : p.correct ? tag("CORRECT", "correct") : tag("WRONG", "wrong");
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${rowClass}">
        <td>${p.made_at}</td>
        <td><strong>${p.ticker}</strong></td>
        <td>${dirTag(p.predicted_direction)}</td>
        <td>${p.ensemble_confidence.toFixed(3)}</td>
        <td>${p.horizon_days}d (ends ${p.horizon_end})</td>
        <td>${p.status}</td>
        <td>${p.actual_return_pct == null ? "—" : fmtPctSigned(p.actual_return_pct)}</td>
        <td>${result}</td>
      </tr>
    `);
  }
}

async function main() {
  const [sb, signals, bt, preds, weights] = await Promise.all([
    loadJson(FILES.scoreboard),
    loadJson(FILES.signals),
    loadJson(FILES.backtest),
    loadJson(FILES.predictions),
    loadJson(FILES.weights),
  ]);
  renderScoreboard(sb);
  renderSignals(signals);
  renderBacktest(bt);
  renderPatterns(bt, weights);
  renderPredictions(preds);
}

main();
