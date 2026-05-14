// Dashboard renderer. Fetches JSON from docs/data/ and paints the page.
// No build step, no framework.

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
const setHTML = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

const confidenceCell = (conf) => {
  const pct = Math.max(0, Math.min(1, (conf - 0.5) / 0.5));
  return `<span class="confidence-bar"><span class="fill" style="width:${pct * 100}%"></span></span>${conf.toFixed(3)}`;
};

const tag = (text, klass) => `<span class="tag ${klass}">${text}</span>`;
const dirTag = (d) => d === "up" ? tag("UP", "up") : d === "down" ? tag("DOWN", "down") : tag("—", "neutral");

const sentimentCell = (sentiment) => {
  if (!sentiment) return `<span class="muted">—</span>`;
  const klass = sentiment.label === "bullish" ? "up" : sentiment.label === "bearish" ? "down" : "neutral";
  return `${tag(sentiment.label, klass)}<br><span class="muted small">${sentiment.score.toFixed(2)}</span>`;
};

// ---------------- Featured (top recommendation) ----------------

function renderFeatured(signalsPayload, methodsPayload) {
  const metas = signalsPayload?.meta_signals || [];
  if (metas.length === 0) {
    setHTML("featured-content",
      `<p class="muted">No high-conviction holistic signal today — meta-ensemble requires ≥2 methodologies above-chance at the same horizon to agree. Check the per-methodology breakdown below to see what individual methods are saying.</p>`);
    return;
  }
  // pick highest confidence
  const top = metas.slice().sort((a, b) => b.confidence - a.confidence)[0];
  const kfoldAcc = methodsPayload?.meta_kfold?.accuracy;
  const dirClass = top.direction === "up" ? "up" : "down";
  const contribs = (top.contributing_methodologies || []).map(c =>
    `<span class="pattern-chip">${c.methodology} → ${c.direction.toUpperCase()}</span>`
  ).join(" ");
  const sizing = top.sizing;
  const opts = top.options;
  setHTML("featured-content", `
    <div class="featured-card">
      <div class="featured-headline">
        <span class="featured-ticker">${top.ticker}</span>
        <span class="featured-dir tag ${dirClass}">${top.direction.toUpperCase()}</span>
        <span class="featured-horizon">${top.horizon_days}-day horizon</span>
        <span class="featured-conf">confidence ${top.confidence.toFixed(3)}</span>
      </div>
      <div class="featured-line muted small">
        Backed by ${top.n_contributing} methodologies (vote margin ${(top.vote_margin * 100).toFixed(1)}%).
        Expected accuracy at this horizon: K-fold cross-validated meta = ${fmtPct(kfoldAcc)}.
      </div>
      <div class="featured-line">
        <strong>Suggested action:</strong>
        ${sizing ? `Buy ${fmtNum(sizing.shares)} shares @ ${fmtUsd(top.price)}, stop at ${fmtUsd(sizing.stop)}, max risk ${fmtUsd(sizing.risk_usd)}.` : "Position sizing unavailable."}
      </div>
      <div class="featured-line">
        <strong>Options alternative:</strong>
        ${opts && opts.use_options ? `${opts.strategy.replaceAll('_', ' ')} — long strike ${opts.long_strike}${opts.short_strike ? ", short " + opts.short_strike : ""}, ~${opts.target_dte_days} days to expiration` : "Equity recommended over options."}
      </div>
      <div class="featured-line muted small">Contributors: ${contribs}</div>
    </div>
  `);
}

// ---------------- Scoreboard ----------------

function renderScoreboard(sb) {
  if (!sb) return;
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
  setText("scoreboard-context", (sb.total_resolved ?? 0) === 0
    ? "— no resolved predictions yet; check back as horizons elapse"
    : `(${sb.total_resolved} resolved, ${sb.open_predictions} open)`);
}

// ---------------- Meta signals (holistic) ----------------

const _metaState = { all: [], horizon: null, search: "", hideLow: false };

function populateHorizonSelect(metas) {
  const sel = document.getElementById("meta-horizon-select");
  const horizons = [...new Set(metas.map(s => s.horizon_days))].sort((a, b) => a - b);
  sel.innerHTML = "";
  if (horizons.length === 0) { sel.innerHTML = `<option>—</option>`; return; }
  for (const h of horizons) {
    sel.insertAdjacentHTML("beforeend", `<option value="${h}">${h}-day</option>`);
  }
  // default to longest horizon (best edge)
  const defaultH = horizons[horizons.length - 1];
  sel.value = String(defaultH);
  _metaState.horizon = defaultH;
}

function renderMetaSignalsTable() {
  const tbody = document.querySelector("#meta-signals-table tbody");
  tbody.innerHTML = "";
  let rows = _metaState.all.slice();
  if (_metaState.horizon !== null) {
    rows = rows.filter(s => s.horizon_days === _metaState.horizon);
  }
  if (_metaState.search) {
    const q = _metaState.search.toUpperCase();
    rows = rows.filter(s => s.ticker.toUpperCase().includes(q));
  }
  if (_metaState.hideLow) rows = rows.filter(s => s.confidence >= 0.65);
  rows.sort((a, b) => b.confidence - a.confidence);

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="muted">No holistic signals match filters. Try a different horizon or clear the search.</td></tr>`;
    return;
  }
  for (const s of rows) {
    const contributors = (s.contributing_methodologies || []).map(c =>
      `<span class="pattern-chip" title="weight ${c.weight.toFixed(2)} from ${(c.accuracy*100).toFixed(0)}% acc">${c.methodology} → ${c.direction.toUpperCase()} (${c.confidence.toFixed(2)})</span>`
    ).join("");
    const sizing = s.sizing, opts = s.options;
    const optsText = opts && opts.use_options
      ? `${opts.strategy.replaceAll('_', ' ')}<br><span class="muted small">long ${opts.long_strike ?? "?"}${opts.short_strike ? " / short " + opts.short_strike : ""}, ${opts.target_dte_days}d</span>`
      : `<span class="muted">equity</span>`;
    const rowClass = s.direction === "up" ? "row-up" : "row-down";
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${rowClass}">
        <td><strong>${s.ticker}</strong><br><span class="muted small">${s.as_of}</span></td>
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
  populateHorizonSelect(_metaState.all);

  document.getElementById("meta-horizon-select").addEventListener("change", e => {
    _metaState.horizon = parseInt(e.target.value);
    renderMetaSignalsTable();
  });
  document.getElementById("meta-search").addEventListener("input", e => {
    _metaState.search = e.target.value.trim();
    renderMetaSignalsTable();
  });
  document.getElementById("meta-hide-low-conf").addEventListener("change", e => {
    _metaState.hideLow = e.target.checked;
    renderMetaSignalsTable();
  });
  renderMetaSignalsTable();
}

// ---------------- Methodologies ----------------

function renderMethodologies(payload) {
  if (!payload) return;
  const kfold = payload.meta_kfold || {};
  setText("kfold-accuracy", fmtPct(kfold.accuracy));
  setText("kfold-counts", kfold.accuracy != null
    ? `${kfold.correct} correct / ${(kfold.signals_emitted ?? 0) - (kfold.correct ?? 0)} wrong of ${kfold.signals_emitted ?? 0} signals (k=${kfold.k}, ${kfold.n_samples} samples)`
    : (kfold.note || "—"));

  const meta = payload.methodologies?.meta_ensemble || {};
  setText("insample-accuracy", fmtPct(meta.accuracy));
  setText("insample-counts", meta.accuracy != null
    ? `${meta.correct} / ${meta.signals_emitted} signals (in-sample, optimistic)`
    : "—");

  const tbody = document.querySelector("#methodologies-table tbody");
  tbody.innerHTML = "";
  const m = payload.methodologies || {};
  const rows = Object.entries(m).sort((a, b) => (b[1].accuracy ?? -1) - (a[1].accuracy ?? -1));
  for (const [name, stats] of rows) {
    const byH = Object.entries(stats.by_horizon || {})
      .map(([h, v]) => `<span class="muted">${h}d:</span> ${fmtPct(v.accuracy)} <span class="muted">(${v.signals})</span>`)
      .join(" · ");
    const klass = name === "meta_ensemble" ? "row-featured" : (stats.pruned ? "row-pruned" : "");
    const badge = name === "meta_ensemble"
      ? ` ${tag("META", "up")}`
      : (stats.pruned ? ` ${tag("PRUNED", "down")}` : "");
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${klass}">
        <td><strong>${name}</strong>${badge}<br><span class="muted small">${stats.description || ""}</span></td>
        <td>${fmtNum(stats.signals_emitted ?? 0)}</td>
        <td>${fmtNum(stats.correct ?? 0)}</td>
        <td><strong>${fmtPct(stats.accuracy)}</strong></td>
        <td>${fmtPct(stats.signal_rate)}</td>
        <td><span class="small">${byH || "—"}</span></td>
      </tr>
    `);
  }
}

// ---------------- Backtest ----------------

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

  const hBody = document.querySelector("#horizon-table tbody");
  hBody.innerHTML = "";
  for (const [h, v] of Object.entries(ens.by_horizon || {})) {
    hBody.insertAdjacentHTML("beforeend", `
      <tr><td>${h}d</td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>
    `);
  }

  const rBody = document.querySelector("#regime-table tbody");
  rBody.innerHTML = "";
  const order = ["bull", "bear", "choppy", "unknown"];
  const regimes = ens.by_regime || {};
  for (const r of order.filter(x => x in regimes).concat(Object.keys(regimes).filter(x => !order.includes(x)))) {
    const v = regimes[r];
    const klass = r === "bull" ? "up" : r === "bear" ? "down" : "neutral";
    rBody.insertAdjacentHTML("beforeend", `
      <tr><td>${tag(r, klass)}</td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>
    `);
  }

  const calBody = document.querySelector("#calibration-table tbody");
  calBody.innerHTML = "";
  for (const row of ens.calibration || []) {
    calBody.insertAdjacentHTML("beforeend", `
      <tr>
        <td>${(row.confidence_lo * 100).toFixed(0)}% – ${(row.confidence_hi * 100).toFixed(0)}%</td>
        <td>${row.n}</td><td>${row.correct}</td><td>${fmtPct(row.accuracy)}</td>
      </tr>
    `);
  }
}

function renderPatterns(bt, weightsPayload) {
  const patterns = bt?.patterns_flat || {};
  const w = weightsPayload?.weights || {};
  const tbody = document.querySelector("#patterns-table tbody");
  tbody.innerHTML = "";
  const names = new Set([...Object.keys(patterns), ...Object.keys(w)]);
  const rows = Array.from(names).map(n => ({
    name: n, stats: patterns[n] || {}, weights_h: w[n] || {},
  }));
  rows.sort((a, b) => (b.stats.fires || 0) - (a.stats.fires || 0));
  for (const r of rows) {
    const s = r.stats;
    const horizons = Object.keys(r.weights_h).sort((a, b) => parseInt(a) - parseInt(b));
    const wText = horizons.length
      ? horizons.map(h => `${h}d:${Number(r.weights_h[h]).toFixed(2)}`).join(" / ")
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

// ---------------- Per-ticker ----------------

const _tickerState = { all: {}, search: "", hideThin: true };

function renderPerTickerTable() {
  const tbody = document.querySelector("#per-ticker-table tbody");
  tbody.innerHTML = "";
  let rows = Object.entries(_tickerState.all).map(([t, v]) => ({ ticker: t, ...v }));
  if (_tickerState.hideThin) rows = rows.filter(r => r.min_samples_met);
  if (_tickerState.search) {
    const q = _tickerState.search.toUpperCase();
    rows = rows.filter(r => r.ticker.toUpperCase().includes(q));
  }
  rows.sort((a, b) => (b.accuracy ?? -1) - (a.accuracy ?? -1));
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">No tickers match.</td></tr>`;
    return;
  }
  for (const r of rows) {
    const thin = !r.min_samples_met ? ` <span class="muted small">(thin)</span>` : "";
    tbody.insertAdjacentHTML("beforeend", `
      <tr>
        <td><strong>${r.ticker}</strong>${thin}</td>
        <td>${r.n}</td>
        <td>${r.correct}</td>
        <td><strong>${fmtPct(r.accuracy)}</strong></td>
        <td>${r.up_n} / ${fmtPct(r.up_accuracy)}</td>
        <td>${r.down_n} / ${fmtPct(r.down_accuracy)}</td>
      </tr>
    `);
  }
}

function renderPerTicker(bt) {
  _tickerState.all = bt?.per_ticker || {};
  document.getElementById("ticker-search").addEventListener("input", e => {
    _tickerState.search = e.target.value.trim();
    renderPerTickerTable();
  });
  document.getElementById("ticker-hide-thin").addEventListener("change", e => {
    _tickerState.hideThin = e.target.checked;
    renderPerTickerTable();
  });
  renderPerTickerTable();
}

// ---------------- Predictions log ----------------

const _predState = { all: [], search: "", onlyResolved: false };

function renderPredictionsTable() {
  const tbody = document.querySelector("#predictions-table tbody");
  tbody.innerHTML = "";
  let rows = _predState.all.slice();
  if (_predState.onlyResolved) rows = rows.filter(p => p.status === "resolved");
  if (_predState.search) {
    const q = _predState.search.toUpperCase();
    rows = rows.filter(p => p.ticker.toUpperCase().includes(q));
  }
  rows.sort((a, b) => (b.made_at || "").localeCompare(a.made_at || ""));
  rows = rows.slice(0, 200);
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted">No predictions match.</td></tr>`;
    return;
  }
  for (const p of rows) {
    const resolved = p.status === "resolved";
    const rowClass = !resolved ? "row-open" : p.correct ? "row-correct" : "row-wrong";
    const result = !resolved ? tag("OPEN", "open") : p.correct ? tag("CORRECT", "correct") : tag("WRONG", "wrong");
    const method = p.notes && p.notes.includes("meta") ? "meta" : "ensemble";
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${rowClass}">
        <td>${p.made_at}</td>
        <td><strong>${p.ticker}</strong></td>
        <td><span class="muted small">${method}</span></td>
        <td>${dirTag(p.predicted_direction)}</td>
        <td>${p.ensemble_confidence.toFixed(3)}</td>
        <td>${p.horizon_days}d</td>
        <td>${p.status}</td>
        <td>${p.actual_return_pct == null ? "—" : fmtPctSigned(p.actual_return_pct)}</td>
        <td>${result}</td>
      </tr>
    `);
  }
}

function renderPredictions(payload) {
  _predState.all = payload?.predictions || [];
  document.getElementById("pred-search").addEventListener("input", e => {
    _predState.search = e.target.value.trim();
    renderPredictionsTable();
  });
  document.getElementById("pred-only-resolved").addEventListener("change", e => {
    _predState.onlyResolved = e.target.checked;
    renderPredictionsTable();
  });
  renderPredictionsTable();
}

// ---------------- Main ----------------

async function main() {
  const [sb, signals, bt, methodologies, preds, weights] = await Promise.all([
    loadJson(FILES.scoreboard),
    loadJson(FILES.signals),
    loadJson(FILES.backtest),
    loadJson(FILES.methodologies),
    loadJson(FILES.predictions),
    loadJson(FILES.weights),
  ]);
  renderFeatured(signals, methodologies);
  renderHolistic(signals);
  renderMethodologies(methodologies);
  renderBacktest(bt);
  renderPatterns(bt, weights);
  renderPerTicker(bt);
  renderScoreboard(sb);
  renderPredictions(preds);
}

main();
