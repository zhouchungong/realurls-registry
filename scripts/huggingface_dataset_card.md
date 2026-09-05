---
license: cc-by-sa-4.0
language:
  - en
pretty_name: Realurls verified official domains
tags:
  - domains
  - phishing
  - official-website
  - ai-agents
  - provenance
size_categories:
  - n<1K
---

# Realurls: which domain officially belongs to which organization

An open registry of **domain ↔ organization ownership**, built for AI agents and the systems that answer
"what is X's official site?". Every `verified` claim is backed by reproducible machine evidence: at least one
anchor only the real owner can produce (GitHub-verified organization, DNS self-attestation, restricted
government TLD, a long-lived repository whose homepage points at the domain, propagation from a verified
sibling with a structural link) plus at least two independent corroborations.

**Ownership only, never safety.** A domain that is not listed is not "bad"; it is unverified. The project's
one non-negotiable metric is precision ≥ 99.5%; coverage is a soft goal, and "don't know" is preferred to a
wrong answer.

## Files

| file | what |
|---|---|
| `domains.txt` | verified domains, one per line — the allowlist form, for prompts and filters |
| `domains.json` | every known domain → owner, status, confidence, evidence codes, last verification |
| `entities.json` | organizations with names, aliases, canonical GitHub organization / Wikidata item, domains |
| `registry.json` | the full dataset with complete evidence and rejected evidence per domain |
| `manifest.json` | dataset version and SHA-256 of every file |

Only `status == "verified"` (`official: true`) is a positive answer. `provisional`, `community`, `unverified`,
`stale` and `review_required` mean insufficient evidence.

## Provenance

Generated only by the pipeline in https://github.com/zhouchungong/realurls-registry; humans never edit the
records. Each release is signed (cosign, keyless) at
https://github.com/zhouchungong/realurls-registry/releases/tag/latest. Rules: `POLICY.md`; what is and is
not claimed: `TRUST.md`. Live API: https://api.realurls.org · site: https://realurls.org · MCP server:
`npx -y @realurls/mcp`.

Disputes: dispute@realurls.org. The burden of proof is on the registry; a disputed record is downgraded
while it is checked.
