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
function recommendOptions(direction, confidence, spot, atr, horizon, allowed, halalOnly) {
  if (!allowed || (direction !== "up" && direction !== "down")) return null;
  // Conventional listed options (calls, puts, vertical spreads) are widely
  // considered non-compliant in mainstream Islamic finance scholarship — AAOIFI
  // Sharia Standard 20 cites gharar (excessive uncertainty), maysir (speculative
  // / gambling element), and absence of underlying ownership transfer. When the
  // Halal filter is on we suppress all option tactics and recommend equity only.
  if (halalOnly) {
    return { strategy: "none", longStrike: null, shortStrike: null, dte: null, skipReason: "conventional options are non-compliant per AAOIFI (gharar / maysir) — equity only under Halal filter" };
  }
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
  sentiments: {},
  horizons: [],
  tickerSectors: {},    // {ticker: sector}
  sectorStats: {},      // {sector: {accuracy, n}}
  selectedSectors: null, // null = all selected, Set otherwise
  halalStatus: {},      // {ticker: {compliant: bool, exclusion_reason: str|null}}
};

// Build a unified per-(ticker, horizon) recommendation list at one horizon.
// Source priority per ticker: consensus_families → meta → no_signal fallback.
// Tickers without an actionable signal still get a placeholder so they remain
// visible/searchable in the agent.
function _buildUnifiedRecs(horizon) {
  const out = [];
  const consensusByTicker = new Map();
  for (const s of _agent.consensus_signals || []) {
    if (s.horizon_days === horizon) consensusByTicker.set(s.ticker, s);
  }
  const metaByTicker = new Map();
  for (const s of _agent.meta_signals || []) {
    if (s.horizon_days === horizon) metaByTicker.set(s.ticker, s);
  }
  for (const baseSig of _agent.signals || []) {
    if (baseSig.horizon_days !== horizon) continue;
    const t = baseSig.ticker;
    const sentiment = _agent.sentiments?.[t] || null;
    const consensus = consensusByTicker.get(t);
    const meta = metaByTicker.get(t);
    // Sector lookup — fall back to ticker_sectors map if meta/consensus
    // didn't carry sector directly
    const tickerSector = consensus?.sector || meta?.sector || _agent.tickerSectors[t] || "Unknown";
    if (consensus) {
      out.push({
        ...consensus,
        _source: "consensus",
        _baseSig: baseSig,
        sentiment: consensus.sentiment || sentiment,
        sector: tickerSector,
      });
    } else if (meta) {
      out.push({
        ...meta,
        _source: "meta",
        _baseSig: baseSig,
        sentiment: meta.sentiment || sentiment,
        sector: tickerSector,
      });
    } else {
      // No meta or consensus signal — but if the all-ensemble has strong
      // conviction (≥0.75 conf + ≥3 patterns fired), surface as a "tentative"
      // recommendation. These haven't been validated by meta/consensus but
      // they're not just noise either. Many horizons (esp. 60d) have no
      // meta/consensus signals at all, so this is the only way to see
      // anything actionable on those tabs.
      const isStrong = baseSig.direction !== "neutral"
        && (baseSig.confidence ?? 0) >= 0.75
        && (baseSig.n_fired ?? 0) >= 3;
      out.push({
        ticker: t,
        as_of: baseSig.as_of,
        horizon_days: baseSig.horizon_days,
        direction: baseSig.direction,
        confidence: baseSig.confidence,
        price: baseSig.price,
        atr: baseSig.atr,
        sentiment: sentiment,
        sector: tickerSector,
        n_fired: baseSig.n_fired ?? (baseSig.fired_patterns || []).length,
        earnings_in_days: null,
        earnings_in_horizon: false,
        vote_margin: null,
        n_contributing: 0,
        n_families: 0,
        contributing_methodologies: [],
        contributing_families: [],
        _source: isStrong ? "tentative" : "no_signal",
        _baseSig: baseSig,
      });
    }
  }
  return out;
}

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

function setupAgent(signalsPayload) {
  _agent.signals = signalsPayload?.signals || [];
  _agent.meta_signals = signalsPayload?.meta_signals || [];
  _agent.consensus_signals = signalsPayload?.consensus_signals || [];
  _agent.sentiments = signalsPayload?.sentiments || {};
  // Sector data — pulled from backtest.json (set up in main())
  _agent.tickerSectors = _allData.backtest?.ticker_sectors || {};
  _agent.sectorStats = _allData.backtest?.by_sector || {};
  _agent.halalStatus = _allData.backtest?.halal_status || {};
  _setupSectorCheckboxes();

  // Horizons available from base all-ensemble signals (covers every ticker)
  const horizons = [...new Set(_agent.signals.map(s => s.horizon_days))].sort((a, b) => a - b);
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
  document.getElementById("agent-advanced-form")?.addEventListener("input", renderAgent);
  document.getElementById("agent-advanced-form")?.addEventListener("change", renderAgent);
  document.getElementById("agent-mode").addEventListener("change", e => {
    document.getElementById("agent-portfolio-n-wrap").style.display = (e.target.value === "portfolio") ? "" : "none";
  });

  // Sector quick-action buttons
  document.getElementById("agent-sector-all")?.addEventListener("click", () => _setSectorCheckboxes("all"));
  document.getElementById("agent-sector-none")?.addEventListener("click", () => _setSectorCheckboxes("none"));
  document.getElementById("agent-sector-invert")?.addEventListener("click", () => _setSectorCheckboxes("invert"));

  // Clear all filters — reset to defaults, no preset, no preferences
  document.getElementById("agent-clear-btn")?.addEventListener("click", () => {
    const defaults = {
      "agent-capital": "3000",
      "agent-risk-pct": "2",
      "agent-max-pos-pct": "25",
      "agent-min-conf": "0.5",  // most permissive
      "agent-direction": "any",
      "agent-mode": "ranked",
      "agent-portfolio-n": "5",
      "agent-ticker-filter": "",
      // Advanced filters
      "agent-style": "none",
      "agent-min-price": "0",
      "agent-max-price": "10000",
      "agent-volatility": "any",
      "agent-min-patterns": "0",
    };
    for (const [id, value] of Object.entries(defaults)) {
      const el = document.getElementById(id);
      if (el) el.value = value;
    }
    // Checkboxes: leave options-allowed on, but uncheck the filtering checkboxes
    const optsAllowed = document.getElementById("agent-options-allowed");
    if (optsAllowed) optsAllowed.checked = true;
    const skipEarnings = document.getElementById("agent-skip-earnings");
    if (skipEarnings) skipEarnings.checked = false;  // most permissive
    const hideNoSignal = document.getElementById("agent-hide-no-signal");
    if (hideNoSignal) hideNoSignal.checked = false;
    // Reset to first horizon (longest available)
    const horizonSel = document.getElementById("agent-horizon");
    if (horizonSel && horizonSel.options.length > 0) {
      horizonSel.selectedIndex = horizonSel.options.length - 1;
    }
    // Reset strategy tab to "Custom (any horizon)"
    document.querySelectorAll(".strategy-tab").forEach(t => t.classList.remove("active"));
    document.querySelector('.strategy-tab[data-strategy="all"]')?.classList.add("active");
    setText("strategy-description", STRATEGY_DESCRIPTIONS.all || "");
    // Hide portfolio-n field since mode is back to ranked
    const portWrap = document.getElementById("agent-portfolio-n-wrap");
    if (portWrap) portWrap.style.display = "none";
    renderAgent();
  });

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

function _setupSectorCheckboxes() {
  const container = document.getElementById("agent-sector-checkboxes");
  if (!container) return;
  // Collect all unique sectors from tickerSectors + sectorStats (union)
  const sectorSet = new Set([
    ...Object.values(_agent.tickerSectors),
    ...Object.keys(_agent.sectorStats),
  ]);
  // Order: by sector accuracy (desc), Unknown/NONE/etc at the bottom
  const sectorList = [...sectorSet].sort((a, b) => {
    const accA = _agent.sectorStats[a]?.accuracy ?? -1;
    const accB = _agent.sectorStats[b]?.accuracy ?? -1;
    return accB - accA;
  });
  container.innerHTML = "";
  if (sectorList.length === 0) {
    container.innerHTML = `<span class="muted small">No sector data yet (workflow needs to run with sector fetching).</span>`;
    return;
  }
  for (const sector of sectorList) {
    const stat = _agent.sectorStats[sector];
    const accStr = stat?.accuracy != null ? `${(stat.accuracy * 100).toFixed(0)}%` : "—";
    const nTickers = Object.values(_agent.tickerSectors).filter(s => s === sector).length;
    container.insertAdjacentHTML("beforeend", `
      <label class="sector-checkbox-row" data-sector="${sector}">
        <input type="checkbox" class="sector-checkbox" value="${sector}" checked />
        <span>${sector}</span>
        <span class="sector-stat">${accStr} acc · ${nTickers} stocks</span>
      </label>
    `);
  }
  // Wire up change handler
  container.querySelectorAll(".sector-checkbox").forEach(cb => {
    cb.addEventListener("change", renderAgent);
  });
  // Initialize selectedSectors to all
  _refreshSelectedSectors();
}

function _refreshSelectedSectors() {
  const checked = [...document.querySelectorAll(".sector-checkbox:checked")].map(cb => cb.value);
  const all = [...document.querySelectorAll(".sector-checkbox")].map(cb => cb.value);
  _agent.selectedSectors = (checked.length === all.length) ? null : new Set(checked);
}

function _setSectorCheckboxes(mode) {
  document.querySelectorAll(".sector-checkbox").forEach(cb => {
    if (mode === "all") cb.checked = true;
    else if (mode === "none") cb.checked = false;
    else if (mode === "invert") cb.checked = !cb.checked;
  });
  _refreshSelectedSectors();
  renderAgent();
}

function getAgentInputs() {
  const cfg = {
    capital: parseFloat(document.getElementById("agent-capital").value) || 0,
    riskPct: parseFloat(document.getElementById("agent-risk-pct").value) || 2,
    maxPosPct: parseFloat(document.getElementById("agent-max-pos-pct").value) || 25,
    horizon: parseInt(document.getElementById("agent-horizon").value) || 60,
    minConf: parseFloat(document.getElementById("agent-min-conf").value) || 0.55,
    direction: document.getElementById("agent-direction").value,
    optionsAllowed: document.getElementById("agent-options-allowed").checked,
    skipEarnings: document.getElementById("agent-skip-earnings").checked,
    hideNoSignal: document.getElementById("agent-hide-no-signal").checked,
    mode: document.getElementById("agent-mode").value,
    portfolioN: parseInt(document.getElementById("agent-portfolio-n").value) || 5,
    tickerFilter: document.getElementById("agent-ticker-filter").value.trim().toUpperCase(),
    // Advanced filters
    style: document.getElementById("agent-style")?.value || "none",
    minPrice: parseFloat(document.getElementById("agent-min-price")?.value) || 0,
    maxPrice: parseFloat(document.getElementById("agent-max-price")?.value) || 1e9,
    volatility: document.getElementById("agent-volatility")?.value || "any",
    minPatterns: parseInt(document.getElementById("agent-min-patterns")?.value) || 0,
    halalOnly: document.getElementById("agent-halal-only")?.checked || false,
  };
  // Apply style preset overlays (gentle — only adjusts if user left defaults)
  if (cfg.style === "conservative") {
    if (cfg.volatility === "any") cfg.volatility = "low";
    // prefer longer horizons; don't force one if user picked specifically
  } else if (cfg.style === "growth") {
    if (cfg.volatility === "any") cfg.volatility = "medium";
  } else if (cfg.style === "momentum") {
    if (cfg.volatility === "any") cfg.volatility = "high";
  } else if (cfg.style === "small_account") {
    if (cfg.maxPrice >= 1e9 || cfg.maxPrice >= 9999) cfg.maxPrice = 100;
  }
  return cfg;
}

function renderAgent() {
  const cfg = getAgentInputs();
  const container = document.getElementById("agent-recommendations");
  container.innerHTML = "";

  // Unified per-ticker view at the selected horizon
  const allRecs = _buildUnifiedRecs(cfg.horizon);
  if (allRecs.length === 0) {
    setText("agent-summary", `No data available for ${cfg.horizon}d horizon. Try another horizon or wait for the next workflow run.`);
    return;
  }

  // Compute filter pass/fail for each candidate, but DON'T filter yet.
  // When the user types a ticker filter, we want to surface that ticker
  // even if it fails other filters — with a clear note on the card.
  function _filterFails(s) {
    const misses = [];
    if (cfg.direction !== "any" && s.direction !== cfg.direction) {
      misses.push(`direction ${s.direction.toUpperCase()} doesn't match your "${cfg.direction}" filter`);
    }
    if (cfg.minConf && s._source !== "no_signal" && s.confidence < cfg.minConf) {
      misses.push(`confidence ${s.confidence.toFixed(2)} below your ${cfg.minConf} threshold`);
    }
    if (cfg.skipEarnings && s.earnings_in_horizon) {
      misses.push(`earnings within horizon (filtered by Skip Earnings)`);
    }
    if (cfg.hideNoSignal && s._source === "no_signal") {
      misses.push(`no actionable signal (filtered by Hide No-Signal)`);
    }
    if (cfg.minPrice > 0 && (s.price ?? 0) < cfg.minPrice) {
      misses.push(`price ${fmtUsd(s.price)} below your $${cfg.minPrice} min`);
    }
    if (cfg.maxPrice < 1e9 && (s.price ?? 0) > cfg.maxPrice) {
      misses.push(`price ${fmtUsd(s.price)} above your $${cfg.maxPrice} max`);
    }
    if (cfg.volatility !== "any" && s.atr && s.price) {
      const atrPct = (s.atr / s.price) * 100;
      const ok = (cfg.volatility === "low" && atrPct < 2)
        || (cfg.volatility === "medium" && atrPct >= 2 && atrPct < 5)
        || (cfg.volatility === "high" && atrPct >= 5);
      if (!ok) misses.push(`volatility ATR ${atrPct.toFixed(1)}% doesn't match your "${cfg.volatility}" filter`);
    }
    if (cfg.minPatterns > 0) {
      const count = s.n_fired ?? s.n_families ?? s.n_contributing ?? 0;
      if (count < cfg.minPatterns) misses.push(`only ${count} patterns fired (you require ≥ ${cfg.minPatterns})`);
    }
    // Sector filter: refresh from checkboxes each call so it stays in sync
    _refreshSelectedSectors();
    if (_agent.selectedSectors && s.sector) {
      if (!_agent.selectedSectors.has(s.sector)) {
        misses.push(`sector "${s.sector}" not in your selected sectors`);
      }
    }
    // Halal filter
    if (cfg.halalOnly) {
      const status = _agent.halalStatus[s.ticker];
      if (status && status.compliant === false) {
        misses.push(`not Halal-compliant: ${status.exclusion_reason || "general exclusion"}`);
      }
    }
    return misses;
  }

  let candidates;
  if (cfg.tickerFilter) {
    // Ticker-search mode: user explicitly named tickers. Surface them
    // regardless of other filters, with an annotation explaining any
    // mismatches. This means "I want to see IBM" actually shows IBM.
    const tokens = cfg.tickerFilter.split(/[,\s]+/).filter(Boolean).map(t => t.toUpperCase());
    candidates = allRecs.filter(s => tokens.some(t => s.ticker.toUpperCase().startsWith(t)));
    candidates.forEach(s => { s._filterMisses = _filterFails(s); });
  } else {
    // Normal filter mode: apply all filters, no annotations needed
    candidates = allRecs.filter(s => _filterFails(s).length === 0);
  }

  // Re-size each actionable candidate using the user's capital.
  // Actionable sources: consensus, meta, tentative (all-ensemble high-conf).
  // no_signal entries skip sizing.
  // Actionable signals where sizing returns null (capital too small) get the
  // 'unsizable' display rather than throwing on null.shares.
  let ranked = candidates.map(s => {
    if (s._source === "no_signal") return { ...s, _sizing: null, _options: null };
    const sizing = sizePosition(s.direction, s.price, s.atr, s.confidence, cfg.capital, cfg.riskPct, cfg.maxPosPct);
    const opts = recommendOptions(s.direction, s.confidence, s.price, s.atr, s.horizon_days, cfg.optionsAllowed, cfg.halalOnly);
    if (sizing == null) {
      return { ...s, _sizing: null, _options: null, _source: "unsizable" };
    }
    return { ...s, _sizing: sizing, _options: opts };
  });
  // Risk-adjusted ranking. Same recommendations are AVAILABLE regardless of
  // risk %, but the ORDER changes so the user sees stocks matching their
  // volatility appetite at the top.
  //
  // Map risk % to a preferred ATR% (rough heuristic — your daily price
  // swing should be commensurate with how much you're willing to risk):
  //   0.5% risk → prefer ATR ~1.5% (boring blue-chip)
  //   2.0% risk → prefer ATR ~3%   (typical mid-cap)
  //   5.0% risk → prefer ATR ~6%   (meme / high-vol momentum)
  // Stocks score highest when their ATR% is close to the preferred value;
  // a bell curve penalizes both too-boring and too-wild for the user's risk.
  const preferredAtrPct = 1 + cfg.riskPct;
  const _volMatchFactor = (atrPct) => {
    if (atrPct == null) return 0.7; // unknown vol → neutral
    const diff = atrPct - preferredAtrPct;
    return Math.exp(-(diff * diff) / 8); // bell curve, sigma ~2
  };
  // Annotate each candidate with its risk-adjusted score
  ranked.forEach(s => {
    const atrPct = (s.atr && s.price) ? (s.atr / s.price * 100) : null;
    s._volMatch = _volMatchFactor(atrPct);
    s._atrPct = atrPct;
    // Composite score: confidence × (0.5 + 0.5 × volMatch), capped at 1.0
    s._riskScore = (s.confidence ?? 0.5) * (0.5 + 0.5 * s._volMatch);
  });
  // Sort: source priority first, then risk-adjusted score (descending)
  const sourcePriority = (src) => ({ consensus: 4, meta: 3, tentative: 2, unsizable: 1, no_signal: 0 }[src] ?? 0);
  ranked.sort((a, b) => {
    const pa = sourcePriority(a._source);
    const pb = sourcePriority(b._source);
    if (pa !== pb) return pb - pa;
    return (b._riskScore || 0) - (a._riskScore || 0);
  });

  if (ranked.length === 0) {
    setText("agent-summary", `No tickers match your filters at ${cfg.horizon}d horizon. Try clearing the ticker filter or lowering min confidence.`);
    return;
  }
  const actionableCount = ranked.filter(s => s._sizing != null).length;

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

    // Sector concentration cap: limit each sector to floor(N/3) positions
    // so a portfolio isn't 5 mega-cap tech stocks pretending to be diversified.
    // Per-position correlation isn't computed (we don't have correlation data
    // in the dashboard), but sector overlap is a strong proxy.
    const maxPerSector = Math.max(1, Math.floor(targetN / 3));
    const sectorCounts = {};
    const sectorFiltered = [];
    for (const s of affordable) {
      const sec = s.sector || "Unknown";
      if ((sectorCounts[sec] || 0) >= maxPerSector) continue;
      sectorFiltered.push(s);
      sectorCounts[sec] = (sectorCounts[sec] || 0) + 1;
    }

    // If fewer affordable than requested, reduce N to fit
    const actualN = Math.min(targetN, sectorFiltered.length);
    const actualSlot = cfg.capital / actualN;
    const picks = sectorFiltered.slice(0, actualN).map(s => {
      const sizing = sizePortfolioSlot(s.direction, s.price, s.atr, actualSlot);
      const opts = recommendOptions(s.direction, s.confidence, s.price, s.atr, s.horizon_days, cfg.optionsAllowed, cfg.halalOnly);
      return { ...s, _sizing: sizing, _options: opts };
    }).filter(s => s._sizing !== null);

    const totalPosUsd = picks.reduce((a, s) => a + s._sizing.posUsd, 0);
    const totalRiskUsd = picks.reduce((a, s) => a + s._sizing.riskUsd, 0);
    const adjustedNote = actualN < targetN
      ? ` (reduced from ${targetN} because not enough affordable stocks fit at ${fmtUsd(cfg.capital / targetN)}/slot)`
      : "";
    const sectorBreakdown = picks.reduce((acc, s) => { acc[s.sector || "Unknown"] = (acc[s.sector || "Unknown"] || 0) + 1; return acc; }, {});
    const sectorBreakdownText = Object.entries(sectorBreakdown).map(([s, n]) => `${s}: ${n}`).join(" · ");
    setText("agent-summary",
      `Portfolio mode: ${picks.length} positions${adjustedNote}, ~${fmtUsd(actualSlot)} each. Total deployed ${fmtUsd(totalPosUsd)} (${(totalPosUsd/cfg.capital*100).toFixed(0)}% of capital), at-risk ${fmtUsd(totalRiskUsd)} (${(totalRiskUsd/cfg.capital*100).toFixed(1)}%). ` +
      `Sector cap applied (max ${maxPerSector} per sector — prevents 'all tech' fake diversification). Breakdown: ${sectorBreakdownText}.`);
    for (const s of picks) container.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg));
    return;
  }

  // Ranked mode (default)
  const tentativeCount = ranked.filter(s => s._source === "tentative").length;
  const validatedCount = ranked.filter(s => s._source === "consensus" || s._source === "meta").length;
  const tentativeNote = tentativeCount > 0
    ? ` (${validatedCount} validated by meta/consensus + ${tentativeCount} tentative all-ensemble picks where consensus didn't fire)`
    : "";
  // Risk profile label so user understands what's affecting the order
  const riskLabel = cfg.riskPct <= 1 ? "conservative (prefers low-vol blue-chips)"
    : cfg.riskPct <= 2 ? "balanced (prefers mid-vol)"
    : cfg.riskPct <= 3 ? "moderate (prefers medium-to-high vol)"
    : "aggressive (prefers high-vol / momentum names)";
  // Long-horizon advisory: technical signals on individual stocks at 5+ year
  // horizons make less sense than just holding broad-market ETFs.
  const longHorizonNote = cfg.horizon >= 1260
    ? ` <span style="color: var(--yellow);">⚠ At 5y horizon, technical analysis on individual stocks has limited evidence. For long-term / Roth IRA money, broad-market ETFs (VTI, VOO, SPY, QQQ) with periodic rebalancing have stronger historical evidence than stock-picking.</span>`
    : "";
  setHTML("agent-summary",
    `${actionableCount} actionable picks out of ${ranked.length} tickers at ${cfg.horizon}d horizon${tentativeNote}. ` +
    `Sized for ${fmtUsd(cfg.capital)} capital. Risk profile ${cfg.riskPct}% = ${riskLabel} — ` +
    `stocks ranked by volatility match: target ATR ~${preferredAtrPct.toFixed(1)}% of price.${longHorizonNote}`);

  const INITIAL_VISIBLE = 10;
  const top = ranked.slice(0, INITIAL_VISIBLE);
  top.forEach((s, i) => {
    container.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg, i + 1));
  });
  if (ranked.length > INITIAL_VISIBLE) {
    container.insertAdjacentHTML("beforeend", `
      <div class="show-more-toggle">
        <button type="button" id="show-more-btn" class="show-more-button">
          Show all ${ranked.length} tickers (${ranked.length - INITIAL_VISIBLE} more) ▾
        </button>
      </div>
      <div id="agent-recommendations-rest" style="display:none"></div>
    `);
    const rest = document.getElementById("agent-recommendations-rest");
    ranked.slice(INITIAL_VISIBLE).forEach((s, i) => {
      rest.insertAdjacentHTML("beforeend", renderRecommendationCard(s, cfg, INITIAL_VISIBLE + i + 1));
    });
    const btn = document.getElementById("show-more-btn");
    btn.addEventListener("click", () => {
      const isHidden = rest.style.display === "none";
      rest.style.display = isHidden ? "" : "none";
      btn.textContent = isHidden
        ? `Hide extra ${ranked.length - INITIAL_VISIBLE} tickers ▴`
        : `Show all ${ranked.length} tickers (${ranked.length - INITIAL_VISIBLE} more) ▾`;
      // After hiding, jump back to the top of the recommendations
      if (!isHidden) {
        document.getElementById("agent").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
}

function renderRecommendationCard(s, cfg, rank) {
  const rankBadge = rank != null ? `<span class="rec-rank">#${rank}</span>` : "";
  // Unsizable: actionable signal but capital too small / confidence factor 0
  if (s._source === "unsizable") {
    const dClass = s.direction === "up" ? "up" : "down";
    return `
      <div class="rec-card no-signal">
        <div class="rec-header">
          ${rankBadge}
          <a href="#" class="rec-ticker ticker-link" data-ticker="${s.ticker}">${s.ticker}</a>
          <span class="tag ${dClass}">${s.direction.toUpperCase()}</span>
          <span class="rec-meta muted">@ ${fmtUsd(s.price)} · ${s.horizon_days}d · conf ${s.confidence.toFixed(3)}</span>
        </div>
        <div class="rec-line muted small">Cannot size: at your capital + risk settings, this position rounds to &lt; 1 share. Click ticker for full breakdown, or increase capital / risk %.</div>
      </div>
    `;
  }
  // no_signal entries get a dimmed, compact card showing the weak all-ensemble hint
  if (s._source === "no_signal") {
    const base = s._baseSig || {};
    const baseDirText = base.direction === "neutral"
      ? `all-ensemble: neutral (no patterns of note fired)`
      : `all-ensemble hint: ${base.direction?.toUpperCase()} at conf ${(base.confidence ?? 0.5).toFixed(3)} (too weak for meta/consensus to fire)`;
    const firedCount = base.n_fired ?? (base.fired_patterns || []).length;
    const firedNote = firedCount > 0
      ? `${firedCount} pattern${firedCount === 1 ? '' : 's'} fired but didn't cross threshold`
      : "no patterns fired";
    return `
      <div class="rec-card no-signal">
        <div class="rec-header">
          ${rankBadge}
          <a href="#" class="rec-ticker ticker-link" data-ticker="${s.ticker}">${s.ticker}</a>
          <span class="tag neutral">no actionable signal</span>
          <span class="rec-meta muted">@ ${fmtUsd(base.price)} · ${s.horizon_days}d</span>
        </div>
        <div class="rec-line muted small">${baseDirText} — ${firedNote}. Click ticker for full breakdown.</div>
      </div>
    `;
  }
  const dClass = s.direction === "up" ? "up" : "down";
  const sizing = s._sizing;
  const opts = s._options;
  const isTentative = s._source === "tentative";
  const sourceBadge = s._source === "consensus"
    ? tag("decorrelated", "confirm")
    : (s._source === "meta" ? tag("correlated meta", "neutral")
       : (isTentative ? tag("tentative · all-ensemble only", "warn") : ""));
  // Sector badge — shows the ticker's sector and whether sector-aware
  // weighting was applied to this signal.
  const sectorBadge = s.sector
    ? `<span class="tag neutral" title="${(s.sector_overrides_used && s.sector_overrides_used.length > 0)
        ? 'Sector-aware weighting applied: ' + s.sector_overrides_used.map(o => o.methodology + ' (sector acc ' + (o.sector_accuracy * 100).toFixed(0) + '%)').join(', ')
        : 'Sector identified; no sector-specific overrides applied (insufficient sector samples for any methodology).'}">${s.sector}${(s.sector_overrides_used && s.sector_overrides_used.length > 0) ? ' ✓' : ''}</span>`
    : "";
  // For tentative signals, "voters" are individual patterns (n_fired), not
  // methodologies. The meta/consensus tiers have explicit voters; the
  // all-ensemble doesn't, so we use pattern-fire count instead.
  const tentativeVoters = isTentative ? (s.n_fired ?? 0) : null;
  // Volatility match badge — shows whether this stock's volatility matches
  // the user's risk profile.
  let volBadge = "";
  if (s._volMatch != null && s._atrPct != null) {
    const matchPct = (s._volMatch * 100).toFixed(0);
    const badgeClass = s._volMatch > 0.8 ? "confirm" : s._volMatch > 0.4 ? "neutral" : "warn";
    const volLabel = s._atrPct < 2 ? "low-vol" : s._atrPct < 5 ? "mid-vol" : "high-vol";
    volBadge = `<span class="tag ${badgeClass}" title="Stock's ATR is ${s._atrPct.toFixed(1)}% of price (${volLabel}). Match score vs your risk profile: ${matchPct}%.">${volLabel} (vol-match ${matchPct}%)</span>`;
  }
  // s.n_contributing (meta) vs s.n_families (consensus) — normalize for display
  const nVoters = s.n_families ?? s.n_contributing ?? 0;
  const voterType = s.n_families != null && s.n_families > 0 ? "families" : "methods";

  const earningsWarn = s.earnings_in_days != null && s.earnings_in_days <= s.horizon_days
    ? `<span class="tag down" title="Earnings ${s.earnings_in_days}d away — event risk">⚠ earnings in ${s.earnings_in_days}d</span>`
    : (s.earnings_in_days != null
        ? `<span class="muted small">earnings in ${s.earnings_in_days}d (after horizon)</span>`
        : "");

  const sentChip = sentimentChip(s.sentiment);
  // Show contributing voters. Tentative cards don't have methodology-level
  // voters; show a pattern-count note instead.
  const familyVoters = s.contributing_families || [];
  const methodVoters = s.contributing_methodologies || [];
  let contribs;
  if (isTentative) {
    contribs = `<span class="pattern-chip" title="The all-ensemble combiner used ${tentativeVoters} individual patterns; methodology-level breakdown not available because no methodology fired for this ticker. Click ticker for full pattern detail.">${tentativeVoters} pattern${tentativeVoters === 1 ? '' : 's'} fired → ${s.direction.toUpperCase()} (no methodology breakdown — click ticker for detail)</span>`;
  } else if (familyVoters.length > 0) {
    contribs = familyVoters.map(c => `<span class="pattern-chip" title="${c.family} family voted ${c.direction.toUpperCase()} with ${(c.internal_confidence * 100).toFixed(0)}% internal agreement; accuracy weight ${(c.accuracy_weight * 100).toFixed(0)}% (from ${(c.accuracy * 100).toFixed(1)}% backtest accuracy)">${c.family} → ${c.direction.toUpperCase()}</span>`).join(" ");
  } else {
    contribs = methodVoters.map(c => `<span class="pattern-chip" title="${c.methodology} fired ${c.direction.toUpperCase()} at confidence ${c.confidence}, weighted by ${(c.weight * 100).toFixed(0)}% (from accuracy ${(c.accuracy * 100).toFixed(1)}%)">${c.methodology} → ${c.direction.toUpperCase()}</span>`).join(" ");
  }

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

  // Tentative cards don't have a methodology-level vote_margin — they
  // come from the all-ensemble where pattern agreement is implicit in
  // confidence. Display differently to avoid misleading "0% consensus".
  const consensusPct = isTentative
    ? null
    : Math.abs((s.vote_margin ?? 0) * 100).toFixed(1);
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
    const halalShortCaveat = cfg.halalOnly
      ? `<div class="rec-line muted small" style="background: rgba(46, 160, 67, 0.06); border-left: 3px solid rgba(46, 160, 67, 0.5); padding: 6px 10px; margin: 4px 0;">
           🕌 <strong>Halal-mode note:</strong> conventional short-selling is also widely considered non-compliant per AAOIFI (bay' al-ma'dum — selling what you don't own — plus interest-based margin borrow fees). The Halal-friendly move on a bearish signal is usually to <strong>simply avoid the position</strong>, not to short it. Below is shown for transparency only.
         </div>`
      : "";
    equityLine = `
      ${halalShortCaveat}
      <div class="rec-line">
        <strong>Equity (short):</strong> <strong>Short-sell ${fmtNum(sizing.shares)} shares</strong> @ ${fmtUsd(s.price)} · stop-loss ${fmtUsd(sizing.stop)} (buy-to-cover if price rises here) · position ${fmtUsd(sizing.posUsd)} (${(sizing.pctOfCapital * 100).toFixed(1)}% of capital) · max risk ${fmtUsd(sizing.riskUsd)}
      </div>
      <details class="rec-line muted small">
        <summary>⚠ Don't own the shares? How short-selling actually works (click to expand)</summary>
        <ul style="margin: 6px 0; padding-left: 18px;">
          <li><strong>Your broker lends you the shares</strong> from their inventory or other margin-account clients' idle holdings.</li>
          <li>You immediately <strong>sell them at market price</strong> — cash from the sale lands in your account.</li>
          <li>Later you <strong>"cover"</strong> by buying the same number of shares back on the open market and returning them to the broker.</li>
          <li><strong>Profit = sell price − buy-back price</strong>, so you profit when the stock falls.</li>
          <li><strong>Requires a margin account.</strong> Not allowed in IRAs / Roth IRAs by law.</li>
          <li><strong>Risk is unbounded</strong> — long position max loss is what you paid; short position max loss is theoretically infinite (stock could rise forever).</li>
          <li><strong>Borrow fee</strong> applies — usually small for liquid large caps, can be 10-50%/yr on hard-to-borrow names.</li>
        </ul>
        <strong>Alternatives if you can't short:</strong>
        <ul style="margin: 6px 0; padding-left: 18px;">
          <li><strong>Buy a put option</strong> (see "Options alt" below if shown). Max loss = premium paid. Allowed in many IRAs.</li>
          <li><strong>Inverse ETFs</strong> like SQQQ (3× inverse Nasdaq) or SPXU (3× inverse S&amp;P). No margin needed.</li>
          <li><strong>Just don't buy this name right now.</strong> Passive, zero-cost way to "play" a bearish signal.</li>
        </ul>
      </details>`;
  } else {
    equityLine = `<div class="rec-line muted">No directional call.</div>`;
  }

  // If the user searched this ticker but it fails some of their filters,
  // surface a "doesn't match your filters" note so they understand why
  // it wouldn't normally appear in their recommendation list.
  const filterMissNote = (s._filterMisses && s._filterMisses.length > 0)
    ? `<div class="rec-line muted small filter-miss-note">
         <strong>Note:</strong> shown because you searched <code>${s.ticker}</code>, but it doesn't match your current filters:
         <ul style="margin: 4px 0 0 18px; padding: 0;">
           ${s._filterMisses.map(m => `<li>${m}</li>`).join("")}
         </ul>
       </div>`
    : "";

  return `
    <div class="rec-card ${s._filterMisses?.length > 0 ? 'rec-card-mismatch' : ''}">
      <div class="rec-header">
        ${rankBadge}
        <a href="#" class="rec-ticker ticker-link" data-ticker="${s.ticker}">${s.ticker}</a>
        <span class="tag ${dClass}">${s.direction.toUpperCase()}</span>
        <span class="rec-meta" title="${isTentative ? 'N patterns fired in the all-ensemble. Meta/consensus methodologies did not validate this — treat as a weaker signal.' : 'Consensus: how strongly the contributing voters agree on direction. 0% = tied, 100% = unanimous. NOT a price change prediction.'}">${s.horizon_days}d · conf ${s.confidence.toFixed(3)} · ${isTentative ? `${tentativeVoters} patterns fired (all-ensemble)` : `consensus ${consensusPct}% · ${nVoters} ${voterType} agree`}</span>
        ${sourceBadge}
        ${sectorBadge}
        ${volBadge}
        ${earningsWarn}
        ${sentChip}
        ${contradictionChip}
      </div>
      ${filterMissNote}
      ${equityLine}
      ${optsLine}
      <div class="rec-line muted small">${isTentative ? "Pattern evidence" : "Voted in favor"}: ${contribs}</div>
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
  // fired_patterns is stored once per ticker in fired_patterns_by_ticker, not per signal
  const firedPatterns = _allData.signals?.fired_patterns_by_ticker?.[ticker] || sample?.fired_patterns || [];

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

  // TradingView Advanced Chart widget container — populated after innerHTML is set
  const chartId = `tv-chart-${ticker}-${Date.now()}`;
  body.innerHTML = `
    <h2>${ticker} <span class="muted small">${price ? "@ " + fmtUsd(price) : ""}</span></h2>
    <div class="modal-section" style="background: rgba(88, 166, 255, 0.05); border: 1px solid rgba(88, 166, 255, 0.2);">
      <p class="muted small" style="margin: 0;">
        <strong>Two different timelines on this page:</strong>
        <br>📈 <strong>Chart below</strong> = live (TradingView free tier, ~15 min delayed for most US stocks). Times shown in Eastern (market) time.
        <br>📊 <strong>Our analysis</strong> (patterns / predictions / sizing) = snapshot from the last workflow run${sample?.as_of ? ` on <strong>${sample.as_of}</strong>` : ""}. To re-run with current prices, click <strong>↻ Refresh now</strong> in the header (~3 min).
      </p>
    </div>
    <div class="modal-section">
      <h4>📈 Live chart <span class="muted small">— TradingView (Eastern Time, ~15 min delayed)</span></h4>
      <div id="${chartId}" class="tv-chart-container" style="height: 420px;"></div>
      <p class="muted small" style="margin-top: 6px;">Pan, zoom, switch timeframes (1m, 5m, 1h, daily, weekly), draw trendlines, change indicators. Times shown in Eastern Time so they match market hours (9:30 AM – 4:00 PM ET on weekdays).</p>
    </div>
    ${metaHtml}
    ${patternsHtml}
    ${sentHtml}
    ${tickerHist}
    ${predsHtml}
  `;
  document.getElementById("ticker-modal").hidden = false;
  // Mount the TradingView widget after DOM is in place
  mountTradingViewChart(ticker, chartId);
}

// Loads TradingView's tv.js once, then renders the Advanced Chart widget.
let _tvLoaded = null;
function loadTradingViewScript() {
  if (_tvLoaded) return _tvLoaded;
  _tvLoaded = new Promise((resolve, reject) => {
    if (window.TradingView && window.TradingView.widget) {
      resolve();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("TradingView script failed to load"));
    document.head.appendChild(s);
  });
  return _tvLoaded;
}

async function mountTradingViewChart(ticker, containerId) {
  try {
    await loadTradingViewScript();
    if (!window.TradingView || !window.TradingView.widget) return;
    // Use the exchange's native timezone (Eastern Time for US stocks) so
    // chart times match market hours naturally (9:30 AM – 4:00 PM ET).
    // Users hovering candles will see times that match when trades actually
    // happened, not UTC offsets they have to mentally convert.
    new window.TradingView.widget({
      autosize: true,
      symbol: ticker, // TradingView auto-resolves exchange (NASDAQ:AAPL, etc.)
      interval: "D",
      timezone: "America/New_York",
      theme: "dark",
      style: "1", // 1 = candles, 8 = heikin ashi, 9 = line
      locale: "en",
      toolbar_bg: "#161b22",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_side_toolbar: false,
      studies: ["MASimple@tv-basicstudies", "RSI@tv-basicstudies", "MACD@tv-basicstudies"],
      container_id: containerId,
    });
  } catch (e) {
    const el = document.getElementById(containerId);
    if (el) {
      el.innerHTML = `<p class="muted small">Could not load TradingView chart: ${e.message}. Network restriction or ad-blocker? You can still view the chart at <a href="https://www.tradingview.com/chart/?symbol=${ticker}" target="_blank" rel="noopener" style="color: var(--accent);">tradingview.com/chart/?symbol=${ticker}</a>.</p>`;
    }
  }
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

// Realistic transaction cost — IBKR / Fidelity / Schwab effective round-trip
// cost on liquid US stocks ranges 0.05% (mega-cap, instant execution) to 0.3%
// (smaller names with wider spreads). Use 0.2% as a reasonable default.
const TXN_COST_ROUND_TRIP_PCT = 0.2;

function _accAfterCosts(rawAccPct, txnCostPct) {
  // Quick approximation: if your raw accuracy is p, you win some by some amount
  // and lose some by another. We deduct the round-trip txn cost from BOTH the
  // expected win and the expected loss (you pay it whether right or wrong).
  // Simpler proxy: just shift accuracy down by a constant tied to txn cost
  // and the threshold. With a 1% directional move threshold and 0.2% costs,
  // an accuracy of 55% effectively becomes ~52-53% after costs because some
  // of your "wins" only barely cleared the threshold.
  if (rawAccPct == null) return null;
  // Approximation: each percentage point of txn cost shaves ~2pp of accuracy
  // when the directional threshold is 1%. Conservative; real impact varies
  // by trade-by-trade distribution.
  return Math.max(0, rawAccPct - txnCostPct * 2);
}

function renderMethodologies(payload) {
  if (!payload) return;
  const kfold = payload.meta_kfold || {};
  setText("kfold-accuracy", fmtPct(kfold.accuracy));
  setText("kfold-counts", kfold.accuracy != null
    ? `${kfold.correct} / ${kfold.signals_emitted ?? 0} signals`
    : (kfold.note || "—"));

  // Sector-aware K-fold side-by-side
  const kfoldSec = payload.meta_kfold_sector_aware || {};
  setText("kfold-sector-accuracy", fmtPct(kfoldSec.accuracy));
  // Show after-cost accuracy alongside raw — honest disclosure about real-world economics
  const rawSec = (kfoldSec.accuracy ?? 0) * 100;
  const afterCostSec = _accAfterCosts(rawSec, TXN_COST_ROUND_TRIP_PCT);
  setText("kfold-sector-counts", kfoldSec.accuracy != null
    ? `${kfoldSec.correct} / ${kfoldSec.signals_emitted ?? 0} signals · raw ${rawSec.toFixed(1)}% / after 0.2% costs ≈ ${afterCostSec.toFixed(1)}%`
    : (kfoldSec.note || "—"));
  // Delta vs baseline
  if (kfoldSec.accuracy != null && kfold.accuracy != null) {
    const delta = (kfoldSec.accuracy - kfold.accuracy) * 100;
    const sign = delta >= 0 ? "+" : "";
    const klass = delta >= 0.5 ? "green" : delta <= -0.5 ? "red" : "muted";
    setHTML("kfold-sector-delta",
      `<span class="${klass}">${sign}${delta.toFixed(1)}pp vs no-sector baseline</span>`);
  } else {
    setText("kfold-sector-delta", "—");
  }

  // Decorrelated families banner (the actual recommendation source)
  const families = (payload.methodologies || {}).consensus_families || {};
  setText("families-accuracy", fmtPct(families.accuracy));
  const famN = families.signals_emitted ?? 0;
  setText("families-counts", families.accuracy != null
    ? `${families.correct} correct / ${famN - (families.correct ?? 0)} wrong of ${famN} signals`
    : "—");
  // Stress-test caveat
  if (famN > 0 && famN < 50) {
    setText("families-warning", `⚠ Small sample (n=${famN}) — accuracy CI is wide. Not enough data to fully stress-test yet.`);
  } else if (famN >= 50) {
    setText("families-warning", `✓ n=${famN} — sample size sufficient for stable estimate.`);
  } else {
    setText("families-warning", "");
  }

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
function renderSectorAnalysis(bt) {
  // Ensemble accuracy by sector
  const sectors = bt?.by_sector || {};
  const tbody = document.querySelector("#sector-overview-table tbody");
  if (tbody) {
    tbody.innerHTML = "";
    const rows = Object.entries(sectors).sort((a, b) => (b[1].accuracy ?? 0) - (a[1].accuracy ?? 0));
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">No sector data yet — workflow needs to run with sector fetching enabled.</td></tr>`;
    } else {
      for (const [sector, s] of rows) {
        tbody.insertAdjacentHTML("beforeend", `
          <tr>
            <td><strong>${sector}</strong></td>
            <td>${s.n}</td>
            <td><strong>${fmtPct(s.accuracy)}</strong></td>
            <td>${s.up_n}/${fmtPct(s.up_accuracy)}</td>
            <td>${s.down_n}/${fmtPct(s.down_accuracy)}</td>
            <td>${s.best_horizon ? `${s.best_horizon}d (${fmtPct(s.best_horizon_accuracy)})` : "—"}</td>
          </tr>
        `);
      }
    }
  }

  // Best methodology per sector
  const sectorMethod = bt?.sector_methodology || {};
  const mtbody = document.querySelector("#sector-method-table tbody");
  if (mtbody) {
    mtbody.innerHTML = "";
    const rows = Object.entries(sectorMethod);
    if (rows.length === 0) {
      mtbody.innerHTML = `<tr><td colspan="5" class="muted">No sector-methodology data yet.</td></tr>`;
    } else {
      for (const [sector, methods] of rows) {
        const entries = Object.entries(methods);
        if (entries.length === 0) continue;
        // Find the best methodology by accuracy (with minimum signal count for fairness)
        const sorted = entries.sort((a, b) => (b[1].accuracy ?? 0) - (a[1].accuracy ?? 0));
        const validSorted = sorted.filter(([_, v]) => v.n >= 5);
        const best = validSorted[0] || sorted[0];
        const allMethodsText = sorted
          .map(([name, v]) => `<span class="pattern-chip" title="${v.n} signals">${name}: ${fmtPct(v.accuracy)}</span>`)
          .join(" ");
        mtbody.insertAdjacentHTML("beforeend", `
          <tr>
            <td><strong>${sector}</strong></td>
            <td><strong>${best?.[0] || "—"}</strong></td>
            <td>${fmtPct(best?.[1]?.accuracy)}</td>
            <td>${best?.[1]?.n ?? 0}</td>
            <td><div class="patterns-list">${allMethodsText}</div></td>
          </tr>
        `);
      }
    }
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
  if (rows.length === 0) { tbody.innerHTML = `<tr><td colspan="10" class="muted">No predictions match.</td></tr>`; return; }
  for (const p of rows) {
    const resolved = p.status === "resolved";
    const klass = !resolved ? "row-open" : p.correct ? "row-correct" : "row-wrong";
    const result = !resolved ? tag("OPEN", "open") : p.correct ? tag("CORRECT", "correct") : tag("WRONG", "wrong");
    const method = p.methodology
      ? (p.methodology === "consensus_families" ? tag("decorrelated", "confirm")
         : p.methodology === "meta_ensemble" ? tag("meta", "neutral")
         : `<span class="muted small">${p.methodology}</span>`)
      : `<span class="muted small">legacy</span>`;
    const sectorCell = p.sector ? `<span class="muted small">${p.sector}</span>` : `<span class="muted small">—</span>`;
    tbody.insertAdjacentHTML("beforeend", `
      <tr class="${klass}">
        <td>${p.made_at}</td><td><a href="#" class="ticker-link" data-ticker="${p.ticker}"><strong>${p.ticker}</strong></a></td>
        <td>${method}</td><td>${sectorCell}</td><td>${dirTag(p.predicted_direction)}</td>
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

// Defensive wrapper — if one renderer throws, the others should still run.
function _safeRun(label, fn) {
  try { fn(); }
  catch (e) { console.error(`[${label}] failed:`, e); }
}

// =========================================================================
// ON-SITE REFRESH — calls a Cloudflare Worker that triggers the workflow,
// then polls for fresh data and reloads the page when it lands.
// =========================================================================

const REFRESH = {
  pollIntervalMs: 30 * 1000,   // poll every 30s
  maxPollMs: 15 * 60 * 1000,   // give up after 15 min
  startedAt: 0,
  lastUpdatedAt: null,
  pollTimer: null,
  elapsedTimer: null,
};

function getTriggerWorkerUrl() {
  return (localStorage.getItem("triggerWorkerUrl") || "").trim();
}

function showRefreshSetup() {
  const dlg = document.getElementById("refresh-setup");
  if (!dlg) return;
  const input = document.getElementById("refresh-worker-url");
  input.value = getTriggerWorkerUrl();
  dlg.hidden = false;
}

function hideRefreshSetup() {
  const dlg = document.getElementById("refresh-setup");
  if (dlg) dlg.hidden = true;
}

function showRefreshOverlay(initialMessage) {
  const ov = document.getElementById("refresh-overlay");
  if (!ov) return;
  document.getElementById("refresh-progress").textContent = initialMessage || "Triggering workflow…";
  document.getElementById("refresh-elapsed").textContent = "Elapsed: 0s";
  ov.hidden = false;
  REFRESH.startedAt = Date.now();
  if (REFRESH.elapsedTimer) clearInterval(REFRESH.elapsedTimer);
  REFRESH.elapsedTimer = setInterval(() => {
    const sec = Math.round((Date.now() - REFRESH.startedAt) / 1000);
    document.getElementById("refresh-elapsed").textContent = `Elapsed: ${sec}s`;
  }, 1000);
}

function hideRefreshOverlay() {
  const ov = document.getElementById("refresh-overlay");
  if (ov) ov.hidden = true;
  if (REFRESH.pollTimer) { clearInterval(REFRESH.pollTimer); REFRESH.pollTimer = null; }
  if (REFRESH.elapsedTimer) { clearInterval(REFRESH.elapsedTimer); REFRESH.elapsedTimer = null; }
}

async function triggerWorkflow(workerUrl) {
  const r = await fetch(workerUrl, { method: "POST" });
  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`Trigger failed (HTTP ${r.status}): ${txt || r.statusText}`);
  }
  return r.json();
}

async function pollForFreshData() {
  // Fetch the scoreboard.json (small file) and check updated_at.
  // When it changes, we know the workflow finished a new run.
  try {
    const r = await fetch(`data/scoreboard.json?cb=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) return;
    const data = await r.json();
    const current = data.updated_at;
    if (REFRESH.lastUpdatedAt && current && current !== REFRESH.lastUpdatedAt) {
      // New data landed
      document.getElementById("refresh-progress").textContent = "✓ Fresh data committed. Reloading…";
      document.getElementById("refresh-stage").textContent = "Done";
      setTimeout(() => { window.location.reload(); }, 800);
      hideRefreshOverlay();
    }
  } catch (e) {
    // ignore network blips
  }
}

async function startRefresh() {
  const workerUrl = getTriggerWorkerUrl();
  if (!workerUrl) {
    showRefreshSetup();
    return;
  }

  // Record current updated_at so we know when fresh data lands
  try {
    const r = await fetch(`data/scoreboard.json?cb=${Date.now()}`, { cache: "no-store" });
    const d = await r.json();
    REFRESH.lastUpdatedAt = d.updated_at;
  } catch (_) {
    REFRESH.lastUpdatedAt = null;
  }

  showRefreshOverlay("Triggering workflow on GitHub Actions…");

  try {
    await triggerWorkflow(workerUrl);
    document.getElementById("refresh-progress").textContent =
      "Workflow triggered. Waiting for fresh data to commit… (typically 3–8 minutes)";
  } catch (e) {
    document.getElementById("refresh-progress").innerHTML =
      `<span style="color: var(--red)">${e.message}</span><br /><br />` +
      `Check that the worker URL is correct and the GITHUB_TOKEN secret is set. ` +
      `You can also <a href="https://github.com/hunain-malik/investing-platform/actions/workflows/analysis.yml" target="_blank" rel="noopener" style="color: var(--accent)">trigger manually on GitHub</a>.`;
    document.getElementById("refresh-spinner").style.display = "none";
    return;
  }

  // Start polling
  REFRESH.pollTimer = setInterval(() => {
    pollForFreshData();
    if (Date.now() - REFRESH.startedAt > REFRESH.maxPollMs) {
      document.getElementById("refresh-progress").innerHTML =
        `Polling timed out after 15 min. The workflow may still be running — try reloading the page in a few minutes.`;
      document.getElementById("refresh-spinner").style.display = "none";
      clearInterval(REFRESH.pollTimer);
      REFRESH.pollTimer = null;
    }
  }, REFRESH.pollIntervalMs);
}

function setupRefreshButton() {
  const btn = document.getElementById("refresh-now-btn");
  if (btn) btn.addEventListener("click", startRefresh);

  // Setup-dialog buttons
  document.getElementById("refresh-setup-close")?.addEventListener("click", hideRefreshSetup);
  document.getElementById("refresh-save-url")?.addEventListener("click", () => {
    const url = document.getElementById("refresh-worker-url").value.trim();
    if (!url) { alert("Paste a worker URL first."); return; }
    if (!/^https:\/\//.test(url)) { alert("URL must start with https://"); return; }
    localStorage.setItem("triggerWorkerUrl", url);
    hideRefreshSetup();
    startRefresh();
  });
  document.getElementById("refresh-fallback-github")?.addEventListener("click", () => {
    hideRefreshSetup();
    window.open(
      "https://github.com/hunain-malik/investing-platform/actions/workflows/analysis.yml",
      "_blank", "noopener"
    );
  });

  // Overlay buttons
  document.getElementById("refresh-cancel")?.addEventListener("click", hideRefreshOverlay);
}

// =========================================================================
// LIVE PRICE OVERLAY — polls /live-prices on the Cloudflare Worker every
// 30s during US market hours. Updates each visible ticker card with the
// current Yahoo quote so users can see how far prices have drifted from
// the analysis snapshot.
// =========================================================================

const LIVE = {
  pollIntervalMs: 30 * 1000,
  timer: null,
  latest: {}, // symbol -> quote
};

function _getUSMarketState() {
  // Returns: "regular", "pre" (4 AM - 9:30 AM ET), "post" (4 PM - 8 PM ET),
  // "closed" (overnight or weekend).
  const now = new Date();
  const dow = now.getUTCDay();
  if (dow === 0 || dow === 6) return "closed";
  const utcMinutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  const etMinutes = (utcMinutes - 4 * 60 + 24 * 60) % (24 * 60);
  if (etMinutes >= 9 * 60 + 30 && etMinutes <= 16 * 60) return "regular";
  if (etMinutes >= 4 * 60 && etMinutes < 9 * 60 + 30) return "pre";
  if (etMinutes > 16 * 60 && etMinutes <= 20 * 60) return "post";
  return "closed";
}
function isUSMarketHoursApprox() {
  return _getUSMarketState() === "regular";
}

async function fetchLiveQuotes(symbols) {
  const workerUrl = (localStorage.getItem("triggerWorkerUrl") || "").trim();
  if (!workerUrl) return null;
  const url = `${workerUrl.replace(/\/+$/, "")}/live-prices?symbols=${encodeURIComponent(symbols.join(","))}`;
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

function _collectVisibleTickers() {
  const set = new Set();
  document.querySelectorAll(".rec-card .ticker-link").forEach(a => {
    const t = (a.dataset.ticker || a.textContent || "").trim();
    if (t && /^[A-Z.\-]{1,10}$/.test(t)) set.add(t);
  });
  return [...set];
}

function _applyLiveQuoteToCards(symbol, quote) {
  if (!quote || quote.price == null) return;
  const dir = (quote.changePct ?? 0) >= 0 ? "up" : "down";
  const cls = dir === "up" ? "green" : "red";
  const arrow = dir === "up" ? "↑" : "↓";
  const state = quote.marketState || "regular";
  // Pick a label based on market state so the user knows what they're seeing
  const stateLabel = state === "regular" ? "LIVE"
    : state === "pre" ? "PRE-MKT"
    : state === "post" ? "AFTER-HRS"
    : "LAST CLOSE";
  const dotClass = state === "regular" ? "live-dot" : "live-dot live-dot-static";
  const chipHtml = `
    <span class="live-chip" data-live-for="${symbol}" title="Quote from Stooq via the Cloudflare Worker. State: ${state}. Updated every 30s during market hours; otherwise shows last close.">
      <span class="${dotClass}"></span>${stateLabel}
      <strong>${fmtUsd(quote.price)}</strong>
      <span class="${cls}">${arrow}${Math.abs(quote.changePct ?? 0).toFixed(2)}%</span>
    </span>`;
  document.querySelectorAll(`.ticker-link[data-ticker="${symbol}"]`).forEach(a => {
    const card = a.closest(".rec-card");
    if (!card) return;
    card.querySelectorAll(`.live-chip[data-live-for="${symbol}"]`).forEach(el => el.remove());
    const header = card.querySelector(".rec-header");
    if (header) header.insertAdjacentHTML("beforeend", chipHtml);
  });
}

async function pollLivePrices() {
  // We poll in all market states; the chip displays the market state so the
  // user knows if they're seeing real-time, after-hours, or last-close data.
  // Outside market hours we keep the polled value but the upstream returns
  // the last close. Polling stops after 5 consecutive misses (e.g., worker down).
  const symbols = _collectVisibleTickers();
  if (symbols.length === 0) return;
  const chunks = [];
  for (let i = 0; i < symbols.length; i += 50) chunks.push(symbols.slice(i, i + 50));
  for (const chunk of chunks) {
    const data = await fetchLiveQuotes(chunk);
    if (!data?.ok || !data.quotes) continue;
    const marketState = _getUSMarketState();
    for (const [sym, quote] of Object.entries(data.quotes)) {
      LIVE.latest[sym] = { ...quote, marketState };
      _applyLiveQuoteToCards(sym, LIVE.latest[sym]);
    }
  }
}

function startLivePricePolling() {
  if (LIVE.timer) return;
  // Initial tick after a short delay (let cards render first)
  setTimeout(() => pollLivePrices(), 1500);
  LIVE.timer = setInterval(pollLivePrices, LIVE.pollIntervalMs);
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
  _allData.signals = signals;
  _allData.backtest = bt;
  _allData.predictions = preds;
  _safeRun("setupRefreshButton", () => setupRefreshButton());
  _safeRun("setupTickerModal", () => setupTickerModal());
  _safeRun("setupAgent",       () => setupAgent(signals));
  _safeRun("renderMethodologies", () => renderMethodologies(methodologies));
  _safeRun("renderScoreboard", () => renderScoreboard(sb));
  _safeRun("renderBacktest",   () => renderBacktest(bt));
  _safeRun("renderPatterns",   () => renderPatterns(bt, weights));
  _safeRun("renderSectorAnalysis", () => renderSectorAnalysis(bt));
  _safeRun("renderPerTicker",  () => renderPerTicker(bt));
  _safeRun("renderPredictions",() => renderPredictions(preds));
  _safeRun("startLivePricePolling", () => startLivePricePolling());
}

main();
