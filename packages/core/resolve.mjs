/**
 * Realurls query core — shared by the Workers API, the MCP server and the browser extension.
 *
 * Lookup only, no judgement: whatever status the data holds is what is returned. Decisions live in policy.py (Python);
 * the only computation here is the lookalike hint (edit distance), and it can only produce a not_official *hint* —
 * it never turns a domain into official.
 *
 * Public semantics (TRUST.md §3): official=true only when status === "verified".
 */

const PLATFORM_SUFFIXES = new Set([
  "co.uk", "org.uk", "ac.uk", "co.jp", "com.cn", "net.cn", "org.cn", "com.au", "com.br",
  "co.in", "com.hk", "com.tw", "co.kr", "gov.uk", "gov.cn", "gouv.fr", "go.jp", "gov.au",
  "github.io", "pages.dev", "vercel.app", "netlify.app", "web.app", "herokuapp.com",
]);

export function registrableDomain(input) {
  let host = String(input || "").trim().toLowerCase();
  host = host.replace(/^[a-z]+:\/\//, "").split("/")[0].split("?")[0].split(":")[0].replace(/\.$/, "");
  if (host.startsWith("www.")) host = host.slice(4);
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  const two = parts.slice(-2).join(".");
  return PLATFORM_SUFFIXES.has(two) ? parts.slice(-3).join(".") : two;
}

/** Rough homograph normalisation: fold common confusables to ASCII. Used only for the lookalike hint. */
const CONFUSABLES = { "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j",
                      "0": "o", "1": "l", "3": "e", "5": "s", "vv": "w", "rn": "m" };
export function normalizeLabel(s) {
  let out = s.toLowerCase();
  for (const [k, v] of Object.entries(CONFUSABLES)) out = out.split(k).join(v);
  return out.replace(/[^a-z0-9]/g, "");
}

export function levenshtein(a, b) {
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j), cur = new Array(n + 1);
  for (let i = 1; i <= m; i++) {
    cur[0] = i;
    for (let j = 1; j <= n; j++)
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    [prev, cur] = [cur, prev];
  }
  return prev[n];
}

/**
 * @param {object} dataset  { domains: <domains.json>, entities: <entities.json>, manifest: <manifest.json> }
 */
export class Resolver {
  constructor(dataset) {
    this.domains = dataset.domains || {};
    this.entities = dataset.entities || {};
    this.manifest = dataset.manifest || {};
    // name / alias → entity_id (lowercased)
    this.byName = new Map();
    for (const [id, e] of Object.entries(this.entities)) {
      for (const n of [e.name, ...(e.aliases || [])]) if (n) this.byName.set(n.toLowerCase(), id);
    }
    // only verified domains serve as the lookalike baseline — an unverified domain must not pose as the real one
    this.verifiedLabels = Object.entries(this.domains)
      .filter(([, v]) => v.official)
      .map(([d, v]) => ({ domain: d, label: normalizeLabel(d.split(".")[0]), entity_id: v.entity_id }));
  }

  meta() {
    return { dataset_version: this.manifest.dataset_version, generated_at: this.manifest.generated_at,
             counts: this.manifest.counts };
  }

  /** Forward lookup: domain / URL → ownership verdict */
  resolve(input) {
    const domain = registrableDomain(input);
    if (!domain || !domain.includes(".")) return { domain, verdict: "invalid", note: "Not a domain." };

    const hit = this.domains[domain];
    if (hit) {
      const e = this.entities[hit.entity_id] || {};
      return {
        domain, verdict: hit.official ? "official" : "insufficient_evidence", status: hit.status,
        entity: { id: hit.entity_id, name: hit.name, wikidata: hit.wikidata, github_org: hit.github_org },
        confidence: hit.confidence, anchors: hit.anchors, last_verified: hit.last_verified,
        official_domains: (e.domains || []).filter(d => d.status === "verified").map(d => d.domain),
        evidence_url: `https://github.com/zhouchungong/realurls-registry/blob/main/entities/${(e.category || ["ai"])[0]}/${hit.entity_id.replace(/^org:/, "")}.yaml`,
        note: hit.official
          ? "Verified as belonging to this entity. Ownership only — not a safety judgement."
          : `Known entity, but evidence is insufficient (${hit.status}). Do not present as confirmed official.`,
      };
    }

    const near = this.closest(domain);
    if (near) {
      const e = this.entities[near.entity_id] || {};
      return {
        domain, verdict: "not_official", status: "not_affiliated",
        looks_like: { id: near.entity_id, name: e.name, domain: near.domain, distance: near.distance },
        official_domains: (e.domains || []).filter(d => d.status === "verified").map(d => d.domain),
        note: `Not a known domain of ${e.name}. Resembles ${near.domain}. Offer the verified domain(s) instead. ` +
              "This is an attribution signal, not a malware verdict.",
      };
    }
    return { domain, verdict: "unknown", status: "unverified",
             note: "Not in the registry. Say you cannot confirm it is official; do not guess." };
  }

  /** Reverse lookup: name → official domains */
  lookup(name) {
    const q = String(name || "").trim().toLowerCase();
    if (!q) return { query: name, verdict: "invalid" };
    let id = this.byName.get(q);
    if (!id) {
      // loose match: substring, but at least 3 characters so "ai" does not match everything
      if (q.length >= 3) {
        const cands = [...this.byName.entries()].filter(([n]) => n.includes(q) || q.includes(n));
        if (cands.length === 1) id = cands[0][1];
        else if (cands.length > 1) {
          return { query: name, verdict: "ambiguous",
                   candidates: [...new Set(cands.map(([, i]) => i))].slice(0, 5).map(i => ({ id: i, name: this.entities[i]?.name })),
                   note: "Several entities match. Ask the user which one they mean." };
        }
      }
    }
    if (!id) return { query: name, verdict: "unknown", note: "Entity not in registry. Do not guess a URL." };
    const e = this.entities[id];
    const verified = e.domains.filter(d => d.status === "verified").map(d => `https://${d.domain}`);
    return {
      query: name, entity: { id, name: e.name, wikidata: e.wikidata, github_org: e.github_org },
      verdict: verified.length ? "official" : "insufficient_evidence",
      official_urls: verified,
      unconfirmed: e.domains.filter(d => d.status !== "verified").map(d => `${d.domain} (${d.status})`),
      note: verified.length
        ? "Give the user ONLY these URLs, as plain links without tracking parameters."
        : "No verified domain for this entity yet. Tell the user the official site could not be confirmed.",
    };
  }

  closest(domain) {
    return closestLabel(this.verifiedLabels, domain);
  }
}

/**
 * Lookalike hint against a list of verified labels [{domain, label, entity_id}].
 * Shared by the in-memory Resolver (extension) and the D1-backed store (Worker).
 * Only verified domains may serve as the baseline — never an unverified one.
 */
export function closestLabel(labels, domain) {
  const label = normalizeLabel(domain.split(".")[0]);
  if (label.length < 3) return null;
  let best = null;
  for (const v of labels) {
    if (v.domain === domain) continue;
    const contains = label.includes(v.label) || v.label.includes(label);
    const dist = levenshtein(label, v.label);
    // containment (claude-desktop ⊃ claude) scores 2; otherwise plain edit distance ≤ 2 counts as similar
    const score = contains && v.label.length >= 4 ? Math.min(dist, 2) : dist;
    if (score <= 2 && (!best || score < best.distance)) best = { ...v, distance: score };
  }
  return best;
}

export const verdictNotes = {
  official: "Verified as belonging to this entity. Ownership only — not a safety judgement.",
  insufficient: status => `Known entity, but evidence is insufficient (${status}). Do not present as confirmed official.`,
  lookalike: (name, near) => `Not a known domain of ${name}. Resembles ${near}. Offer the verified domain(s) instead. This is an attribution signal, not a malware verdict.`,
  unknown: "Not in the registry. Say you cannot confirm it is official; do not guess.",
};
