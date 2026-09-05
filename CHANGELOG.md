# Changelog

What changed for people who consume the data or the API. Rule changes are listed with their effect on
existing records, because a rule change is a change to the public trust promise (POLICY.md §4).
The dataset itself is released continuously as the rolling `latest` GitHub Release (signed).

## 2026-09-06

### Rules
- **A6 (propagation) requires a backlink when one can be observed.** A verified site links to many third
  parties, and name-server pairs come from shared pools; a candidate whose own page has outbound links but
  none back to the anchor is rejected. A page that cannot be fetched or has no links at all (a JavaScript
  app, a 403 to our fetcher) is "unknown", not "no". Effect on existing records: none (claude.ai unknown,
  claude.com and n8n.cloud link back). New adversarial-corpus case.
- **Owner self-attestation (A5) end to end.** Seeds may carry the token we issued, the matched token is stored
  on the A5 record and re-checked daily. First owner request: kagi.com.

## 2026-09-05

### Rules
- **A4 (OV/EV certificate) must name the anchored entity.** An OV certificate for another organisation
  proves control, not ownership; it no longer anchors a domain. Found through a false positive in the first
  large batch (a verified site linked to instagram.com; Instagram's certificate was accepted as an anchor for
  that site's entity). Effect on existing records: `qwen.ai` verified → community (certificate belongs to
  Alibaba, entity is Qwen); no record moved up.
- **AI review layer** added as a second audit over every `verified` record. It is one-directional: it can move
  a record to `review_required` and hold it there until a human clears it; it can never promote. The
  200-record manual sample before each release stays.

### Data
- Seeds opened to every organisation behind a GitHub repository with 5,000+ stars (batch `gh-01`, `gh-02`,
  3,418 candidates); results land as reviewed pull requests, not directly on `main`.
- Sibling domains found on a verified primary's homepage are verified automatically through the propagation
  rule (A6), which still requires a structural link (shared name servers or certificate SAN).

### API and integrations
- `@realurls/mcp` 0.1.2: every result carries `say_to_user`, the sentence the agent should give for that
  verdict. Published to npm and the official MCP Registry.
- realurls.org/builders: how to integrate (allowlist, behaviour rule, HTTP tool shapes, MCP).
- realurls.org now lists organisations by category (`/c/<category>`, `/browse`); the home page no longer
  renders every organisation.
- Data moved from the Worker bundle to Cloudflare D1; response shapes unchanged.

## 2026-09-04 and earlier
- All public text in English; Chinese mirrors under `docs/zh/`.
- api.realurls.org live; realurls.org evidence pages; browser extension built (store listing pending);
  `@realurls/mcp` 0.1.1 in the official MCP Registry; signed rolling dataset release.
