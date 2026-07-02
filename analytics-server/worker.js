/**
 * Continuum analytics counter — Cloudflare Worker + D1.
 *
 * Receives anonymous, opt-in pings from the Continuum desktop app and counts
 * unique installs and active users. It stores ONLY what the app sends: a random
 * install id, an event name, app version, OS family and CPU arch. No chat
 * content, no personal data, no IP retention beyond Cloudflare's defaults.
 *
 * Routes:
 *   POST /api/continuum/ping            -> record a ping (called by the app)
 *   GET  /api/continuum/stats?key=TOKEN -> read aggregate counts (you, via browser)
 *
 * Deploy: see README.md in this folder.
 */
const PING_PATH = "/api/continuum/ping";
const STATS_PATH = "/api/continuum/stats";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    if (request.method === "POST" && url.pathname === PING_PATH) {
      let b;
      try { b = await request.json(); } catch { return json({ ok: false }, 400); }
      const id = String(b.install_id || "").slice(0, 64);
      const event = String(b.event || "").slice(0, 32);
      if (!id || !event) return json({ ok: false }, 400);

      const version = String(b.version || "").slice(0, 32);
      const os = String(b.os || "").slice(0, 32);
      const arch = String(b.arch || "").slice(0, 32);
      const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
      const now = Math.floor(Date.now() / 1000);

      // Unique install (idempotent), every ping recorded, daily-active per id.
      await env.DB.batch([
        env.DB.prepare(
          "INSERT OR IGNORE INTO installs(id, first_seen, version, os, arch) VALUES(?,?,?,?,?)"
        ).bind(id, now, version, os, arch),
        env.DB.prepare(
          "INSERT INTO pings(id, event, ts, version, os, arch) VALUES(?,?,?,?,?,?)"
        ).bind(id, event, now, version, os, arch),
        env.DB.prepare(
          "INSERT OR IGNORE INTO active_days(day, id) VALUES(?,?)"
        ).bind(today, id),
      ]);
      return json({ ok: true }, 200);
    }

    if (request.method === "GET" && url.pathname === STATS_PATH) {
      if (url.searchParams.get("key") !== env.STATS_TOKEN) return json({ ok: false }, 401);
      const today = new Date().toISOString().slice(0, 10);
      const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
      const q = async (sql, ...a) => (await env.DB.prepare(sql).bind(...a).first())?.n ?? 0;
      const [installs, dau, mau, byVersion] = await Promise.all([
        q("SELECT COUNT(*) n FROM installs"),
        q("SELECT COUNT(DISTINCT id) n FROM active_days WHERE day = ?", today),
        q("SELECT COUNT(DISTINCT id) n FROM active_days WHERE day >= ?", monthAgo),
        env.DB.prepare(
          "SELECT version, COUNT(*) n FROM installs GROUP BY version ORDER BY n DESC"
        ).all().then(r => r.results),
      ]);
      return json({ ok: true, total_installs: installs, active_today: dau,
                    active_30d: mau, by_version: byVersion }, 200);
    }

    return json({ ok: false }, 404);
  },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}
