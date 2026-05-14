// Dashboard renderer + Personal Agent.

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
  try { const r = await fetch(path, { cache: "no-store" }); if (!r.ok) return null; return await r.json(); }
  catch (e) { console.warn(path, e); return null; }
}

const setText = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };
const setHTML = (id, h) => { const el = document.getElementById(id); if (el) el.innerHTML = h; };

const tag = (text, klass) => `<span class="tag ${klass}">${text}</span>`;
const dirTag = (d) => d === "up" ? tag("UP", "up") : d === "down" ? tag("DOWN", "down") : tag("—", "neutral");

const sentimentChip = (s) => {
  if (!s) return "";
  const klass = s.label === "bullish" ? "up" : s.label === "bearish" ? "down" : "neutral";
  return `${tag(`news ${s.label}`, klass)}`;
};

// =========================================================================
// PERSONAL AGENT
// =========================================================================

// Mirror of analysis/sizing.py — ATR-based stop, confidence-scaled risk
function sizePosition(direction, entry, atr, confidence, capital, riskPct, maxPosPct) {
  const ATR_MULT = 2.0;
  if (direction !== "up" && direction !== "down") return null;
  if (entry <= 0 || atr <= 0) return null;

  let cf;
  if (confidence <= 0.5) cf = 0;
  else if (confidence >= 0.85) cf = 1;
  else cf = (confidence - 0.5) / 0.35;
  if (cf === 0) return null;

  const riskDollars = capital * (riskPct / 100) * cf;
  const stopDistance = ATR_MULT * atr;
  if (stopDistance <= 0) return null;

  const stop = direction === "up" ? entry - stopDistance : entry + stopDistance;
  const idealShares = riskDollars / stopDistance;
  const idealPosUsd = idealShares * entry;
  const maxPosUsd = capital * (maxPosPct / 100);
  const cappedShares = idealPosUsd > maxPosUsd ? maxPosUsd / entry : idealShares;
  const shares = Math.floor(cappedShares);
  if (shares <= 0) return null;
  const posUsd = shares * entry;
  const riskUsd = shares * stopDistance;
  return {
    direction, entry, stop, shares,
    posUsd, riskUsd,
    confFactor: cf,
    pctOfCapital: posUsd / capital,
  };
}

// Mirror of analysis/options.py heuristic
function recommendOptions(direction, confidence, spot, atr, horizon, allowed) {
  if (!allowed || (direction !== "up" && direction !== "down")) return null;
  if (confidence < 0.6) return null;
  const dte = Math.max(30, horizon * 2);
  const roundStrike = (p) => p < 50 ? Math.round(p) : p < 200 ? Math.round(p * 2) / 2 : Math.round(p / 5) * 5;
  if (direction === "up") {
    if (confidence >= 0.75 && horizon <= 20) {
      return { strategy: "long_call", longStrike: roundStrike(spot * 1.015), dte };
    }
    return { strategy: "bull_call_spread", longStrike: roundStrike(spot * 1.005), shortStrike: roundStrike(spot + atr * 2), dte };
  }
  if (confidence >= 0.75 && horizon <= 20) {
    return { strategy: "long_put", longStrike: roundStrike(spot * 0.985), dte };
  }
  return { strategy: "bear_put_spread", longStrike: roundStrike(spot * 0.995), shortStrike: roundStrike(spot - atr * 2), dte };
}

const _agent = {
  signals: [],
  meta_signals: [],
  horizons: [],
};

function setupAgent(signalsPayload) {
  _agent.signals = signalsPayload?.signals || [];
  _agent.meta_signals = signalsPayload?.meta_signals || [];

  // Horizons available from meta signals (or fall back to signals)
  const horizons = [...new Set(_agent.meta_signals.map(s => s.horizon_days))].sort((a, b) => a - b);
  _agent.horizons = horizons;
  const sel = document.getElementById("agent-horizon");
  sel.innerHTML = "";
  if (horizons.length === 0) {
    sel.innerHTML = `<option>—</option>`;
  } else {
    for (const h of horizons) sel.insertAdjacentHTML("beforeend", `<option value="${h}">${h}-day</option>`);
    sel.value = String(horizons[horizons.length - 1]); // default to longest (best edge)
  }

  document.getElementById("agent-form").addEventListener("input", renderAgent);
  renderAgent();
}

function getAgentInputs() {
  return {
    capital: parseFloat(document.getElementById("agent-capital").value) || 0,
    riskPct: parseFloat(document.getElementById("agent-risk-pct").value) || 2,
    maxPosPct: parseFloat(document.getElementById("agent-max-pos-pct").value) || 25,
    horizon: parseInt(document.getElementById("agent-horizon").value) || 60,
    minConf: parseFloat(document.getElementById("agent-min-conf").value) || 0.6,
    direction: document.getElementById("agent-direction").value,
    optionsAllowed: document.getElementById("agent-options-allowed").checked,
    skipEarnings: document.getElementById("agent-skip-earnings").checked,
    tickerFilter: document.getElementById("agent-ticker-filter").value.trim().toUpperCase(),
  };
}

function renderAgent() {
  const cfg = getAgentInputs();
  let candidates = _agent.meta_signals.filter(s => s.horizon_days === cfg.horizon);
  if (cfg.direction !== "any") candidates = candidates.filter(s => s.direction === cfg.direction);
  if (cfg.minConf) candidates = candidates.filter(s => s.confidence >= cfg.minConf);
  if (cfg.skipEarnings) candidates = candidates.filter(s => !s.earnings_in_horizon);
  if (cfg.tickerFilter) {
    const tokens = cfg.tickerFilter.split(/[,\s]+/).filter(Boolean);
    candidates = candidates.filter(s => tokens.some(t => s.ticker.startsWith(t)));
  }

  // Re-size each candidate using the user's capital
  const ranked = candidates.map(s => {
    const sizing = sizePosition(s.direction, s.price, s.atr, s.confidence, cfg.capital, cfg.riskPct, cfg.maxPosPct);
    const opts = recommendOptions(s.direction, s.confidence, s.price, s.atr, s.horizon_days, cfg.optionsAllowed);
    return { ...s, _sizing: sizing, _options: opts };
  }).filter(s => s._sizing !== null);

  ranked.sort((a, b) => b.confidence - a.confidence);

  setText("agent-summary",
    ranked.length === 0
      ? `No recommendations match your filters. Try lowering min confidence, switching horizon, or allowing both directions.`
      : `Showing ${Math.min(ranked.length, 10)} of ${ranked.length} matching recommendations (sized for $${cfg.capital.toLocaleString()} capital, ${cfg.riskPct}% risk per trade).`);

  const container = document.getElementById("agent-recommendations");
  container.innerHTML = "";
  if (ranked.length === 0) return;

  const showAll = ranked.length <= 10;
  const top = ranked.slice(0, 10);
  for (const s of top) {
    container.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg));
  }
  if (!showAll) {
    container.insertAdjacentHTML("beforeend", `
      <details class="show-more">
        <summary>Show all ${ranked.length} recommendations</summary>
        <div id="agent-recommendations-rest"></div>
      </details>
    `);
    const rest = document.getElementById("agent-recommendations-rest");
    for (const s of ranked.slice(10)) rest.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg));
  }
}

function renderRecommendationCard(s, cfg) {
  const dClass = s.direction === "up" ? "up" : "down";
  const sizing = s._sizing;
  const opts = s._options;

  const earningsWarn = s.earnings_in_days != null && s.earnings_in_days <= s.horizon_days
    ? `<span class="tag down" title="Earnings ${s.earnings_in_days}d away — event risk">⚠ earnings in ${s.earnings_in_days}d</span>`
    : (s.earnings_in_days != null
        ? `<span class="muted small">earnings in ${s.earnings_in_days}d (after horizon)</span>`
        : "");

  const sentChip = sentimentChip(s.sentiment);
  const contribs = (s.contributing_methodologies || [])
    .slice(0, 4)
    .map(c => `<span class="pattern-chip">${c.methodology}</span>`).join(" ");

  let optsLine = "";
  if (opts) {
    const strat = opts.strategy.replaceAll("_", " ");
    const strikeStr = opts.shortStrike
      ? `long $${opts.longStrike} / short $${opts.shortStrike}`
      : `long $${opts.longStrike}`;
    optsLine = `<div class="rec-line"><strong>Options alt:</strong> ${strat}, ${strikeStr}, ~${opts.dte}d to expiration</div>`;
  } else if (cfg.optionsAllowed) {
    optsLine = `<div class="rec-line muted">Options: not recommended at this confidence — equity only.</div>`;
  }

  return `
    <div class="rec-card">
      <div class="rec-header">
        <span class="rec-ticker">${s.ticker}</span>
        <span class="tag ${dClass}">${s.direction.toUpperCase()}</span>
        <span class="rec-meta">${s.horizon_days}d · conf ${s.confidence.toFixed(3)} · ${s.n_contributing} methods agree</span>
        ${earningsWarn}
        ${sentChip}
      </div>
      <div class="rec-line">
        <strong>Equity:</strong> Buy <strong>${fmtNum(sizing.shares)} shares</strong> @ ${fmtUsd(s.price)} · stop ${fmtUsd(sizing.stop)} · position ${fmtUsd(sizing.posUsd)} (${(sizing.pctOfCapital * 100).toFixed(1)}% of capital) · max risk ${fmtUsd(sizing.riskUsd)}
      </div>
      ${optsLine}
      <div class="rec-line muted small">Methodologies in favor: ${contribs}</div>
    </div>
  `;
}

// =========================================================================
// METHODOLOGY LEADERBOARD
// =========================================================================

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
    const byH = stats.by_horizon || {};
    let bestH = null, bestAcc = -1;
    for (const [h, v] of Object.entries(byH)) {
      if (v.accuracy != null && v.accuracy > bestAcc) { bestAcc = v.accuracy; bestH = h; }
    }
    const byHText = Object.entries(byH)
      .map(([h, v]) => `<span class="muted">${h}d:</span>${fmtPct(v.accuracy)}<span class="muted">(${v.signals})</span>`)
      .join(" · ");
    const klass = name === "meta_ensemble" ? "row-featured" : (stats.pruned ? "row-pruned" : "");
    const badge = name === "meta_ensemble" ? ` ${tag("META", "up")}` : (stats.pruned ? ` ${tag("PRUNED", "down")}` : "");
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${klass}">
        <td><strong>${name}</strong>${badge}<br><span class="muted small">${stats.description || ""}</span></td>
        <td>${fmtNum(stats.signals_emitted ?? 0)}</td>
        <td><strong>${fmtPct(stats.accuracy)}</strong></td>
        <td>${bestH ? `${bestH}d (${fmtPct(bestAcc)})` : "—"}</td>
        <td><span class="small">${byHText || "—"}</span></td>
      </tr>
    `);
  }
}

// =========================================================================
// SCOREBOARD
// =========================================================================

function renderScoreboard(sb) {
  if (!sb) return;
  setText("updated-at", sb.updated_at ? `updated ${sb.updated_at}` : "—");
  setText("overall-accuracy", fmtPct(sb.overall_accuracy));
  setText("overall-counts", `${sb.total_correct ?? 0} correct / ${(sb.total_resolved ?? 0) - (sb.total_correct ?? 0)} wrong (${sb.total_resolved ?? 0} resolved)`);
  setText("total-correct", fmtNum(sb.total_correct ?? 0));
  setText("total-wrong", fmtNum((sb.total_resolved ?? 0) - (sb.total_correct ?? 0)));
  setText("open-count", fmtNum(sb.open_predictions ?? 0));
  setText("bullish-accuracy", fmtPct(sb.bullish?.accuracy));
  setText("bearish-accuracy", fmtPct(sb.bearish?.accuracy));
  setText("scoreboard-context", (sb.total_resolved ?? 0) === 0
    ? "— no resolved live predictions yet; check back as horizons elapse"
    : `(${sb.total_resolved} resolved, ${sb.open_predictions} open)`);
}

// =========================================================================
// DETAILS (collapsed sections)
// =========================================================================

function renderBacktest(bt) {
  if (!bt) return;
  const ens = bt.ensemble || {};
  const dirTotal = ens.directional_total ?? 0;
  const dirCorrect = ens.directional_correct ?? 0;
  setText("bt-accuracy", fmtPct(ens.accuracy));
  setText("bt-counts", `${dirCorrect}/${dirTotal} directional calls (${ens.total_samples ?? 0} total, ${fmtPct(ens.neutral_rate)} neutral)`);
  setText("bt-bullish", fmtPct(ens.by_direction?.up?.accuracy));
  setText("bt-bearish", fmtPct(ens.by_direction?.down?.accuracy));

  const hBody = document.querySelector("#horizon-table tbody");
  hBody.innerHTML = "";
  for (const [h, v] of Object.entries(ens.by_horizon || {})) {
    hBody.insertAdjacentHTML("beforeend", `<tr><td>${h}d</td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>`);
  }

  const rBody = document.querySelector("#regime-table tbody");
  rBody.innerHTML = "";
  const order = ["bull", "bear", "choppy", "unknown"];
  const regimes = ens.by_regime || {};
  for (const r of order.filter(x => x in regimes).concat(Object.keys(regimes).filter(x => !order.includes(x)))) {
    const v = regimes[r];
    const klass = r === "bull" ? "up" : r === "bear" ? "down" : "neutral";
    rBody.insertAdjacentHTML("beforeend", `<tr><td>${tag(r, klass)}</td><td>${v.total}</td><td>${v.correct}</td><td>${fmtPct(v.accuracy)}</td></tr>`);
  }

  const calBody = document.querySelector("#calibration-table tbody");
  calBody.innerHTML = "";
  for (const row of ens.calibration || []) {
    calBody.insertAdjacentHTML("beforeend", `<tr><td>${(row.confidence_lo * 100).toFixed(0)}–${(row.confidence_hi * 100).toFixed(0)}%</td><td>${row.n}</td><td>${row.correct}</td><td>${fmtPct(row.accuracy)}</td></tr>`);
  }
}

function renderPatterns(bt, weightsPayload) {
  const patterns = bt?.patterns_flat || {};
  const w = weightsPayload?.weights || {};
  const tbody = document.querySelector("#patterns-table tbody");
  tbody.innerHTML = "";
  const names = new Set([...Object.keys(patterns), ...Object.keys(w)]);
  const rows = Array.from(names).map(n => ({ name: n, stats: patterns[n] || {}, weights_h: w[n] || {} }));
  rows.sort((a, b) => (b.stats.fires || 0) - (a.stats.fires || 0));
  for (const r of rows) {
    const s = r.stats;
    const wText = Object.keys(r.weights_h).sort((a, b) => parseInt(a) - parseInt(b))
      .map(h => `${h}d:${Number(r.weights_h[h]).toFixed(2)}`).join(" / ");
    tbody.insertAdjacentHTML("beforeend", `
      <tr>
        <td><code>${r.name}</code></td>
        <td>${fmtNum(s.fires ?? 0)}</td>
        <td>${fmtNum(s.correct ?? 0)}</td>
        <td>${fmtPct(s.raw_accuracy)}</td>
        <td>${fmtPct(s.shrunk_accuracy)}</td>
        <td><span class="green">${fmtNum(s.by_up ?? 0)}</span></td>
        <td><span class="red">${fmtNum(s.by_down ?? 0)}</span></td>
        <td><span class="small">${wText || "—"}</span></td>
      </tr>
    `);
  }
}

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
  if (rows.length === 0) { tbody.innerHTML = `<tr><td colspan="6" class="muted">No tickers match.</td></tr>`; return; }
  for (const r of rows.slice(0, 200)) {
    const thin = !r.min_samples_met ? ` <span class="muted small">(thin)</span>` : "";
    tbody.insertAdjacentHTML("beforeend", `
      <tr><td><strong>${r.ticker}</strong>${thin}</td><td>${r.n}</td><td>${r.correct}</td><td><strong>${fmtPct(r.accuracy)}</strong></td><td>${r.up_n}/${fmtPct(r.up_accuracy)}</td><td>${r.down_n}/${fmtPct(r.down_accuracy)}</td></tr>
    `);
  }
}
function renderPerTicker(bt) {
  _tickerState.all = bt?.per_ticker || {};
  document.getElementById("ticker-search").addEventListener("input", e => { _tickerState.search = e.target.value.trim(); renderPerTickerTable(); });
  document.getElementById("ticker-hide-thin").addEventListener("change", e => { _tickerState.hideThin = e.target.checked; renderPerTickerTable(); });
  renderPerTickerTable();
}

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
  if (rows.length === 0) { tbody.innerHTML = `<tr><td colspan="8" class="muted">No predictions match.</td></tr>`; return; }
  for (const p of rows) {
    const resolved = p.status === "resolved";
    const klass = !resolved ? "row-open" : p.correct ? "row-correct" : "row-wrong";
    const result = !resolved ? tag("OPEN", "open") : p.correct ? tag("CORRECT", "correct") : tag("WRONG", "wrong");
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${klass}">
        <td>${p.made_at}</td><td><strong>${p.ticker}</strong></td><td>${dirTag(p.predicted_direction)}</td>
        <td>${p.ensemble_confidence.toFixed(3)}</td><td>${p.horizon_days}d</td><td>${p.status}</td>
        <td>${p.actual_return_pct == null ? "—" : fmtPctSigned(p.actual_return_pct)}</td><td>${result}</td>
      </tr>
    `);
  }
}
function renderPredictions(payload) {
  _predState.all = payload?.predictions || [];
  document.getElementById("pred-search").addEventListener("input", e => { _predState.search = e.target.value.trim(); renderPredictionsTable(); });
  document.getElementById("pred-only-resolved").addEventListener("change", e => { _predState.onlyResolved = e.target.checked; renderPredictionsTable(); });
  renderPredictionsTable();
}

// =========================================================================
// MAIN
// =========================================================================

async function main() {
  const [sb, signals, bt, methodologies, preds, weights] = await Promise.all([
    loadJson(FILES.scoreboard),
    loadJson(FILES.signals),
    loadJson(FILES.backtest),
    loadJson(FILES.methodologies),
    loadJson(FILES.predictions),
    loadJson(FILES.weights),
  ]);
  setupAgent(signals);
  renderMethodologies(methodologies);
  renderScoreboard(sb);
  renderBacktest(bt);
  renderPatterns(bt, weights);
  renderPerTicker(bt);
  renderPredictions(preds);
}

main();
