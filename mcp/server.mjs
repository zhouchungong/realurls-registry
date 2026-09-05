#!/usr/bin/env node
/**
 * Realurls MCP server.
 *
 * Holds no data: every tool call goes to the Realurls API. The `instructions` string is the lever that
 * matters — in our experiments it is the only text a host reads at the moment the model "already knows"
 * a URL, so it tells the model to verify first and to say "could not confirm" rather than guess.
 *
 * Every non-positive verdict is returned with a `say_to_user` line so the agent has the wording ready;
 * only `official` carries URLs the agent may hand out.
 *
 * Environment:
 *   REALURLS_API   API root, default https://api.realurls.org (local development: http://127.0.0.1:8787)
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API = (process.env.REALURLS_API || "https://api.realurls.org").replace(/\/+$/, "");
const VERSION = "0.1.4";

const INSTRUCTIONS =
  "Realurls verifies which domain officially belongs to a software product, AI tool, or company. " +
  "Whenever you are about to give the user a URL for downloading, installing, logging into, or visiting the " +
  "official site of ANY software product or company, call get_official_url first and use ONLY the URLs it " +
  "returns — even if you are confident you already know the URL. Popular, well-known tools are exactly the " +
  "ones targeted by SEO-poisoned lookalike download sites, and memorized URLs can be stale. " +
  "When the user pastes a URL and asks whether it is official, call verify_url. " +
  "If the tool returns insufficient_evidence or unknown, say so plainly rather than guessing; confidence never " +
  "upgrades a non-official answer. An unknown domain is queued for examination when you ask about it: if the " +
  "answer says queued, tell the user a check is running and they can ask again in about fifteen minutes. " +
  "If get_official_url returns unknown and you believe you know the URL, call verify_url on it: do not present " +
  "it as official, but the check queues that domain for examination. " +
  "Realurls judges ownership only, never safety.";

async function call(path, params) {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url, { headers: { "User-Agent": `realurls-mcp/${VERSION}` } });
  const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) return { verdict: "error", note: `Realurls API ${res.status}: ${body.error || "unavailable"}.`,
                        say_to_user: "Official-site verification is unavailable right now, so I cannot confirm any URL as official." };
  return withGuidance(body);
}

/** Wording for the agent, per verdict. The API's `note` says what the verdict means; this says what to tell the user. */
function withGuidance(r) {
  const name = r.entity?.name || r.looks_like?.name;
  const urls = (r.official_urls || (r.official_domains || []).map(d => `https://${d}`));
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

const server = new McpServer({ name: "realurls", version: VERSION }, { instructions: INSTRUCTIONS });

server.tool(
  "verify_url",
  "Check whether a URL or domain is the verified official website of a software product, AI tool, or company. " +
  "Returns official | not_official (with the real official domains) | insufficient_evidence | unknown. " +
  "Judges ownership only, never safety.",
  { url: z.string().describe("URL or bare domain, e.g. https://claude-desktop.io/download") },
  async ({ url }) => ({ content: [{ type: "text", text: JSON.stringify(await call("/v1/resolve", { domain: url }), null, 2) }] }),
);

server.tool(
  "get_official_url",
  "Look up the verified official website for a software product, AI tool, or company by name. " +
  "Returns verified URLs with the evidence behind them, or says the site could not be confirmed.",
  { name: z.string().describe("Product, tool, or company name, e.g. 'Ollama', 'Claude Code'") },
  async ({ name }) => ({ content: [{ type: "text", text: JSON.stringify(await call("/v1/entity", { q: name }), null, 2) }] }),
);

await server.connect(new StdioServerTransport());
