# Trigger Worker — one-time setup (10 minutes, free)

This is a tiny Cloudflare Worker that lets the dashboard's "Refresh now"
button trigger the analysis workflow without sending you to GitHub.

You only need to do this once. The Worker holds a GitHub token as a secret
and proxies the workflow trigger request.

## Step 1 — Create a fine-grained GitHub Personal Access Token (3 min)

1. Go to https://github.com/settings/personal-access-tokens/new
2. Token name: `investing-platform-trigger`
3. Expiration: 90 days (you'll rotate it later)
4. Resource owner: your account (`hunain-malik`)
5. Repository access: **Only select repositories** → `investing-platform`
6. Permissions → **Repository permissions**:
   - **Actions: Read and write** ← required
   - **Contents: Read-only** (optional, lets the worker check repo state)
   - Leave everything else as "No access"
7. Click **Generate token**, copy it (starts with `github_pat_...`).

This token can ONLY trigger workflows on this one repo. It cannot read code,
modify files, or affect other repos. Worst case if it leaked: someone
triggers your workflow runs (consumes free Actions minutes).

## Step 2 — Install Wrangler (Cloudflare CLI) (2 min)

```bash
npm install -g wrangler
```

If you don't have Node.js, install it from https://nodejs.org.

## Step 3 — Sign up for Cloudflare and authenticate (2 min)

```bash
wrangler login
```

This opens a browser to authorize the CLI. Free tier covers 100,000 worker
requests per day — vastly more than this needs.

## Step 4 — Deploy the worker (1 min)

From this folder (`infrastructure/trigger-worker/`):

```bash
# Store the GitHub token as a secret
wrangler secret put GITHUB_TOKEN
# (it prompts — paste the github_pat_... token you copied in Step 1)

# Deploy
wrangler deploy
```

Wrangler will print a URL like:
```
https://investing-platform-trigger.<your-subdomain>.workers.dev
```

Copy that URL.

## Step 5 — Tell the dashboard the Worker URL (30 seconds)

Open the dashboard, hit `Ctrl+Shift+J` (or `Cmd+Option+J` on Mac) to open
the browser console, and run:

```js
localStorage.setItem("triggerWorkerUrl", "https://investing-platform-trigger.YOUR-SUBDOMAIN.workers.dev");
```

Reload. The "Refresh now" button will now trigger the workflow on-site
instead of opening GitHub. The dashboard polls for fresh data and
auto-reloads when the run completes (~3 minutes).

## Cost

Cloudflare Workers free tier: 100,000 requests/day. This needs maybe 50/day
even with heavy use. Permanently free.

GitHub Actions free tier: 2000 minutes/month on public repos (this one is
public). Each analysis run is ~8 minutes, so you can trigger up to 250
runs/month. Well within budget.

## Rotating the token

The fine-grained PAT expires every 90 days. When that happens:
1. Repeat Step 1 to generate a new one.
2. Run `wrangler secret put GITHUB_TOKEN` again to update the secret.
3. No code redeploy needed.
