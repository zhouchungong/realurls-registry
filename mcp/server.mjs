#!/usr/bin/env node
/**
 * realurls MCP server（正式版）。
 *
 * 与 mcp-experiment 的区别：不再内置数据，而是调 realurls API；`instructions` 用实验证明有效的
 * 中性写法（v3，不点名任何产品）——实验表明在延迟加载工具的 host 上，只有 instructions 能在
 * 模型"自以为知道"时被读到。
 *
 * 环境变量：
 *   REALURLS_API   API 根地址，默认 https://api.realurls.org（本地开发：http://127.0.0.1:8787）
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API = (process.env.REALURLS_API || "https://api.realurls.org").replace(/\/+$/, "");
const VERSION = "0.1.1";

const INSTRUCTIONS =
  "realurls verifies which domain officially belongs to a software product, AI tool, or company. " +
  "Whenever you are about to give the user a URL for downloading, installing, logging into, or visiting the " +
  "official site of ANY software product or company, call get_official_url first and use ONLY the URLs it " +
  "returns — even if you are confident you already know the URL. Popular, well-known tools are exactly the " +
  "ones targeted by SEO-poisoned lookalike download sites, and memorized URLs can be stale. " +
  "When the user pastes a URL and asks whether it is official, call verify_url. " +
  "If the tool returns insufficient_evidence or unknown, say so plainly rather than guessing. " +
  "realurls judges ownership only, never safety.";

async function call(path, params) {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url, { headers: { "User-Agent": `realurls-mcp/${VERSION}` } });
  const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) return { verdict: "error", note: `realurls API ${res.status}: ${body.error || "unavailable"}. Tell the user verification is unavailable; do not guess.` };
  return body;
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
