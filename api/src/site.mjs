/**
 * realurls.org 站点 —— 与 API 同一个 Worker，按 host 分流。
 *
 * 页面：
 *   /                 搜索框 + 数据集概况 + 已收录实体列表
 *   /e/<slug>         实体证据页：每条证据、被拒证据及原因、复现命令、Schema.org JSON-LD
 *   /d/<domain>       域名判定页（在库 → 跳实体页；不在库 → 相似提示或未知）
 *   /sitemap.xml /robots.txt /llms.txt
 *
 * 设计原则：证据页是产品本身——"清单说相信我，我们说命令都给你了，你自己验"。
 * 没有 JS 框架、没有外部资源、单文件 CSS，任何页面 <30KB。
 */

import { registrableDomain } from "../../packages/core/resolve.mjs";
import registry from "../../dist/registry.json";
import manifest from "../../dist/manifest.json";

const REPO = "https://github.com/zhouchungong/realurls-registry";
const API = "https://api.realurls.org";

const EVIDENCE_LABELS = {
  A1: "GitHub org verified this domain (DNS-level check by GitHub)",
  A2: "Package provenance → repository → verified org",
  A3: "Corporate registrar fingerprint (brand-protection registrar, long prepaid term, registry locks)",
  A4: "TLS certificate carries organisation name (OV/EV)",
  A5: "DNS TXT self-attestation (_realurls.<domain>)",
  A6: "Propagated from a verified sibling domain (first-party link + shared infrastructure)",
  A7: "Restricted government TLD",
  A8: "Anchored repository's homepage points here, and this site links back",
  B1: "Wikidata official-website claim (P856) on the anchored item",
  B2: "Package registry homepage field",
  B3: "App-store developer website field",
  B4: "Wayback Machine history",
  B5: "Tranco top-1M ranking",
  B6: "Official social profile links here",
  B7: "Google Safe Browsing: no record",
};

const byId = new Map(registry.map(e => [e.entity_id, e]));
const bySlug = new Map(registry.map(e => [e.entity_id.replace(/^org:/, ""), e]));
const byDomain = new Map();
for (const e of registry) for (const d of e.domains) byDomain.set(d.domain, { e, d });

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const slugOf = e => e.entity_id.replace(/^org:/, "");
const verifiedDomains = e => e.domains.filter(d => d.status === "verified");

const CSS = `
:root{--bg:#fff;--fg:#111;--mute:#666;--line:#e5e5e5;--ok:#0a7d32;--okbg:#e8f6ec;--warn:#9a3412;--warnbg:#fff1e6;--unk:#555;--unkbg:#f1f1f1;--link:#0b57d0;--code:#f6f6f6}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8e8e8;--mute:#9a9a9a;--line:#2a2d33;--ok:#4ade80;--okbg:#0f2a19;--warn:#fdba74;--warnbg:#3a1d0a;--unk:#bbb;--unkbg:#1e2126;--link:#8ab4f8;--code:#171a1f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
main{max-width:880px;margin:0 auto;padding:24px 20px 60px}header{display:flex;align-items:baseline;gap:14px;margin-bottom:28px}
header .brand{font-weight:700;font-size:20px;color:var(--fg)}header nav a{margin-left:14px;color:var(--mute);font-size:14px}
h1{font-size:28px;margin:0 0 6px}h2{font-size:18px;margin:30px 0 10px}.sub{color:var(--mute);margin:0 0 20px}
.search{display:flex;gap:8px;margin:20px 0}.search input{flex:1;font-size:18px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--fg)}
.search button{font-size:16px;padding:12px 18px;border:0;border-radius:10px;background:var(--fg);color:var(--bg);cursor:pointer}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:13px;font-weight:600}.ok{background:var(--okbg);color:var(--ok)}.warn{background:var(--warnbg);color:var(--warn)}.unk{background:var(--unkbg);color:var(--unk)}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0 16px}th,td{text-align:left;padding:8px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600}
code,pre{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);border-radius:6px}code{padding:1px 5px}pre{padding:12px;overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}.card{border:1px solid var(--line);border-radius:10px;padding:10px 12px}.card .d{color:var(--mute);font-size:13px}
.result{border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}.result h3{margin:0 0 6px;font-size:20px}
.muted{color:var(--mute);font-size:14px}.stats{display:flex;gap:22px;flex-wrap:wrap;color:var(--mute);font-size:14px}.stats b{color:var(--fg);font-size:18px;display:block}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--line);color:var(--mute);font-size:13px}
.rej li{color:var(--mute);font-size:14px}details summary{cursor:pointer;color:var(--mute)}
`;

function layout(title, body, { description = "", jsonld = null, canonical = "" } = {}) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>${description ? `<meta name="description" content="${esc(description)}">` : ""}
${canonical ? `<link rel="canonical" href="${esc(canonical)}">` : ""}
<meta name="realurls-dataset" content="${esc(manifest.dataset_version)}">
<style>${CSS}</style>${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld)}</script>` : ""}</head>
<body><main><header><a class="brand" href="/">realurls</a><nav><a href="/">Search</a><a href="${REPO}/blob/main/TRUST.md">Trust model</a><a href="${API}">API</a><a href="${REPO}">GitHub</a></nav></header>
${body}
<footer>Ownership only, never safety. Every verdict here is machine-reproducible — commands are on each page. Dataset <code>${esc(manifest.dataset_version)}</code>, signed with cosign, <a href="${REPO}/releases/tag/latest">download</a>. Data CC BY-SA 4.0 · Disputes: <a href="mailto:dispute@realurls.org">dispute@realurls.org</a></footer>
</main></body></html>`;
}

// ------------------------------------------------------------------ 首页

function home() {
  const c = manifest.counts;
  const cards = registry.slice().sort((a, b) => a.names.en.localeCompare(b.names.en)).map(e => {
    const v = verifiedDomains(e);
    return `<a class="card" href="/e/${esc(slugOf(e))}"><div>${esc(e.names.en)}</div><div class="d">${v.map(d => esc(d.domain)).join(" · ") || "—"}</div></a>`;
  }).join("");
  return layout("realurls — which domain is really the official one", `
<h1>Which domain is really the official one?</h1>
<p class="sub">An open registry of <b>domain ↔ organization</b> ownership, for AI agents and people. Not a safety judgement — only ownership, and only when the evidence is reproducible.<br>域名到底属于谁——只判归属，不判安全；每一条都能复现。</p>
<form class="search" action="/d/" onsubmit="location.href='/d/'+encodeURIComponent(this.q.value.trim());return false">
  <input name="q" placeholder="Paste a URL or domain… e.g. claude-desktop.io  /  or a name: ollama" autofocus>
  <button>Check</button>
</form>
<div class="stats"><div><b>${c.entities}</b>organizations</div><div><b>${c.verified}</b>verified domains</div><div><b>≥99.5%</b>precision target</div><div><b>${esc(manifest.generated_at.slice(0, 10))}</b>dataset date</div></div>
<h2>How to use it from an AI agent</h2>
<pre>claude mcp add realurls -- npx -y @realurls/mcp
# or any MCP host:  { "command": "npx", "args": ["-y", "@realurls/mcp"] }
# plain HTTP:       curl "${API}/v1/resolve?domain=claude-desktop.io"</pre>
<p class="muted">The MCP server ships <em>instructions</em> telling the agent to call it before handing out any download or login link — in our tests that single line is what turns "answers from memory" into "verifies first".</p>
<h2>Verified organizations</h2>
<div class="grid">${cards}</div>
<h2>What "verified" means</h2>
<p class="muted">At least one <b>anchor</b> (something only the real owner can produce: a GitHub-verified org, a DNS self-attestation, a restricted government TLD, a long-lived repository whose homepage points here…) <b>and</b> at least two independent corroborations. Anything less is reported as insufficient evidence. We would rather say "don't know" than be wrong. Full rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a>.</p>
`, { description: "Open, reproducible registry of which domain belongs to which organization. For AI agents and people. Ownership only, never safety.", canonical: "https://realurls.org/" });
}

// ------------------------------------------------------------------ 实体页

function reproduceCommands(e, d) {
  const cmds = [];
  const org = e.canonical?.github_org;
  for (const ev of d.evidence) {
    if (ev.code === "A1" && org) cmds.push(`# A1 — GitHub verified this org's domain\ncurl -s https://api.github.com/orgs/${org} | jq '{name, blog, is_verified}'`);
    if (ev.code === "A3") cmds.push(`# A3 — registrar / dates / locks\ncurl -sL https://rdap.org/domain/${d.domain} | jq '{status, events, registrar: [.entities[]|select(.roles[]=="registrar")|.vcardArray[1][1][3]]}'`);
    if (ev.code === "A8" && ev.data?.repo) cmds.push(`# A8 — anchored repo's homepage\ncurl -s https://api.github.com/repos/${ev.data.repo} | jq '{homepage, created_at, stargazers_count}'`);
    if (ev.code === "B1" && e.wikidata) cmds.push(`# B1 — Wikidata P856\ncurl -s "https://www.wikidata.org/w/api.php?action=wbgetclaims&entity=${e.wikidata}&property=P856&format=json"`);
    if (ev.code === "B4") cmds.push(`# B4 — first Wayback snapshot\ncurl -s "http://web.archive.org/cdx/search/cdx?url=${d.domain}&limit=1&output=json"`);
    if (ev.code === "B5") cmds.push(`# B5 — Tranco rank\ncurl -s https://tranco-list.eu/api/ranks/domain/${d.domain}`);
  }
  cmds.push(`# Re-run our whole pipeline for this domain\ngit clone ${REPO} && cd realurls-registry && pip install -e . && python -m src.verify ${d.domain}`);
  return [...new Set(cmds)].join("\n\n");
}

function evidenceRows(d) {
  const rejected = new Set((d.rejected_evidence || []).map(r => r.split(":")[0]));
  return d.evidence.map(ev => {
    const bad = rejected.has(ev.code);
    const data = Object.entries(ev.data || {}).filter(([k]) => !["org_name", "created_at"].includes(k))
      .map(([k, v]) => `${esc(k)}=<code>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</code>`).join(" ");
    return `<tr><td><code>${esc(ev.code)}</code> <span class="badge ${bad ? "unk" : "ok"}">${bad ? "not counted" : ev.code[0] === "A" ? "anchor" : "corroboration"}</span></td>
<td>${esc(EVIDENCE_LABELS[ev.code] || ev.code)}<div class="muted">${data}</div></td>
<td>${ev.source && /^https?:/.test(ev.source) ? `<a href="${esc(ev.source)}">source</a>` : `<span class="muted">${esc(ev.source || "")}</span>`}</td></tr>`;
  }).join("");
}

function entityPage(e) {
  const v = verifiedDomains(e);
  const jsonld = {
    "@context": "https://schema.org", "@type": "Organization", name: e.names.en,
    url: v[0] ? `https://${v[0].domain}` : undefined,
    sameAs: [...v.slice(1).map(d => `https://${d.domain}`), e.wikidata ? `https://www.wikidata.org/wiki/${e.wikidata}` : null,
             e.canonical?.github_org ? `https://github.com/${e.canonical.github_org}` : null].filter(Boolean),
    alternateName: e.aliases?.length ? e.aliases : undefined,
  };
  const domains = e.domains.map(d => {
    const cls = d.status === "verified" ? "ok" : "unk";
    return `<div class="result" id="${esc(d.domain)}">
<h3><a href="https://${esc(d.domain)}" rel="nofollow">${esc(d.domain)}</a> <span class="badge ${cls}">${esc(d.status)}</span> <span class="muted">${esc(d.role)} · confidence ${(d.confidence ?? 0).toFixed(2)} · verified ${esc((d.last_verified || "").slice(0, 10))}</span></h3>
<p class="muted">${(d.reasons || []).map(esc).join(" · ")}</p>
<table><tr><th>Evidence</th><th>What it shows</th><th></th></tr>${evidenceRows(d)}</table>
${d.rejected_evidence?.length ? `<details><summary>${d.rejected_evidence.length} piece(s) of evidence not counted — why</summary><ul class="rej">${d.rejected_evidence.map(r => `<li>${esc(r)}</li>`).join("")}</ul></details>` : ""}
<details><summary>Reproduce this yourself</summary><pre>${esc(reproduceCommands(e, d))}</pre></details>
</div>`;
  }).join("");

  const anchorsrc = (e.canonical?.sources || []).map(s => `<code>${esc(s)}</code>`).join(" ");
  return layout(`${e.names.en} — official domains — realurls`, `
<h1>${esc(e.names.en)}</h1>
<p class="sub">${e.aliases?.length ? `Also known as: ${e.aliases.map(esc).join(", ")}. ` : ""}${e.wikidata ? `Wikidata <a href="https://www.wikidata.org/wiki/${esc(e.wikidata)}">${esc(e.wikidata)}</a>. ` : ""}${e.canonical?.github_org ? `GitHub <a href="https://github.com/${esc(e.canonical.github_org)}">${esc(e.canonical.github_org)}</a>.` : ""}</p>
<p><b>Official domains:</b> ${v.length ? v.map(d => `<a href="https://${esc(d.domain)}" rel="nofollow"><code>${esc(d.domain)}</code></a>`).join(" ") : '<span class="badge unk">none verified yet</span>'}</p>
<p class="muted">Identity anchored by: ${anchorsrc || "—"}. <span title="names.en source">Display name from <code>${esc(e.provenance?.label_source || "?")}</code>.</span></p>
${domains}
<p class="muted">Think this is wrong? <a href="${REPO}/issues/new?template=dispute.yml">Open a dispute</a> — the burden of proof is on us, and the record is downgraded while we check. Record: <a href="${REPO}/blob/main/entities/${esc(e.category[0])}/${esc(slugOf(e))}.yaml">YAML</a>.</p>
`, { description: `Verified official domains of ${e.names.en}: ${v.map(d => d.domain).join(", ")}. Evidence-backed, reproducible.`, jsonld, canonical: `https://realurls.org/e/${slugOf(e)}` });
}

// ------------------------------------------------------------------ 域名页

function domainPage(input, resolver) {
  const domain = registrableDomain(input);
  const hit = byDomain.get(domain);
  if (hit) return Response.redirect(`https://realurls.org/e/${slugOf(hit.e)}#${domain}`, 302);

  // 也许用户输入的是名字——但带点号的输入一律按域名处理，否则 claude-desktop.io 会被
  // 模糊匹配成 "claude" 而跳到 Anthropic 页，恰好掩盖了它是仿冒域的事实
  const looksLikeDomain = /[.\/]/.test(input) || /^https?:/i.test(input);
  const looked = looksLikeDomain ? { verdict: "skip" } : resolver.lookup(input);
  if (looked.verdict === "official" || looked.verdict === "insufficient_evidence") {
    const e = byId.get(looked.entity.id);
    if (e) return Response.redirect(`https://realurls.org/e/${slugOf(e)}`, 302);
  }
  if (looked.verdict === "ambiguous") {
    return new Response(layout(`"${input}" — realurls`, `<h1>Several matches for “${esc(input)}”</h1><ul>${looked.candidates.map(c => `<li><a href="/e/${esc(c.id.replace(/^org:/, ""))}">${esc(c.name)}</a></li>`).join("")}</ul>`), { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }

  const r = resolver.resolve(input);
  let body;
  if (r.verdict === "not_official") {
    const e = byId.get(r.looks_like.id);
    body = `<h1><code>${esc(domain)}</code> <span class="badge warn">not a known domain of ${esc(r.looks_like.name)}</span></h1>
<p class="sub">This domain resembles <code>${esc(r.looks_like.domain)}</code>, which <b>is</b> verified for ${esc(r.looks_like.name)}. We have no evidence that <code>${esc(domain)}</code> belongs to them.</p>
<div class="result"><h3>Verified domains of ${esc(r.looks_like.name)}</h3>${r.official_domains.map(d => `<div><a href="https://${esc(d)}" rel="nofollow"><code>${esc(d)}</code></a></div>`).join("")}<p class="muted"><a href="/e/${esc(slugOf(e))}">See the evidence →</a></p></div>
<p class="muted">This is an <b>attribution</b> signal, not a malware verdict. A lookalike domain can be legitimate and unrelated; it can also be a phishing site. We only say: it is not the one you probably meant.</p>`;
  } else {
    body = `<h1><code>${esc(domain)}</code> <span class="badge unk">not in the registry</span></h1>
<p class="sub">We have no verdict for this domain — neither positive nor negative. "Don't know" is the honest answer here.</p>
<p class="muted">Know who owns it? <a href="${REPO}/issues/new?template=submit-domain.yml">Submit a lead</a> — you give us a clue, our pipeline gathers the evidence. If you <em>are</em> the owner, a DNS TXT record settles it: <code>_realurls.${esc(domain)} TXT "realurls-site-verification=…"</code>.</p>`;
  }
  return new Response(layout(`${domain} — realurls`, body, { description: `Ownership check for ${domain}.` }), { headers: { "Content-Type": "text/html; charset=utf-8", "X-Robots-Tag": r.verdict === "unknown" ? "noindex" : "all" } });
}

// ------------------------------------------------------------------ 杂项

function sitemap() {
  const urls = ["https://realurls.org/", ...registry.map(e => `https://realurls.org/e/${slugOf(e)}`)];
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.map(u => `<url><loc>${u}</loc><lastmod>${manifest.generated_at.slice(0, 10)}</lastmod></url>`).join("")}</urlset>`, { headers: { "Content-Type": "application/xml" } });
}

const LLMS_TXT = `# realurls

> Which domain officially belongs to which software product or company. Ownership only, never safety. Every verdict is backed by reproducible machine evidence.

- API: ${API}/v1/resolve?domain=<domain>  and  ${API}/v1/entity?q=<name>
- MCP server: npx -y @realurls/mcp  (ships instructions: call before giving any download/login URL)
- Trust model: ${REPO}/blob/main/TRUST.md
- Rules: ${REPO}/blob/main/POLICY.md
- Signed dataset: ${REPO}/releases/tag/latest

Statuses: only "verified" is a positive answer. provisional / community / unverified mean "insufficient evidence" — do not present those domains as confirmed official.
`;

export function handleSite(request, resolver) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const html = body => new Response(body, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300", "X-Realurls-Dataset": manifest.dataset_version } });

  if (path === "/") return html(home());
  if (path === "/robots.txt") return new Response(`User-agent: *\nAllow: /\nSitemap: https://realurls.org/sitemap.xml\n`, { headers: { "Content-Type": "text/plain" } });
  if (path === "/sitemap.xml") return sitemap();
  if (path === "/llms.txt") return new Response(LLMS_TXT, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  if (path.startsWith("/e/")) {
    const e = bySlug.get(decodeURIComponent(path.slice(3)));
    return e ? html(entityPage(e)) : new Response(layout("Not found — realurls", `<h1>No such organization</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
  if (path.startsWith("/d/")) {
    const q = decodeURIComponent(path.slice(3)).trim();
    return q ? domainPage(q, resolver) : Response.redirect("https://realurls.org/", 302);
  }
  // 允许在站点域上直接调 API 路径，方便前端
  if (path.startsWith("/v1/") || path === "/healthz") return null;
  return new Response(layout("Not found — realurls", `<h1>Not found</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
}
