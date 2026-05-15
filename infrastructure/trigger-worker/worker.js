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

    // GET = health check
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
