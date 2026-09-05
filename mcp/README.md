# @realurls/mcp

MCP server that tells an AI agent **which domain officially belongs to which software product or company** — so it stops
handing users SEO-poisoned lookalike download sites.

Ownership only. Never a safety judgement. Read [TRUST.md](../TRUST.md) for exactly what we do and do not claim.

## Tools

| tool | when the agent calls it | returns |
|---|---|---|
| `get_official_url(name)` | before giving any download / login / official-site link | `official` + verified URLs, or `insufficient_evidence` / `unknown` |
| `verify_url(url)` | user pastes a link and asks if it's real | `official` / `not_official` (+ the real domain) / `insufficient_evidence` / `unknown` |

The server ships **`instructions`** telling the host to call `get_official_url` *even when it thinks it already knows the URL*.
In our tests that single line is what makes the difference: without it, agents answer well-known tools from memory and never verify.

## Install

Claude Desktop — `claude_desktop_config.json`:

```json
{ "mcpServers": { "realurls": { "command": "npx", "args": ["-y", "@realurls/mcp"] } } }
```

Claude Code:

```bash
claude mcp add realurls -- npx -y @realurls/mcp
```

Point at a local API during development: `REALURLS_API=http://127.0.0.1:8787`.

## What "official" means

`official` = the domain has ≥1 anchor (GitHub-verified org, DNS self-attestation, restricted government TLD, …) **and** ≥2 independent
corroborations, all machine-reproducible. Anything less is reported as insufficient evidence — we would rather say "don't know" than be wrong.
