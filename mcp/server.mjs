#!/usr/bin/env node
/**
 * Realurls MCP server for stdio hosts: a thin bridge to the remote MCP endpoint.
 *
 * The remote endpoint (POST https://api.realurls.org/mcp, Streamable HTTP) is the single implementation:
 * instructions, tool definitions and every answer, including the `say_to_user` wording, come from there.
 * This process only speaks stdio to the host and JSON-RPC over HTTPS to the endpoint, so the two ways of
 * installing Realurls can never disagree.
 *
 * If the endpoint cannot be reached at start-up the two known tools are still registered so the host does
 * not fail to load; each call then reports that verification is unavailable rather than guessing.
 *
 * Environment:
 *   REALURLS_API   API root, default https://api.realurls.org (local development: http://127.0.0.1:8787)
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API = (process.env.REALURLS_API || "https://api.realurls.org").replace(/\/+$/, "");
const VERSION = "0.1.5";
const UNAVAILABLE = {
  verdict: "error",
  say_to_user: "Official-site verification is unavailable right now, so I cannot confirm any URL as official. Do not present any URL as official meanwhile.",
};

let nextId = 1;
async function rpc(method, params = {}) {
  const res = await fetch(`${API}/mcp`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": `realurls-mcp/${VERSION}` },
    body: JSON.stringify({ jsonrpc: "2.0", id: nextId++, method, params }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || body.error) throw new Error(body?.error?.message || `HTTP ${res.status}`);
  return body.result;
}

/** The endpoint's JSON Schema for a tool → a zod shape (all inputs are plain strings). */
function shapeOf(schema) {
  const shape = {};
  for (const [name, prop] of Object.entries(schema?.properties || {})) {
    let field = z.string();
    if (prop.description) field = field.describe(prop.description);
    shape[name] = (schema.required || []).includes(name) ? field : field.optional();
  }
  return shape;
}

const FALLBACK_TOOLS = [
  { name: "verify_url", description: "Check whether a URL or domain is the verified official website of a software product, AI tool, or company. Judges ownership only, never safety.",
    inputSchema: { type: "object", properties: { url: { type: "string", description: "URL or bare domain" } }, required: ["url"] } },
  { name: "get_official_url", description: "Look up the verified official website for a software product, AI tool, or company by name.",
    inputSchema: { type: "object", properties: { name: { type: "string", description: "Product, tool, or company name" } }, required: ["name"] } },
];

let instructions = "Realurls verifies which domain officially belongs to a software product, AI tool, or company. Call get_official_url before giving any download, install or login URL and use only the URLs it returns; if it returns insufficient_evidence or unknown, say so rather than guessing. Ownership only, never safety.";
let tools = FALLBACK_TOOLS;
try {
  const init = await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "realurls-mcp-stdio", version: VERSION } });
  if (init?.instructions) instructions = init.instructions;
  const listed = await rpc("tools/list");
  if (listed?.tools?.length) tools = listed.tools;
} catch { /* offline at start-up: fall back to the static definitions above */ }

const server = new McpServer({ name: "realurls", version: VERSION }, { instructions });

for (const tool of tools) {
  server.tool(tool.name, tool.description, shapeOf(tool.inputSchema), async args => {
    try {
      const result = await rpc("tools/call", { name: tool.name, arguments: args });
      return result;
    } catch (exc) {
      return { content: [{ type: "text", text: JSON.stringify({ ...UNAVAILABLE, detail: String(exc.message || exc) }, null, 2) }] };
    }
  });
}

await server.connect(new StdioServerTransport());
