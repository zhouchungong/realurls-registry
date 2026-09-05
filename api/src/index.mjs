/**
 * realurls API —— Cloudflare Worker。
 *
 * 零运维：数据集在构建时打进 Worker（dist/domains.json + entities.json + manifest.json），
 * 没有数据库、没有外部调用、每次请求纯内存查表。数据更新 = 重新部署（release.yml 之后触发）。
 * 数据集 <1MB 内这是最简单也最稳的做法；超过再迁 D1/KV。
 *
 * 端点（全部 GET、无鉴权、CORS 开放）：
 *   /v1/resolve?domain=<domain or url>   正查：这个域名属于谁 / 像谁
 *   /v1/entity?q=<name>                  反查：这个名字的官网
 *   /v1/manifest                         数据集版本、条数、各文件 sha256
 *   /v1/domains.txt                      verified 白名单
 *   /healthz
 *
 * 每个响应都带 X-Realurls-Dataset: <git rev>，调用方能对上签名的 manifest。
 */

import { Resolver } from "../../packages/core/resolve.mjs";
import domains from "../../dist/domains.json";
import entities from "../../dist/entities.json";
import manifest from "../../dist/manifest.json";

const resolver = new Resolver({ domains, entities, manifest });
const VERIFIED_TXT = Object.entries(domains).filter(([, v]) => v.official).map(([d]) => d).sort().join("\n") + "\n";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      "X-Realurls-Dataset": manifest.dataset_version,
      "X-Realurls-Trust": "https://github.com/realurls/registry/blob/main/TRUST.md",
      ...CORS, ...extra,
    },
  });
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (request.method !== "GET") return json({ error: "GET only" }, 405);

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    switch (path) {
      case "/healthz":
        return json({ ok: true, ...resolver.meta() });

      case "/v1/manifest":
        return json(manifest);

      case "/v1/domains.txt":
        return new Response(VERIFIED_TXT, {
          headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=3600",
                     "X-Realurls-Dataset": manifest.dataset_version, ...CORS },
        });

      case "/v1/resolve": {
        const q = url.searchParams.get("domain") || url.searchParams.get("url");
        if (!q) return json({ error: "missing ?domain=" }, 400);
        return json({ ...resolver.resolve(q), dataset_version: manifest.dataset_version });
      }

      case "/v1/entity": {
        const q = url.searchParams.get("q") || url.searchParams.get("name");
        if (!q) return json({ error: "missing ?q=" }, 400);
        return json({ ...resolver.lookup(q), dataset_version: manifest.dataset_version });
      }

      case "/":
        return json({
          name: "realurls", what: "Which domain officially belongs to which organization. Ownership only, never safety.",
          endpoints: ["/v1/resolve?domain=", "/v1/entity?q=", "/v1/manifest", "/v1/domains.txt", "/healthz"],
          trust: "https://github.com/realurls/registry/blob/main/TRUST.md",
          ...resolver.meta(),
        });

      default:
        return json({ error: "not found" }, 404);
    }
  },
};
