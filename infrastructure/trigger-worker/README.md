# Trigger Worker — one-time setup (10 minutes, free)

This is a tiny Cloudflare Worker that lets the dashboard's "Refresh now"
button trigger the analysis workflow without sending you to GitHub.

You only need to do this once. The Worker holds a GitHub token as a secret
and proxies the workflow trigger request.

## Quickest path: use your existing `gh` CLI token

If you already have the `gh` CLI installed and authenticated (which you do —
we used it earlier to create the repo), you can skip token creation
entirely. After installing Wrangler (Step 2), run:

```powershell
gh auth token | wrangler secret put GITHUB_TOKEN
```

The pipe sends your existing token straight into Cloudflare's secret
store without it ever appearing on screen or being saved anywhere else.
Skip to Step 4 (Deploy).

Tradeoff: this token has broader access (all your repos, not just this
one). The Worker's CORS + origin check protects it in practice, but a
narrowly-scoped PAT (Step 1) is technically safer.

---

## Alternative: create a Personal Access Token explicitly

### Step 1 — Generate a classic PAT (3 min, simpler than fine-grained)

1. Go to https://github.com/settings/tokens (this is the "Tokens (classic)" page)
2. Top right, click the green **"Generate new token"** dropdown
3. Click **"Generate new token (classic)"** (NOT "fine-grained")
4. Fill in:
   - **Note**: `investing-platform-trigger`
   - **Expiration**: `90 days` (rotate when it expires)
   - **Select scopes** — check these two boxes:
     - **`repo`** (top of the scopes list — full control of private repos)
     - **`workflow`** (further down — update GitHub Action workflows)
   - Leave everything else unchecked
5. Scroll to the bottom, click green **"Generate token"**
6. **Copy the token** (`ghp_...`) — GitHub only shows it once

### Step 2 — Install Wrangler (Cloudflare CLI) (2 min)

```powershell
npm install -g wrangler
```

If you don't have Node.js, install it from https://nodejs.org first.

### Step 3 — Sign up for Cloudflare and authenticate (2 min)

```powershell
wrangler login
```

This opens a browser to authorize the CLI. Free tier covers 100,000 worker
requests per day — vastly more than we need.

### Step 4 — Deploy the worker (1 min)

From this folder (`infrastructure/trigger-worker/`):

```powershell
# Store the token as a secret. If you used "Quickest path" above, you
# already did this. Otherwise paste the ghp_... token when prompted.
wrangler secret put GITHUB_TOKEN

# Deploy
wrangler deploy
```

Wrangler will print a URL like:
```
https://investing-platform-trigger.<your-subdomain>.workers.dev
```

Copy that URL.

### Step 5 — Tell the dashboard the Worker URL (30 seconds)

On the dashboard, click **"↻ Refresh now"**. A setup dialog will appear.
Paste the worker URL into the input field and click **Save**. That's it —
stored in browser localStorage; you'll never see this dialog again.

(Alternatively, you can set it via the browser console:
`localStorage.setItem("triggerWorkerUrl", "https://YOUR-URL.workers.dev")`)

After saving, click "Refresh now" again — this time it triggers the
workflow on-site, shows a progress modal, polls for fresh data, and
auto-reloads the page when the run completes (~3-8 min).

## Cost

Cloudflare Workers free tier: 100,000 requests/day. This needs maybe 50/day
even with heavy use. Permanently free.

GitHub Actions free tier: 2000 minutes/month on public repos (this repo is
public). Each analysis run is ~8 minutes, so you can trigger up to 250
runs/month. Well within budget.

## Rotating the token

The classic PAT expires every 90 days (if you chose 90 days). When that
happens:
1. Repeat Step 1 to generate a new token.
2. Run `wrangler secret put GITHUB_TOKEN` again to update the secret.
3. No code redeploy needed.

If you used the `gh auth token` shortcut, just rerun the pipe whenever
gh refreshes its token (gh manages this automatically usually).
