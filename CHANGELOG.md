# Changelog

What changed for people who consume the data or the API. Rule changes are listed with their effect on
existing records, because a rule change is a change to the public trust promise (POLICY.md §4).
The dataset itself is released continuously as the rolling `latest` GitHub Release (signed).

## 2026-09-06

### Rules
- **A3 never anchors on its own; nor does A7 when the entity has an identity of its own.** A brand-protection registrar or a restricted TLD proves that
  *someone* substantial holds the domain, not who; together with B4 (history) and B5 (rank), neither of which
  names the entity either, they verified anthropic.com under the Python project, digitalocean.com under five
  projects it sponsors and vmware.com under RabbitMQ in the first full-category batch. An entity-agnostic anchor
  now counts only when at least one identity-bearing piece of evidence (A1/A2/A4/A5/A6/A8/A9/B1) passed too.
  Existing records: none change (checked with revalidate). New adversarial cases.
- **A6 (propagation): pooled name servers are not a link, and a domain another GitHub organization declares
  as its own is never propagated into.** cmake.org and kitware.com share only Namecheap's default name servers;
  matrix.org is run alongside element.io but belongs to the matrix-org organization, so it has to enter as its
  own entity. Records whose shared name servers were not recorded (older collector) lose the link until
  re-collected. Two adversarial cases.
- **Labels: `names.en` is always English.** The batch had shown Arabic, Korean and Tamil Wikidata labels
  for WordPress, Docker, Vim and 21 others, and product names (Next.js, javascript) for organizations
  (Vercel, Airbnb). Wikidata's English label wins only when it names the organization; otherwise the
  organization's own name is used and the Wikidata label becomes an alias. `src.relabel` applies the same
  chain to stored records.
- **A6 (propagation): shared name servers alone now need a backlink that was actually seen.** The first
  full-category batch propagated anthropic.com, digitalocean.com, alibabacloud.com, vmware.com and others
  from open-source projects that merely link to their sponsors, because those sites answer 403 to the
  fetcher and their backlink was "unknown". Unknown now counts as no; the source's own certificate
  covering the domain still stands on its own. Existing records: claude.ai keeps verified through A9;
  claude.com and n8n.cloud lose their propagated anchor (see the batch review). New adversarial case.
- **New anchor A9, App Store history.** An app sold to the domain by an Apple-verified company named like
  the (already anchored) entity, on the store at least 2 years with at least 1,000 ratings. The commercial
  counterpart of A8 for organisations that never verify a GitHub domain. Weight 0.55. Measured before
  adoption on 220 domains (55 stored + the 2026-09 survey, a GitHub-biased sample): 20 have an app whose
  seller URL points at the domain, 3 meet the bar with a matching name (claude.ai, openai.com,
  mozilla.org), 0 meet the bar with a non-matching name for a genuinely related company. Existing records:
  0 status changes. Several real companies keep long-lived apps with few ratings (YouTrack 29 ratings in
  10 years); the 1,000-ratings floor is deliberately conservative and will be revisited with more data.
- **A6 (propagation) requires a backlink when one can be observed.** A verified site links to many third
  parties, and name-server pairs come from shared pools; a candidate whose own page has outbound links but
  none back to the anchor is rejected. A page that cannot be fetched or has no links at all (a JavaScript
  app, a 403 to our fetcher) is "unknown", not "no". Effect on existing records: none (claude.ai unknown,
  claude.com and n8n.cloud link back). New adversarial-corpus case.
- **Owner self-attestation (A5) end to end.** Seeds may carry the token we issued, the matched token is stored
  on the A5 record and re-checked daily. First owner request: kagi.com.

### After the verdict
- **Disputes act within minutes.** A `dispute` issue moves the record to `disputed` at once, deploys, and
  holds it there until a maintainer clears the hold with a public note (TRUST.md 7 now says so).
- **Feedback loops close.** When a domain verifies later, the open lead / owner issues that asked about it
  are closed with the live link; owners are told on their own issue when daily re-verification downgrades
  their record. TRUST.md 5a maps where every outcome lives and who hears about it.

### API and integrations
- **Answers explain themselves to agents.** `/v1/resolve` and the MCP tools now return `evidence` (each
  anchor code with its meaning), `freshness`, `missing` (for insufficient_evidence: what was rejected and
  why), `confidence_note` (confidence ranks verified records; it never upgrades a non-official answer) and
  `examination` (queued / examined-on). `@realurls/mcp` 0.1.3: `say_to_user` covers the queued and
  examined cases, and the instructions tell the agent to retry after a queued answer and to run
  `verify_url` on a remembered URL when a name lookup is unknown (which queues that domain).
- **On-demand examination.** A domain that is asked about and was never examined is queued
  (`/v1/examine-queue`) and run through the pipeline within about fifteen minutes; verified records are
  merged after the corpus and AI review pass, other outcomes are stored so `/v1/resolve` answers
  `examination: {status, checked_at, reasons}` instead of plain "unknown".
- **Aggregate query demand.** Each query adds one to a per-day counter for its key and verdict; nothing
  about who asked is stored (TRUST.md 6a). `GET /v1/demand` publishes the most-asked keys of the last 30
  days with a floor of three, and `python -m src.seeds --source demand` turns the unanswered domains into
  seeds, so coverage follows demand rather than star counts.

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
