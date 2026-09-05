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

import { registrableDomain, EVIDENCE_LABELS } from "../../packages/core/resolve.mjs";

const REPO = "https://github.com/zhouchungong/realurls-registry";
const API = "https://api.realurls.org";
const SITE = "https://realurls.org";



const CATEGORY_LABELS = {
  ai: "AI", "developer-tools": "Developer tools", infrastructure: "Infrastructure", "open-source": "Open source",
  saas: "SaaS", security: "Security", hardware: "Hardware", finance: "Finance", government: "Government", other: "Other",
};
const categoryLabel = c => CATEGORY_LABELS[c] || c;
const PAGE_SIZE = 100;

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
.topnav{display:flex;justify-content:flex-end;gap:18px;font-size:14px}.topnav a{color:var(--mute)}
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
.pager{display:flex;justify-content:space-between;align-items:center;margin:22px 0 8px;font-size:14px;color:var(--mute)}
@media(max-width:640px){.bar{flex-wrap:wrap}.bar nav{width:100%;margin:0}.hero{margin-top:4vh}.hero .brand{font-size:36px}}
`;

const SEARCH_JS = `document.querySelectorAll('form[data-check]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();const v=f.q.value.trim();if(v)location.href='/d/'+encodeURIComponent(v)}));
document.querySelectorAll('.copy button').forEach(b=>b.addEventListener('click',()=>{navigator.clipboard.writeText(b.parentNode.querySelector('pre').innerText).then(()=>{b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200)})}));`;

function searchForm(value = "", big = false) {
  return `<form data-check action="/d/" method="get" role="search"><div class="q"><input name="q" value="${esc(value)}" placeholder="Paste a URL or domain, or type a product name" aria-label="Check a domain or name" ${big ? "autofocus" : ""}><button type="submit" aria-label="Check">Check</button></div></form>`;
}

function layout(meta, title, body, { description = "", jsonld = null, canonical = "", query = "", home = false, robots = "" } = {}) {
  const manifest = meta;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>${description ? `<meta name="description" content="${esc(description)}">` : ""}
${canonical ? `<link rel="canonical" href="${esc(canonical)}">` : ""}${robots ? `<meta name="robots" content="${esc(robots)}">` : ""}
<meta name="realurls-dataset" content="${esc(manifest.dataset_version)}">
<style>${CSS}</style>${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld)}</script>` : ""}</head>
<body>${home ? "" : `<header><div class="bar"><a class="brand" href="/">Realurls</a>${searchForm(query)}<nav><a href="/builders">For AI builders</a><a href="${REPO}/blob/main/TRUST.md">Trust model</a><a href="${API}">API</a><a href="${REPO}">GitHub</a></nav></div></header>`}
<main>${body}
<footer>Ownership only, never safety. Every verdict is reproducible — the commands are on each page.<br>Dataset <code>${esc(manifest.dataset_version)}</code> · <a href="${REPO}/releases/tag/latest">signed download</a> · data CC BY-SA 4.0 · disputes: <a href="mailto:dispute@realurls.org">dispute@realurls.org</a></footer>
</main><script>${SEARCH_JS}</script></body></html>`;
}

// ------------------------------------------------------------------ home

async function home(store, manifest) {
  const c = manifest.counts;
  const cats = (await store.categories()).map(x =>
    `<a class="card" href="/c/${esc(x.category)}"><div>${esc(categoryLabel(x.category))}</div><div class="d">${x.n} organization${x.n === 1 ? "" : "s"}</div></a>`
  ).join("");
  return layout(manifest, "Realurls — which domain is really the official one?", `
<div class="topnav"><a href="/builders">For AI builders</a><a href="${REPO}/blob/main/TRUST.md">Trust model</a><a href="${API}">API</a><a href="${REPO}">GitHub</a></div>
<div class="hero"><a class="brand" href="/">Realurls</a>${searchForm("", true)}
<p>Which domain really belongs to which company. Ownership only — never a safety judgement — and only when the evidence is reproducible.</p></div>
<div class="stats"><div><b>${c.entities}</b>organizations</div><div><b>${c.verified}</b>verified domains</div><div><b>≥ 99.5%</b>precision target</div><div><b>${esc(manifest.generated_at.slice(0, 10))}</b>dataset date</div></div>
<h2>For AI agents</h2>
<div class="copy"><button type="button">Copy</button><pre>claude mcp add realurls -- npx -y @realurls/mcp</pre></div>
<p class="muted">Any MCP host: <code>{ "command": "npx", "args": ["-y", "@realurls/mcp"] }</code>. Plain HTTP: <code>${API}/v1/resolve?domain=…</code>. The server ships <em>instructions</em> telling the agent to call it before handing out any download or login link — in our tests that single line is what turns "answers from memory" into "verifies first". No MCP? <a href="/builders">Three other ways in</a>, down to a one-line allowlist.</p>
<h2>Browse by category</h2>
<div class="grid">${cats}</div>
<p class="muted"><a href="/browse">All ${c.entities} organizations, A–Z →</a></p>
<h2>What "verified" means</h2>
<p class="muted">At least one <b>anchor</b> — something only the real owner can produce: a GitHub-verified organization, a DNS self-attestation, a restricted government TLD, a long-lived repository whose homepage points here — <b>and</b> at least two independent corroborations. Anything less is reported as insufficient evidence. We would rather say "don't know" than be wrong. Full rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a>. Own a domain? <a href="/verify">Verify it in a minute</a>.</p>
`, { description: "Open, reproducible registry of which domain belongs to which organization. For AI agents and people. Ownership only, never safety.", canonical: `${SITE}/`, home: true });
}

// ------------------------------------------------------------------ for AI builders

const AGENT_RULE = `Before giving the user any URL for downloading, installing, logging into, or visiting the official site of a software product or company, look the domain up in Realurls and use ONLY the URLs it returns, even if you are confident you already know the URL. Well-known tools are exactly the ones targeted by lookalike download sites, and memorised URLs go stale. If Realurls answers insufficient_evidence or unknown, tell the user the official site could not be confirmed instead of guessing. Realurls judges ownership only, never safety.`;

function buildersPage(manifest) {
  const block = (title, code, note = "") => `<h2>${esc(title)}</h2><div class="copy"><button type="button">Copy</button><pre>${esc(code)}</pre></div>${note ? `<p class="muted">${note}</p>` : ""}`;
  return layout(manifest, "For AI builders — Realurls", `
<p class="sub"><a href="/">Realurls</a> › For AI builders</p>
<h1>Put a verified official-domain check into your agent</h1>
<p class="sub">Three ways in, from zero integration to a full tool. All free, no key, ${manifest.counts.verified} verified domains, refreshed daily, every verdict reproducible.</p>

${block("1. Zero integration: the allowlist in your prompt or RAG", `curl -s ${API}/v1/domains.txt`,
  `A plain-text list of every verified domain, one per line, tens of KB. Drop it into a system prompt, a retrieval index, or a URL filter. <code>${API}/v1/domains.json</code> carries the same list with the owning organization, status and evidence codes per domain. Both are cached at the edge; fetch once an hour or once a day.`)}

${block("2. The behaviour rule (copy into your system prompt)", AGENT_RULE,
  `This is the sentence that changes behaviour. In our tests an agent that merely <em>had</em> the tool still answered well-known products from memory; an agent given this rule verified first. Use it with whichever integration below you pick.`)}

${block("3a. HTTP tool: check a URL the user pasted", `curl "${API}/v1/resolve?domain=claude-desktop.io"`,
  `Returns <code>official</code>, <code>not_official</code> (with the real verified domains of the organization it resembles), <code>insufficient_evidence</code> or <code>unknown</code>. Every response includes a <code>note</code> written for the agent: what to tell the user. Only <code>official</code> is a positive answer.`)}

${block("3b. HTTP tool: find the official site by name", `curl "${API}/v1/entity?q=ollama"`,
  `<code>official_urls</code> is the list to hand the user, as plain links. <code>insufficient_evidence</code> means we know the organization but could not verify a domain: say so, do not fill the gap from memory. <code>ambiguous</code> lists candidates: ask the user which they mean.`)}

${block("3c. MCP, remote: one URL for claude.ai, ChatGPT, Cursor and any host that takes a server URL", `${API}/mcp`,
  `Streamable HTTP, no auth, stateless. Same two tools and the same instructions as the npm package below. In Claude Code: <code>claude mcp add --transport http realurls ${API}/mcp</code>.`)}

${block("3d. MCP, local: one line for Claude Code", `claude mcp add realurls -- npx -y @realurls/mcp`,
  `Any MCP host: <code>{ "command": "npx", "args": ["-y", "@realurls/mcp"] }</code>. The server ships the rule above as its <em>instructions</em>, so hosts that honour instructions get the behaviour without prompt changes. Tools: <code>get_official_url(name)</code>, <code>verify_url(url)</code>. Source and README: <a href="${REPO}/tree/main/mcp">mcp/</a>.`)}

<h2>How to phrase the answer</h2>
<table><tr><th>verdict</th><th>what the agent should say</th></tr>
<tr><td><code>official</code></td><td>Give these URLs, as plain links, no tracking parameters. Optionally cite the evidence page.</td></tr>
<tr><td><code>not_official</code></td><td>"That is not a known domain of X. X's verified site is Y." Do not call the domain malicious; we do not know that.</td></tr>
<tr><td><code>insufficient_evidence</code></td><td>"I could not confirm the official site." Do not present any URL as official, including ones you remember.</td></tr>
<tr><td><code>unknown</code></td><td>"I could not confirm the official site." Suggest the user verify through a source they already trust. Read <code>examination</code>: <code>queued</code> means the pipeline will examine the domain within about fifteen minutes (ask again); <code>checked_at</code> means it was examined and fell short, with the reasons.</td></tr></table>
<p class="muted">Fields worth reading: <code>evidence</code> (each anchor code with its meaning, so the agent can say <em>why</em>), <code>freshness</code> (records are re-verified daily), <code>missing</code> (for insufficient_evidence: what the rules rejected and why), and <code>confidence</code> with its note: it ranks verified records among themselves and never upgrades a non-official answer.</p>

<h2>The dataset itself</h2>
<p class="muted">Every release is signed (cosign, keyless) and published at <a href="${REPO}/releases/tag/latest">GitHub Releases</a> with a manifest of file hashes; the current version is <code>${esc(manifest.dataset_version)}</code>. License CC BY-SA 4.0. The source records are YAML files in <a href="${REPO}/tree/main/entities">entities/</a>, generated only by the pipeline, each with the full evidence and the commands to reproduce it. If you ship a product on top of it, <a href="mailto:security@realurls.org">tell us</a> so we can warn you before any breaking change.</p>

<h2>What you get and what you do not</h2>
<p class="muted">You get: ownership, with evidence, at ≥ 99.5% target precision, or an honest "don't know". You do not get: a safety score, a blacklist, a reputation. A domain we cannot verify is not "bad", it is unverified. Full rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a>; what we promise and what we do not: <a href="${REPO}/blob/main/TRUST.md">TRUST.md</a>.</p>
`, { description: "How to add a verified official-domain check to an AI agent: allowlist, HTTP API, or MCP. Free, reproducible, ownership only.", canonical: `${SITE}/builders` });
}

// ------------------------------------------------------------------ for domain owners

function verifyPage(manifest) {
  const issue = `${REPO}/issues/new?template=verify-domain.yml`;
  return layout(manifest, "Verify your domain — Realurls", `
<p class="sub"><a href="/">Realurls</a> › Verify your domain</p>
<h1>Get your domain verified in a minute</h1>
<p class="sub">You control the domain. Prove it once, and every AI agent that asks Realurls gets your real site instead of a lookalike. No human in the loop; the result is a public record with the evidence.</p>

<h2>Option A: one DNS TXT record</h2>
<ol>
<li>Open a <a href="${issue}">Verify my domain</a> issue on GitHub (domain, organization name). A bot replies with a token within a minute.</li>
<li>Publish it in your DNS zone:</li>
</ol>
<div class="copy"><button type="button">Copy</button><pre>_realurls.example.com.   TXT   "realurls-site-verification=&lt;token&gt;"</pre></div>
<ol start="3">
<li>Comment <code>/verify</code> on the issue (or wait for the daily run). The pipeline checks the record, collects the corroborating evidence, and merges the record once the adversarial corpus and the AI review pass. Minutes later it is live here and in the API.</li>
</ol>
<p class="muted">This is evidence <b>A5</b>, the highest-weight anchor we have (0.90) and the only one that waives the 180-day domain-age floor. The token is not a secret; what it proves is control of the zone.</p>

<h2>Option B: GitHub, no token</h2>
<p class="muted">If your organization is on GitHub: Settings → <b>Verified and approved domains</b> → add the domain. GitHub performs the DNS check; the pipeline reads the result as evidence <b>A1</b>. Then open the same issue and comment <code>/verify</code>, or just wait for the next batch.</p>

<h2>What this does and does not mean</h2>
<p class="muted">Verified means the domain belongs to the organization named, with reproducible evidence. It is not a safety, quality or reputation judgement, and it cannot be used to claim a domain you do not control: the record has to be in your zone. Every record is re-verified daily; if the record disappears, the status changes. Rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a>.</p>
`, { description: "Domain owners: verify your domain with one DNS TXT record or a GitHub verified domain. Ownership only, reproducible evidence, no human in the loop.", canonical: `${SITE}/verify` });
}

// ------------------------------------------------------------------ category / browse listings

async function listing(store, manifest, { category = null, page = 1 }) {
  const total = await store.count(category);
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  page = Math.min(Math.max(1, page), pages);
  const rows = await store.list({ category, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const base = category ? `/c/${category}` : "/browse";
  const title = category ? `${categoryLabel(category)} — verified organizations` : "All organizations";
  const cards = rows.map(e =>
    `<a class="card" href="/e/${esc(slugOf(e))}"><div>${esc(e.name)}</div><div class="d">${esc(e.verified) || "—"}</div></a>`
  ).join("");
  const nav = pages > 1 ? `<nav class="pager">${page > 1 ? `<a href="${base}?page=${page - 1}" rel="prev">← Previous</a>` : "<span></span>"}<span>Page ${page} of ${pages}</span>${page < pages ? `<a href="${base}?page=${page + 1}" rel="next">Next →</a>` : "<span></span>"}</nav>` : "";
  const crumbs = category
    ? `<p class="sub"><a href="/">Realurls</a> › <a href="/browse">All organizations</a> › ${esc(categoryLabel(category))}</p>`
    : `<p class="sub"><a href="/">Realurls</a> › All organizations</p>`;
  const others = category ? `<p class="muted">Other categories: ${(await store.categories()).filter(x => x.category !== category).map(x => `<a href="/c/${esc(x.category)}">${esc(categoryLabel(x.category))}</a> (${x.n})`).join(" · ")}</p>` : "";
  return layout(manifest, `${title} — Realurls`, `
${crumbs}<h1>${esc(title)}</h1>
<p class="muted">${total} organization${total === 1 ? "" : "s"}${category ? ` in ${esc(categoryLabel(category))}` : ""}, alphabetical. Every entry links to its evidence and the commands to reproduce it.</p>
<div class="grid">${cards || "<p class='muted'>Nothing here yet.</p>"}</div>
${nav}${others}`, {
    description: `${title}: ${total} organizations whose official domains are verified by reproducible evidence.`,
    canonical: `${SITE}${base}${page > 1 ? `?page=${page}` : ""}`,
    robots: page > 1 ? "noindex, follow" : "",
  });
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

function entityPage(e, manifest) {
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
  return layout(manifest, `${e.names.en} — official domains — Realurls`, `
<h1>${esc(e.names.en)}</h1>
<p class="sub">${e.aliases?.length ? `Also known as ${e.aliases.map(esc).join(", ")}. ` : ""}${e.wikidata ? `Wikidata <a href="https://www.wikidata.org/wiki/${esc(e.wikidata)}">${esc(e.wikidata)}</a>. ` : ""}${e.canonical?.github_org ? `GitHub <a href="https://github.com/${esc(e.canonical.github_org)}">${esc(e.canonical.github_org)}</a>.` : ""}</p>
<p><b>Official domains:</b> ${v.length ? v.map(d => `<a href="https://${esc(d.domain)}" rel="nofollow"><code>${esc(d.domain)}</code></a>`).join(" ") : '<span class="badge unk">none verified yet</span>'}</p>
<p class="muted">Identity anchored by ${anchorsrc || "—"}. Display name from <code>${esc(e.provenance?.label_source || "?")}</code>.</p>
${domains}
<p class="muted">Think this is wrong? <a href="${REPO}/issues/new?template=dispute.yml">Open a dispute</a> — the burden of proof is on us, and the record is downgraded while we check. Source record: <a href="${REPO}/blob/main/entities/${esc(e.category[0])}/${esc(slugOf(e))}.yaml">YAML</a>.</p>
`, { description: `Verified official domains of ${e.names.en}: ${v.map(d => d.domain).join(", ")}. Evidence-backed and reproducible.`, jsonld, canonical: `${SITE}/e/${slugOf(e)}`, query: e.names.en });
}

// ------------------------------------------------------------------ verdict page

async function domainPage(input, store, manifest) {
  const domain = registrableDomain(input);
  const r = await store.resolve(input);
  if (r.verdict === "official" || r.verdict === "insufficient_evidence") {
    return Response.redirect(`${SITE}/e/${r.entity.id.replace(/^org:/, "")}#${domain}`, 302);
  }

  // Anything with a dot or a scheme is treated as a domain, never as a name — otherwise
  // claude-desktop.io would fuzzy-match "claude" and land on Anthropic's page, hiding that it's a lookalike.
  const looksLikeDomain = /[.\/]/.test(input) || /^https?:/i.test(input);
  const looked = looksLikeDomain ? { verdict: "skip" } : await store.lookup(input);
  if (looked.verdict === "official" || looked.verdict === "insufficient_evidence") {
    return Response.redirect(`${SITE}/e/${looked.entity.id.replace(/^org:/, "")}`, 302);
  }
  const html = (body, extra = {}) => new Response(layout(manifest, `${input} — Realurls`, body, { query: input, ...extra }), { headers: { "Content-Type": "text/html; charset=utf-8" } });

  if (looked.verdict === "ambiguous") {
    return html(`<h1>Several matches for “${esc(input)}”</h1><ul>${looked.candidates.map(c => `<li><a href="/e/${esc(c.id.replace(/^org:/, ""))}">${esc(c.name)}</a></li>`).join("")}</ul>`, { robots: "noindex" });
  }
  if (!looksLikeDomain) {
    return html(`<h1>“${esc(input)}” <span class="badge unk">not in the registry</span></h1>
<p class="sub">No organization by that name yet. We only list organizations whose domains we could verify with reproducible evidence.</p>
<p class="muted">Know their official site? <a href="${REPO}/issues/new?template=submit-domain.yml">Submit a lead</a> — you give us a clue, the pipeline gathers the evidence.</p>`, { robots: "noindex" });
  }

  if (r.verdict === "not_official") {
    const slug = r.looks_like.id.replace(/^org:/, "");
    return html(`<h1><code>${esc(domain)}</code> <span class="badge warn">not a known domain of ${esc(r.looks_like.name)}</span></h1>
<p class="sub">This domain resembles <code>${esc(r.looks_like.domain)}</code>, which <b>is</b> verified for ${esc(r.looks_like.name)}. We have no evidence that <code>${esc(domain)}</code> belongs to them.</p>
<div class="result"><h3>Verified domains of ${esc(r.looks_like.name)}</h3>${r.official_domains.map(d => `<div><a href="https://${esc(d)}" rel="nofollow"><code>${esc(d)}</code></a></div>`).join("")}<p class="muted"><a href="/e/${esc(slug)}">See the evidence →</a></p></div>
<p class="muted">This is an <b>attribution</b> signal, not a malware verdict. A lookalike domain can be legitimate and unrelated; it can also be a phishing site. We only say: it is not the one you probably meant.</p>`, { robots: "noindex" });
  }
  const ex = r.examination || {};
  const exLine = ex.checked_at
    ? `<p class="muted">Examined on ${esc(String(ex.checked_at).slice(0, 10))}: the rules reached <code>${esc(ex.status)}</code>, not verified${ex.reasons ? ` (${esc(ex.reasons)})` : ""}. It is re-examined as evidence changes.</p>`
    : `<p class="muted">This domain has just been queued: the pipeline examines it within about fifteen minutes. Reload this page afterwards.</p>`;
  return html(`<h1><code>${esc(domain)}</code> <span class="badge unk">not in the registry</span></h1>
${exLine}
<p class="sub">We have no verdict for this domain — neither positive nor negative. "Don't know" is the honest answer here. The registry holds ${manifest.counts.entities} organizations today and grows in reviewed batches; not being listed means not yet examined, nothing more.</p>
<p class="muted">Know who owns it? <a href="${REPO}/issues/new?template=submit-domain.yml">Submit a lead</a>. If you <em>are</em> the owner, <a href="/verify">one DNS TXT record settles it</a>.</p>`, { robots: "noindex" });
}

// ------------------------------------------------------------------ API landing (browsers only)

export function apiLanding(meta) {
  const ex = [
    ["Check a URL or domain", `curl "${API}/v1/resolve?domain=claude-desktop.io"`],
    ["Find the official site by name", `curl "${API}/v1/entity?q=ollama"`],
    ["Dataset version and file hashes", `curl ${API}/v1/manifest`],
    ["Plain-text allowlist of verified domains", `curl ${API}/v1/domains.txt`],
    ["Full domain index (JSON)", `curl ${API}/v1/domains.json`],
  ].map(([t, c]) => `<h2>${esc(t)}</h2><div class="copy"><button type="button">Copy</button><pre>${esc(c)}</pre></div>`).join("");
  return layout(meta, "Realurls API", `
<h1>Realurls API</h1>
<p class="sub">Free, no key, CORS open, GET only. Every response carries <code>X-Realurls-Dataset</code> so you can match it to the <a href="${REPO}/releases/tag/latest">signed release</a>.</p>
${ex}
<h2>Verdicts</h2>
<table><tr><th>verdict</th><th>meaning</th></tr>
<tr><td><code>official</code></td><td>Verified: ≥1 anchor + ≥2 independent corroborations. The only positive answer.</td></tr>
<tr><td><code>not_official</code></td><td>Resembles a verified domain but is not one of that organization's known domains. Attribution signal, not a malware verdict.</td></tr>
<tr><td><code>insufficient_evidence</code></td><td>Known organization, but this domain has not met the threshold. Do not present as official.</td></tr>
<tr><td><code>unknown</code></td><td>Not in the registry. "Don't know", not "bad".</td></tr></table>
<h2>MCP</h2>
<div class="copy"><button type="button">Copy</button><pre>claude mcp add --transport http realurls ${API}/mcp</pre></div>
<div class="copy"><button type="button">Copy</button><pre>claude mcp add realurls -- npx -y @realurls/mcp</pre></div>
<p class="muted">Building an agent? <a href="${SITE}/builders">For AI builders</a>: allowlist, behaviour rule, tool shapes. Trust model: <a href="${REPO}/blob/main/TRUST.md">TRUST.md</a> · Rules: <a href="${REPO}/blob/main/POLICY.md">POLICY.md</a> · Rate limits: none yet; be reasonable.</p>
`, { description: "Realurls API: which domain officially belongs to which organization. Free, no key.", canonical: `${API}/` });
}

// ------------------------------------------------------------------ misc

async function sitemap(store, manifest) {
  const urls = [`${SITE}/`, `${SITE}/builders`, `${SITE}/verify`, `${SITE}/browse`, ...(await store.categories()).map(x => `${SITE}/c/${x.category}`)];
  for (let offset = 0; ; offset += 5000) {
    const batch = await store.list({ limit: 5000, offset });
    urls.push(...batch.map(e => `${SITE}/e/${e.entity_id.replace(/^org:/, "")}`));
    if (batch.length < 5000 || urls.length >= 49000) break;
  }
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.map(u => `<url><loc>${u}</loc><lastmod>${manifest.generated_at.slice(0, 10)}</lastmod></url>`).join("")}</urlset>`, { headers: { "Content-Type": "application/xml" } });
}

const LLMS_TXT = `# Realurls

> Which domain officially belongs to which software product or company. Ownership only, never safety. Every verdict is backed by reproducible machine evidence.

- For AI builders (allowlist, behaviour rule, tool shapes): ${SITE}/builders
- For domain owners (verify with one DNS TXT record): ${SITE}/verify
- API: ${API}/v1/resolve?domain=<domain>  and  ${API}/v1/entity?q=<name>
- Allowlist of verified domains, one per line: ${API}/v1/domains.txt
- MCP server, remote (Streamable HTTP): ${API}/mcp   local: npx -y @realurls/mcp  (both ship instructions: call before giving any download/login URL)
- Trust model: ${REPO}/blob/main/TRUST.md
- Rules: ${REPO}/blob/main/POLICY.md
- Signed dataset: ${REPO}/releases/tag/latest

Statuses: only "verified" is a positive answer. provisional / community / unverified mean "insufficient evidence" — do not present those domains as confirmed official.
`;

export async function handleSite(request, store, manifest) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const html = body => new Response(body, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300", "X-Realurls-Dataset": manifest.dataset_version } });

  if (path === "/") return html(await home(store, manifest));
  if (path === "/builders") return html(buildersPage(manifest));
  if (path === "/verify") return html(verifyPage(manifest));
  if (path === "/browse") return html(await listing(store, manifest, { page: +url.searchParams.get("page") || 1 }));
  if (path.startsWith("/c/")) {
    const category = decodeURIComponent(path.slice(3));
    if (!CATEGORY_LABELS[category]) return new Response(layout(manifest, "Not found — Realurls", `<h1>No such category</h1><p><a href="/browse">Browse all organizations</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
    return html(await listing(store, manifest, { category, page: +url.searchParams.get("page") || 1 }));
  }
  if (path === "/robots.txt") return new Response(`User-agent: *\nAllow: /\nSitemap: ${SITE}/sitemap.xml\n`, { headers: { "Content-Type": "text/plain" } });
  if (path === "/sitemap.xml") return sitemap(store, manifest);
  if (path === "/llms.txt") return new Response(LLMS_TXT, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  if (path.startsWith("/e/")) {
    const e = await store.entityBySlug(decodeURIComponent(path.slice(3)));
    return e ? html(entityPage(e, manifest)) : new Response(layout(manifest, "Not found — Realurls", `<h1>No such organization</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
  if (path === "/d" || path.startsWith("/d/")) {
    const q = (path.length > 3 ? decodeURIComponent(path.slice(3)) : url.searchParams.get("q") || "").trim();
    return q ? domainPage(q, store, manifest) : Response.redirect(`${SITE}/`, 302);
  }
  if (path.startsWith("/v1/") || path === "/healthz") return null;   // API paths also work on the site host
  return new Response(layout(manifest, "Not found — Realurls", `<h1>Not found</h1><p><a href="/">Back to search</a></p>`), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
}
