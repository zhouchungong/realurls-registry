import { test } from "node:test";
import assert from "node:assert/strict";
import { Resolver, registrableDomain, levenshtein } from "./resolve.mjs";

const dataset = {
  manifest: { dataset_version: "test", counts: { verified: 2 } },
  entities: {
    "org:anthropics": { name: "Anthropic", aliases: ["Claude", "Claude Code"], wikidata: "Q1", github_org: "anthropics",
                        category: ["ai"], domains: [{ domain: "anthropic.com", role: "primary", status: "verified" },
                                                    { domain: "claude.ai", role: "product", status: "verified" }] },
    "org:cursor": { name: "Cursor", aliases: ["Anysphere"], category: ["developer-tools"],
                    domains: [{ domain: "cursor.com", role: "primary", status: "community" }] },
    "org:ollama": { name: "Ollama", aliases: [], category: ["ai"], domains: [{ domain: "ollama.com", status: "verified" }] },
  },
  domains: {
    "anthropic.com": { entity_id: "org:anthropics", name: "Anthropic", status: "verified", official: true, confidence: 0.93 },
    "claude.ai": { entity_id: "org:anthropics", name: "Anthropic", status: "verified", official: true, confidence: 0.71 },
    "cursor.com": { entity_id: "org:cursor", name: "Cursor", status: "community", official: false, confidence: 0.27 },
    "ollama.com": { entity_id: "org:ollama", name: "Ollama", status: "verified", official: true, confidence: 0.85 },
  },
};
const r = new Resolver(dataset);

test("registrableDomain strips scheme/path/www and handles multi-part suffixes", () => {
  assert.equal(registrableDomain("https://www.anthropic.com/download?x=1"), "anthropic.com");
  assert.equal(registrableDomain("docs.claude.com"), "claude.com");
  assert.equal(registrableDomain("x.pages.dev"), "x.pages.dev");
  assert.equal(registrableDomain("a.b.example.co.uk"), "example.co.uk");
});

test("resolve: verified domain → official", () => {
  const out = r.resolve("https://claude.ai/download");
  assert.equal(out.verdict, "official");
  assert.deepEqual(out.official_domains, ["anthropic.com", "claude.ai"]);
});

test("resolve: community status is never official", () => {
  const out = r.resolve("cursor.com");
  assert.equal(out.verdict, "insufficient_evidence");
  assert.equal(out.status, "community");
});

test("resolve: lookalike → not_official with the real domain", () => {
  const out = r.resolve("https://claude-desktop.io/download");
  assert.equal(out.verdict, "not_official");
  assert.equal(out.looks_like.name, "Anthropic");
  assert.ok(out.official_domains.includes("claude.ai"));
});

test("resolve: cyrillic homograph is caught", () => {
  const out = r.resolve("аnthropic.com"); // Cyrillic а
  assert.equal(out.verdict, "not_official");
});

test("resolve: unrelated domain → unknown, never guesses", () => {
  assert.equal(r.resolve("totally-unrelated.example").verdict, "unknown");
});

test("resolve: lookalike baseline uses only verified domains", () => {
  // cursor.com is only community, so cursor-ide.dev must not be called "like Cursor's official site" — we never confirmed cursor.com is
  const out = r.resolve("cursor-ide.dev");
  assert.equal(out.verdict, "unknown");
});

test("lookup: alias → official urls", () => {
  const out = r.lookup("claude code");
  assert.equal(out.verdict, "official");
  assert.deepEqual(out.official_urls, ["https://anthropic.com", "https://claude.ai"]);
});

test("lookup: entity without verified domain → insufficient_evidence, lists unconfirmed", () => {
  const out = r.lookup("Cursor");
  assert.equal(out.verdict, "insufficient_evidence");
  assert.deepEqual(out.official_urls, []);
  assert.deepEqual(out.unconfirmed, ["cursor.com (community)"]);
});

test("lookup: short query never fuzzy-matches", () => {
  assert.equal(r.lookup("ai").verdict, "unknown");
});

test("levenshtein basics", () => {
  assert.equal(levenshtein("kitten", "sitting"), 3);
  assert.equal(levenshtein("", "abc"), 3);
});
