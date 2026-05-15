/**
 * Cloudflare Worker: triggers the investing-platform GitHub Actions workflow.
 *
 * Why this exists: GitHub Pages can't run server code, so the dashboard
 * cannot call GitHub's workflow_dispatch API directly without exposing a
 * personal access token in public JavaScript. This tiny Worker holds the
 * token as a secret and acts as a CORS-restricted proxy.
 *
 * Deploy steps live in the README in this folder.
 */

const REPO_OWNER = "hunain-malik";
const REPO_NAME = "investing-platform";
const WORKFLOW_FILE = "analysis.yml";
const ALLOWED_ORIGIN = "https://hunain-malik.github.io";

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const url = new URL(request.url);
    const corsHeaders = {
      "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    };

    // Preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // GET /live-prices — proxies Yahoo Finance quote API for real-time-ish prices
    if (request.method === "GET" && url.pathname === "/live-prices") {
      return handleLivePrices(url, corsHeaders);
    }

    // GET = health check (default for any other GET)
    if (request.method === "GET") {
      return new Response(JSON.stringify({ ok: true, name: "investing-platform-trigger" }), {
        status: 200,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405, headers: corsHeaders });
    }

    // Lightweight origin check (defense in depth; the CORS headers already
    // restrict browsers, but a direct HTTP client could ignore CORS).
    if (origin && !origin.startsWith(ALLOWED_ORIGIN)) {
      return new Response(JSON.stringify({ ok: false, error: "origin not allowed" }), {
        status: 403,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    if (!env.GITHUB_TOKEN) {
      return new Response(JSON.stringify({ ok: false, error: "GITHUB_TOKEN secret not set" }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    // Trigger the workflow
    const dispatchUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
    const ghResp = await fetch(dispatchUrl, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "investing-platform-trigger-worker",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    });

    const ok = ghResp.status === 204;
    let detail = "";
    if (!ok) {
      try {
        detail = await ghResp.text();
      } catch (_) {}
    }
    return new Response(
      JSON.stringify({ ok, status: ghResp.status, detail }),
      {
        status: ok ? 200 : 502,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      }
    );
  },
};


/**
 * Fetches recent quotes from Stooq.com (free, no auth).
 * Yahoo's quote API now requires a crumb + cookie dance; Stooq doesn't.
 * Stooq data is typically real-time-ish during market hours.
 *
 * Stooq format: aapl.us,msft.us,ibm.us — US tickers get .us suffix.
 * Returns CSV; we parse and emit the same JSON shape as before.
 */
async function handleLivePrices(url, corsHeaders) {
  const symbolsParam = url.searchParams.get("symbols");
  if (!symbolsParam) {
    return new Response(JSON.stringify({ ok: false, error: "no symbols param" }), {
      status: 400, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
  // Cap at 50 symbols per request to avoid abuse
  const symbols = symbolsParam.split(",").map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 50);
  if (symbols.length === 0) {
    return new Response(JSON.stringify({ ok: false, error: "empty symbols list" }), {
      status: 400, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  // Stooq expects lowercase tickers with .us suffix for US equities/ETFs.
  // BRK.B -> brk-b.us (dots replaced with hyphens).
  const stooqSyms = symbols.map(s => `${s.toLowerCase().replace(/\./g, "-")}.us`);
  const stooqUrl = `https://stooq.com/q/l/?s=${stooqSyms.join(",")}&f=sd2t2ohlcv&h&e=csv`;

  let csv;
  try {
    const resp = await fetch(stooqUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; InvestingPlatformWorker/1.0)",
        "Accept": "text/csv,text/plain",
      },
      cf: { cacheTtl: 30 },
    });
    if (!resp.ok) {
      return new Response(JSON.stringify({ ok: false, status: resp.status, error: "stooq upstream error" }), {
        status: 502, headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
    csv = await resp.text();
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: e.message || "fetch failed" }), {
      status: 502, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  // Parse CSV: header row, then one row per symbol
  // Example: "Symbol,Date,Time,Open,High,Low,Close,Volume"
  const lines = csv.trim().split(/\r?\n/);
  if (lines.length < 2) {
    return new Response(JSON.stringify({ ok: false, error: "empty stooq response" }), {
      status: 502, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
  const header = lines[0].split(",").map(h => h.trim());
  const idx = (name) => header.findIndex(h => h.toLowerCase() === name.toLowerCase());
  const iSymbol = idx("Symbol");
  const iDate = idx("Date");
  const iTime = idx("Time");
  const iOpen = idx("Open");
  const iClose = idx("Close");

  const quotes = {};
  for (let r = 1; r < lines.length; r++) {
    const cols = lines[r].split(",");
    const sym = (cols[iSymbol] || "").toUpperCase().replace(/-US$|\.US$/i, "").replace(/-/g, ".");
    const open = parseFloat(cols[iOpen]);
    const close = parseFloat(cols[iClose]);
    if (!sym || isNaN(close)) continue;
    const change = !isNaN(open) ? (close - open) : null;
    const changePct = !isNaN(open) && open > 0 ? ((close - open) / open) * 100 : null;
    // Build a timestamp from Stooq's date + time fields (UTC-ish — Stooq uses local exchange time)
    let timeEpoch = null;
    if (cols[iDate] && cols[iTime]) {
      const dt = new Date(`${cols[iDate]}T${cols[iTime]}Z`);
      if (!isNaN(dt.getTime())) timeEpoch = Math.floor(dt.getTime() / 1000);
    }
    quotes[sym] = {
      price: close,
      change: change != null ? Math.round(change * 10000) / 10000 : null,
      changePct: changePct != null ? Math.round(changePct * 100) / 100 : null,
      time: timeEpoch,
      market: null, // Stooq doesn't expose market state
      currency: "USD",
      source: "stooq",
    };
  }

  return new Response(
    JSON.stringify({ ok: true, quotes, fetched_at: Math.floor(Date.now() / 1000), source: "stooq" }),
    {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=20",
        ...corsHeaders,
      },
    }
  );
}
