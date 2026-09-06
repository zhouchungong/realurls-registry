/**
 * POST /v1/submit: file a lead or an owner-verification request without a GitHub account.
 *
 * The Worker creates the issue with a fine-grained token (secret GITHUB_ISSUES_TOKEN, issues:write on this
 * repository only). The issue body uses the same "### label" headings the templates produce, so the lead
 * and owner workflows parse it unchanged; the label is what triggers them. Without the secret the endpoint
 * answers 503 and the site falls back to the prefilled GitHub form.
 *
 * Abuse limits: a honeypot field, a domain syntax check, and a daily cap counted in the aggregate table
 * (kind "submit"). Nothing about the submitter is stored; the issue is authored by the token's account and
 * says it came through the site form.
 */

import { registrableDomain } from "../../packages/core/resolve.mjs";

const REPO = "zhouchungong/realurls-registry";
const DAILY_CAP = 100;
const DOMAIN_RE = /^(?!-)[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$/;

function json(body, status, cors) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...cors } });
}

export async function handleSubmit(request, env, store, cors) {
  if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);
  if (!env.GITHUB_ISSUES_TOKEN) return json({ error: "site submissions are not enabled; use the GitHub form" }, 503, cors);

  let body;
  try { body = await request.json(); } catch { return json({ error: "invalid JSON" }, 400, cors); }
  if (body.website) return json({ ok: true }, 200, cors);   // honeypot: pretend, do nothing

  const kind = body.kind === "verify" ? "verify" : body.kind === "lead" ? "lead" : null;
  const domain = registrableDomain(String(body.domain || ""));
  const org = String(body.org || "").trim().slice(0, 120);
  if (!kind) return json({ error: "kind must be lead or verify" }, 400, cors);
  if (!domain || !DOMAIN_RE.test(domain)) return json({ error: "that is not a domain" }, 400, cors);
  if (!org) return json({ error: "organization is required" }, 400, cors);

  if ((await store.submissionsToday()) >= DAILY_CAP) return json({ error: "daily submission limit reached; use the GitHub form" }, 429, cors);

  const title = kind === "verify" ? `[verify] ${domain}` : `[lead] ${org}`;
  const labels = [kind === "verify" ? "owner-verification" : "lead"];
  const bodyText = kind === "verify"
    ? `### Domain\n\n${domain}\n\n### Organization\n\n${org}\n\n### GitHub organization (optional)\n\n_No response_\n\n### Category (optional)\n\nother\n\n### Confirmation\n\n- [x] I control this domain's DNS zone and I am authorized to state which organization it belongs to.\n\n_Filed through the form at https://realurls.org/verify._`
    : `### Organization / company\n\n${org}\n\n### Domain you believe is the official site\n\n${domain}\n\n### How do you know this is the official site? (optional)\n\n_No response_\n\n### Other names people search for (optional)\n\n_No response_\n\n### Confirm\n\n- [x] I understand Realurls judges domain ownership only, never whether a site is safe or lawful, and I have disclosed any interest in this organization above.\n\n_Filed through the form at https://realurls.org/d/${domain}._`;

  const res = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.GITHUB_ISSUES_TOKEN}`, "Accept": "application/vnd.github+json",
               "Content-Type": "application/json", "User-Agent": "realurls-site" },
    body: JSON.stringify({ title, body: bodyText, labels }),
  });
  if (!res.ok) return json({ error: `GitHub answered ${res.status}` }, 502, cors);
  const issue = await res.json();
  await store.tally("submit", kind, "ok");
  return json({ ok: true, url: issue.html_url, number: issue.number }, 200, cors);
}
