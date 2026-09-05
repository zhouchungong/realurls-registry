/**
 * Remote MCP endpoint (Streamable HTTP, stateless) at POST /mcp on api.realurls.org.
 *
 * Same two tools and the same `instructions` as the stdio package @realurls/mcp, so hosts that take a
 * URL instead of a command (claude.ai connectors, ChatGPT, Smithery, Cursor remote servers) get the
 * identical behaviour: verify before handing out any download or login URL, say "could not confirm"
 * rather than guess. No sessions, no SSE: every request is one JSON-RPC message answered with JSON.
 */

const PROTOCOL = "2025-06-18";
const VERSION = "0.1.3";

export const INSTRUCTIONS =
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

const TOOLS = [
  {
    name: "verify_url",
    description: "Check whether a URL or domain is the verified official website of a software product, AI tool, or company. " +
      "Returns official | not_official (with the real official domains) | insufficient_evidence | unknown. Judges ownership only, never safety.",
    inputSchema: { type: "object", properties: { url: { type: "string", description: "URL or bare domain, e.g. https://claude-desktop.io/download" } }, required: ["url"] },
  },
  {
    name: "get_official_url",
    description: "Look up the verified official website for a software product, AI tool, or company by name. " +
      "Returns verified URLs with the evidence behind them, or says the site could not be confirmed.",
    inputSchema: { type: "object", properties: { name: { type: "string", description: "Product, tool, or company name, e.g. 'Ollama', 'Claude Code'" } }, required: ["name"] },
  },
];

/** Wording for the agent, per verdict (mirrors @realurls/mcp). Only `official` carries URLs to hand out. */
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

const rpc = (id, result) => ({ jsonrpc: "2.0", id, result });
const rpcError = (id, code, message) => ({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });

async function handleMessage(msg, store, meta, ctx) {
  const { id, method, params = {} } = msg;
  switch (method) {
    case "initialize":
      return rpc(id, { protocolVersion: PROTOCOL, capabilities: { tools: {} }, serverInfo: { name: "realurls", version: VERSION }, instructions: INSTRUCTIONS });
    case "ping":
      return rpc(id, {});
    case "tools/list":
      return rpc(id, { tools: TOOLS });
    case "resources/list":
      return rpc(id, { resources: [] });
    case "prompts/list":
      return rpc(id, { prompts: [] });
    case "tools/call": {
      const args = params.arguments || {};
      let body;
      if (params.name === "verify_url") {
        body = withGuidance(await store.resolve(String(args.url || "")));
        ctx?.waitUntil(store.count("domain", body.domain, body.verdict));
      } else if (params.name === "get_official_url") {
        body = withGuidance(await store.lookup(String(args.name || "")));
        ctx?.waitUntil(store.count("name", String(args.name || ""), body.verdict));
      } else return rpcError(id, -32602, `unknown tool ${params.name}`);
      body.dataset_version = meta.dataset_version;
      return rpc(id, { content: [{ type: "text", text: JSON.stringify(body, null, 2) }], structuredContent: body });
    }
    default:
      if (method && method.startsWith("notifications/")) return null;   // acknowledged, no body
      return rpcError(id, -32601, `method not found: ${method}`);
  }
}

export async function handleMcp(request, store, meta, cors, ctx = null) {
  const headers = { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Realurls-Dataset": meta.dataset_version, ...cors };
  if (request.method === "GET") {
    // No server-initiated stream in this stateless deployment; hosts fall back to plain POST.
    return new Response(JSON.stringify({ name: "realurls", transport: "streamable-http", protocolVersion: PROTOCOL, note: "POST JSON-RPC messages to this URL." }), { status: 405, headers: { ...headers, Allow: "POST, OPTIONS" } });
  }
  if (request.method !== "POST") return new Response(null, { status: 405, headers: { ...headers, Allow: "POST, OPTIONS" } });
  let payload;
  try { payload = await request.json(); }
  catch { return new Response(JSON.stringify(rpcError(null, -32700, "parse error")), { status: 400, headers }); }

  const batch = Array.isArray(payload) ? payload : [payload];
  const out = [];
  for (const msg of batch) {
    if (!msg || msg.jsonrpc !== "2.0") { out.push(rpcError(msg?.id, -32600, "invalid request")); continue; }
    const res = await handleMessage(msg, store, meta, ctx);
    if (res) out.push(res);
  }
  if (!out.length) return new Response(null, { status: 202, headers });
  return new Response(JSON.stringify(Array.isArray(payload) ? out : out[0]), { status: 200, headers });
}
