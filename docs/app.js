// Dashboard renderer. Fetches JSON files written by analysis/run.py
// (committed to docs/data/ by the GitHub Actions workflow) and paints
// the page. No build step, no framework.

const FILES = {
  scoreboard: "data/scoreboard.json",
  signals: "data/signals.json",
  backtest: "data/backtest.json",
  methodologies: "data/methodologies.json",
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

const setText = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };

function confidenceCell(conf) {
  const pct = Math.max(0, Math.min(1, (conf - 0.5) / 0.5));
  return `<span class="confidence-bar"><span class="fill" style="width:${pct * 100}%"></span></span>${conf.toFixed(3)}`;
}

const tag = (text, klass) => `<span class="tag ${klass}">${text}</span>`;
const dirTag = (d) => d === "up" ? tag("UP", "up") : d === "down" ? tag("DOWN", "down") : tag("—", "neutral");

function sentimentCell(sentiment) {
  if (!sentiment) return `<span class="muted">no headlines</span>`;
  const label = sentiment.label;
  const klass = label === "bullish" ? "up" : label === "bearish" ? "down" : "neutral";
  return `${tag(label, klass)}<br><span class="muted small">${sentiment.score.toFixed(2)} · ${sentiment.headline_count} headlines</span>`;
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

  setText("scoreboard-context",
    (sb.total_resolved ?? 0) === 0
      ? "— no resolved predictions yet, check back as horizons elapse"
      : "");
}

let _signalsState = { all: [], hideNeutral: true, hideLow: false };

function renderSignalsTable() {
  const tbody = document.querySelector("#signals-table tbody");
  tbody.innerHTML = "";
  let rows = _signalsState.all.slice().sort((a, b) => b.confidence - a.confidence);
  if (_signalsState.hideNeutral) rows = rows.filter(s => s.direction !== "neutral");
  if (_signalsState.hideLow) rows = rows.filter(s => s.confidence >= 0.65);
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="muted">No signals matching filters.</td></tr>`;
    return;
  }
  for (const s of rows) {
    const patterns = (s.fired_patterns || []).map(p =>
      `<span class="pattern-chip" title="${(p.note || '').replace(/"/g, '&quot;')}">${p.name} (${p.direction[0].toUpperCase()})</span>`
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
        <td>${s.horizon_days}d</td>
        <td>${dirTag(s.direction)}</td>
        <td>${confidenceCell(s.confidence)}</td>
        <td>${fmtUsd(s.price)}</td>
        <td><div class="patterns-list">${patterns || '<span class="muted">none fired</span>'}</div></td>
        <td>${sentimentCell(s.sentiment)}</td>
        <td>${sizing ? fmtNum(sizing.shares) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.stop) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.risk_usd) : "—"}</td>
        <td>${optsText}</td>
      </tr>
    `);
  }
}

function renderSignals(payload) {
  _signalsState.all = payload?.signals || [];
  document.getElementById("hide-neutral").addEventListener("change", e => {
    _signalsState.hideNeutral = e.target.checked;
    renderSignalsTable();
  });
  document.getElementById("hide-low-conf").addEventListener("change", e => {
    _signalsState.hideLow = e.target.checked;
    renderSignalsTable();
  });
  renderSignalsTable();
}

function renderMethodologies(payload) {
  const tbody = document.querySelector("#methodologies-table tbody");
  tbody.innerHTML = "";
  const m = payload?.methodologies || {};
  const defs = (payload?.definitions || []).reduce((acc, d) => { acc[d.name] = d; return acc; }, {});
  const rows = Object.entries(m).sort((a, b) =>
    (b[1].accuracy ?? -1) - (a[1].accuracy ?? -1)
  );
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">No methodology data yet.</td></tr>`;
    return;
  }
  for (const [name, stats] of rows) {
    const def = defs[name] || {};
    const byH = Object.entries(stats.by_horizon || {})
      .map(([h, v]) => `<span class="muted">${h}d:</span> ${fmtPct(v.accuracy)} <span class="muted">(${v.signals})</span>`)
      .join(" · ");
    tbody.insertAdjacentHTML("beforeend", `
      <tr>
        <td><strong>${name}</strong><br><span class="muted small">${def.description || stats.description || ""}</span></td>
        <td>${fmtNum(stats.signals_emitted ?? 0)}</td>
        <td>${fmtNum(stats.correct ?? 0)}</td>
        <td><strong>${fmtPct(stats.accuracy)}</strong></td>
        <td>${fmtPct(stats.signal_rate)}</td>
        <td><span class="small">${byH || "—"}</span></td>
      </tr>
    `);
  }
}

function renderBacktest(bt) {
  if (!bt) return;
  const ens = bt.ensemble || {};
  const dirTotal = ens.directional_total ?? 0;
  const dirCorrect = ens.directional_correct ?? 0;
  setText("bt-accuracy", fmtPct(ens.accuracy));
  setText("bt-counts",
    `${dirCorrect} correct / ${dirTotal - dirCorrect} wrong of ${dirTotal} directional calls ` +
    `(${ens.total_samples ?? 0} total samples, ${fmtPct(ens.neutral_rate)} neutral)`);
  setText("bt-bullish", fmtPct(ens.by_direction?.up?.accuracy));
  setText("bt-bearish", fmtPct(ens.by_direction?.down?.accuracy));

  // by horizon
  const hBody = document.querySelector("#horizon-table tbody");
  hBody.innerHTML = "";
  for (const [h, v] of Object.entries(ens.by_horizon || {})) {
    hBody.insertAdjacentHTML("beforeend", `
      <tr><td>${h}d</td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>
    `);
  }
  if (Object.keys(ens.by_horizon || {}).length === 0) {
    hBody.innerHTML = `<tr><td colspan="4" class="muted">No data yet.</td></tr>`;
  }

  // by regime
  const rBody = document.querySelector("#regime-table tbody");
  rBody.innerHTML = "";
  const regimeOrder = ["bull", "bear", "choppy", "unknown"];
  const regimes = ens.by_regime || {};
  const orderedRegimes = regimeOrder.filter(r => r in regimes).concat(
    Object.keys(regimes).filter(r => !regimeOrder.includes(r))
  );
  for (const r of orderedRegimes) {
    const v = regimes[r];
    rBody.insertAdjacentHTML("beforeend", `
      <tr><td><span class="tag ${r === 'bull' ? 'up' : r === 'bear' ? 'down' : 'neutral'}">${r}</span></td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>
    `);
  }
  if (orderedRegimes.length === 0) {
    rBody.innerHTML = `<tr><td colspan="4" class="muted">No data yet.</td></tr>`;
  }

  // calibration
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
  const patterns = bt?.patterns_flat || {};
  const w = weights?.weights || {};
  const tbody = document.querySelector("#patterns-table tbody");
  tbody.innerHTML = "";

  const names = new Set([...Object.keys(patterns), ...Object.keys(w)]);
  const rows = Array.from(names).map(n => {
    const wRaw = w[n] || {};
    return { name: n, stats: patterns[n] || {}, weights_h: wRaw };
  });
  rows.sort((a, b) => (b.stats.fires || 0) - (a.stats.fires || 0));

  for (const r of rows) {
    const s = r.stats;
    const horizons = Object.keys(r.weights_h).sort((a, b) => parseInt(a) - parseInt(b));
    const wText = horizons.length
      ? horizons.map(h => `${h}d: ${Number(r.weights_h[h]).toFixed(2)}`).join(" / ")
      : "—";
    tbody.insertAdjacentHTML("beforeend", `
      <tr>
        <td><code>${r.name}</code></td>
        <td>${fmtNum(s.fires ?? 0)}</td>
        <td>${fmtNum(s.correct ?? 0)}</td>
        <td>${fmtPct(s.raw_accuracy)}</td>
        <td>${fmtPct(s.shrunk_accuracy)}</td>
        <td><span class="green">${fmtNum(s.by_up ?? 0)}</span></td>
        <td><span class="red">${fmtNum(s.by_down ?? 0)}</span></td>
        <td><span class="small">${wText}</span></td>
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
    const rowClass = !isResolved ? "row-open" : p.correct ? "row-correct" : "row-wrong";
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

let _metaState = { all: [], hideLow: false };

function renderMetaSignalsTable() {
  const tbody = document.querySelector("#meta-signals-table tbody");
  tbody.innerHTML = "";
  let rows = _metaState.all.slice().sort((a, b) => b.confidence - a.confidence);
  if (_metaState.hideLow) rows = rows.filter(s => s.confidence >= 0.65);
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="12" class="muted">No holistic signals — meta-ensemble requires ≥2 methodologies (with above-chance accuracy) to agree. Either methodologies are below chance or none fired today.</td></tr>`;
    return;
  }
  for (const s of rows) {
    const contributors = (s.contributing_methodologies || []).map(c =>
      `<span class="pattern-chip" title="weight ${c.weight.toFixed(2)}, acc ${(c.accuracy*100).toFixed(0)}%">${c.methodology} → ${c.direction.toUpperCase()} (${c.confidence.toFixed(2)})</span>`
    ).join("");
    const sizing = s.sizing;
    const opts = s.options;
    const optsText = opts && opts.use_options
      ? `${opts.strategy.replaceAll('_', ' ')}<br><span class="muted small">long ${opts.long_strike ?? "?"}${opts.short_strike ? " / short " + opts.short_strike : ""}, ${opts.target_dte_days}d</span>`
      : `<span class="muted">equity only</span>`;
    const rowClass = s.direction === "up" ? "row-up" : "row-down";
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${rowClass}">
        <td><strong>${s.ticker}</strong><br><span class="muted small">${s.as_of}</span></td>
        <td>${s.horizon_days}d</td>
        <td>${dirTag(s.direction)}</td>
        <td>${confidenceCell(s.confidence)}</td>
        <td>${(s.vote_margin * 100).toFixed(1)}%</td>
        <td><div class="patterns-list">${contributors}</div></td>
        <td>${fmtUsd(s.price)}</td>
        <td>${sentimentCell(s.sentiment)}</td>
        <td>${sizing ? fmtNum(sizing.shares) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.stop) : "—"}</td>
        <td>${sizing ? fmtUsd(sizing.risk_usd) : "—"}</td>
        <td>${optsText}</td>
      </tr>
    `);
  }
}

function renderHolistic(signalsPayload) {
  const regime = signalsPayload?.live_regime || "unknown";
  const regimeEl = document.getElementById("live-regime");
  regimeEl.textContent = regime;
  regimeEl.className = "tag " + (regime === "bull" ? "up" : regime === "bear" ? "down" : "neutral");
  _metaState.all = signalsPayload?.meta_signals || [];
  document.getElementById("meta-hide-low-conf").addEventListener("change", e => {
    _metaState.hideLow = e.target.checked;
    renderMetaSignalsTable();
  });
  renderMetaSignalsTable();
}

async function main() {
  const [sb, signals, bt, methodologies, preds, weights] = await Promise.all([
    loadJson(FILES.scoreboard),
    loadJson(FILES.signals),
    loadJson(FILES.backtest),
    loadJson(FILES.methodologies),
    loadJson(FILES.predictions),
    loadJson(FILES.weights),
  ]);
  renderHolistic(signals);
  renderScoreboard(sb);
  renderSignals(signals);
  renderMethodologies(methodologies);
  renderBacktest(bt);
  renderPatterns(bt, weights);
  renderPredictions(preds);
}

main();
