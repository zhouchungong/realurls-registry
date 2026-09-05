/**
 * realurls Worker — API on api.realurls.org, HTML site on realurls.org, selected by Host.
 *
 * All data lives in D1 (binding DB); the Worker bundle contains code only, so it does not grow with the
 * dataset. The lookalike index is the single in-memory cache (see store.mjs).
 *
 * Endpoints (GET only, no auth, CORS open):
 *   /v1/resolve?domain=<domain or url>   who owns this domain / what it resembles
 *   /v1/entity?q=<name>                  official site(s) by name
 *   /v1/manifest                         dataset version and counts
 *   /v1/domains.txt                      plain-text allowlist of verified domains
 *   /v1/domains.json                     full domain index (the browser extension downloads it daily)
 *   /healthz
 *
 * Every response carries X-Realurls-Dataset (git revision of the data) so callers can match it to the
 * signed release.
 */

import { Store } from "./store.mjs";
import { handleSite, apiLanding } from "./site.mjs";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};
const TRUST = "https://github.com/zhouchungong/realurls-registry/blob/main/TRUST.md";

function json(body, version, status = 200, extra = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=300",
               "X-Realurls-Dataset": version || "", "X-Realurls-Trust": TRUST, ...CORS, ...extra },
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (request.method !== "GET") return json({ error: "GET only" }, null, 405);

    const store = new Store(env.DB);
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    // wrangler dev rewrites url.hostname but keeps the Host header; prefer the header so -H Host works locally
    const host = (request.headers.get("host") || url.hostname).split(":")[0].toLowerCase();

    let meta;
    try { meta = await store.meta(); }
    catch (e) { return json({ error: "dataset not loaded", detail: String(e.message || e) }, null, 503, { "Cache-Control": "no-store" }); }

    if (host === "realurls.org" || host === "www.realurls.org") {
      const page = await handleSite(request, store, meta);
      if (page) return page;
    }

    // Large, slow-changing responses go through the edge cache for an hour.
    const cached = async (key, produce) => {
      const cache = caches.default;
      const req = new Request(`https://cache.realurls.internal${key}?v=${meta.dataset_version}`);
      let res = await cache.match(req);
      if (!res) { res = await produce(); ctx.waitUntil(cache.put(req, res.clone())); }
      return res;
    };

    switch (path) {
      case "/healthz":
        return json({ ok: true, ...meta }, meta.dataset_version, 200, { "Cache-Control": "no-store" });

      case "/v1/manifest":
        return json(meta, meta.dataset_version);

      case "/v1/domains.json":
        return cached("/domains.json", async () => json(await store.domainsIndex(), meta.dataset_version, 200, { "Cache-Control": "public, max-age=3600" }));

      case "/v1/domains.txt":
        return cached("/domains.txt", async () => new Response(await store.verifiedText(), {
          headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=3600", "X-Realurls-Dataset": meta.dataset_version, ...CORS },
        }));

      case "/v1/resolve": {
        const q = url.searchParams.get("domain") || url.searchParams.get("url");
        if (!q) return json({ error: "missing ?domain=" }, meta.dataset_version, 400);
        return json({ ...(await store.resolve(q)), dataset_version: meta.dataset_version }, meta.dataset_version);
      }

      case "/v1/entity": {
        const q = url.searchParams.get("q") || url.searchParams.get("name");
        if (!q) return json({ error: "missing ?q=" }, meta.dataset_version, 400);
        return json({ ...(await store.lookup(q)), dataset_version: meta.dataset_version }, meta.dataset_version);
      }

      case "/":
        // Browsers get a copy-friendly landing page; curl / fetch / agents get JSON.
        if ((request.headers.get("accept") || "").includes("text/html")) {
          return new Response(apiLanding(meta), { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300", ...CORS } });
        }
        return json({
          name: "realurls", what: "Which domain officially belongs to which organization. Ownership only, never safety.",
          endpoints: ["/v1/resolve?domain=", "/v1/entity?q=", "/v1/manifest", "/v1/domains.txt", "/v1/domains.json", "/healthz"],
          trust: TRUST, ...meta,
        }, meta.dataset_version);

      default:
        return json({ error: "not found" }, meta.dataset_version, 404);
    }
  },
};
