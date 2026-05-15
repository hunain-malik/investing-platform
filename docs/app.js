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
  let chip = tag(`news ${s.label}`, klass);
  // Show cross-sectional relative label too (which compensates for VADER's positive bias)
  if (s.relative_label && s.relative_label !== "neutral_vs_peers") {
    const relText = s.relative_label === "bullish_vs_peers" ? "↑ vs peers" : "↓ vs peers";
    const relKlass = s.relative_label === "bullish_vs_peers" ? "up" : "down";
    chip += ` ${tag(relText, relKlass)}`;
  }
  return chip;
};

// Detect when news sentiment contradicts the model's directional prediction.
// Returns the contradiction note HTML, or "" if no conflict.
function sentimentContradictionChip(direction, sentiment) {
  if (!sentiment) return "";
  if (direction === "up" && sentiment.label === "bearish") {
    return `<span class="tag warn" title="Model expects price UP but recent news is bearish. Either the news is noise (e.g. backward-looking) or the model is wrong. Worth investigating before trading.">⚠ news disagrees</span>`;
  }
  if (direction === "down" && sentiment.label === "bullish") {
    return `<span class="tag warn" title="Model expects price DOWN but recent news is bullish. Either the news is noise (analyst upgrades after a run-up, etc.) or the model is wrong. Worth investigating before trading.">⚠ news disagrees</span>`;
  }
  if ((direction === "up" && sentiment.label === "bullish") ||
      (direction === "down" && sentiment.label === "bearish")) {
    return `<span class="tag confirm" title="News sentiment agrees with the model's directional call — confirmation signal.">✓ news agrees</span>`;
  }
  return "";
}

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

// Portfolio-mode sizing: allocate up to `slotCapital` per position. ATR-based
// stop still applies. Returns null only if even 1 share doesn't fit the slot.
function sizePortfolioSlot(direction, entry, atr, slotCapital) {
  const ATR_MULT = 2.0;
  if (direction !== "up" && direction !== "down") return null;
  if (entry <= 0) return null;
  const maxShares = Math.floor(slotCapital / entry);
  if (maxShares <= 0) return null;
  const stopDistance = atr > 0 ? atr * ATR_MULT : entry * 0.05; // 5% fallback if ATR missing
  const stop = direction === "up" ? entry - stopDistance : entry + stopDistance;
  const posUsd = maxShares * entry;
  const riskUsd = maxShares * stopDistance;
  return {
    direction, entry, stop,
    shares: maxShares,
    posUsd, riskUsd,
    confFactor: 1.0,
    pctOfCapital: posUsd / slotCapital,
  };
}

// Mirror of analysis/options.py heuristic
function recommendOptions(direction, confidence, spot, atr, horizon, allowed) {
  if (!allowed || (direction !== "up" && direction !== "down")) return null;
  if (confidence < 0.6) return null;
  // Skip options for very long horizons — listed options stop at LEAPS (~1y).
  if (horizon > 252) return { strategy: "none", longStrike: null, shortStrike: null, dte: null, skipReason: `horizon ${horizon}d > 1y — equity only` };
  // Retail-standard DTE: horizon + 30d buffer, clamped to [45, 365]
  const dte = Math.max(45, Math.min(365, horizon + 30));
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
  consensus_signals: [],
  source: "consensus",  // "consensus" (decorrelated families) or "meta" (correlated methodologies)
  horizons: [],
};

const STRATEGY_DESCRIPTIONS = {
  trading: "Trading: 3-6 month holds aimed at momentum and trend moves. Active position management.",
  swing: "Swing / Position: 1-2 year holds. Captures longer trends without the noise of intraday.",
  longterm: "Long-term / Roth: 5+ year holds. Best for tax-advantaged accounts; rides through multi-cycle moves.",
  all: "Custom: pick any horizon from the dropdown below.",
};

function applyStrategyFilter() {
  const activeTab = document.querySelector(".strategy-tab.active");
  if (!activeTab) return null;
  const allowed = activeTab.dataset.horizons;
  if (!allowed) return null; // "all" mode
  return allowed.split(",").map(s => parseInt(s));
}

function _currentAgentSignals() {
  return _agent.source === "consensus"
    ? (_agent.consensus_signals || [])
    : (_agent.meta_signals || []);
}

function setupAgent(signalsPayload) {
  _agent.signals = signalsPayload?.signals || [];
  _agent.meta_signals = signalsPayload?.meta_signals || [];
  _agent.consensus_signals = signalsPayload?.consensus_signals || [];

  // Default to decorrelated consensus if available, else fall back to meta
  if (_agent.consensus_signals.length === 0) _agent.source = "meta";

  // Horizons available from current source
  const source = _currentAgentSignals();
  const horizons = [...new Set(source.map(s => s.horizon_days))].sort((a, b) => a - b);
  _agent.horizons = horizons;
  const sel = document.getElementById("agent-horizon");
  sel.innerHTML = "";
  if (horizons.length === 0) {
    sel.innerHTML = `<option>—</option>`;
  } else {
    for (const h of horizons) sel.insertAdjacentHTML("beforeend", `<option value="${h}">${h}-day</option>`);
    // Default to first horizon in the active strategy (or longest if all)
    const allowed = applyStrategyFilter();
    if (allowed && allowed.length > 0 && horizons.includes(allowed[0])) {
      sel.value = String(allowed[0]);
    } else {
      sel.value = String(horizons[horizons.length - 1]);
    }
  }

  document.getElementById("agent-form").addEventListener("input", renderAgent);
  document.getElementById("agent-form").addEventListener("change", renderAgent);
  document.getElementById("agent-mode").addEventListener("change", e => {
    document.getElementById("agent-portfolio-n-wrap").style.display = (e.target.value === "portfolio") ? "" : "none";
  });

  // Source radio (decorrelated families vs correlated meta)
  for (const r of document.querySelectorAll('input[name="agent-source"]')) {
    r.addEventListener("change", e => {
      _agent.source = e.target.value;
      // Repopulate horizon dropdown — sources may have different horizons
      const source = _currentAgentSignals();
      const horizons = [...new Set(source.map(s => s.horizon_days))].sort((a, b) => a - b);
      const sel = document.getElementById("agent-horizon");
      sel.innerHTML = "";
      for (const h of horizons) sel.insertAdjacentHTML("beforeend", `<option value="${h}">${h}-day</option>`);
      if (horizons.length > 0) sel.value = String(horizons[horizons.length - 1]);
      renderAgent();
    });
  }

  // Strategy tab clicks
  for (const tab of document.querySelectorAll(".strategy-tab")) {
    tab.addEventListener("click", () => {
      for (const t of document.querySelectorAll(".strategy-tab")) t.classList.remove("active");
      tab.classList.add("active");
      const strategy = tab.dataset.strategy;
      setText("strategy-description", STRATEGY_DESCRIPTIONS[strategy] || "");
      // If the strategy has horizons, default the horizon dropdown to the first
      const allowed = applyStrategyFilter();
      if (allowed && allowed.length > 0) {
        const sel = document.getElementById("agent-horizon");
        if ([...sel.options].some(o => parseInt(o.value) === allowed[0])) {
          sel.value = String(allowed[0]);
        }
      }
      renderAgent();
    });
  }

  renderAgent();
}

function getAgentInputs() {
  return {
    capital: parseFloat(document.getElementById("agent-capital").value) || 0,
    riskPct: parseFloat(document.getElementById("agent-risk-pct").value) || 2,
    maxPosPct: parseFloat(document.getElementById("agent-max-pos-pct").value) || 25,
    horizon: parseInt(document.getElementById("agent-horizon").value) || 60,
    minConf: parseFloat(document.getElementById("agent-min-conf").value) || 0.55,
    direction: document.getElementById("agent-direction").value,
    optionsAllowed: document.getElementById("agent-options-allowed").checked,
    skipEarnings: document.getElementById("agent-skip-earnings").checked,
    mode: document.getElementById("agent-mode").value,
    portfolioN: parseInt(document.getElementById("agent-portfolio-n").value) || 5,
    tickerFilter: document.getElementById("agent-ticker-filter").value.trim().toUpperCase(),
  };
}

function renderAgent() {
  const cfg = getAgentInputs();
  const container = document.getElementById("agent-recommendations");
  container.innerHTML = "";

  const sourceSignals = _currentAgentSignals();
  if (sourceSignals.length === 0) {
    setText("agent-summary", `No signals fired today for the selected source. The decorrelated consensus needs ≥3 independent pattern families agreeing. Try switching to the correlated meta-ensemble (less strict) using the toggle above.`);
    return;
  }

  // Diagnostics: how many at each filter step?
  const totalAtHorizon = sourceSignals.filter(s => s.horizon_days === cfg.horizon).length;

  let candidates = sourceSignals.filter(s => s.horizon_days === cfg.horizon);
  if (cfg.direction !== "any") candidates = candidates.filter(s => s.direction === cfg.direction);
  if (cfg.minConf) candidates = candidates.filter(s => s.confidence >= cfg.minConf);
  if (cfg.skipEarnings) candidates = candidates.filter(s => !s.earnings_in_horizon);
  if (cfg.tickerFilter) {
    const tokens = cfg.tickerFilter.split(/[,\s]+/).filter(Boolean);
    candidates = candidates.filter(s => tokens.some(t => s.ticker.startsWith(t)));
  }

  // Re-size each candidate using the user's capital
  let ranked = candidates.map(s => {
    const sizing = sizePosition(s.direction, s.price, s.atr, s.confidence, cfg.capital, cfg.riskPct, cfg.maxPosPct);
    const opts = recommendOptions(s.direction, s.confidence, s.price, s.atr, s.horizon_days, cfg.optionsAllowed);
    return { ...s, _sizing: sizing, _options: opts };
  }).filter(s => s._sizing !== null);

  ranked.sort((a, b) => b.confidence - a.confidence);

  if (ranked.length === 0) {
    setText("agent-summary",
      `No recommendations match your filters (${totalAtHorizon} signals exist at ${cfg.horizon}d horizon, but none pass confidence ≥ ${cfg.minConf} + your other filters). Try lowering min confidence, switching horizon, or allowing both directions.`);
    return;
  }

  // Portfolio mode: pick top-N affordable, allocate slot capital each.
  if (cfg.mode === "portfolio") {
    const targetN = cfg.portfolioN;
    const perSlot = cfg.capital / targetN;

    // Pre-filter to affordable stocks (at least 1 share fits per slot)
    const affordable = ranked.filter(s => s.price <= perSlot * 0.98);

    if (affordable.length === 0) {
      const cheapestPrice = ranked.length > 0 ? Math.min(...ranked.map(r => r.price)) : 0;
      const minCapitalNeeded = cheapestPrice * targetN;
      setText("agent-summary",
        `Portfolio mode: no stocks priced cheap enough to fit ${targetN} positions of ~${fmtUsd(perSlot)} each. The cheapest qualifying recommendation is ${fmtUsd(cheapestPrice)}/share, which would need ${fmtUsd(minCapitalNeeded)} of total capital for ${targetN} positions. Try fewer positions or more capital.`);
      return;
    }

    // If fewer affordable than requested, reduce N to fit
    const actualN = Math.min(targetN, affordable.length);
    const actualSlot = cfg.capital / actualN;
    const picks = affordable.slice(0, actualN).map(s => {
      const sizing = sizePortfolioSlot(s.direction, s.price, s.atr, actualSlot);
      const opts = recommendOptions(s.direction, s.confidence, s.price, s.atr, s.horizon_days, cfg.optionsAllowed);
      return { ...s, _sizing: sizing, _options: opts };
    }).filter(s => s._sizing !== null);

    const totalPosUsd = picks.reduce((a, s) => a + s._sizing.posUsd, 0);
    const totalRiskUsd = picks.reduce((a, s) => a + s._sizing.riskUsd, 0);
    const adjustedNote = actualN < targetN
      ? ` (reduced from ${targetN} because not enough affordable stocks fit at ${fmtUsd(cfg.capital / targetN)}/slot)`
      : "";
    setText("agent-summary",
      `Portfolio mode: ${picks.length} positions${adjustedNote}, ~${fmtUsd(actualSlot)} each. Total deployed ${fmtUsd(totalPosUsd)} (${(totalPosUsd/cfg.capital*100).toFixed(0)}% of capital), at-risk ${fmtUsd(totalRiskUsd)} (${(totalRiskUsd/cfg.capital*100).toFixed(1)}%). Sized to allocate slot capital (ignores per-trade risk cap so you actually get diversified positions).`);
    for (const s of picks) container.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg));
    return;
  }

  // Ranked mode (default)
  setText("agent-summary",
    `Showing ${Math.min(ranked.length, 10)} of ${ranked.length} matching recommendations (sized for ${fmtUsd(cfg.capital)} capital, ${cfg.riskPct}% risk per trade).`);

  const top = ranked.slice(0, 10);
  for (const s of top) {
    container.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg));
  }
  if (ranked.length > 10) {
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
  // s.n_contributing (meta) vs s.n_families (consensus) — normalize for display
  const nVoters = s.n_contributing ?? s.n_families ?? 0;
  const voterType = s.n_families != null ? "families" : "methods";

  const earningsWarn = s.earnings_in_days != null && s.earnings_in_days <= s.horizon_days
    ? `<span class="tag down" title="Earnings ${s.earnings_in_days}d away — event risk">⚠ earnings in ${s.earnings_in_days}d</span>`
    : (s.earnings_in_days != null
        ? `<span class="muted small">earnings in ${s.earnings_in_days}d (after horizon)</span>`
        : "");

  const sentChip = sentimentChip(s.sentiment);
  // Show contributing voters — different schemas for consensus vs meta sources
  const familyVoters = s.contributing_families || [];
  const methodVoters = s.contributing_methodologies || [];
  const contribs = familyVoters.length > 0
    ? familyVoters.map(c => `<span class="pattern-chip" title="${c.family} family voted ${c.direction.toUpperCase()} with ${(c.internal_confidence * 100).toFixed(0)}% internal agreement; accuracy weight ${(c.accuracy_weight * 100).toFixed(0)}% (from ${(c.accuracy * 100).toFixed(1)}% backtest accuracy)">${c.family} → ${c.direction.toUpperCase()}</span>`).join(" ")
    : methodVoters.map(c => `<span class="pattern-chip" title="${c.methodology} fired ${c.direction.toUpperCase()} at confidence ${c.confidence}, weighted by ${(c.weight * 100).toFixed(0)}% (from accuracy ${(c.accuracy * 100).toFixed(1)}%)">${c.methodology} → ${c.direction.toUpperCase()}</span>`).join(" ");

  let optsLine = "";
  if (opts && opts.strategy === "none") {
    optsLine = `<div class="rec-line muted">Options: <em>not recommended</em> — ${opts.skipReason}.</div>`;
  } else if (opts) {
    const strat = opts.strategy.replaceAll("_", " ");
    const strikeStr = opts.shortStrike
      ? `long $${opts.longStrike} / short $${opts.shortStrike}`
      : `long $${opts.longStrike}`;
    optsLine = `<div class="rec-line"><strong>Options alt:</strong> ${strat}, ${strikeStr}, ~${opts.dte}d to expiration</div>`;
  } else if (cfg.optionsAllowed) {
    optsLine = `<div class="rec-line muted">Options: not recommended at this confidence — equity only.</div>`;
  }

  // Recent news headlines if sentiment available
  let newsBlock = "";
  if (s.sentiment && Array.isArray(s.sentiment.headlines) && s.sentiment.headlines.length > 0) {
    const items = s.sentiment.headlines.slice(0, 3).map(h => `<li>${h}</li>`).join("");
    newsBlock = `
      <details class="news-details">
        <summary class="muted small">Recent headlines (${s.sentiment.headline_count})</summary>
        <ul class="news-list">${items}</ul>
      </details>
    `;
  }

  const consensusPct = Math.abs(s.vote_margin * 100).toFixed(1);
  const contradictionChip = sentimentContradictionChip(s.direction, s.sentiment);
  // Equity recommendation depends on direction:
  // - UP   -> long entry (buy shares, sell at target / stop below)
  // - DOWN -> short entry (sell-to-open, requires margin account; stop above)
  let equityLine;
  if (s.direction === "up") {
    equityLine = `
      <div class="rec-line">
        <strong>Equity (long):</strong> <strong>Buy ${fmtNum(sizing.shares)} shares</strong> @ ${fmtUsd(s.price)} · stop-loss ${fmtUsd(sizing.stop)} · position ${fmtUsd(sizing.posUsd)} (${(sizing.pctOfCapital * 100).toFixed(1)}% of capital) · max risk ${fmtUsd(sizing.riskUsd)}
      </div>`;
  } else if (s.direction === "down") {
    equityLine = `
      <div class="rec-line">
        <strong>Equity (short):</strong> <strong>Short-sell ${fmtNum(sizing.shares)} shares</strong> @ ${fmtUsd(s.price)} · stop-loss ${fmtUsd(sizing.stop)} (buy-to-cover if price rises here) · position ${fmtUsd(sizing.posUsd)} (${(sizing.pctOfCapital * 100).toFixed(1)}% of capital) · max risk ${fmtUsd(sizing.riskUsd)}
      </div>
      <div class="rec-line muted small">⚠ Shorting requires a margin-enabled brokerage account. Not allowed in IRAs/Roth IRAs. If you can't short, consider a put option (see below) or simply <em>avoid buying</em> this name until the bearish horizon resolves.</div>`;
  } else {
    equityLine = `<div class="rec-line muted">No directional call.</div>`;
  }

  return `
    <div class="rec-card">
      <div class="rec-header">
        <a href="#" class="rec-ticker ticker-link" data-ticker="${s.ticker}">${s.ticker}</a>
        <span class="tag ${dClass}">${s.direction.toUpperCase()}</span>
        <span class="rec-meta" title="Consensus: how strongly the contributing voters agree on direction. 0% = tied, 100% = unanimous. NOT a price change prediction.">${s.horizon_days}d · conf ${s.confidence.toFixed(3)} · consensus ${consensusPct}% · ${nVoters} ${voterType} agree</span>
        ${earningsWarn}
        ${sentChip}
        ${contradictionChip}
      </div>
      ${equityLine}
      ${optsLine}
      <div class="rec-line muted small">Voted in favor: ${contribs}</div>
      ${newsBlock}
    </div>
  `;
}

// =========================================================================
// TICKER DEEP-DIVE MODAL
// =========================================================================

const _allData = { signals: null, backtest: null, predictions: null };

function showTickerModal(ticker) {
  const body = document.getElementById("ticker-modal-body");
  ticker = ticker.toUpperCase();

  const metas = (_allData.signals?.meta_signals || []).filter(s => s.ticker === ticker);
  const allSigs = (_allData.signals?.signals || []).filter(s => s.ticker === ticker);
  const perTicker = _allData.backtest?.per_ticker?.[ticker] || null;
  const ticker_preds = (_allData.predictions?.predictions || []).filter(p => p.ticker === ticker).slice(0, 20);
  const sentiment = _allData.signals?.sentiments?.[ticker];

  const sigByHorizon = {};
  for (const s of allSigs) {
    sigByHorizon[s.horizon_days] = sigByHorizon[s.horizon_days] || [];
    sigByHorizon[s.horizon_days].push(s);
  }

  const sample = allSigs[0] || metas[0];
  const price = sample?.price;
  const atr = sample?.atr;
  const firedPatterns = sample?.fired_patterns || [];

  let metaHtml = "";
  if (metas.length > 0) {
    metaHtml = `<div class="modal-section">
      <h4>Holistic meta-ensemble across horizons</h4>
      <p class="muted small">Consensus = how unanimously the contributing methodologies agree on direction (100% = all agree). Not a price change.</p>
      <table style="width:100%"><thead><tr><th>Horizon</th><th>Direction</th><th>Confidence</th><th>Consensus</th><th>Methods</th></tr></thead><tbody>
      ${metas.sort((a,b) => a.horizon_days - b.horizon_days).map(m => `
        <tr>
          <td>${m.horizon_days}d</td>
          <td>${dirTag(m.direction)}</td>
          <td>${m.confidence.toFixed(3)}</td>
          <td>${Math.abs(m.vote_margin * 100).toFixed(1)}%</td>
          <td>${m.contributing_methodologies.map(c => `<span class="pattern-chip">${c.methodology} ${c.direction[0].toUpperCase()}</span>`).join(" ")}</td>
        </tr>
      `).join("")}
      </tbody></table>
    </div>`;
  } else {
    metaHtml = `<div class="modal-section"><h4>Holistic meta-ensemble</h4><p class="muted">No meta signal fired for ${ticker} today.</p></div>`;
  }

  const patternsHtml = firedPatterns.length > 0
    ? `<div class="modal-section">
        <h4>Patterns fired today (${firedPatterns.length})</h4>
        <ul class="news-list">${firedPatterns.map(p => `<li><code>${p.name}</code> → ${p.direction.toUpperCase()} (conf ${p.confidence.toFixed(2)}) — <span class="muted">${p.note}</span></li>`).join("")}</ul>
      </div>`
    : `<div class="modal-section"><h4>Patterns fired today</h4><p class="muted">No patterns fired for ${ticker}.</p></div>`;

  let sentHtml = "";
  if (sentiment) {
    const items = (sentiment.headlines || []).slice(0, 5).map(h => `<li>${h}</li>`).join("");
    sentHtml = `<div class="modal-section">
      <h4>News sentiment: ${sentiment.label} (${sentiment.score.toFixed(2)})</h4>
      <ul class="news-list">${items || "<li>no headlines</li>"}</ul>
    </div>`;
  }

  const tickerHist = perTicker
    ? `<div class="modal-section">
        <h4>Backtest accuracy for ${ticker}</h4>
        <p>
          <strong>${fmtPct(perTicker.accuracy)}</strong> on ${perTicker.n} samples (${perTicker.correct} correct)
          ${!perTicker.min_samples_met ? '<span class="muted small">(small sample)</span>' : ""}
        </p>
        <p class="muted small">
          Bullish ${perTicker.up_n}/${fmtPct(perTicker.up_accuracy)} · Bearish ${perTicker.down_n}/${fmtPct(perTicker.down_accuracy)}
        </p>
      </div>`
    : `<div class="modal-section"><h4>Backtest accuracy for ${ticker}</h4><p class="muted">No backtest data for ${ticker} yet.</p></div>`;

  const predsHtml = ticker_preds.length > 0
    ? `<div class="modal-section"><h4>Live predictions for ${ticker}</h4>
      <table style="width:100%"><thead><tr><th>Made</th><th>Direction</th><th>Conf</th><th>Horizon</th><th>Status</th><th>Return</th></tr></thead><tbody>
      ${ticker_preds.map(p => `<tr>
        <td>${p.made_at}</td><td>${dirTag(p.predicted_direction)}</td><td>${p.ensemble_confidence.toFixed(2)}</td>
        <td>${p.horizon_days}d</td><td>${p.status}</td><td>${p.actual_return_pct == null ? "—" : fmtPctSigned(p.actual_return_pct)}</td>
      </tr>`).join("")}
      </tbody></table>
      </div>`
    : "";

  body.innerHTML = `
    <h2>${ticker} <span class="muted small">${price ? "@ " + fmtUsd(price) : ""}</span></h2>
    <p class="muted small">Today's snapshot ${sample?.as_of ? "as of " + sample.as_of : ""}.</p>
    ${metaHtml}
    ${patternsHtml}
    ${sentHtml}
    ${tickerHist}
    ${predsHtml}
  `;
  document.getElementById("ticker-modal").hidden = false;
}

function setupTickerModal() {
  document.getElementById("ticker-modal-close").addEventListener("click", () => {
    document.getElementById("ticker-modal").hidden = true;
  });
  document.getElementById("ticker-modal").addEventListener("click", e => {
    if (e.target.id === "ticker-modal") document.getElementById("ticker-modal").hidden = true;
  });
  document.addEventListener("click", e => {
    const a = e.target.closest(".ticker-link");
    if (a) {
      e.preventDefault();
      const ticker = a.dataset.ticker || a.textContent.trim();
      showTickerModal(ticker);
    }
  });
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

  // Bullish vs bearish K-fold split (derive from kfold direction breakdown if available;
  // else compute from regime aggregates as approximation)
  const kfoldDirSplit = kfold.by_direction || null;
  if (kfoldDirSplit && (kfoldDirSplit.up || kfoldDirSplit.down)) {
    const up = kfoldDirSplit.up || {};
    const dn = kfoldDirSplit.down || {};
    setText("kfold-direction-split",
      `Bullish: ${fmtPct(up.accuracy)} (${up.signals ?? 0}) · Bearish: ${fmtPct(dn.accuracy)} (${dn.signals ?? 0})`);
  } else {
    setText("kfold-direction-split", "Bullish/bearish split: see by-regime + by-horizon tables below");
  }

  // Numerical model side-by-side
  const num = payload.numerical_model_kfold || {};
  setText("numerical-accuracy", fmtPct(num.accuracy));
  setText("numerical-counts", num.accuracy != null
    ? `${num.correct} correct / ${(num.signals_emitted ?? 0) - (num.correct ?? 0)} wrong of ${num.signals_emitted ?? 0} signals`
    : (num.note || "—"));

  // K-fold horizon + regime breakouts (the user can't see these otherwise)
  const khBody = document.querySelector("#kfold-horizon-table tbody");
  if (khBody) {
    khBody.innerHTML = "";
    for (const [h, v] of Object.entries(kfold.by_horizon || {})) {
      khBody.insertAdjacentHTML("beforeend", `<tr><td>${h}d</td><td>${v.signals}</td><td><strong>${fmtPct(v.accuracy)}</strong></td></tr>`);
    }
  }
  const krBody = document.querySelector("#kfold-regime-table tbody");
  if (krBody) {
    krBody.innerHTML = "";
    const order = ["bull", "bear", "choppy", "unknown"];
    const regimes = kfold.by_regime || {};
    for (const r of order.filter(x => x in regimes).concat(Object.keys(regimes).filter(x => !order.includes(x)))) {
      const v = regimes[r];
      const klass = r === "bull" ? "up" : r === "bear" ? "down" : "neutral";
      krBody.insertAdjacentHTML("beforeend", `<tr><td>${tag(r, klass)}</td><td>${v.signals}</td><td><strong>${fmtPct(v.accuracy)}</strong></td></tr>`);
    }
  }

  // Numerical model breakouts
  const nhBody = document.querySelector("#numerical-horizon-table tbody");
  if (nhBody) {
    nhBody.innerHTML = "";
    for (const [h, v] of Object.entries(num.by_horizon || {})) {
      nhBody.insertAdjacentHTML("beforeend", `<tr><td>${h}d</td><td>${v.signals}</td><td><strong>${fmtPct(v.accuracy)}</strong></td></tr>`);
    }
  }
  const nrBody = document.querySelector("#numerical-regime-table tbody");
  if (nrBody) {
    nrBody.innerHTML = "";
    const order = ["bull", "bear", "choppy", "unknown"];
    const regimes = num.by_regime || {};
    for (const r of order.filter(x => x in regimes).concat(Object.keys(regimes).filter(x => !order.includes(x)))) {
      const v = regimes[r];
      const klass = r === "bull" ? "up" : r === "bear" ? "down" : "neutral";
      nrBody.insertAdjacentHTML("beforeend", `<tr><td>${tag(r, klass)}</td><td>${v.signals}</td><td><strong>${fmtPct(v.accuracy)}</strong></td></tr>`);
    }
  }
  const ncBody = document.querySelector("#numerical-coef-table tbody");
  if (ncBody) {
    ncBody.innerHTML = "";
    const coefs = num.model_coefficients || {};
    const sorted = Object.entries(coefs).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    for (const [feat, c] of sorted) {
      const dirText = c > 0 ? "↑ bullish driver" : "↓ bearish driver";
      const klass = c > 0 ? "up" : "down";
      ncBody.insertAdjacentHTML("beforeend", `<tr><td><code>${feat}</code></td><td>${c.toFixed(3)}</td><td>${tag(dirText, klass)}</td></tr>`);
    }
  }
  const ncalBody = document.querySelector("#numerical-calibration-table tbody");
  if (ncalBody) {
    ncalBody.innerHTML = "";
    for (const row of num.calibration || []) {
      ncalBody.insertAdjacentHTML("beforeend", `<tr><td>${(row.confidence_lo * 100).toFixed(0)}–${(row.confidence_hi * 100).toFixed(0)}%</td><td>${row.n}</td><td>${fmtPct(row.accuracy)}</td></tr>`);
    }
  }

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
    let klass = "", badge = "";
    if (name === "consensus_families") {
      klass = "row-featured";
      badge = ` ${tag("DECORRELATED", "confirm")}`;
    } else if (name === "meta_ensemble") {
      klass = "row-featured";
      badge = ` ${tag("META (correlated)", "up")}`;
    } else if (stats.pruned) {
      klass = "row-pruned";
      badge = ` ${tag("PRUNED", "down")}`;
    }
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
      <tr><td><a href="#" class="ticker-link" data-ticker="${r.ticker}"><strong>${r.ticker}</strong></a>${thin}</td><td>${r.n}</td><td>${r.correct}</td><td><strong>${fmtPct(r.accuracy)}</strong></td><td>${r.up_n}/${fmtPct(r.up_accuracy)}</td><td>${r.down_n}/${fmtPct(r.down_accuracy)}</td></tr>
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
        <td>${p.made_at}</td><td><a href="#" class="ticker-link" data-ticker="${p.ticker}"><strong>${p.ticker}</strong></a></td><td>${dirTag(p.predicted_direction)}</td>
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
  _allData.signals = signals;
  _allData.backtest = bt;
  _allData.predictions = preds;
  setupTickerModal();
  setupAgent(signals);
  renderMethodologies(methodologies);
  renderScoreboard(sb);
  renderBacktest(bt);
  renderPatterns(bt, weights);
  renderPerTicker(bt);
  renderPredictions(preds);
}

main();
