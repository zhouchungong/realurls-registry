/**
 * realurls.org — served by the same Worker as the API, selected by Host.
 *
 * Pages
 *   /               home: one big search box (Google-style), dataset stats, verified orgs
 *   /e/<slug>       entity evidence page: every piece of evidence, rejected evidence with reasons,
 *                   commands to reproduce, Schema.org JSON-LD
 *   /d/<query>      verdict page for a domain/URL (redirects to the entity page when known)
 *   /sitemap.xml /robots.txt /llms.txt
 *
 * The search box stays in the header on every page — after a check you can immediately check the next.
 * No JS framework, no external assets, one inline stylesheet; every page well under 40 KB.
 * The evidence page *is* the product: a list says "trust me", we say "here are the commands, run them".
 */

import { registrableDomain } from "../../packages/core/resolve.mjs";
import registry from "../../dist/registry.json";
import manifest from "../../dist/manifest.json";

const REPO = "https://github.com/zhouchungong/realurls-registry";
const API = "https://api.realurls.org";
const SITE = "https://realurls.org";

const EVIDENCE_LABELS = {
  A1: "GitHub verified this organization's domain (DNS-level check performed by GitHub)",
  A2: "Package provenance → repository → verified organization",
  A3: "Corporate registrar fingerprint (brand-protection registrar, long prepaid term, registry locks)",
  A4: "TLS certificate carries the organization name (OV/EV)",
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

// ------------------------------------------------------------------ styles

const CSS = `
:root{--bg:#fff;--fg:#1f1f1f;--mute:#5f6368;--line:#e3e3e3;--ok:#137333;--okbg:#e6f4ea;--warn:#b3261e;--warnbg:#fce8e6;--unk:#5f6368;--unkbg:#f1f3f4;--link:#1a0dab;--code:#f8f9fa;--accent:#1a73e8}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--mute:#9aa0a6;--line:#2b2f36;--ok:#81c995;--okbg:#0f2a19;--warn:#f28b82;--warnbg:#3a1d1a;--unk:#bdc1c6;--unkbg:#1e2126;--link:#8ab4f8;--code:#171a1f;--accent:#8ab4f8}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);z-index:5}
.bar{max-width:1000px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;gap:18px}
.brand{font-weight:700;font-size:22px;color:var(--fg);letter-spacing:-.3px;white-space:nowrap}.brand:hover{text-decoration:none}
.bar form{flex:1;display:flex;max-width:640px}.bar nav{margin-left:auto;display:flex;gap:16px}.bar nav a{color:var(--mute);font-size:14px;white-space:nowrap}
.q{display:flex;width:100%;border:1px solid var(--line);border-radius:24px;background:var(--bg);box-shadow:0 1px 3px rgba(0,0,0,.06)}
.q:focus-within{box-shadow:0 1px 6px rgba(32,33,36,.28);border-color:transparent}
.q input{flex:1;border:0;background:transparent;color:var(--fg);font-size:16px;padding:10px 18px;outline:0;min-width:0}
.q button{border:0;background:transparent;color:var(--mute);padding:0 16px;cursor:pointer;font-size:15px}.q button:hover{color:var(--fg)}
main{max-width:1000px;margin:0 auto;padding:28px 20px 60px}
.hero{max-width:640px;margin:8vh auto 0;text-align:center}.hero .brand{font-size:44px;display:block;margin-bottom:22px}
.hero .q{box-shadow:0 1px 6px rgba(32,33,36,.22);border-color:transparent}.hero .q input{font-size:18px;padding:14px 22px}
.hero p{color:var(--mute);margin:18px 0 0}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-.3px}h2{font-size:17px;margin:34px 0 10px;color:var(--mute);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.sub{color:var(--mute);margin:0 0 18px}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:13px;font-weight:600;vertical-align:middle}.ok{background:var(--okbg);color:var(--ok)}.warn{background:var(--warnbg);color:var(--warn)}.unk{background:var(--unkbg);color:var(--unk)}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0 12px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;font-size:13px}
code,pre{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);border-radius:6px}code{padding:1px 6px}pre{padding:14px;overflow-x:auto;border:1px solid var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}.card{border:1px solid var(--line);border-radius:12px;padding:12px 14px;color:var(--fg)}.card:hover{text-decoration:none;box-shadow:0 1px 6px rgba(32,33,36,.16)}.card .d{color:var(--mute);font-size:13px;margin-top:2px}
.result{border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:16px 0}.result h3{margin:0 0 6px;font-size:21px}
.muted{color:var(--mute);font-size:14px}.stats{display:flex;gap:28px;flex-wrap:wrap;justify-content:center;color:var(--mute);font-size:13px;margin-top:38px}.stats b{color:var(--fg);font-size:20px;display:block}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);color:var(--mute);font-size:13px;line-height:1.7}
.rej li{color:var(--mute);font-size:14px}details summary{cursor:pointer;color:var(--mute);font-size:14px}details{margin-top:8px}
.copy{position:relative}.copy button{position:absolute;right:8px;top:8px;font-size:12px;padding:3px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--mute);cursor:pointer}
@media(max-width:640px){.bar{flex-wrap:wrap}.bar nav{width:100%;margin:0}.hero{margin-top:4vh}.hero .brand{font-size:36px}}
`;

const SEARCH_JS = `document.querySelectorAll('form[data-check]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();const v=f.q.value.trim();if(v)location.href='/d/'+encodeURIComponent(v)}));
document.querySelectorAll('.copy button').forEach(b=>b.addEventListener('click',()=>{navigator.clipboard.writeText(b.parentNode.querySelector('pre').innerText).then(()=>{b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200)})}));`;

function searchForm(value = "", big = false) {
  return `<form data-check action="/d/" method="get" role="search"><div class="q"><input name="q" value="${esc(value)}" placeholder="Paste a URL or domain, or type a product name" aria-label="Check a domain or name" ${big ? "autofocus" : ""}><button type="submit" aria-label="Check">Check</button></div></form>`;
}

function layout(title, body, { description = "", jsonld = null, canonical = "", query = "", home = false, robots = "" } = {}) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>${description ? `<meta name="description" content="${esc(description)}">` : ""}
${canonical ? `<link rel="canonical" href="${esc(canonical)}">` : ""}${robots ? `<meta name="robots" content="${esc(robots)}">` : ""}
<meta name="realurls-dataset" content="${esc(manifest.dataset_version)}">
<style>${CSS}</style>${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld)}</script>` : ""}</head>
<body>${home ? "" : `<header><div class="bar"><a class="brand" href="/">realurls</a>${searchForm(query)}<nav><a href="${REPO}/blob/main/TRUST.md">Trust model</a><a href="${API}">API</a><a href="${REPO}">GitHub</a></nav></div></header>`}
<main>${body}
<footer>Ownership only, never safety. Every verdict is reproducible — the commands are on each page.<br>Dataset <code>${esc(manifest.dataset_version)}</code> · <a href="${REPO}/releases/tag/latest">signed download</a> · data CC BY-SA 4.0 · disputes: <a href="mailto:dispute@realurls.org">dispute@realurls.org</a></footer>
</main><script>${SEARCH_JS}</script></body></html>`;
}

// ------------------------------------------------------------------ home

function home() {
  const c = manifest.counts;
  const cards = registry.slice().sort((a, b) => a.names.en.localeCompare(b.names.en)).map(e => {
    const v = verifiedDomains(e);
    return `<a class="card" href="/e/${esc(slugOf(e))}"><div>${esc(e.names.en)}</div><div class="d">${v.map(d => esc(d.domain)).join(" · ") || "—"}</div></a>`;
  }).join("");
  return layout("realurls — which domain is really the official one?", `
<div class="hero"><a class="brand" href="/">realurls</a>${searchForm("", true)}
<p>Which domain really belongs to which company. Ownership only — never a safety judgement — and only when the evidence is reproducible.</p></div>
<div class="stats"><div><b>${c.entities}</b>organizations</div><div><b>${c.verified}</b>verified domains</div><div><b>≥ 99.5%</b>precision target</div><div><b>${esc(manifest.generated_at.slice(0, 10))}</b>dataset date</div></div>
<h2>For AI agents</h2>
<div class="copy"><button type="button">Copy</button><pre>claude mcp add realurls -- npx -y @realurls/mcp</pre></div>
<p class="muted">Any MCP host: <code>{ "command": "npx", "args": ["-y", "@realurls/mcp"] }</code>. Plain HTTP: <code>${API}/v1/resolve?domain=…</code>. The server ships <em>instructions</em> telling the agent to call it before handing out any download or login link — in our tests that single line is what turns "answers from memory" into "verifies first".</p>
<h2>Verified organizations</h2>
<div class="grid">${cards}</div>
<h2>What "verified" means</h2>
<p class="muted">At least one <b>anchor</b> — something only the real owner can produce: a GitHub-verified organization, a DNS self-attestation, a restricted government TLD, a long-lived repository whose homepage points here — <b>and</b> at least two independent corroborations. Anything less is reported as insufficient evidence. We would rather say "don't know" than be wrong. Full rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a>.</p>
`, { description: "Open, reproducible registry of which domain belongs to which organization. For AI agents and people. Ownership only, never safety.", canonical: `${SITE}/`, home: true });
}

// ------------------------------------------------------------------ entity page

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
  cmds.push(`# Re-run the whole pipeline for this domain\ngit clone ${REPO} && cd realurls-registry && pip install -e . && python -m src.verify ${d.domain}`);
  return [...new Set(cmds)].join("\n\n");
}

function evidenceRows(d) {
  const rejected = new Set((d.rejected_evidence || []).map(r => r.split(":")[0]));
  return d.evidence.map(ev => {
    const bad = rejected.has(ev.code);
    const data = Object.entries(ev.data || {}).filter(([k]) => !["org_name", "created_at"].includes(k))
      .map(([k, v]) => `${esc(k)}=<code>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</code>`).join(" ");
    return `<tr><td style="white-space:nowrap"><code>${esc(ev.code)}</code> <span class="badge ${bad ? "unk" : "ok"}">${bad ? "not counted" : ev.code[0] === "A" ? "anchor" : "corroboration"}</span></td>
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
<details><summary>Reproduce this yourself</summary><div class="copy"><button type="button">Copy</button><pre>${esc(reproduceCommands(e, d))}</pre></div></details>
</div>`;
  }).join("");

  const anchorsrc = (e.canonical?.sources || []).map(s => `<code>${esc(s)}</code>`).join(" ");
  return layout(`${e.names.en} — official domains — realurls`, `
<h1>${esc(e.names.en)}</h1>
<p class="sub">${e.aliases?.length ? `Also known as ${e.aliases.map(esc).join(", ")}. ` : ""}${e.wikidata ? `Wikidata <a href="https://www.wikidata.org/wiki/${esc(e.wikidata)}">${esc(e.wikidata)}</a>. ` : ""}${e.canonical?.github_org ? `GitHub <a href="https://github.com/${esc(e.canonical.github_org)}">${esc(e.canonical.github_org)}</a>.` : ""}</p>
<p><b>Official domains:</b> ${v.length ? v.map(d => `<a href="https://${esc(d.domain)}" rel="nofollow"><code>${esc(d.domain)}</code></a>`).join(" ") : '<span class="badge unk">none verified yet</span>'}</p>
<p class="muted">Identity anchored by ${anchorsrc || "—"}. Display name from <code>${esc(e.provenance?.label_source || "?")}</code>.</p>
${domains}
<p class="muted">Think this is wrong? <a href="${REPO}/issues/new?template=dispute.yml">Open a dispute</a> — the burden of proof is on us, and the record is downgraded while we check. Source record: <a href="${REPO}/blob/main/entities/${esc(e.category[0])}/${esc(slugOf(e))}.yaml">YAML</a>.</p>
`, { description: `Verified official domains of ${e.names.en}: ${v.map(d => d.domain).join(", ")}. Evidence-backed and reproducible.`, jsonld, canonical: `${SITE}/e/${slugOf(e)}`, query: e.names.en });
}

// ------------------------------------------------------------------ verdict page

function domainPage(input, resolver) {
  const domain = registrableDomain(input);
  const hit = byDomain.get(domain);
  if (hit) return Response.redirect(`${SITE}/e/${slugOf(hit.e)}#${domain}`, 302);

  // Anything with a dot or a scheme is treated as a domain, never as a name — otherwise
  // claude-desktop.io would fuzzy-match "claude" and land on Anthropic's page, hiding that it's a lookalike.
  const looksLikeDomain = /[.\/]/.test(input) || /^https?:/i.test(input);
  const looked = looksLikeDomain ? { verdict: "skip" } : resolver.lookup(input);
  if (looked.verdict === "official" || looked.verdict === "insufficient_evidence") {
    const e = byId.get(looked.entity.id);
    if (e) return Response.redirect(`${SITE}/e/${slugOf(e)}`, 302);
  }
  const html = (body, extra = {}) => new Response(layout(`${input} — realurls`, body, { query: input, ...extra }), { headers: { "Content-Type": "text/html; charset=utf-8" } });

  if (looked.verdict === "ambiguous") {
    return html(`<h1>Several matches for “${esc(input)}”</h1><ul>${looked.candidates.map(c => `<li><a href="/e/${esc(c.id.replace(/^org:/, ""))}">${esc(c.name)}</a></li>`).join("")}</ul>`, { robots: "noindex" });
  }
  if (!looksLikeDomain) {
    return html(`<h1>“${esc(input)}” <span class="badge unk">not in the registry</span></h1>
<p class="sub">No organization by that name yet. We only list organizations whose domains we could verify with reproducible evidence.</p>
<p class="muted">Know their official site? <a href="${REPO}/issues/new?template=submit-domain.yml">Submit a lead</a> — you give us a clue, the pipeline gathers the evidence.</p>`, { robots: "noindex" });
  }

  const r = resolver.resolve(input);
  if (r.verdict === "not_official") {
    const e = byId.get(r.looks_like.id);
    return html(`<h1><code>${esc(domain)}</code> <span class="badge warn">not a known domain of ${esc(r.looks_like.name)}</span></h1>
<p class="sub">This domain resembles <code>${esc(r.looks_like.domain)}</code>, which <b>is</b> verified for ${esc(r.looks_like.name)}. We have no evidence that <code>${esc(domain)}</code> belongs to them.</p>
<div class="result"><h3>Verified domains of ${esc(r.looks_like.name)}</h3>${r.official_domains.map(d => `<div><a href="https://${esc(d)}" rel="nofollow"><code>${esc(d)}</code></a></div>`).join("")}<p class="muted"><a href="/e/${esc(slugOf(e))}">See the evidence →</a></p></div>
<p class="muted">This is an <b>attribution</b> signal, not a malware verdict. A lookalike domain can be legitimate and unrelated; it can also be a phishing site. We only say: it is not the one you probably meant.</p>`, { robots: "noindex" });
  }
  return html(`<h1><code>${esc(domain)}</code> <span class="badge unk">not in the registry</span></h1>
<p class="sub">We have no verdict for this domain — neither positive nor negative. "Don't know" is the honest answer here.</p>
<p class="muted">Know who owns it? <a href="${REPO}/issues/new?template=submit-domain.yml">Submit a lead</a>. If you <em>are</em> the owner, one DNS TXT record settles it: <code>_realurls.${esc(domain)} TXT "realurls-site-verification=…"</code>.</p>`, { robots: "noindex" });
}

// ------------------------------------------------------------------ API landing (browsers only)

export function apiLanding() {
  const ex = [
    ["Check a URL or domain", `curl "${API}/v1/resolve?domain=claude-desktop.io"`],
    ["Find the official site by name", `curl "${API}/v1/entity?q=ollama"`],
    ["Dataset version and file hashes", `curl ${API}/v1/manifest`],
    ["Plain-text allowlist of verified domains", `curl ${API}/v1/domains.txt`],
    ["Full domain index (JSON)", `curl ${API}/v1/domains.json`],
  ].map(([t, c]) => `<h2>${esc(t)}</h2><div class="copy"><button type="button">Copy</button><pre>${esc(c)}</pre></div>`).join("");
  return layout("realurls API", `
<h1>realurls API</h1>
<p class="sub">Free, no key, CORS open, GET only. Every response carries <code>X-Realurls-Dataset</code> so you can match it to the <a href="${REPO}/releases/tag/latest">signed release</a>.</p>
${ex}
<h2>Verdicts</h2>
<table><tr><th>verdict</th><th>meaning</th></tr>
<tr><td><code>official</code></td><td>Verified: ≥1 anchor + ≥2 independent corroborations. The only positive answer.</td></tr>
<tr><td><code>not_official</code></td><td>Resembles a verified domain but is not one of that organization's known domains. Attribution signal, not a malware verdict.</td></tr>
<tr><td><code>insufficient_evidence</code></td><td>Known organization, but this domain has not met the threshold. Do not present as official.</td></tr>
<tr><td><code>unknown</code></td><td>Not in the registry. "Don't know", not "bad".</td></tr></table>
<h2>MCP</h2>
<div class="copy"><button type="button">Copy</button><pre>claude mcp add realurls -- npx -y @realurls/mcp</pre></div>
<p class="muted">Trust model: <a href="${REPO}/blob/main/TRUST.md">TRUST.md</a> · Rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a> · Rate limits: none yet; be reasonable.</p>
`, { description: "realurls API: which domain officially belongs to which organization. Free, no key.", canonical: `${API}/` });
}

// ------------------------------------------------------------------ misc

function sitemap() {
  const urls = [`${SITE}/`, ...registry.map(e => `${SITE}/e/${slugOf(e)}`)];
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
  if (path === "/robots.txt") return new Response(`User-agent: *\nAllow: /\nSitemap: ${SITE}/sitemap.xml\n`, { headers: { "Content-Type": "text/plain" } });
  if (path === "/sitemap.xml") return sitemap();
  if (path === "/llms.txt") return new Response(LLMS_TXT, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  if (path.startsWith("/e/")) {
    const e = bySlug.get(decodeURIComponent(path.slice(3)));
    return e ? html(entityPage(e)) : new Response(layout("Not found — realurls", `<h1>No such organization</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
  if (path === "/d" || path.startsWith("/d/")) {
    const q = (path.length > 3 ? decodeURIComponent(path.slice(3)) : url.searchParams.get("q") || "").trim();
    return q ? domainPage(q, resolver) : Response.redirect(`${SITE}/`, 302);
  }
  if (path.startsWith("/v1/") || path === "/healthz") return null;   // API paths also work on the site host
  return new Response(layout("Not found — realurls", `<h1>Not found</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
}
