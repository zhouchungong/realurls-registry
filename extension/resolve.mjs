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

    const near = this.closest(domain, input);
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

  closest(domain, host = domain) {
    return closestLabel(this.verifiedLabels, domain, host);
  }
}

/**
 * Lookalike hint against a list of verified labels [{domain, label, entity_id}].
 * Shared by the in-memory Resolver (extension) and the D1-backed store (Worker).
 * Only verified domains may serve as the baseline — never an unverified one.
 */
/** RFC 3492 Punycode decoder for one "xn--" label, so that a homograph registered as IDN is compared
 *  after confusable folding (xn--nthropic-06g → аnthropic → anthropic). Returns the input unchanged on
 *  malformed data. */
export function decodePunycode(label) {
  if (!label.startsWith("xn--")) return label;
  const input = label.slice(4);
  const base = 36, tMin = 1, tMax = 26, skew = 38, damp = 700;
  let n = 128, i = 0, bias = 72;
  const basicEnd = input.lastIndexOf("-");
  const out = basicEnd > 0 ? Array.from(input.slice(0, basicEnd)) : [];
  const digit = c => (c >= "0" && c <= "9") ? c.charCodeAt(0) - 22 : c.charCodeAt(0) - 97;
  const adapt = (delta, len, first) => {
    delta = first ? Math.floor(delta / damp) : delta >> 1;
    delta += Math.floor(delta / len);
    let k = 0;
    for (; delta > ((base - tMin) * tMax) >> 1; k += base) delta = Math.floor(delta / (base - tMin));
    return k + Math.floor(((base - tMin + 1) * delta) / (delta + skew));
  };
  try {
    for (let p = basicEnd > 0 ? basicEnd + 1 : 0; p < input.length;) {
      const oldI = i;
      let w = 1;
      for (let k = base; ; k += base) {
        if (p >= input.length) return label;
        const d = digit(input[p++]);
        if (d < 0 || d >= base) return label;
        i += d * w;
        const t = k <= bias ? tMin : k >= bias + tMax ? tMax : k - bias;
        if (d < t) break;
        w *= base - t;
      }
      bias = adapt(i - oldI, out.length + 1, oldI === 0);
      n += Math.floor(i / (out.length + 1));
      i %= out.length + 1;
      out.splice(i++, 0, String.fromCodePoint(n));
    }
  } catch { return label; }
  return out.join("");
}

/** Hostname of an input (URL, host or bare domain), lowercased, without port. */
export function hostOf(input) {
  let s = String(input || "").trim().toLowerCase();
  s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split(/[/?#]/)[0].split("@").pop().split(":")[0];
  return s.replace(/\.$/, "");
}

/** Closest verified label to the input. Every label of the full hostname is a candidate, not only the
 *  registrable one: login.anthropic.com.evil-host.net puts the brand in a subdomain, xn-- labels are
 *  decoded first. `domain` is the registrable domain (never matched against itself). */
export function closestLabel(labels, domain, host = domain) {
  const suffix = domain.split(".").slice(1).join(".");
  const candidates = new Set();
  for (const raw of hostOf(host).split(".")) {
    const lab = normalizeLabel(decodePunycode(raw));
    if (lab.length >= 3 && !suffix.split(".").includes(raw)) candidates.add(lab);
  }
  candidates.add(normalizeLabel(decodePunycode(domain.split(".")[0])));
  let best = null;
  for (const label of candidates) {
    if (label.length < 3) continue;
    for (const v of labels) {
      if (v.domain === domain) continue;
      const contains = label.includes(v.label) || v.label.includes(label);
      const dist = levenshtein(label, v.label);
      // containment (claude-desktop ⊃ claude) scores 2; otherwise plain edit distance ≤ 2 counts as similar
      const score = contains && v.label.length >= 4 ? Math.min(dist, 2) : dist;
      if (score <= 2 && (!best || score < best.distance)) best = { ...v, distance: score, matched: label };
    }
  }
  return best;
}

export const EVIDENCE_LABELS = {
  A1: "GitHub verified this organization's domain (DNS-level check performed by GitHub)",
  A2: "Package provenance → repository → verified organization",
  A3: "Corporate registrar fingerprint (brand-protection registrar, long prepaid term, registry locks)",
  A4: "TLS certificate carries the organization name (OV/EV)",
  A5: "DNS TXT self-attestation (_realurls.<domain>)",
  A6: "Propagated from a verified sibling domain (first-party link + shared infrastructure)",
  A7: "Restricted government TLD",
  A8: "Anchored repository's homepage points here, and this site links back",
  A9: "App Store history: an established app by an Apple-verified company named like the entity, seller URL points here",
  B1: "Wikidata official-website claim (P856) on the anchored item",
  B2: "Package registry homepage field",
  B3: "App-store developer website field",
  B4: "Wayback Machine history",
  B5: "Tranco top-1M ranking",
  B6: "Official social profile links here",
  B7: "Google Safe Browsing: no record",
};

/** Human-readable description of anchor/corroboration codes, for agents that explain their answer. */
export const describeEvidence = codes => (codes || []).map(c => ({ code: c, meaning: EVIDENCE_LABELS[c] || c }));

export const CONFIDENCE_NOTE = "confidence ranks verified records among themselves (two independent anchors score higher than one); it never turns a non-verified answer into a positive one. Only verdict=official is a positive answer.";

export const verdictNotes = {
  official: "Verified as belonging to this entity. Ownership only — not a safety judgement.",
  insufficient: status => `Known entity, but evidence is insufficient (${status}). Do not present as confirmed official.`,
  lookalike: (name, near) => `Not a known domain of ${name}. Resembles ${near}. Offer the verified domain(s) instead. This is an attribution signal, not a malware verdict.`,
  unknown: "Not in the registry. Say you cannot confirm it is official; do not guess.",
};

/** Wording for the agent, per verdict; used by the remote MCP endpoint (the npm package is a bridge to it). Only `official` carries URLs to hand out. */
export function withGuidance(r) {
  const name = r.entity?.name || r.looks_like?.name;
  const urls = r.official_urls || (r.official_domains || []).map(d => `https://${d}`);
  const say = {
    official: `These are the verified official URLs${name ? ` of ${name}` : ""}: ${urls.join(", ")}. Give them as plain links.`,
    not_official: `${r.domain} is not a known domain of ${name}. ${name}'s verified site is ${urls.join(", ") || "not yet verified"}. This is about ownership, not safety.`,
    insufficient_evidence: urls.length
      ? `I could not verify ${r.domain || "that domain"}${name ? ` for ${name}` : ""}; ${name}'s verified domains are ${urls.join(", ")}.`
      : `I could not confirm the official site${name ? ` of ${name}` : ""}. Do not present any URL as official, including ones from memory. ` +
        "(If the user owns the domain, they can verify it in a minute at https://realurls.org/verify.)",
    unknown: r.examination?.status === "queued"
      ? "I could not confirm the official site. It has just been queued for examination; ask again in about fifteen minutes. " +
        "Do not present any URL as official meanwhile."
      : r.examination?.checked_at
      ? `I could not confirm the official site. It was examined on ${String(r.examination.checked_at).slice(0, 10)} and did not reach verified ` +
        `(${r.examination.reasons || "insufficient evidence"}). If the user owns the domain, they can verify it in a minute at https://realurls.org/verify.`
      : "I could not confirm the official site. Do not present any URL as official; suggest a source the user already trusts. " +
        "(If the user owns the domain, they can verify it in a minute at https://realurls.org/verify.)",
    ambiguous: `Several organizations match: ${(r.candidates || []).map(c => c.name).join(", ")}. Ask which one is meant.`,
    invalid: "That is not a domain or URL.",
  }[r.verdict];
  return say ? { ...r, say_to_user: say } : r;
}
