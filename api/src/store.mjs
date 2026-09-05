/**
 * D1-backed store. Same output shapes as the in-memory Resolver in packages/core, but the data lives in
 * Cloudflare D1 instead of the Worker bundle — the bundle no longer grows with the dataset.
 *
 * The only thing kept in memory is the lookalike index (verified domain labels): one query on first use,
 * cached per isolate and refreshed when the dataset version changes. ~30 bytes per domain, so 40k domains
 * is about 1 MB.
 */

import { registrableDomain, normalizeLabel, closestLabel, verdictNotes, describeEvidence, CONFIDENCE_NOTE } from "../../packages/core/resolve.mjs";

const REPO = "https://github.com/zhouchungong/realurls-registry";

let labelCache = { version: null, labels: [] };
let metaCache = { at: 0, meta: null };

export class Store {
  constructor(db) { this.db = db; }

  async meta() {
    if (metaCache.meta && Date.now() - metaCache.at < 60_000) return metaCache.meta;
    const { results } = await this.db.prepare("SELECT key, value FROM meta").all();
    const m = Object.fromEntries(results.map(r => [r.key, r.value]));
    const meta = {
      dataset_version: m.dataset_version, generated_at: m.generated_at,
      counts: { entities: +m.entities, domains: +m.domains, verified: +m.verified },
    };
    metaCache = { at: Date.now(), meta };
    return meta;
  }

  async labels() {
    const { dataset_version } = await this.meta();
    if (labelCache.version === dataset_version) return labelCache.labels;
    const { results } = await this.db.prepare("SELECT domain, entity_id FROM domains WHERE official = 1").all();
    labelCache = { version: dataset_version, labels: results.map(r => ({ domain: r.domain, entity_id: r.entity_id, label: normalizeLabel(r.domain.split(".")[0]) })) };
    return labelCache.labels;
  }

  async entity(id) {
    const e = await this.db.prepare("SELECT * FROM entities WHERE entity_id = ?").bind(id).first();
    if (!e) return null;
    const { results: ds } = await this.db.prepare("SELECT * FROM domains WHERE entity_id = ? ORDER BY official DESC, domain").bind(id).all();
    return shapeEntity(e, ds);
  }

  async entityBySlug(slug) { return this.entity(`org:${slug}`); }

  /** Compact listing for category pages / sitemap. `category` filters on the comma-joined column. */
  async list({ category = null, limit = 100, offset = 0 } = {}) {
    const where = category ? "WHERE ',' || e.category || ',' LIKE ?" : "";
    const args = category ? [`%,${category},%`, limit, offset] : [limit, offset];
    const { results } = await this.db.prepare(
      "SELECT e.entity_id, e.name, e.category, GROUP_CONCAT(CASE WHEN d.official=1 THEN d.domain END, ' · ') AS verified " +
      `FROM entities e LEFT JOIN domains d ON d.entity_id = e.entity_id ${where} GROUP BY e.entity_id ORDER BY e.name COLLATE NOCASE LIMIT ? OFFSET ?`
    ).bind(...args).all();
    return results.map(r => ({ entity_id: r.entity_id, name: r.name, category: (r.category || "").split(",").filter(Boolean), verified: r.verified || "" }));
  }

  async count(category = null) {
    const row = category
      ? await this.db.prepare("SELECT COUNT(*) AS n FROM entities WHERE ',' || category || ',' LIKE ?").bind(`%,${category},%`).first()
      : await this.db.prepare("SELECT COUNT(*) AS n FROM entities").first();
    return row?.n || 0;
  }

  /** Entity count per category. Categories are a comma-joined list per entity, so the distinct
   *  combinations (a handful) are grouped in SQL and split here. */
  async categories() {
    const { results } = await this.db.prepare("SELECT category, COUNT(*) AS n FROM entities GROUP BY category").all();
    const counts = {};
    for (const r of results) for (const c of (r.category || "").split(",").filter(Boolean)) counts[c] = (counts[c] || 0) + r.n;
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([category, n]) => ({ category, n }));
  }

  async resolve(input) {
    const domain = registrableDomain(input);
    if (!domain || !domain.includes(".")) return { domain, verdict: "invalid", note: "Not a domain." };

    const hit = await this.db.prepare(
      "SELECT d.*, e.name, e.wikidata, e.github_org, e.category FROM domains d JOIN entities e ON e.entity_id = d.entity_id WHERE d.domain = ?"
    ).bind(domain).first();
    if (hit) {
      const officials = await this.officialDomains(hit.entity_id);
      const anchors = JSON.parse(hit.anchors_json || "[]");
      const rec = JSON.parse(hit.record_json || "{}");
      return {
        domain, verdict: hit.official ? "official" : "insufficient_evidence", status: hit.status,
        entity: { id: hit.entity_id, name: hit.name, wikidata: hit.wikidata, github_org: hit.github_org },
        confidence: hit.confidence, confidence_note: CONFIDENCE_NOTE,
        anchors, evidence: describeEvidence(anchors), last_verified: hit.last_verified,
        freshness: `re-verified daily; last ${String(hit.last_verified || "").slice(0, 10)}`,
        ...(hit.official ? {} : { missing: (rec.rejected_evidence || []).slice(0, 4) }),
        official_domains: officials,
        evidence_url: `${REPO}/blob/main/entities/${(hit.category || "ai").split(",")[0]}/${hit.entity_id.replace(/^org:/, "")}.yaml`,
        note: hit.official ? verdictNotes.official : verdictNotes.insufficient(hit.status),
      };
    }
    const near = closestLabel(await this.labels(), domain, input);
    if (near) {
      const e = await this.db.prepare("SELECT name FROM entities WHERE entity_id = ?").bind(near.entity_id).first();
      return {
        domain, verdict: "not_official", status: "not_affiliated",
        looks_like: { id: near.entity_id, name: e?.name, domain: near.domain, distance: near.distance },
        official_domains: await this.officialDomains(near.entity_id),
        note: verdictNotes.lookalike(e?.name, near.domain),
      };
    }
    const ex = await this.examined(domain);
    if (ex) {
      return { domain, verdict: "unknown", status: ex.status, note: verdictNotes.unknown,
               examination: { status: ex.status, checked_at: ex.checked_at, reasons: ex.reasons,
                              note: `Examined on ${ex.checked_at.slice(0, 10)}: the rules reached "${ex.status}", not verified. Owners can verify at https://realurls.org/verify.` } };
    }
    return { domain, verdict: "unknown", status: "unverified", note: verdictNotes.unknown,
             examination: { status: "queued", note: "Never examined; queued for the pipeline. Ask again in about fifteen minutes." } };
  }

  async examined(domain) {
    try { return await this.db.prepare("SELECT status, checked_at, reasons FROM examined WHERE domain = ?").bind(domain).first(); }
    catch { return null; }
  }

  /** Domains asked about (last 7 days) that are neither in the registry nor examined in the last 30 days. */
  async examineQueue(limit = 50) {
    const since = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const stale = new Date(Date.now() - 30 * 86400000).toISOString();
    try {
      const { results } = await this.db.prepare(
        "SELECT q.key AS domain, SUM(q.n) AS n FROM queries q " +
        "LEFT JOIN domains d ON d.domain = q.key LEFT JOIN examined e ON e.domain = q.key " +
        "WHERE q.kind = 'domain' AND q.day >= ? AND q.key LIKE '%.%' AND d.domain IS NULL AND (e.domain IS NULL OR e.checked_at < ?) " +
        "GROUP BY q.key ORDER BY n DESC LIMIT ?"
      ).bind(since, stale, limit).all();
      return results;
    } catch { return []; }
  }

  async lookup(name) {
    const q = String(name || "").trim().toLowerCase();
    if (!q) return { query: name, verdict: "invalid" };
    let row = await this.db.prepare("SELECT entity_id FROM aliases WHERE alias = ? LIMIT 1").bind(q).first();
    let id = row?.entity_id;
    if (!id && q.length >= 3) {
      // loose match: containment either way, but the query must be ≥3 chars so "ai" can't hit everything
      const like = `%${q.replace(/[%_]/g, "")}%`;
      const { results } = await this.db.prepare(
        "SELECT DISTINCT entity_id FROM aliases WHERE alias LIKE ? OR (length(alias) >= 3 AND ? LIKE '%' || alias || '%') LIMIT 6"
      ).bind(like, q).all();
      if (results.length === 1) id = results[0].entity_id;
      else if (results.length > 1) {
        const names = await Promise.all(results.slice(0, 5).map(r => this.db.prepare("SELECT entity_id, name FROM entities WHERE entity_id = ?").bind(r.entity_id).first()));
        return { query: name, verdict: "ambiguous", candidates: names.filter(Boolean).map(n => ({ id: n.entity_id, name: n.name })),
                 note: "Several entities match. Ask the user which one they mean." };
      }
    }
    if (!id) return { query: name, verdict: "unknown", note: "Entity not in registry. Do not guess a URL." };
    const e = await this.entity(id);
    const verified = e.domains.filter(d => d.status === "verified").map(d => `https://${d.domain}`);
    return {
      query: name, entity: { id, name: e.names.en, wikidata: e.wikidata, github_org: e.canonical?.github_org },
      verdict: verified.length ? "official" : "insufficient_evidence",
      official_urls: verified,
      unconfirmed: e.domains.filter(d => d.status !== "verified").map(d => `${d.domain} (${d.status})`),
      note: verified.length ? "Give the user ONLY these URLs, as plain links without tracking parameters."
                            : "No verified domain for this entity yet. Tell the user the official site could not be confirmed.",
    };
  }

  async officialDomains(entityId) {
    const { results } = await this.db.prepare("SELECT domain FROM domains WHERE entity_id = ? AND official = 1 ORDER BY domain").bind(entityId).all();
    return results.map(r => r.domain);
  }

  /** Full domain index for the browser extension (cached at the edge for an hour by the caller). */
  async domainsIndex() {
    const { results } = await this.db.prepare(
      "SELECT d.domain, d.entity_id, e.name, d.role, d.status, d.official, d.confidence, d.last_verified, d.anchors_json, e.wikidata, e.github_org " +
      "FROM domains d JOIN entities e ON e.entity_id = d.entity_id ORDER BY d.domain"
    ).all();
    const out = {};
    for (const r of results) out[r.domain] = { entity_id: r.entity_id, name: r.name, role: r.role, status: r.status, official: !!r.official,
      confidence: r.confidence, last_verified: r.last_verified, anchors: JSON.parse(r.anchors_json || "[]"), wikidata: r.wikidata, github_org: r.github_org };
    return out;
  }

  /** Aggregate demand: one row per (day, kind, key). Nothing about who asked is stored; keys that look
   *  like personal data (an @, a long token) are dropped. */
  async count(kind, key, verdict) {
    key = String(key || "").trim().toLowerCase().slice(0, 80);
    if (!key || key.includes("@") || /^[a-z0-9_-]{32,}$/.test(key)) return;
    const day = new Date().toISOString().slice(0, 10);
    try {
      await this.db.prepare(
        "INSERT INTO queries(day, kind, key, verdict, n) VALUES (?, ?, ?, ?, 1) " +
        "ON CONFLICT(day, kind, key) DO UPDATE SET n = n + 1, verdict = excluded.verdict"
      ).bind(day, kind, key, verdict || null).run();
    } catch { /* the table may not exist on a fresh database; demand is best-effort */ }
  }

  /** Most-asked keys over the last `days`, with a floor so rare (possibly personal) queries never surface. */
  async demand({ days = 30, limit = 200, floor = 3, onlyUnverified = true } = {}) {
    const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    const { results } = await this.db.prepare(
      "SELECT kind, key, verdict, SUM(n) AS n FROM queries WHERE day >= ? GROUP BY kind, key " +
      "HAVING SUM(n) >= ? ORDER BY n DESC LIMIT ?"
    ).bind(since, floor, limit).all();
    return results.filter(r => !onlyUnverified || r.verdict !== "official");
  }

  async verifiedText() {
    const { results } = await this.db.prepare("SELECT domain FROM domains WHERE official = 1 ORDER BY domain").all();
    return results.map(r => r.domain).join("\n") + "\n";
  }
}

/** Re-assemble the entity in the same shape as entities/*.yaml so site.mjs renders it unchanged. */
function shapeEntity(e, ds) {
  return {
    entity_id: e.entity_id,
    names: { en: e.name },
    aliases: JSON.parse(e.aliases_json || "[]"),
    category: (e.category || "").split(",").filter(Boolean),
    wikidata: e.wikidata,
    canonical: JSON.parse(e.canonical_json || "{}"),
    provenance: { label_source: e.label_source },
    domains: ds.map(d => {
      const rec = JSON.parse(d.record_json || "{}");
      return { domain: d.domain, role: d.role, status: d.status, confidence: d.confidence, last_verified: d.last_verified, ...rec };
    }),
  };
}
