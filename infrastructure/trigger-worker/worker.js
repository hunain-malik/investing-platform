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
    const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
    const ghResp = await fetch(url, {
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
 * Fetches near-real-time quotes from Yahoo Finance's public quote API.
 * No auth required. Quotes update every minute or so during market hours.
 * Returns: { ok, quotes: { SYMBOL: { price, change, changePct, time, market } } }
 */
async function handleLivePrices(url, corsHeaders) {
  const symbolsParam = url.searchParams.get("symbols");
  if (!symbolsParam) {
    return new Response(JSON.stringify({ ok: false, error: "no symbols param" }), {
      status: 400, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
  // Cap at 50 symbols per request to avoid abuse
  const symbols = symbolsParam.split(",").map(s => s.trim()).filter(Boolean).slice(0, 50);
  if (symbols.length === 0) {
    return new Response(JSON.stringify({ ok: false, error: "empty symbols list" }), {
      status: 400, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const yahooUrl = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(symbols.join(","))}`;
  let data;
  try {
    const yResp = await fetch(yahooUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; InvestingPlatformWorker/1.0)",
        "Accept": "application/json",
      },
      cf: { cacheTtl: 30 }, // Cloudflare edge cache for 30s
    });
    if (!yResp.ok) {
      return new Response(JSON.stringify({ ok: false, status: yResp.status, error: "yahoo upstream error" }), {
        status: 502, headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
    data = await yResp.json();
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: e.message || "fetch failed" }), {
      status: 502, headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const result = (data?.quoteResponse?.result || []);
  const quotes = {};
  for (const q of result) {
    quotes[q.symbol] = {
      price: q.regularMarketPrice ?? null,
      change: q.regularMarketChange ?? null,
      changePct: q.regularMarketChangePercent ?? null,
      time: q.regularMarketTime ?? null, // epoch seconds
      market: q.marketState ?? null, // REGULAR / CLOSED / PRE / POST
      currency: q.currency ?? "USD",
    };
  }

  return new Response(
    JSON.stringify({ ok: true, quotes, fetched_at: Math.floor(Date.now() / 1000) }),
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
