# Continuum analytics counter

A tiny, self-hosted endpoint that counts **installs** and **active users** of the
Continuum desktop app, while keeping the app's sovereignty promise intact.

The app only ever sends a ping **with the user's explicit consent**, and the ping
contains only: a random install id, the event (`install`/`heartbeat`), app
version, OS family, and CPU arch. No chat content, no titles, no prompts, no
personal data. See `ski_memory/analytics.py`.

## What you get

- `POST /api/continuum/ping` — the app calls this (anonymous, consent-gated).
- `GET  /api/continuum/stats?key=YOUR_TOKEN` — you call this to read counts:
  `total_installs`, `active_today`, `active_30d`, and a breakdown `by_version`.

## Deploy (Cloudflare Workers + D1, free tier is plenty)

1. Install the CLI and log in:
   ```
   npm i -g wrangler
   wrangler login
   ```
2. Create the database and apply the schema:
   ```
   wrangler d1 create continuum_analytics
   # copy the printed database_id into wrangler.toml
   wrangler d1 execute continuum_analytics --remote --file=schema.sql
   ```
3. Set the token that protects the stats endpoint:
   ```
   wrangler secret put STATS_TOKEN
   ```
4. Deploy:
   ```
   wrangler deploy
   ```
5. Point the app at it. Either:
   - host the Worker at `https://kpifinity.com/api/continuum/*` (uncomment the
     `routes` line in `wrangler.toml`), which matches the app's default URL; or
   - use the `*.workers.dev` URL and set `CONTINUUM_ANALYTICS_URL` for the app.

## Check your numbers

```
https://kpifinity.com/api/continuum/stats?key=YOUR_TOKEN
```

## Notes

- If the endpoint is down or unreachable, the app is unaffected — pings are
  best-effort with a short timeout and all errors are swallowed.
- Counts are unique by random install id. Reinstalls with a fresh data folder
  count as new installs (there is intentionally no cross-install fingerprint).
- D1 SQL keeps the counts exact; no third-party analytics vendor is involved.
